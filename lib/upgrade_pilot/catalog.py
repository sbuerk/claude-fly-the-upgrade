"""Which versions of a third-party package support a core version: released, only on a branch, or none.

Sources, in this order:
- Packagist metadata (p2, tagged releases and the ~dev branches) for packages installed from Packagist
- `composer show --all` for packages from other repositories (VCS, private composer repositories)
- the TYPO3 Extension Repository (TER) REST API, by extension key, as a second opinion for extensions:
  https://extensions.typo3.org/api/v1/docs (GET /extension/{key}/versions needs no token)
- what the development branches state themselves: the TYPO3 range of ext_emconf.php and mentions of
  the target major in README and documentation, read from the deps git cache

A version supports a core version when every typo3/cms-* requirement allows it. Released means a
stable version (not a development branch, not a pre-release).
"""

from __future__ import annotations

import json
import re
import shlex
import time
import urllib.error
import urllib.request
from pathlib import Path

from .core import Flight, extract_json, load_json, now, sh, slug, write_json
from .platform import PACKAGIST, allows, expand_minified, vtuple

TER_API = 'https://extensions.typo3.org/api/v1'
USER_AGENT = 'upgrade-pilot (Claude Code plugin; +https://github.com/sbuerk/claude-fly-the-upgrade)'
PRE_RELEASE = re.compile(r'(alpha|beta|rc|dev)', re.I)
CORE_PACKAGE = re.compile(r'^typo3/cms-')
# How many versions of a package from another repository are described one by one (composer show is slow).
MAX_DESCRIBED = 12

STATUSES = {
    'released': 'a released version supports the target',
    'released-ter': 'only the TER has a release for the target, composer has none',
    'dev-only': 'only a development branch supports the target',
    'claimed': 'no version requires the target, but the documentation of a development branch mentions it',
    'none': 'nothing supports the target',
    'independent': 'no TYPO3 requirement, composer decides',
}


# -- fetching -----------------------------------------------------------------------------------------

def fetch_json(url: str, cache: Path | None, method: str = 'GET'):
    """JSON from a URL, cached per assessment run. None for 404 and network errors."""
    target = cache / (slug(url.split('://', 1)[-1]) + '.json') if cache else None
    if target and target.is_file():
        return json.loads(target.read_text(encoding='utf-8'))
    request = urllib.request.Request(url, method=method, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
            remaining = response.headers.get('X-RateLimit-Remaining')
            if remaining is not None and remaining.isdigit() and int(remaining) < 5:
                time.sleep(2)  # the TER API is rate limited, slow down before it refuses
    except urllib.error.HTTPError as error:
        data = None if error.code == 404 else {'_error': error.code}
    except (urllib.error.URLError, TimeoutError, ValueError):
        data = {'_error': 'unreachable'}
    if target and not (isinstance(data, dict) and data.get('_error')):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding='utf-8')
    return data


def from_packagist(name: str, cache: Path | None) -> tuple[list[dict], list[dict]] | None:
    """(tagged versions, development versions) with their requirements, or None when Packagist has no such package."""
    tagged = fetch_json(PACKAGIST.format(name=name), cache)
    if tagged is None or (isinstance(tagged, dict) and tagged.get('_error')):
        return None
    dev = fetch_json(PACKAGIST.format(name=f'{name}~dev'), cache) or {}
    versions = expand_minified((tagged.get('packages') or {}).get(name, []))
    branches = expand_minified((dev.get('packages') or {}).get(name, [])) if not dev.get('_error') else []
    return versions, branches


def from_composer(flight: Flight, name: str) -> tuple[list[dict], list[dict]]:
    """For packages of other repositories: ask composer, as the project resolves them (with its credentials)."""
    composer = flight.config['runtime']['composer']
    rc, out, _ = sh(f'{composer} show --all --format=json {shlex.quote(name)}', flight.root, merge=False)
    listing = (extract_json(out) or {}) if rc == 0 else {}
    names = listing.get('versions') or []
    dev_names = [v for v in names if is_dev(v)]
    stable = sorted((v for v in names if not is_dev(v)), key=vtuple, reverse=True)[:MAX_DESCRIBED]
    described = []
    for version in dev_names + stable:
        rc, out, _ = sh(f'{composer} show --all --format=json {shlex.quote(name)} {shlex.quote(version)}', flight.root, merge=False)
        data = (extract_json(out) or {}) if rc == 0 else {}
        described.append({'version': version, 'require': data.get('requires') or {},
                          'source': data.get('source') or {}, 'time': data.get('released')})
    return [d for d in described if not is_dev(d['version'])], [d for d in described if is_dev(d['version'])]


