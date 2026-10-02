"""Composer patches of the project, read the way the installed patch plugin reads them, and checked
against the target version of each patched package.

Two plugins are in use in TYPO3 projects, with different syntaxes (verified against their sources):

- cweagans/composer-patches 1.x: root `extra.patches` or `extra.patches-file`, compact
  `{"vendor/pkg": {"description": "path or url"}}`, no version constraints, strip levels 1, 0, 2, 4
  tried in that order (`extra.patchLevel` forces one), dependency patches only when patching is enabled.
- cweagans/composer-patches 2.x: root `extra.patches`, `patches.json` (or
  `extra.composer-patches.patches-file`), dependencies' `extra.patches`, compact or expanded
  (`[{"description", "url", "depth"}]`). One strip level (`depth`, `package-depths`, `default-patch-depth`,
  default 1). When `patches.lock.json` exists, it is what gets installed.
- vaimo/composer-patches: `extra.patches`, `extra.patches-file` (one or many), `extra.patches-search`
  (directories of `*.patch` files with `@package`, `@version`, `@level` header tags), the same under
  `extra.patcher`, in the root and in dependencies. Values: a source, `{"<constraint>": "source"}` or an
  object with `source`/`url`, `version`, `level`, `cwd`, `skip`. Paths are relative to the package that
  defines them. Strip levels 0, 1, 2 unless `level` forces one.

A patch is checked with `git apply --check` in a copy of the package's source at the target version:
it applies, it fails, it is already contained (it applies in reverse, the fix arrived upstream), or the
plugin would not apply it there (vaimo version constraint).
"""

from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import urllib.request
from pathlib import Path

from .core import Flight, load_json, now, sh, slug, write_json
from .init import locked_packages
from .platform import allows

PLUGINS = {'cweagans/composer-patches': 'cweagans', 'vaimo/composer-patches': 'vaimo'}
HEADER_TAG = re.compile(r'^@(\w+)\s*(.*)$')
GIT_META = re.compile(r'^(diff --git |index [0-9a-f]|new file mode|deleted file mode|similarity index|rename (from|to) |old mode|new mode)')
TAG_ALIASES = {'desc': 'label', 'description': 'label', 'reason': 'label', 'ticket': 'issue', 'issues': 'issue',
               'tickets': 'issue', 'constraint': 'version', 'target': 'package', 'module': 'package', 'targets': 'package',
               'links': 'link', 'reference': 'link', 'ref': 'link', 'url': 'link', 'mode': 'type'}


# -- which plugin ---------------------------------------------------------------------------------------

def detect(root: Path, lock: dict[str, dict] | None = None) -> dict | None:
    """{'plugin': 'cweagans'|'vaimo', 'major': int|None, 'version': str} of the installed patch plugin."""
    lock = lock if lock is not None else locked_packages(root)
    composer = load_json(root / 'composer.json', {}) or {}
    required = {**(composer.get('require') or {}), **(composer.get('require-dev') or {})}
    for name, plugin in PLUGINS.items():
        if name in lock or name in required:
            version = (lock.get(name) or {}).get('version') or required.get(name, '')
            match = re.search(r'(\d+)', version.lstrip('v^~'))
            return {'plugin': plugin, 'package': name, 'version': version, 'major': int(match.group(1)) if match else None}
    return None


# -- definitions ----------------------------------------------------------------------------------------

def definition(package: str, description: str, source: str, origin: str, owner: str, base: str, **extra) -> dict:
    return {'package': package, 'description': description, 'source': source, 'origin': origin, 'owner': owner,
            'base': base, 'levels': extra.pop('levels', None), 'version': extra.pop('version', None),
            'skip': extra.pop('skip', False), 'cwd': extra.pop('cwd', 'install'), 'notes': extra.pop('notes', [])}


