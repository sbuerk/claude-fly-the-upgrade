"""Third-party dependencies: what moves, and what their maintainers wrote about it.

The core documents every change in Documentation/Changelog. Many extensions
and libraries do the same, or keep CHANGELOG / UPGRADE / MIGRATION files,
upgrade guides in their documentation, or mark breaking commits with [!!!].
Nothing here is bound to a vendor: packages are found through composer (the
bump probe or the lock files), their sources through composer metadata (so
private repositories work with the project's credentials), and their notes
by file conventions only.

Docs are read from the target *release* (the locked or resolved commit), never
from a branch: unreleased notes do not apply to the version you install.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .changelog import COMMENT, needles, own_files, parse_entry_text
from .core import Flight, die, extract_json, load_json, now, sh, slug, write_json
from .init import locked_packages
from .platform import vtuple

CORE_PREFIX = 'typo3/cms-'
NOTE_FILE = re.compile(r'(^|/)(CHANGELOG|CHANGES|UPGRADE|UPGRADING|MIGRATION|MIGRATING|NEWS|HISTORY|RELEASE[-_]?NOTES|BREAKING[-_ ]?CHANGES)[^/]*\.(md|markdown|rst|txt)$', re.I)
GUIDE_FILE = re.compile(r'(^|/)(Documentation|docs?)/(.*/)?[^/]*(upgrad|migrat|update)[^/]*\.(md|rst)$', re.I)
TYPO3_CHANGELOG = re.compile(r'(^|/)Documentation/Changelog/(\d+(?:\.\d+)*(?:\.x)?)/([A-Za-z]+)-[^/]*\.rst$')
WIZARD_PATH = re.compile(r'(^|/)Classes/(.*/)?(Upgrade|Upgrades|Update|Updates|Wizard|Wizards)/[^/]+\.php$')
WIZARD_ID = re.compile(r'#\[UpgradeWizard\(\s*[\'"]([^\'"]+)[\'"]')
SKIP_PATH = re.compile(r'(^|/)(vendor|node_modules|\.Build|Tests|tests|Build)/')
VERSION_TOKEN = re.compile(r'v?(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?')
VERSION_HEADING = re.compile(r'^\W*(?:(?:version|release|upgrade(?:\s+to)?|upgrading(?:\s+to)?|changes\s+in)\s+)?\[?(v?\d+(?:\.(?:\d+|x|\*)){0,2})\]?(?=$|[\s\-:(,)\]])', re.I)
BREAKING_LINE = re.compile(r'\[!!!\]|\bBREAKING\b|\(BREAKING\)|^\s*[-*]\s*\w+(\([^)]*\))?!:|\bbreaking change', re.I)
BREAKING_SUBJECT = re.compile(r'\[!!!\]|\bBREAKING\b|^\w+(\([^)]*\))?!:', re.I)
TYPE_ORDER = {'Breaking': 0, 'Deprecation': 1, 'Important': 2, 'Feature': 3, 'Bugfix': 4}


# -- versions -----------------------------------------------------------------------

def clean(version: str) -> str:
    return version.strip().lstrip('vV')


def kind_of(old: str | None, new: str | None) -> str:
    if not old:
        return 'added'
    if not new:
        return 'removed'
    if not numeric(old) or not numeric(new):
        return 'changed'
    a, b = vtuple(clean(old)), vtuple(clean(new))
    if a[0] != b[0]:
        return 'major' if b > a else 'downgrade'
    if a[1] != b[1]:
        return 'minor' if b > a else 'downgrade'
    return 'patch' if b >= a else 'downgrade'


def interval(token: str) -> tuple[tuple, tuple] | None:
    """When a version token's changes arrived, as [low, high].

    '6.0.7', '6.0' and '6' name the release that introduced the change: a point.
    '6.x' and '6.0.x' group releases: a range ('6.0.x' covers the patches after 6.0.0).
    """
    match = VERSION_TOKEN.fullmatch(token.strip())
    if not match:
        return None
    major, minor, patch = int(match.group(1)), match.group(2), match.group(3)
    if minor in ('x', '*'):
        return (major, 0, 0), (major, 999, 999)
    if patch in ('x', '*'):
        return (major, int(minor), 1), (major, int(minor), 999)
    point = (major, int(minor or 0), int(patch or 0))
    return point, point


def in_range(token_interval: tuple[tuple, tuple], old: str, new: str) -> bool:
    """Did anything of [low, high] arrive after the installed version, up to the target?"""
    low, high = token_interval
    return high > vtuple(clean(old)) and low <= vtuple(clean(new))


# -- which packages move --------------------------------------------------------------

def own_packages(flight: Flight) -> set[str]:
    return {ext['package'] for ext in flight.extensions() if ext.get('package')}


def moves_from_probe(flight: Flight) -> list[dict]:
    probes = flight.log.get('probes') or []
    if not probes:
        die('no bump probe recorded yet. Run: upgrade-pilot bump probe')
    return parse_operations((flight.root / probes[-1]['log']).read_text(encoding='utf-8', errors='replace'))


def parse_operations(text: str) -> list[dict]:
    """Package operations of composer output (dry run or real), deduplicated."""
    moves: dict[str, dict] = {}
    for verb, name, versions in re.findall(r'-\s+(Upgrading|Downgrading|Installing|Removing)\s+(\S+)\s+\(([^)]*)\)', text):
        if verb in ('Upgrading', 'Downgrading'):
            old, _, new = versions.partition(' => ')
        elif verb == 'Installing':
            old, new = None, versions
        else:
            old, new = versions, None
        moves[name] = {'name': name, **split_version('from', old), **split_version('to', new)}
    return list(moves.values())


def split_version(side: str, text: str | None) -> dict:
    """'dev-main 7ea78cc' -> version 'dev-main' plus commit '7ea78cc'."""
    if not text:
        return {side: None}
    version, _, ref = text.strip().partition(' ')
    return {side: version, f'{side}_ref': ref or None}


def numeric(version: str | None) -> bool:
    return bool(version and re.match(r'^\d', clean(version)))


def lock_at(flight: Flight, ref: str) -> dict[str, dict]:
    rc, out, _ = sh(f'git show {shlex.quote(ref)}:composer.lock', flight.root, merge=False)
    if rc != 0:
        die(f'no composer.lock at {ref}')
    lock = extract_json(out) or {}
    packages = {}
    for section in ('packages', 'packages-dev'):
        for package in lock.get(section, []):
            packages[package['name']] = package
    return packages


def moves_from_locks(flight: Flight, ref: str) -> list[dict]:
    before, after = lock_at(flight, ref), locked_packages(flight.root)
    moves = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old and new and old['version'] == new['version'] and old.get('source', {}).get('reference') == new.get('source', {}).get('reference'):
            continue
        moves.append({'name': name, 'from': old and old['version'], 'to': new and new['version'],
                      'from_ref': old and old.get('source', {}).get('reference'), 'to_ref': new and new.get('source', {}).get('reference')})
    return moves


def direct_requirements(flight: Flight) -> set[str]:
    names: set[str] = set()
    files = [flight.root / 'composer.json'] + [flight.root / e['path'] / 'composer.json' for e in flight.extensions() if e['path'] != '.']
    for path in files:
        data = load_json(path, {}) or {}
        for section in ('require', 'require-dev'):
            names |= set((data.get(section) or {}).keys())
    return names


def used_namespaces(flight: Flight, packages: dict[str, dict]) -> set[str]:
    """Packages whose PSR-4/PSR-0 namespaces appear in own extension code."""
    text = '\n'.join('\n'.join(lines) for lines in own_files(flight).values())
    used = set()
    for name, meta in packages.items():
        autoload = meta.get('autoload') or {}
        for key in ('psr-4', 'psr-0'):
            for namespace in (autoload.get(key) or {}):
                namespace = namespace.strip('\\')
                if len(namespace) > 3 and re.search(r'(?<![\w\\])\\?' + re.escape(namespace).replace('\\\\', '\\\\\\\\?') + r'\\', text):
                    used.add(name)
    return used


def classify(flight: Flight, moves: list[dict], before: dict[str, dict]) -> list[dict]:
    own = own_packages(flight)
    after = locked_packages(flight.root)
    direct = direct_requirements(flight)
    used = used_namespaces(flight, {**before, **after})
    out = []
    for move in moves:
        name = move['name']
        if name.startswith(CORE_PREFIX) or name in own or name == 'php' or name.startswith('ext-'):
            continue
        meta = after.get(name) or before.get(name) or {}
        out.append({**move, 'type': meta.get('type'), 'kind': kind_of(move['from'], move['to']),
                    'abandoned': meta.get('abandoned'), 'direct': name in direct, 'used': name in used})
    return out


def selected(moves: list[dict], wanted: list[str] | None, everything: bool) -> list[dict]:
    """Default: every TYPO3 extension, direct requirements that jump a major or are new, packages own code uses."""
    if wanted:
        return [m for m in moves if m['name'] in wanted]
    if everything:
        return [m for m in moves if m['to']]
    return [m for m in moves if m['to'] and (
        m['type'] == 'typo3-cms-extension'
        or (m.get('direct') and m['kind'] in ('major', 'added'))
        or (m.get('used') and m['kind'] in ('major', 'minor', 'added')))]


# -- where the sources are ----------------------------------------------------------------

def composer_meta(flight: Flight, name: str, version: str, lock: dict[str, dict]) -> dict:
    locked = lock.get(name)
    if locked and clean(locked['version']) == clean(version):
        return locked
    composer = flight.config['runtime']['composer']
    cmd = f'{composer} show --all --format=json {shlex.quote(name)} {shlex.quote(version)}'
    for _ in range(2):  # network and registry hiccups happen, retry once
        rc, out, err = sh(cmd, flight.root, merge=False)
        data = extract_json(out) if rc == 0 else None
        if data:
            return data
    print(f'    WARNING: composer could not describe {name} {version} (exit {rc}): {(err or out).strip()[-300:]}')
    return {}


def repo_dir(flight: Flight, url: str) -> Path:
    return flight.dir / 'cache' / 'deps' / (slug(re.sub(r'^\w+://|^git@', '', url)) + '.git')


def candidates(reference: str | None, version: str | None) -> list[str]:
    return [c for c in dict.fromkeys([reference, version, version and f'v{clean(version)}', version and clean(version)]) if c]


def first_commit(repo: Path, refs: list[str]) -> str | None:
    for ref in refs:
        if sh(f'git -C {shlex.quote(str(repo))} cat-file -e {shlex.quote(ref)}^{{commit}}', repo)[0] == 0:
            return ref
    return None


def ensure_repo(flight: Flight, url: str, refs: list[str]) -> Path | None:
    """Blobless bare clone of the package source, fetching tags when a ref is missing."""
    target = repo_dir(flight, url)
    if not target.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        rc, out, _ = sh(f'git clone --quiet --bare --filter=blob:none {shlex.quote(url)} {shlex.quote(str(target))}', flight.root)
        if rc != 0:
            print(f'    clone failed: {out.strip()[:300]}')
            return None
    if not first_commit(target, refs):
        sh(f'git -C {shlex.quote(str(target))} fetch --quiet --filter=blob:none --tags origin', flight.root)
    return target


class Tree:
    """Read-only view of one package version: a git commit, or an installed directory."""

    def __init__(self, repo: Path | None = None, ref: str | None = None, directory: Path | None = None):
        self.repo, self.ref, self.directory = repo, ref, directory

    def files(self) -> list[str]:
        if self.repo:
            rc, out, _ = sh(f'git -C {shlex.quote(str(self.repo))} ls-tree -r --name-only {shlex.quote(self.ref)}', self.repo, merge=False)
            return out.splitlines() if rc == 0 else []
        if self.directory and self.directory.is_dir():
            return [str(p.relative_to(self.directory)) for p in self.directory.rglob('*') if p.is_file()]
        return []

    def read(self, path: str) -> str:
        if self.repo:
            rc, out, _ = sh(f'git -C {shlex.quote(str(self.repo))} show {shlex.quote(self.ref + ":" + path)}', self.repo, merge=False)
            return out if rc == 0 else ''
        return (self.directory / path).read_text(encoding='utf-8', errors='replace')


def resolve_trees(flight: Flight, move: dict, before: dict[str, dict], after: dict[str, dict]) -> tuple[Tree | None, Tree | None, str]:
    name = move['name']
    new_meta = composer_meta(flight, name, move['to'], after)
    old_meta = composer_meta(flight, name, move['from'], before) if move['from'] else {}
    source = new_meta.get('source') or {}
    if source.get('type') == 'git' and source.get('url'):
        new_refs = candidates(move.get('to_ref'), None) + candidates(source.get('reference'), move['to'])
        old_refs = (candidates(move.get('from_ref'), None) + candidates((old_meta.get('source') or {}).get('reference'), move['from'])) if move['from'] else []
        repo = ensure_repo(flight, source['url'], new_refs + old_refs)
        new_ref = repo and first_commit(repo, new_refs)
        if new_ref:
            old_ref = first_commit(repo, old_refs) if old_refs else None
            return (Tree(repo, old_ref) if old_ref else None), Tree(repo, new_ref), f'git {source["url"]} at {new_ref[:12]}'
    installed = flight.root / 'vendor' / name
    locked = after.get(name)
    if installed.is_dir() and locked and clean(locked['version']) == clean(move['to']):
        return None, Tree(directory=installed), f'installed copy vendor/{name} (no git source)'
    return None, None, 'no readable source (no git source, not installed in the target version)'


# -- reading the notes ---------------------------------------------------------------------

def split_sections(text: str, markdown: bool) -> list[tuple[str, int, str]]:
    """(heading, level, body) chunks. Markdown '#' headings, or rst underlined headings."""
    lines = text.splitlines()
    marks: list[tuple[int, str, int]] = []
    if markdown:
        for i, line in enumerate(lines):
            match = re.match(r'^(#{1,6})\s+(.*)$', line)
            if match:
                marks.append((i, match.group(2).strip(), len(match.group(1))))
    else:
        levels: dict[str, int] = {}
        for i in range(len(lines) - 1):
            under = lines[i + 1]
            if lines[i].strip() and re.fullmatch(r'([=\-~^"#*+])\1{2,}', under.strip()) and len(under.strip()) >= len(lines[i].strip()) - 2:
                levels.setdefault(under.strip()[0], len(levels) + 1)
                marks.append((i, lines[i].strip(), levels[under.strip()[0]]))
    chunks = []
    for index, (start, heading, level) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(lines)
        body_start = start + (1 if markdown else 2)
        chunks.append((heading, level, '\n'.join(lines[body_start:end]).strip()))
    return chunks


def sections_in_range(text: str, path: str, old: str | None, new: str) -> tuple[list[dict], bool]:
    """Sections whose version heading (own or inherited) overlaps (old, new]. Second value: file has version headings."""
    markdown = not path.lower().endswith('.rst')
    chunks = split_sections(text, markdown)
    stack: list[tuple[int, tuple | None]] = []
    picked, versioned = [], False
    for heading, level, body in chunks:
        while stack and stack[-1][0] >= level:
            stack.pop()
        match = VERSION_HEADING.match(heading)
        own = interval(match.group(1)) if match else None
        if own:
            versioned = True
        effective = own or next((iv for _, iv in reversed(stack) if iv), None)
        stack.append((level, own))
        if effective and (old is None or in_range(effective, old, new)) and (body or own):
            breaking = [line.strip() for line in (heading + '\n' + body).splitlines() if BREAKING_LINE.search(line)]
            picked.append({'heading': heading, 'body': body, 'breaking': breaking})
    return picked, versioned


def note_sections(text: str, path: str, old_text: str | None, old: str | None, new: str) -> tuple[list[dict], str]:
    """Sections worth reading, and how they were chosen: 'diff' against the old release, 'range' by version headings, 'whole'."""
    markdown = not path.lower().endswith('.rst')
    def with_breaking(heading, body):
        return {'heading': heading, 'body': body, 'breaking': [l.strip() for l in (heading + '\n' + body).splitlines() if BREAKING_LINE.search(l)]}
    if old_text is not None:
        chunks = split_sections(text, markdown)
        if chunks:
            known = {(h, b) for h, _, b in split_sections(old_text, markdown)}
            return [with_breaking(h, b) for h, _, b in chunks if (h, b) not in known and (b or h)], 'diff'
        import difflib
        added = [l[2:] for l in difflib.ndiff(old_text.splitlines(), text.splitlines()) if l.startswith('+ ')]
        return ([with_breaking('(lines added since the installed release)', '\n'.join(added))] if added else []), 'diff'
    if numeric(new) and (old is None or numeric(old)):
        sections, versioned = sections_in_range(text, path, old, new)
        if versioned:
            return sections, 'range'
    return [with_breaking('(whole file, no version headings)', text[:20000])], 'whole'


def literals(text: str) -> list[str]:
    """Code literals in Markdown or rst that look like PHP symbols."""
    found = set(re.findall(r'``([^`]+)``', text)) | set(re.findall(r'(?<!`)`([^`\n]+)`(?!`)', text)) | set(re.findall(r':php:`([^`]+)`', text))
    return sorted(f.strip() for f in found if re.search(r'\\\\|\\|::|->|\(\)$|^\$GLOBALS|^[A-Z][A-Z0-9_]{5,}$', f.strip()))


def own_hits(entry: dict, files: dict[str, list[str]]) -> list[dict]:
    hits = []
    for needle in needles(entry):
        for rel, lines in files.items():
            uses_class = needle['class'] and any(re.search(rf'\b{re.escape(needle["class"])}\b', l) for l in lines)
            for number, line in enumerate(lines, 1):
                if COMMENT.match(line) or not needle['pattern'].search(line):
                    continue
                strength = needle['strength']
                if needle['class']:
                    strength = 'strong' if uses_class and strength == 'strong' else 'weak'
                hits.append({'needle': needle['label'], 'strength': strength, 'file': rel, 'line': number, 'code': line.strip()[:160]})
    return hits[:20]


def wizards(tree: Tree | None, files: list[str]) -> dict[str, str]:
    if not tree:
        return {}
    out = {}
    for path in files:
        if WIZARD_PATH.search(path) and not SKIP_PATH.search(path):
            for identifier in WIZARD_ID.findall(tree.read(path)):
                out[identifier] = path
    return out


def hosting_path(url: str) -> tuple[str, str] | None:
    """('github.com', 'owner/repo') from https or ssh git URLs."""
    match = re.match(r'^(?:https?://(?:[^@/]+@)?|git@|ssh://git@)([^/:]+)[/:](.+?)(?:\.git)?/?$', url)
    return (match.group(1).lower(), match.group(2)) if match else None


def fetch_releases(url: str) -> list[dict]:
    """Release notes from GitHub or a GitLab-style host. Empty when unavailable, never fatal."""
    import json
    import shutil
    import urllib.parse
    import urllib.request
    where = hosting_path(url)
    if not where:
        return []
    host, path = where
    raw = None
    try:
        if host == 'github.com':
            if shutil.which('gh'):
                rc, out, _ = sh(f'gh api --paginate {shlex.quote(f"repos/{path}/releases?per_page=100")}', Path('.'), merge=False)
                if rc == 0:
                    raw = json.loads('[' + out.strip().replace('][', '],[') + ']') if out.strip() else []
                    raw = [r for page in raw for r in page] if raw and isinstance(raw[0], list) else raw
            if raw is None:
                request = urllib.request.Request(f'https://api.github.com/repos/{path}/releases?per_page=100',
                                                 headers={'User-Agent': 'upgrade-pilot', 'Accept': 'application/vnd.github+json'})
                raw = json.load(urllib.request.urlopen(request, timeout=30))
            return [{'tag': r.get('tag_name', ''), 'name': r.get('name') or '', 'body': r.get('body') or ''} for r in raw]
        request = urllib.request.Request(f'https://{host}/api/v4/projects/{urllib.parse.quote(path, safe="")}/releases?per_page=100',
                                         headers={'User-Agent': 'upgrade-pilot'})
        raw = json.load(urllib.request.urlopen(request, timeout=30))
        return [{'tag': r.get('tag_name', ''), 'name': r.get('name') or '', 'body': r.get('description') or ''} for r in raw]
    except Exception:
        return []


def releases_in_range(url: str, old: str | None, new: str) -> list[dict]:
    if not numeric(new) or (old and not numeric(old)):
        return []
    picked = []
    for release in fetch_releases(url):
        match = VERSION_TOKEN.fullmatch(release['tag'].strip())
        iv = interval(release['tag']) if match else None
        if not iv or (old and not in_range(iv, old, new)) or (not old and iv[0] > vtuple(clean(new))):
            continue
        breaking = [l.strip() for l in release['body'].splitlines() if BREAKING_LINE.search(l)]
        picked.append({**release, 'breaking': breaking, 'version': iv[0]})
    return sorted(picked, key=lambda r: r['version'])


def breaking_commits(tree_old: Tree | None, tree_new: Tree) -> list[str]:
    if not tree_old or not tree_new.repo:
        return []
    rc, out, _ = sh(f'git -C {shlex.quote(str(tree_new.repo))} log --format=%h%x09%s {shlex.quote(tree_old.ref)}..{shlex.quote(tree_new.ref)}',
                    tree_new.repo, merge=False)
    return [line for line in out.splitlines() if rc == 0 and BREAKING_SUBJECT.search(line.split('\t', 1)[-1])]


def inspect(flight: Flight, move: dict, before: dict, after: dict, own: dict[str, list[str]]) -> dict:
    old_tree, new_tree, origin = resolve_trees(flight, move, before, after)
    result = {**move, 'origin': origin, 'at': now(), 'typo3_changelog': [], 'notes': [], 'guides': [],
              'commits_breaking': [], 'releases': [], 'wizards_new': {}, 'hits': 0}
    if not new_tree:
        return result
    files = [f for f in new_tree.files() if not SKIP_PATH.search(f)]
    old_files = set(old_tree.files()) if old_tree else None
    old, new = move['from'], move['to']
    result['method'] = 'diff against the installed release' if old_tree else 'version headings (installed release not readable)'
    # TYPO3-style changelog directories
    for path in files:
        match = TYPO3_CHANGELOG.search(path)
        if not match:
            continue
        if old_files is not None:
            if path in old_files:
                continue
        elif numeric(new) and old and numeric(old):
            iv = interval(match.group(2))
            if not iv or not in_range(iv, old, new):
                continue
        text = new_tree.read(path)
        entry = parse_entry_text(Path(path).name, text)
        entry['php'] = sorted(set(entry['php']) | set(literals(text)))
        hits = own_hits(entry, own)
        result['typo3_changelog'].append({'version': match.group(2), 'type': match.group(3), 'file': path, 'title': entry['title'] or Path(path).stem,
                                         'text': text, 'hits': hits})
    result['typo3_changelog'].sort(key=lambda e: (TYPE_ORDER.get(e['type'], 9), vtuple(e['version'].replace('.x', '.999'))))
    # CHANGELOG / UPGRADE / MIGRATION / NEWS files
    for path in files:
        if not NOTE_FILE.search(path) or TYPO3_CHANGELOG.search(path):
            continue
        text = new_tree.read(path)
        old_text = old_tree.read(path) if old_files is not None and path in old_files else ('' if old_files is not None else None)
        if old_text is not None and old_text == text:
            continue
        sections, how = note_sections(text, path, old_text, old, new)
        if sections:
            hits = own_hits({'title': path, 'php': literals('\n'.join(s['body'] for s in sections)), 'typoscript': []}, own)
            result['notes'].append({'file': path, 'how': how, 'sections': sections, 'hits': hits})
    # Upgrade guides in the documentation
    for path in files:
        if not GUIDE_FILE.search(path) or TYPO3_CHANGELOG.search(path) or NOTE_FILE.search(path):
            continue
        numbers = [int(n) for n in re.findall(r'(\d+)', Path(path).stem)]
        changed = old_files is None or path not in old_files or old_tree.read(path) != new_tree.read(path)
        in_majors = numeric(old) and numeric(new) and any(vtuple(clean(old))[0] <= n <= vtuple(clean(new))[0] for n in numbers)
        relevant = changed or in_majors
        if relevant:
            text = new_tree.read(path)
            hits = own_hits({'title': path, 'php': literals(text), 'typoscript': []}, own)
            result['guides'].append({'file': path, 'text': text, 'hits': hits})
    result['commits_breaking'] = breaking_commits(old_tree, new_tree)
    source_url = result['origin'].split(' ')[1] if result['origin'].startswith('git ') else None
    result['releases'] = releases_in_range(source_url, old, new) if source_url else []
    new_wizards = wizards(new_tree, files)
    old_wizards = wizards(old_tree, old_tree.files()) if old_tree else {}
    result['wizards_new'] = {k: v for k, v in new_wizards.items() if k not in old_wizards}
    release_text = '\n'.join(r['body'] for r in result['releases'])
    release_hits = own_hits({'title': 'releases', 'php': literals(release_text), 'typoscript': []}, own) if release_text else []
    result['release_hits'] = release_hits
    result['hits'] = sum(len(e['hits']) for e in result['typo3_changelog'] + result['notes'] + result['guides']) + len(release_hits)
    return result


# -- output ----------------------------------------------------------------------------------

def package_markdown(result: dict) -> str:
    lines = [f'# {result["name"]} {result["from"] or "(new)"} -> {result["to"]} ({result["kind"]}, {result.get("type") or "?"})', '',
             f'Source: {result["origin"]}', f'Selection: {result.get("method", "")}', '']
    if result.get('abandoned'):
        lines += [f'**Abandoned.** Replacement: {result["abandoned"] if isinstance(result["abandoned"], str) else "none suggested"}', '']
    if result['wizards_new']:
        lines += ['## New upgrade wizards in this range', ''] + [f'- `{k}` ({v})' for k, v in result['wizards_new'].items()] + ['']
    if result['commits_breaking']:
        lines += ['## Commits flagged as breaking', ''] + [f'- {c}' for c in result['commits_breaking']] + ['']
    for entry in result['typo3_changelog']:
        lines += [f'## {entry["type"]} ({entry["version"]}): {entry["title"]}', '', f'`{entry["file"]}`', '']
        lines += [f'- own code: {h["file"]}:{h["line"]} ({h["needle"]}, {h["strength"]})' for h in entry['hits']]
        lines += ['', '```rst', entry['text'].strip(), '```', '']
    for note in result['notes']:
        lines += [f'## {note["file"]} ({ {"diff": "new or changed since the installed release", "range": "sections in the version range", "whole": "whole file"}[note["how"]] })', '']
        lines += [f'- own code: {h["file"]}:{h["line"]} ({h["needle"]})' for h in note['hits']]
        for section in note['sections']:
            lines += [f'### {section["heading"]}', '', section['body'], '']
    if result.get('releases'):
        lines += ['## Release notes on the hosting platform', '']
        lines += [f'- own code: {h["file"]}:{h["line"]} ({h["needle"]})' for h in result.get('release_hits', [])]
        for release in result['releases']:
            lines += ['', f'### {release["tag"]}' + (f': {release["name"]}' if release['name'] and release['name'] != release['tag'] else ''), '',
                      release['body'].strip() or '_empty_']
        lines.append('')
    for guide in result['guides']:
        lines += [f'## Guide: {guide["file"]}', '']
        lines += [f'- own code: {h["file"]}:{h["line"]} ({h["needle"]})' for h in guide['hits']]
        lines += ['', guide['text'].strip(), '']
    if not (result['typo3_changelog'] or result['notes'] or result['guides'] or result['commits_breaking'] or result.get('releases')):
        lines += ['_No changelog, upgrade notes or breaking commits found for this range. Check the project page or '
                  'release notes on the hosting platform by hand._', '']
    return '\n'.join(lines) + '\n'


def summary_line(result: dict) -> str:
    counts: dict[str, int] = {}
    for entry in result['typo3_changelog']:
        counts[entry['type']] = counts.get(entry['type'], 0) + 1
    parts = []
    if counts:
        parts.append('changelog ' + ', '.join(f'{v} {k}' for k, v in sorted(counts.items(), key=lambda kv: TYPE_ORDER.get(kv[0], 9))))
    notes_breaking = sum(len(s['breaking']) for n in result['notes'] for s in n['sections'])
    if result['notes']:
        parts.append(f'{sum(len(n["sections"]) for n in result["notes"])} note section(s)' + (f' ({notes_breaking} breaking line(s))' if notes_breaking else ''))
    if result['guides']:
        parts.append(f'{len(result["guides"])} guide(s)')
    if result.get('releases'):
        releases_breaking = sum(len(r['breaking']) for r in result['releases'])
        parts.append(f'{len(result["releases"])} release note(s)' + (f' ({releases_breaking} breaking line(s))' if releases_breaking else ''))
    if result['commits_breaking']:
        parts.append(f'{len(result["commits_breaking"])} breaking commit(s)')
    if result['wizards_new']:
        parts.append(f'{len(result["wizards_new"])} new wizard(s)')
    if result['hits']:
        parts.append(f'{result["hits"]} hit(s) in own code')
    return '; '.join(parts) if parts else 'nothing documented found'


# -- commands ----------------------------------------------------------------------------------

def cmd_list(args) -> None:
    flight = Flight.load()
    if args.from_lock:
        moves, before = moves_from_locks(flight, args.from_lock), lock_at(flight, args.from_lock)
        origin = f'lock {args.from_lock} -> working tree'
    else:
        moves, before = moves_from_probe(flight), locked_packages(flight.root)
        origin = 'last bump probe'
    classified = classify(flight, moves, before)
    flight.log['dependencies'] = {'origin': origin, 'ref': args.from_lock, 'at': now(), 'moves': classified,
                                  'docs': flight.log.get('dependencies', {}).get('docs', {})}
    flight.event(f'deps list from {origin}: {len(classified)} third-party package(s) move')
    flight.save()
    chosen = {m['name'] for m in selected(classified, None, False)}
    print(f'third-party packages that move ({origin}): {len(classified)}, selected for docs by default: {len(chosen)}')
    for move in sorted(classified, key=lambda m: (m['name'] not in chosen, m['kind'] != 'major', m['name'])):
        flag = '*' if move['name'] in chosen else ' '
        marks = ','.join(filter(None, ['direct' if move.get('direct') else '', 'used by own code' if move.get('used') else '']))
        extra = (f' [{marks}]' if marks else '') + (' ABANDONED' if move.get('abandoned') else '')
        print(f' {flag} {move["kind"]:<9} {move["name"]:<45} {move["from"] or "-":>12} -> {move["to"] or "-":<12} {move.get("type") or "?"}{extra}')
    print('  * = read by "deps docs" by default: TYPO3 extensions, direct requirements with a major step or new,')
    print('      packages own code uses. --all or --package for more.')


def cmd_docs(args) -> None:
    flight = Flight.load()
    deps = flight.log.get('dependencies')
    if args.package and args.from_version and args.to_version:
        before, after = locked_packages(flight.root), locked_packages(flight.root)
        meta = composer_meta(flight, args.package[0], args.to_version, after)
        moves = [{'name': args.package[0], 'from': args.from_version, 'to': args.to_version,
                  'kind': kind_of(args.from_version, args.to_version), 'type': meta.get('type')}]
    else:
        if not deps:
            die('run upgrade-pilot deps list first (after bump probe, or --from-lock <ref> after the bump)')
        before = lock_at(flight, deps['ref']) if deps.get('ref') else locked_packages(flight.root)
        after = locked_packages(flight.root)
        moves = selected(deps['moves'], args.package, args.all)
    own = own_files(flight)
    out_dir = flight.dir / 'deps'
    out_dir.mkdir(parents=True, exist_ok=True)
    adhoc = bool(args.package and args.from_version and args.to_version)
    docs = {} if adhoc or not deps else deps.setdefault('docs', {})
    for move in moves:
        print(f'{move["name"]} {move["from"] or "(new)"} -> {move["to"]} ({move["kind"]})')
        result = inspect(flight, move, before, after, own)
        report = out_dir / f'{slug(move["name"])}-{slug(move["from"] or "new")}-{slug(move["to"])}.md'
        report.write_text(package_markdown(result), encoding='utf-8')
        write_json(report.with_suffix('.json'), result)
        line = summary_line(result)
        print(f'    source: {result["origin"]}')
        print(f'    {line}')
        for identifier, path in result['wizards_new'].items():
            print(f'    new wizard: {identifier} ({path})')
        print(f'    read: {flight.rel(report)}')
        docs[move['name']] = {'from': move['from'], 'to': move['to'], 'summary': line, 'report': flight.rel(report),
                              'wizards_new': list(result['wizards_new']), 'hits': result['hits'], 'at': now()}
    if deps and not adhoc:
        flight.log['dependencies'] = deps
    flight.event(f'deps docs: {len(moves)} package(s) read' + (' (ad hoc, not part of the flight\'s dependency list)' if adhoc else ''))
    flight.save()