def ter_versions(key: str, cache: Path | None) -> list[dict] | None:
    """Versions of an extension key in the TER, or None when the key is unknown there."""
    data = fetch_json(f'{TER_API}/extension/{key}/versions', cache)
    if data is None or (isinstance(data, dict) and data.get('_error')):
        return None
    # The API wraps the version list in a list.
    if isinstance(data, list) and data and isinstance(data[0], list):
        data = data[0]
    return [v for v in data if isinstance(v, dict)]


# -- deciding -----------------------------------------------------------------------------------------

def is_dev(version: str) -> bool:
    v = version.strip()
    return v.startswith('dev-') or v.endswith('-dev')


def is_stable(version: str) -> bool:
    return not is_dev(version) and not PRE_RELEASE.search(version)


def core_requirements(require: dict) -> dict[str, str]:
    return {k: v for k, v in (require or {}).items() if CORE_PACKAGE.match(k)}


def supports(require: dict, core: str) -> bool | None:
    """True or False for packages that require core packages, None for packages that do not."""
    constraints = core_requirements(require)
    if not constraints:
        return None
    return all(allows(c, core) for c in constraints.values())


def ter_range(dependency) -> str | None:
    """TER typo3 dependency as a constraint: '>=13.4.29 <=14.3.99' stays, '13.4.0-14.3.99' becomes a range."""
    if not dependency or not isinstance(dependency, str):
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)*)\s*-\s*(\d+(?:\.\d+)*)\s*', dependency)
    if match:
        low, high = match.groups()
        return f'>={low}' + ('' if high.startswith('0') else f' <={high}')
    return dependency


def ter_supports(version: dict, core: str) -> bool:
    dependencies = version.get('dependencies') or {}
    constraint = ter_range(dependencies.get('typo3')) if isinstance(dependencies, dict) else None
    return bool(constraint) and allows(constraint, core)


MAIN_LINE = re.compile(r'^(dev-(main|master|develop|development)|v?\d+(\.\d+)*\.x-dev|v?\d+(\.\d+)*-dev)$')


def main_lines(branches: list[dict]) -> list[dict]:
    """Development lines a project would use: main branches, version branches, anything with a branch alias.
    Feature branches (dev-task/..., dev-fix/...) only when nothing else qualifies."""
    lines = [b for b in branches if MAIN_LINE.match(b['version']) or branch_alias(b)]
    return lines or branches


def branch_alias(entry: dict) -> str | None:
    aliases = (entry.get('extra') or {}).get('branch-alias') or {}
    return aliases.get(entry['version']) or None


def classify(name: str, installed: str | None, core: str, php: str | None, versions: list[dict],
             branches: list[dict], ter: list[dict] | None, constraint: str | None) -> dict:
    """Release status of one package for one core version. php: the PHP version the project will run."""
    entry = {'name': name, 'installed': installed, 'constraint': constraint, 'core': core}
    stable = [v for v in versions if is_stable(v['version'])]
    known = [v for v in stable if supports(v.get('require'), core) is not None]
    if not known and not any(supports(b.get('require'), core) is not None for b in branches):
        entry['status'] = 'independent'
        return entry
    compatible = sorted((v for v in stable if supports(v.get('require'), core)), key=lambda v: vtuple(v['version']))
    if compatible:
        newest = compatible[-1]
        php_req = (newest.get('require') or {}).get('php')
        entry.update({'status': 'released', 'version': newest['version'], 'released_at': newest.get('time'),
                      'versions': [v['version'] for v in compatible][-5:],
                      'php': php_req, 'php_ok': None if not (php and php_req) else allows(php_req, php),
                      'in_constraint': None if constraint is None else allows(constraint, newest['version'])})
        return entry
    if ter:
        ter_ok = [v for v in ter if ter_supports(v, core) and (v.get('state') or 'stable') == 'stable']
        if ter_ok:
            newest = max(ter_ok, key=lambda v: vtuple(v.get('number', '0')))
            entry.update({'status': 'released-ter', 'version': newest.get('number'),
                          'released_at': newest.get('upload_date'), 'ter_typo3': (newest.get('dependencies') or {}).get('typo3')})
            return entry
    dev = main_lines([b for b in branches if supports(b.get('require'), core)])
    if dev:
        entry.update({'status': 'dev-only', 'branches': [{'version': b['version'], 'alias': branch_alias(b),
                                                          'reference': (b.get('source') or {}).get('reference'),
                                                          'requires': core_requirements(b.get('require'))} for b in dev]})
        return entry
    entry['status'] = 'none'
    entry['branches_checked'] = [b['version'] for b in branches]
    return entry