def cweagans_definitions(root: Path, extra: dict, major: int | None, lock: dict[str, dict]) -> list[dict]:
    out = []
    v2 = (major or 1) >= 2
    config = extra.get('composer-patches') or {}
    package_depths = config.get('package-depths') or {}
    default_depth = config.get('default-patch-depth', 1)

    def levels_for(package: str, patch_depth=None) -> list[int]:
        if v2:
            if patch_depth is not None:
                return [int(patch_depth)]
            if package in package_depths:
                return [int(package_depths[package])]
            if package == 'drupal/core':
                return [2]
            return [int(default_depth)]
        forced = (extra.get('patchLevel') or {}).get(package)
        return [int(str(forced).lstrip('-p'))] if forced else [1, 0, 2, 4]

    def add(patches: dict, origin: str, owner: str):
        for package, defs in (patches or {}).items():
            if isinstance(defs, list):  # 2.x expanded form
                for d in defs:
                    if isinstance(d, dict) and d.get('url'):
                        out.append(definition(package, d.get('description', ''), d['url'], origin, owner, '.',
                                              levels=levels_for(package, d.get('depth'))))
            elif isinstance(defs, dict):
                for description, source in defs.items():
                    if isinstance(source, str):
                        out.append(definition(package, description, source, origin, owner, '.', levels=levels_for(package)))

    if v2 and (root / 'patches.lock.json').is_file():
        # 2.x installs from its lock when it exists: that is the truth, whatever composer.json says.
        locked = load_json(root / 'patches.lock.json', {}) or {}
        for d in locked.get('patches') or []:
            provenance = ((d.get('extra') or {}).get('provenance') or 'root')
            out.append(definition(d.get('package', ''), d.get('description', ''), d.get('url', ''), f'patches.lock.json ({provenance})',
                                  provenance.split(':', 1)[1] if provenance.startswith('dependency:') else 'root', '.',
                                  levels=[int(d['depth'])] if d.get('depth') is not None else levels_for(d.get('package', ''))))
        return out
    if extra.get('patches'):
        add(extra['patches'], 'composer.json extra.patches', 'root')
    patches_file = config.get('patches-file') if v2 else (extra.get('patches-file') if not extra.get('patches') else None)
    if v2 and not patches_file:
        patches_file = 'patches.json'
    if patches_file and (root / patches_file).is_file():
        add((load_json(root / patches_file, {}) or {}).get('patches'), patches_file, 'root')
    enabled = v2 or any(k in extra for k in ('patches', 'patches-ignore', 'patches-file')) or extra.get('enable-patching')
    ignored = set(config.get('ignore-dependency-patches') or [])
    if enabled:
        for name, package in lock.items():
            if name in ignored:
                continue
            dep_patches = (package.get('extra') or {}).get('patches')
            if isinstance(dep_patches, dict):
                add(dep_patches, f'{name} composer.json extra.patches', name)
    return out


def vaimo_value(package: str, label: str, value, origin: str, owner: str, base: str, shared: dict) -> dict | None:
    """One vaimo definition: string, {constraint: source}, or an object."""
    settings = {**shared}
    if isinstance(value, str):
        settings['source'] = value
    elif isinstance(value, dict):
        keys = set(value)
        known = {'source', 'url', 'version', 'depends', 'level', 'cwd', 'skip', 'local', 'after', 'before', 'sha1',
                 'label', 'issue', 'ticket', 'link', 'category', 'targets'}
        if keys and not keys & known and all(isinstance(v, str) for v in value.values()):
            constraint, source = next(iter(value.items()))  # {"<1.2.3": "file.patch"}
            settings.update({'version': constraint, 'source': source})
        else:
            settings.update(value)
    if not settings.get('source') and settings.get('url'):
        settings['source'] = settings['url']
    if not settings.get('source'):
        settings['source'] = slug(label) + '.patch'  # the plugin derives the file from the label
    source = settings['source']
    skip = bool(settings.get('skip')) or source.endswith('#skip')
    level = settings.get('level')
    notes = []
    if settings.get('depends'):
        notes.append(f'depends on {settings["depends"]}')
    if package == '*':
        notes.append('bundle patch, targets several packages')
    return definition(package, label, source.split('#skip')[0], origin, owner, base,
                      levels=[int(level)] if level not in (None, '') else [0, 1, 2],
                      version=settings.get('version'), skip=skip, cwd=settings.get('cwd') or 'install', notes=notes)