def latest_release(versions: list[dict]) -> dict | None:
    stable = [v for v in versions if is_stable(v['version'])]
    return max(stable, key=lambda v: vtuple(v['version'])) if stable else None


# -- documentation claims of development branches -----------------------------------------------------

EMCONF_TYPO3 = re.compile(r"""['"]typo3['"]\s*=>\s*['"]([^'"]+)['"]""")
DOC_FILES = re.compile(r'^(README(\.\w+)?|Documentation/(Index|Introduction/Index|Installation/Index|Settings)\.(rst|md)|docs?/[^/]*\.md)$', re.I)


def mention(major: str) -> re.Pattern:
    return re.compile(rf'TYPO3\s*(?:CMS\s*)?(?:v|version\s*)?{major}(?:\.\d+)?(?:\s*LTS)?\b', re.I)


def documentation_claims(flight: Flight, name: str, branches: list[dict], core: str, source_url: str | None) -> list[dict]:
    """What development branches state about the target: ext_emconf range, README and documentation mentions."""
    from .deps import Tree, ensure_repo
    if not source_url:
        return []
    refs = [(b.get('source') or {}).get('reference') for b in branches if (b.get('source') or {}).get('reference')]
    repo = ensure_repo(flight, source_url, refs) if refs else None
    if not repo:
        return []
    major = core.split('.')[0]
    pattern, claims = mention(major), []
    for branch in main_lines(branches):
        ref = (branch.get('source') or {}).get('reference')
        if not ref:
            continue
        tree = Tree(repo, ref)
        files = tree.files()
        if 'ext_emconf.php' in files:
            match = EMCONF_TYPO3.search(tree.read('ext_emconf.php'))
            if match and ter_range(match.group(1)) and allows(ter_range(match.group(1)), core):
                claims.append({'branch': branch['version'], 'file': 'ext_emconf.php', 'text': f"'typo3' => '{match.group(1)}'"})
        for path in (f for f in files if DOC_FILES.match(f)):
            lines = tree.read(path).splitlines()
            for number, line in enumerate(lines, 1):
                if pattern.search(line):
                    # The sentences around the mention say what it means: supported, planned, or a version elsewhere.
                    context = ' '.join(l.strip() for l in lines[number - 1:number + 2] if l.strip())
                    claims.append({'branch': branch['version'], 'file': f'{path}:{number}', 'text': context[:400]})
                    break
    return claims


# -- one package, all sources -------------------------------------------------------------------------

def assess_package(flight: Flight, package: dict, core: str, php: str | None, constraint: str | None,
                   cache: Path, ter_key: str | None) -> dict:
    name = package['name']
    from_packagist_registry = 'packagist.org' in (package.get('notification-url') or '')
    data = from_packagist(name, cache) if from_packagist_registry else None
    versions, branches = data if data is not None else from_composer(flight, name)
    ter = ter_versions(ter_key, cache) if ter_key else None
    entry = classify(name, package.get('version'), core, php, versions, branches, ter, constraint)
    entry['type'] = package.get('type')
    entry['extension_key'] = ter_key
    entry['source'] = 'packagist' if data is not None else 'composer repository'
    latest = latest_release(versions)
    entry['latest_release'] = latest and latest['version']
    entry['latest_release_at'] = latest and latest.get('time')
    entry['last_branch_activity'] = max((b.get('time') or '' for b in branches), default='') or None
    abandoned = package.get('abandoned') or next((v.get('abandoned') for v in versions[-1:] if v.get('abandoned')), None)
    entry['abandoned'] = abandoned
    if ter is not None:
        entry['ter'] = {'versions': len(ter), 'latest': (max(ter, key=lambda v: vtuple(v.get('number', '0'))) or {}).get('number') if ter else None}
    if entry['status'] in ('dev-only', 'none'):
        source_url = (package.get('source') or {}).get('url')
        candidates = branches if entry['status'] == 'none' else [b for b in branches if b['version'] in {x['version'] for x in entry['branches']}]
        claims = documentation_claims(flight, name, candidates, core, source_url)
        if claims:
            entry['claims'] = claims
            if entry['status'] == 'none':
                entry['status'] = 'claimed'
    return entry


def extension_key(package: dict) -> str | None:
    return ((package.get('extra') or {}).get('typo3/cms') or {}).get('extension-key')