def vaimo_header(text: str) -> dict:
    """Header tags of a patch file: every line before the first ---/+++ line."""
    tags: dict = {'label': []}
    for line in text.splitlines():
        if line.startswith(('--- ', '+++ ')):
            break
        match = HEADER_TAG.match(line.strip())
        if match:
            key = TAG_ALIASES.get(match.group(1).lower(), match.group(1).lower())
            tags[key] = match.group(2).strip() if match.group(2).strip() else True
        elif line.strip() and not GIT_META.match(line):
            tags['label'].append(line.strip())
    tags['label'] = tags.get('label') if isinstance(tags.get('label'), str) else ' '.join(tags['label'])
    return tags


def vaimo_definitions(root: Path, extra: dict, owner: str, base: str) -> list[dict]:
    out = []
    patcher = extra.get('patcher') if isinstance(extra.get('patcher'), dict) else {}
    if extra.get('patcher') is False:
        return out

    def setting(key: str, mirrored: str):
        return extra.get(key) if extra.get(key) is not None else patcher.get(mirrored)

    def add(patches: dict, origin: str):
        shared = patches.get('_config') if isinstance(patches.get('_config'), dict) else {}
        for package, labels in patches.items():
            if package.startswith('_') or not isinstance(labels, dict):
                continue
            local_shared = {**shared, **(labels.get('_config') if isinstance(labels.get('_config'), dict) else {})}
            for label, value in labels.items():
                if label.startswith('_'):
                    continue
                d = vaimo_value(package, label, value, origin, owner, base, local_shared)
                if d:
                    out.append(d)

    for key in ('patches', 'patches-dev'):
        if isinstance(extra.get(key), dict):
            add(extra[key], f'{base}/composer.json extra.{key}'.lstrip('./'))
    for key, mirrored in (('patches-file', 'file'), ('patches-file-dev', 'file-dev')):
        files = setting(key, mirrored)
        for name in ([files] if isinstance(files, str) else files or []):
            data = load_json(root / base / name, {}) or {}
            add(data.get('patches') if isinstance(data.get('patches'), dict) else data, f'{base}/{name}'.lstrip('./'))
    for key, mirrored in (('patches-search', 'search'), ('patches-search-dev', 'search-dev')):
        dirs = setting(key, mirrored)
        for pattern in ([dirs] if isinstance(dirs, str) else dirs or []):
            for directory in glob.glob(str(root / base / pattern)):
                for path in sorted(Path(directory).rglob('*.patch')):
                    tags = vaimo_header(path.read_text(encoding='utf-8', errors='replace'))
                    package = tags.get('package')
                    if not isinstance(package, str):
                        continue
                    version = tags.get('version') if isinstance(tags.get('version'), str) else None
                    notes = []
                    if version and ':' in version and '/' in version.split(':', 1)[0]:
                        notes.append(f'version constraint on {version.split(":", 1)[0]}')
                        version = None
                    rel = str(path.relative_to(root / base))
                    level = tags.get('level')
                    out.append(definition(package, tags.get('label') or path.name, rel, f'{base}/{rel}'.lstrip('./'), owner, base,
                                          levels=[int(level)] if isinstance(level, str) and level.isdigit() else [0, 1, 2],
                                          version=version, skip=bool(tags.get('skip')), cwd=tags.get('cwd') or 'install',
                                          notes=notes + ([f'depends on {tags["depends"]}'] if tags.get('depends') else [])))
    return out


def definitions(root: Path, plugin: dict | None = None, lock: dict[str, dict] | None = None) -> list[dict]:
    lock = lock if lock is not None else locked_packages(root)
    plugin = plugin or detect(root, lock)
    if not plugin:
        return []
    extra = (load_json(root / 'composer.json', {}) or {}).get('extra') or {}
    if plugin['plugin'] == 'cweagans':
        return cweagans_definitions(root, extra, plugin.get('major'), lock)
    out = vaimo_definitions(root, extra, 'root', '.')
    for name, package in lock.items():
        dep_extra = package.get('extra') or {}
        if any(k in dep_extra for k in ('patches', 'patches-file', 'patches-search', 'patcher')):
            base = f'vendor/{name}'
            if (root / base).is_dir():
                out += vaimo_definitions(root, dep_extra, name, base)
    return out


# -- checking -------------------------------------------------------------------------------------------

def patch_file(flight: Flight, d: dict) -> Path | None:
    source = d['source']
    if re.match(r'^https?://', source):
        target = flight.dir / 'cache' / 'patches' / (slug(source.split('://', 1)[1])[:120] + '.patch')
        if not target.is_file():
            try:
                request = urllib.request.Request(source, headers={'User-Agent': 'upgrade-pilot'})
                with urllib.request.urlopen(request, timeout=30) as response:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(response.read())
            except Exception:
                return None
        return target
    path = flight.root / d['base'] / source
    return path if path.is_file() else None


def apply_check(directory: Path, patch: Path, levels: list[int], reverse: bool = False) -> int | None:
    """The first strip level at which the patch applies (or reverse-applies), else None.

    GIT_CEILING_DIRECTORIES keeps git from treating the project repository as the one to patch.
    """
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(directory.parent)}
    for level in levels:
        cmd = f'git apply --check {"-R " if reverse else ""}-p{level} {shlex.quote(str(patch))}'
        if sh(cmd, directory, env=env)[0] == 0:
            return level
    return None


def export_tree(repo: Path, ref: str, target: Path) -> bool:
    if target.is_dir():
        return True
    target.mkdir(parents=True, exist_ok=True)
    rc, _, _ = sh(f'git -C {shlex.quote(str(repo))} archive --format=tar {shlex.quote(ref)} | tar -x -C {shlex.quote(str(target))}', repo)
    if rc != 0:
        shutil.rmtree(target, ignore_errors=True)
    return rc == 0


def target_source(flight: Flight, name: str, target_version: str | None) -> tuple[Path | None, str]:
    """The package's source at the target version, from the deps git cache. (directory, description)."""
    from .deps import candidates, ensure_repo, first_commit
    from .touchpoints import deps_result
    result = deps_result(flight, name)
    repo, ref = (Path(result['repo']), result['new_ref']) if result else (None, None)
    if not repo:
        package = locked_packages(flight.root).get(name) or {}
        url = (package.get('source') or {}).get('url')
        move = next((m for m in (flight.log.get('dependencies') or {}).get('moves', []) if m['name'] == name), None)
        version = target_version or (move or {}).get('to')
        if not url or not version:
            return None, 'target source not known: run upgrade-pilot deps list (after a bump probe) first'
        repo = ensure_repo(flight, url, candidates((move or {}).get('to_ref'), version))
        ref = repo and first_commit(repo, candidates((move or {}).get('to_ref'), version))
        if not ref:
            return None, f'target source not readable ({url} at {version})'
    directory = flight.dir / 'tmp' / 'patch-check' / f'{slug(name)}-{ref[:12]}'
    return (directory, ref[:12]) if export_tree(repo, ref, directory) else (None, 'export of the target source failed')


def target_version_of(flight: Flight, name: str) -> str | None:
    from .touchpoints import deps_result
    result = deps_result(flight, name)
    if result:
        return result.get('to')
    move = next((m for m in (flight.log.get('dependencies') or {}).get('moves', []) if m['name'] == name), None)
    return (move or {}).get('to')


def check(flight: Flight, d: dict) -> dict:
    result = {**d, 'installed': 'unknown', 'target': 'unknown', 'detail': ''}
    lock = locked_packages(flight.root)
    if d['skip']:
        result.update({'installed': 'skipped', 'target': 'skipped', 'detail': 'marked as skipped'})
        return result
    if d['package'] == '*' or d['cwd'] != 'install':
        result['detail'] = 'bundle or non-default cwd: check by hand'
        return result
    patch = patch_file(flight, d)
    if not patch:
        result['detail'] = f'patch file not found: {d["source"]}'
        result['target'] = 'missing'
        return result
    installed_dir = flight.root / 'vendor' / d['package']
    installed_version = (lock.get(d['package']) or {}).get('version')
    if installed_dir.is_dir():
        level = apply_check(installed_dir, patch, d['levels'] or [1], reverse=True)
        result['installed'] = 'applied' if level is not None else ('applies' if apply_check(installed_dir, patch, d['levels'] or [1]) is not None
                                                                   else 'not applied')
    target_version = target_version_of(flight, d['package'])
    result['target_version'] = target_version
    if not target_version or target_version == installed_version:
        result['target'] = 'not moving'
        return result
    directory, info = target_source(flight, d['package'], target_version)
    levels = d['levels'] or [1]
    if d.get('version') and re.match(r'^v?\d', target_version) and not allows(d['version'], target_version.lstrip('v')):
        # The plugin will not apply it there. Fine if the change arrived upstream, lost otherwise.
        contained = bool(directory) and apply_check(directory, patch, levels, reverse=True) is not None
        result.update({'target': 'retired' if contained else 'out of range',
                       'detail': f'version constraint {d["version"]} excludes {target_version}: '
                                 + ('not applied there, and the change is in the target already' if contained
                                    else 'not applied there, the change is LOST unless it is solved otherwise')})
        return result
    if not directory:
        result['detail'] = info
        return result
    if apply_check(directory, patch, levels) is not None:
        result['target'] = 'applies'
    elif apply_check(directory, patch, levels, reverse=True) is not None:
        result.update({'target': 'contained', 'detail': 'applies in reverse: the change is already in the target, remove the patch'})
    else:
        result.update({'target': 'fails', 'detail': 'does not apply to the target: rebase it, or drop it if the fix landed differently'})
    return result


VERDICT = {'applies': 'ok', 'not moving': 'ok', 'skipped': 'ok', 'retired': 'ok', 'out of range': 'attention', 'contained': 'attention',
           'fails': 'attention', 'missing': 'attention', 'unknown': 'manual'}


def run(flight: Flight, packages: list[str] | None = None, label: str = 'check') -> dict:
    lock = locked_packages(flight.root)
    plugin = detect(flight.root, lock)
    defs = [d for d in definitions(flight.root, plugin, lock) if not packages or d['package'] in packages]
    results = [check(flight, d) for d in defs]
    for r in results:
        r['status'] = VERDICT.get(r['target'], 'manual')
    report = {'at': now(), 'plugin': plugin, 'patches': results}
    write_json(flight.dir / 'patches.json', report)
    flight.log.setdefault('patches', []).append({'label': label, 'plugin': plugin and f'{plugin["package"]} {plugin["version"]}',
                                                 'total': len(results),
                                                 'attention': sum(1 for r in results if r['status'] == 'attention'),
                                                 'manual': sum(1 for r in results if r['status'] == 'manual'), **flight.stamp()})
    return report


def cmd_patches(args) -> None:
    flight = Flight.load()
    report = run(flight, args.package, args.label)
    plugin = report['plugin']
    if not plugin:
        print('no composer patch plugin in the project (cweagans/composer-patches or vaimo/composer-patches)')
    else:
        print(f'patch plugin: {plugin["package"]} {plugin["version"]}')
    for r in report['patches']:
        print(f'  {r["package"]:<40} {r["description"][:60]}')
        print(f'    {r["origin"]}: {r["source"]}' + (f'  version {r["version"]}' if r.get('version') else ''))
        print(f'    installed: {r["installed"]}   target {r.get("target_version") or "?"}: {r["target"]}'
              + (f'  [{r["status"]}]' if r['status'] != 'ok' else '') + (f'  {r["detail"]}' if r['detail'] else ''))
        for note in r['notes']:
            print(f'    note: {note}')
    flight.event(f'patches {args.label}: {len(report["patches"])} checked')
    flight.save()
    print(f'\nfull report: {flight.rel(flight.dir / "patches.json")}')
