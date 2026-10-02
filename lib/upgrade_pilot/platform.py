"""Version facts (fetched, never assumed), the composer bump, local snapshots."""

from __future__ import annotations

import json
import re
import shlex
import urllib.request
from pathlib import Path

from .core import Flight, die, extract_json, git, load_json, now, sh, write_json

GET_TYPO3 = 'https://get.typo3.org/api/v1/major/{major}'
PACKAGIST = 'https://repo.packagist.org/p2/{name}.json'


def fetch_json(url: str):
    request = urllib.request.Request(url, headers={'User-Agent': 'upgrade-pilot (Claude Code plugin)'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def expand_minified(versions: list[dict]) -> list[dict]:
    """Packagist p2 metadata is minified: each entry only lists what changed."""
    expanded, current = [], {}
    for entry in versions:
        current = dict(current)
        for key, value in entry.items():
            if value == '__unset':
                current.pop(key, None)
            else:
                current[key] = value
        expanded.append(current)
    return expanded


def vtuple(version: str) -> tuple:
    parts = re.findall(r'\d+', version.split('@')[0])
    return tuple(int(p) for p in (parts + ['0', '0', '0'])[:3])


def atom_allows(atom: str, version: tuple) -> bool:
    atom = atom.strip().split('@')[0].lstrip('v')
    if not atom or atom == '*':
        return True
    match = re.match(r'^(\^|~|>=|<=|>|<|==|=|!=)?\s*([\d.*x]+)', atom)
    if not match:
        return False
    op, raw = match.group(1) or '', match.group(2)
    if '*' in raw or 'x' in raw:
        fixed = [int(p) for p in re.split(r'\.', raw) if p.isdigit()]
        return list(version[:len(fixed)]) == fixed
    target = vtuple(raw)
    count = len(raw.split('.'))
    if op == '^':
        upper = (target[0] + 1, 0, 0) if target[0] > 0 else (0, target[1] + 1, 0)
        return target <= version < upper
    if op == '~':
        upper = (target[0] + 1, 0, 0) if count <= 2 else (target[0], target[1] + 1, 0)
        return target <= version < upper
    return {'>=': version >= target, '<=': version <= target, '>': version > target, '<': version < target,
            '!=': version != target}.get(op, version[:count] == target[:count])


def allows(constraint: str, version: str) -> bool:
    candidate = vtuple(version)
    for alternative in re.split(r'\s*\|\|?\s*', constraint):
        atoms = [a for a in re.split(r'[\s,]+', alternative.strip()) if a]
        if atoms and all(atom_allows(a, candidate) for a in atoms):
            return True
    return False


def declared_branch_alias(name: str, version: str) -> dict:
    """Branch aliases a development version declares. composer show does not print extra, Packagist does (best effort)."""
    try:
        data = fetch_json(PACKAGIST.format(name=f'{name}~dev'))
    except Exception:  # not on Packagist, or offline: nothing to compare with
        return {}
    entry = next((v for v in expand_minified(data['packages'].get(name, [])) if v.get('version') == version), None)
    return ((entry or {}).get('extra') or {}).get('branch-alias') or {}


def packagist_versions(name: str) -> list[dict]:
    data = fetch_json(PACKAGIST.format(name=name))
    return [v for v in expand_minified(data['packages'][name]) if not v['version'].startswith('dev-')]


# Packages that follow the core. "latest": move to the newest major that supports the
# target (aligned with core LTS lines). "keep": only move when the current constraint
# allows no release that supports the target.
COMPANIONS = {
    'typo3/testing-framework': {'policy': 'latest', 'what': 'test framework'},
    'helhum/typo3-console': {'policy': 'keep', 'what': 'TYPO3 Console (database:updateschema and more)'},
}


def core_compatible(name: str, probes: list[str], php: str | None = None) -> list[str]:
    """Stable versions whose typo3/cms-core requirement allows every probe, and the PHP version if given."""
    out = []
    for version in packagist_versions(name):
        require = version.get('require', {})
        if not require.get('typo3/cms-core') or not all(allows(require['typo3/cms-core'], probe) for probe in probes):
            continue
        if php and require.get('php') and not allows(require['php'], php):
            continue
        out.append(version['version'])
    return sorted(out, key=vtuple)


def companion_facts(target_probe: str, source_installed: str | None, php: str | None = None) -> dict:
    """target_probe is a concrete core version, preferably the latest patch of the target line."""
    facts = {}
    for name in COMPANIONS:
        compatible = core_compatible(name, [target_probe], php)
        if not compatible:
            continue
        entry = {'latest_compatible': compatible[-1], 'constraint': f'^{vtuple(compatible[-1])[0]}',
                 'compatible': compatible}
        if source_installed:
            bridge = core_compatible(name, [source_installed, target_probe], php)
            if bridge:
                entry['bridge'] = {'latest': bridge[-1], 'constraint': f'^{vtuple(bridge[-1])[0]}.{vtuple(bridge[-1])[1]}'}
        facts[name] = entry
    return facts


def version_facts(target: str, source_installed: str | None = None, php: str | None = None) -> dict:
    major = target.split('.')[0]
    facts: dict = {'target': target, 'fetched': now()}
    info = fetch_json(GET_TYPO3.format(major=major))
    facts['support'] = {k: info.get(k) for k in ('title', 'release_date', 'maintained_until', 'elts_until')}
    facts['requirements'] = [r for r in info.get('requirements', []) if r.get('category') in ('php', 'database', 'composer')]
    core = [v for v in packagist_versions('typo3/cms-core') if v['version'].lstrip('v').startswith(target + '.')]
    if core:
        latest = max(core, key=lambda v: vtuple(v['version']))
        facts['core_latest'] = latest['version']
        facts['core_php'] = latest.get('require', {}).get('php')
    probe = (facts.get('core_latest') or f'{target}.0').lstrip('v')
    facts['companions'] = companion_facts(probe, source_installed, php)
    framework = facts['companions'].get('typo3/testing-framework')
    if framework:
        facts['testing_framework'] = {'latest_compatible': framework['latest_compatible'], 'constraint': framework['constraint']}
    return facts


def versions_packages(flight: Flight) -> None:
    """Packages scope: does the target fit the installed core and PHP?"""
    scope = flight.config['packages']
    core = (load_json(flight.root / 'composer.lock', {}) or {})
    core_version = next((p['version'].lstrip('v') for s in ('packages', 'packages-dev') for p in core.get(s, [])
                         if p['name'] == 'typo3/cms-core'), None)
    php = flight.config.get('platform', {}).get('php')
    composer = flight.config['runtime']['composer']
    facts = {}
    for name in scope['names']:
        rc, out, _ = sh(f'{composer} show --all --format=json {shlex.quote(name)} {shlex.quote(scope["to"])}', flight.root, merge=False)
        from .core import extract_json
        meta = (extract_json(out) or {}) if rc == 0 else {}
        requires = meta.get('requires') or meta.get('require') or {}
        alias = (meta.get('extra') or {}).get('branch-alias') or (declared_branch_alias(name, scope['to']) if scope.get('dev') else {})
        entry = {'version': (meta.get('versions') or [scope['to']])[0], 'core': requires.get('typo3/cms-core'), 'php': requires.get('php'),
                 'branch_alias': alias, 'abandoned': meta.get('abandoned'), 'source': (meta.get('source') or {}).get('url')}
        ok_core = entry['core'] is None or core_version is None or allows(entry['core'], core_version)
        ok_php = entry['php'] is None or php is None or allows(entry['php'], php)
        entry['fits'] = ok_core and ok_php
        facts[name] = entry
        print(f'{name} {scope["installed"].get(name)} -> {scope["to"]}' + (f' (branch alias {", ".join(alias.values())})' if alias else ''))
        print(f'  requires typo3/cms-core {entry["core"]} (installed {core_version}): {"ok" if ok_core else "NOT satisfied"}')
        print(f'  requires php {entry["php"]} (runtime {php}): {"ok" if ok_php else "NOT satisfied"}')
        if alias and scope['to'] not in alias:
            print(f'  WARNING: the branch alias is declared for {", ".join(alias)}, composer names this version {scope["to"]}: '
                  'the alias is not applied, constraints of other packages on the aliased version will not match it')
        if meta == {}:
            print('  composer could not describe this version: check the name and the target')
    flight.config.setdefault('facts', {})['packages'] = {'at': now(), 'core': core_version, 'php': php, 'packages': facts}
    flight.event(f'versions (packages): {sum(1 for f in facts.values() if f["fits"])} of {len(facts)} fit core {core_version} and PHP {php}')
    flight.save()


def cmd_versions(args) -> None:
    flight = Flight.load()
    if flight.config.get('scope') == 'packages' and not args.target:
        return versions_packages(flight)
    target = args.target or flight.config['target']
    installed = flight.config.get('source_installed')
    php = flight.config.get('platform', {}).get('php')
    facts = version_facts(target, installed if target != flight.config['source'] else None, php)
    source_facts = version_facts(flight.config['source'], php=php) if not args.target else None
    flight.config.setdefault('facts', {})[target] = facts
    if source_facts:
        flight.config['facts'][flight.config['source']] = source_facts
    flight.save()
    for label, data in ((flight.config['source'], source_facts), (target, facts)):
        if not data:
            continue
        support = data['support']
        print(f'TYPO3 {label}: {support.get("title")}, released {str(support.get("release_date"))[:10]}, '
              f'free support until {str(support.get("maintained_until"))[:10]}, ELTS until {str(support.get("elts_until"))[:10]}')
        print(f'  latest {data.get("core_latest")}, core requires php {data.get("core_php")}')
        for req in data['requirements']:
            print(f'  {req["category"]}/{req["name"]}: {req.get("min", "")} .. {req.get("max", "")}')
        for name, companion in data.get('companions', {}).items():
            line = f'  {name}: {companion["constraint"]} (latest compatible {companion["latest_compatible"]})'
            if companion.get('bridge'):
                line += f', supports {installed} and {label} too: {companion["bridge"]["constraint"]} (up to {companion["bridge"]["latest"]})'
            print(line)
    platform = flight.config.get('platform', {})
    composer = load_json(flight.root / 'composer.json', {})
    pinned = composer.get('config', {}).get('platform', {}).get('php')
    print(f'runtime php {platform.get("php")}, composer platform php {pinned or "(not pinned)"}')
    if facts.get('core_php') and platform.get('php') and not allows(facts['core_php'], platform['php']):
        print(f'  WARNING: runtime php {platform["php"]} does not satisfy {facts["core_php"]}. Move PHP first, on the current core.')
    if facts.get('core_php') and pinned and not allows(facts['core_php'], pinned):
        print(f'  WARNING: composer platform php {pinned} does not satisfy {facts["core_php"]}.')


# -- composer bump ---------------------------------------------------------------

def bump_constraint(constraint: str, target: str) -> str:
    return f'^{target}' if constraint != '@dev' and not constraint.startswith('dev-') else constraint


def companion_constraint(name: str, current: str, facts: dict) -> str | None:
    """New constraint for a companion package, or None to keep the current one."""
    companion = facts.get('companions', {}).get(name)
    if not companion or current.startswith('dev-') or current in ('@dev', '*'):
        return None
    if COMPANIONS[name]['policy'] == 'latest':
        return None if allows(current, companion['latest_compatible']) else companion['constraint']
    if any(allows(current, version) for version in companion['compatible']):
        return None
    return companion['constraint']


def planned_changes(flight: Flight, target: str) -> tuple[list[dict], list[tuple[Path, str, str]], list[str]]:
    """Constraint changes for composer.json files (done through composer), ext_emconf.php edits, warnings."""
    changes, emconf_edits, warnings = [], [], []
    facts = flight.config.get('facts', {}).get(target, {})
    dirs = ['.'] + [ext['path'] for ext in flight.extensions() if ext['path'] != '.']
    for directory in dirs:
        data = load_json(flight.root / directory / 'composer.json', None)
        if not data:
            continue
        for section in ('require', 'require-dev'):
            for name, constraint in (data.get(section) or {}).items():
                new = None
                if name.startswith('typo3/cms-') and name not in ('typo3/cms-composer-installers', 'typo3/cms-cli'):
                    bumped = bump_constraint(constraint, target)
                    new = bumped if bumped != constraint else None
                elif name in COMPANIONS:
                    new = companion_constraint(name, constraint, facts)
                    before_eight = not any(allows(constraint, probe) for probe in ('8.0.0', '8.99.0', '9.0.0', '9.99.0'))
                    if new and name == 'helhum/typo3-console' and before_eight and vtuple(new)[0] >= 8:
                        warnings.append('TYPO3 Console moves to 8.0 or newer: the typo3cms binary is gone, its commands run '
                                        'through vendor/bin/typo3. Update deployment scripts in the same change.')
                if new:
                    changes.append({'dir': directory, 'section': section, 'name': name, 'old': constraint, 'new': new})
    for ext in flight.extensions():
        emconf = flight.root / ext['path'] / 'ext_emconf.php'
        if emconf.is_file():
            text = emconf.read_text(encoding='utf-8')
            new_text = re.sub(r"(['\"]typo3['\"]\s*=>\s*['\"])[\d.]+-[\d.]+(['\"])", rf'\g<1>{target}.0-{target}.99\g<2>', text)
            if new_text != text:
                emconf_edits.append((emconf, text, new_text))
    return changes, emconf_edits, warnings


def require_commands(changes: list[dict]) -> list[str]:
    """One composer require --no-update per composer.json and section, runtime-neutral."""
    commands = []
    groups: dict[tuple[str, str], list[dict]] = {}
    for change in changes:
        groups.setdefault((change['dir'], change['section']), []).append(change)
    for (directory, section), items in groups.items():
        parts = ['composer', 'require', '--no-update']
        if section == 'require-dev':
            parts.append('--dev')
        if directory != '.':
            parts.append(f'--working-dir={directory}')
        parts += [shlex.quote(f'{c["name"]}:{c["new"]}') for c in items]
        commands.append(' '.join(parts))
    return commands


def composer_audit(flight: Flight, label: str) -> dict:
    """Security advisories and abandoned packages of the current composer.lock, from composer audit."""
    # Through the runtime's exec, not its composer wrapper: composer audit exits non-zero when it finds something,
    # and wrappers such as "ddev composer" drop the output of a failing command.
    rc, out, _, _ = flight.run_runtime('composer audit --locked --format=json --no-interaction', merge=False)
    data = extract_json(out)
    if not isinstance(data, dict):
        return {'label': label, 'error': f'composer audit gave no JSON (exit {rc})', 'advisories': {}, 'abandoned': {}}
    advisories = data.get('advisories') or {}
    if isinstance(advisories, list):  # composer prints [] when there is nothing
        advisories = {}
    abandoned = data.get('abandoned') or {}
    result = {'label': label, 'at': now(), 'advisories': advisories, 'abandoned': abandoned if isinstance(abandoned, dict) else {}}
    write_json(flight.dir / 'assess' / f'audit-{label}.json', result)
    return result


def probe_update(flight: Flight, update: str, audit: bool) -> tuple[int, str, Path, dict | None]:
    """Resolve the target graph without installing it. With audit, the target lock is written, audited and restored."""
    lock = flight.root / 'composer.lock'
    saved = lock.read_bytes() if lock.is_file() else None
    flags = ' --no-install --no-audit' if audit else ' --dry-run --no-audit'
    rc, out, log = flight.run_host(update + flags, log_name='bump-probe')
    result = None
    try:
        if audit and rc == 0:
            (flight.dir / 'assess').mkdir(parents=True, exist_ok=True)
            (flight.dir / 'assess' / 'target-composer.lock').write_bytes(lock.read_bytes())
            result = composer_audit(flight, 'target')
    finally:
        if saved is not None:
            lock.write_bytes(saved)
    return rc, out, log, result


def snapshot_files(root: Path, rels: list[str]) -> dict[str, bytes | None]:
    """The exact bytes of files before a probe touches them. Restoring these keeps uncommitted work, git checkout would not."""
    return {rel: ((root / rel).read_bytes() if (root / rel).is_file() else None) for rel in rels}


def restore_files(root: Path, saved: dict[str, bytes | None]) -> None:
    for rel, data in saved.items():
        if data is None:
            (root / rel).unlink(missing_ok=True)  # created by the probe, did not exist before
        else:
            (root / rel).write_bytes(data)


def run_composer(flight: Flight, command: str) -> tuple[int, str]:
    """command starts with "composer": run it through the configured composer of the runtime."""
    rc, out, _ = sh(flight.config['runtime']['composer'] + command[len('composer'):], flight.root)
    return rc, out


def package_changes(flight: Flight) -> tuple[list[str], list[str], list[str]]:
    """Packages scope: stability commands, require commands, the update command. All runtime-neutral."""
    scope = flight.config['packages']
    to = scope['to']
    stability = []
    if scope.get('dev') and scope.get('dev_stability') == 'minimum-stability':
        composer = load_json(flight.root / 'composer.json', {}) or {}
        if composer.get('minimum-stability') != 'dev':
            stability.append('composer config minimum-stability dev')
        if composer.get('prefer-stable') is not True:
            stability.append('composer config prefer-stable true')
    changes = []
    aliases = scope.get('aliases') or {}
    dirs = ['.'] + [ext['path'] for ext in flight.extensions() if ext['path'] != '.']
    for directory in dirs:
        data = load_json(flight.root / directory / 'composer.json', None) or {}
        for section in ('require', 'require-dev'):
            for name, constraint in (data.get(section) or {}).items():
                # Inline aliases only work in the root composer.json, so an own extension keeps the plain target.
                new = f'{to} as {aliases[name]}' if name in aliases and directory == '.' else to
                if name in scope['names'] and constraint != new:
                    changes.append({'dir': '.', 'section': section, 'name': name, 'old': constraint, 'new': new} if directory == '.'
                                   else {'dir': directory, 'section': section, 'name': name, 'old': constraint, 'new': new})
    root = load_json(flight.root / 'composer.json', {}) or {}
    for name, alias in aliases.items():
        if not any(name in (root.get(s) or {}) for s in ('require', 'require-dev')):
            changes.append({'dir': '.', 'section': 'require', 'name': name, 'old': None, 'new': f'{to} as {alias}'})
    if not changes and not any(name in (load_json(flight.root / d / 'composer.json', {}) or {}).get(s, {})
                               for d in dirs for s in ('require', 'require-dev') for name in scope['names']):
        die('none of the packages is a direct requirement of the project or an own extension. Name the package that '
            'pulls them in with --package, or require one of them first')
    update = 'composer update ' + ' '.join(shlex.quote(n) for n in scope['names']) + ' -W --no-interaction'
    return stability, require_commands(changes), update


def cmd_bump_packages(flight: Flight, args) -> None:
    aliases = dict(a.split('=', 1) for a in (args.alias or []) if '=' in a)
    unknown = sorted(set(aliases) - set(flight.config['packages']['names']))
    if unknown or len(aliases) != len(args.alias or []):
        die('--alias takes NAME=VERSION for a package of this flight, e.g. acme/shop-base=2.4.x-dev' + (f' (not in the flight: {", ".join(unknown)})' if unknown else ''))
    if aliases:
        # Remembered, so that apply repeats what the probe resolved with.
        flight.config['packages'].setdefault('aliases', {}).update(aliases)
        flight.save()
    stability, requires, update = package_changes(flight)
    commands = stability + requires
    print('composer commands:')
    for command in commands + [update]:
        print(f'  {command}')
    if args.mode == 'show':
        return
    touched = ['composer.json'] + [f'{ext["path"]}/composer.json' for ext in flight.extensions() if ext['path'] != '.']
    touched = [t for t in touched if (flight.root / t).is_file()]
    saved = snapshot_files(flight.root, touched)
    for command in commands:
        rc, out = run_composer(flight, command)
        if rc != 0:
            restore_files(flight.root, saved)
            die(f'{command} failed, files restored:\n{out[-2000:]}')
    if args.mode == 'probe':
        composer = flight.config['runtime']['composer']
        rc, out, log, audit = probe_update(flight, composer + update[len('composer'):], bool(getattr(args, 'audit', False)))
        restore_files(flight.root, saved)
        report_audit(flight, audit)
        verdict = 'resolves' if rc == 0 else 'does NOT resolve'
        flight.log.setdefault('probes', []).append({'target': flight.config['packages']['to'], 'exit': rc, 'log': flight.rel(log),
                                                    'at': now(), 'commands': commands + [update]})
        flight.event(f'bump probe to {flight.config["packages"]["to"]}: {verdict} (exit {rc})')
        flight.save()
        print(f'\nbump probe: {verdict} (exit {rc}). Files restored. Log: {flight.rel(log)}')
        problems = re.findall(r'(Problem \d+[\s\S]*?)(?=\n\s*Problem \d+|\n\n)', out)
        for problem in problems[:10]:
            print('  ' + problem.strip().replace('\n', '\n  '))
        if rc != 0 and not problems:
            print(out[-3000:])
        if rc != 0:
            alias_hints(flight, out)
        raise SystemExit(0 if rc == 0 else 1)
    from .commit import record_command
    for command in commands:
        record_command(flight, command)
    flight.event(f'bump applied for {flight.config["packages"]["to"]}: {len(commands)} composer command(s)')
    flight.save()
    print(f'\napplied and recorded for the commit. Next: upgrade-pilot composer {update[len("composer "):]}')


def report_audit(flight: Flight, audit: dict | None) -> None:
    if not audit:
        return
    count = sum(len(v) for v in audit['advisories'].values())
    flight.log.setdefault('audits', []).append({'label': audit['label'], 'advisories': count,
                                                'packages': sorted(audit['advisories']), **flight.stamp()})
    print(f'composer audit of the target graph: {count} advisory(ies) in {len(audit["advisories"])} package(s)')


def ignored_aliases(facts: dict, to: str) -> dict[str, str]:
    """Branch aliases declared for another version name than the target: composer does not apply them."""
    out = {}
    for name, fact in facts.items():
        declared = fact.get('branch_alias') or {}
        if declared and to not in declared:
            out[name] = ', '.join(f'{k} -> {v}' for k, v in declared.items())
    return out


def alias_hints(flight: Flight, output: str) -> None:
    """A package of the flight required in a range its development branch does not reach: say why and what helps."""
    scope = flight.config.get('packages')
    if not scope:
        return  # core scope: no development targets of its own
    facts = (flight.config.get('facts', {}).get('packages') or {}).get('packages', {})
    ignored = ignored_aliases(facts, scope['to'])
    for required, constraint in sorted(set(re.findall(r'requires (\S+) (\S+) -> found \1\[[^\]]*\] but it does not match the constraint', output))):
        if required not in scope['names'] or required in (scope.get('aliases') or {}):
            continue
        print(f'\n  {required} {scope["to"]} does not satisfy {constraint}.')
        if required in ignored:
            print(f'  Its branch alias ({ignored[required]}) is declared for another version name than {scope["to"]}, so composer does not apply it.')
            print('  That is a packaging issue to report to the maintainers.')
        print('  Options: wait for a release, target another branch, or bridge it with an inline alias in the root composer.json')
        print(f'  (a deliberate, temporary decision): upgrade-pilot bump probe --alias {required}=<version matching {constraint}>')


def cmd_bump(args) -> None:
    flight = Flight.load()
    if flight.config.get('scope') == 'packages':
        return cmd_bump_packages(flight, args)
    target = flight.config['target']
    if target not in flight.config.get('facts', {}):
        die('run upgrade-pilot versions first, the bump uses its testing-framework and PHP facts')
    changes, emconf_edits, warnings = planned_changes(flight, target)
    for warning in warnings:
        print(f'WARNING: {warning}')
    commands = require_commands(changes)
    if not commands and not emconf_edits:
        print('nothing to change, constraints already on target')
    for change in changes:
        print(f'  {change["dir"]}/composer.json {change["section"]}: {change["name"]} {change["old"]} -> {change["new"]}')
    for path, old, new in emconf_edits:
        print(f'  {flight.rel(path)}: ' + '; '.join(f'{a.strip()} -> {b.strip()}' for a, b in zip(old.splitlines(), new.splitlines()) if a != b))
    if commands:
        print('composer commands:')
        for command in commands:
            print(f'  {command}')
    if args.mode == 'show':
        return
    touched = sorted({f'{c["dir"]}/composer.json'.lstrip('./') if c['dir'] != '.' else 'composer.json' for c in changes}
                     | {flight.rel(p) for p, _, _ in emconf_edits})
    saved = snapshot_files(flight.root, touched)
    for command in commands:
        rc, out = run_composer(flight, command)
        if rc != 0:
            restore_files(flight.root, saved)
            die(f'{command} failed, files restored:\n{out[-2000:]}')
    for path, _, new in emconf_edits:
        path.write_text(new, encoding='utf-8')
    composer = flight.config['runtime']['composer']
    if args.mode == 'probe':
        rc, out, log, audit = probe_update(flight, f'{composer} update -W --no-interaction', bool(getattr(args, 'audit', False)))
        restore_files(flight.root, saved)
        report_audit(flight, audit)
        verdict = 'resolves' if rc == 0 else 'does NOT resolve'
        flight.log.setdefault('probes', []).append({'target': target, 'exit': rc, 'log': flight.rel(log), 'at': now(),
                                                    'commands': commands})
        flight.event(f'bump probe to {target}: {verdict} (exit {rc})')
        flight.save()
        print(f'\nbump probe: the target graph {verdict} (exit {rc}). Files restored. Log: {flight.rel(log)}')
        problems = re.findall(r'(Problem \d+[\s\S]*?)(?=\n\s*Problem \d+|\n\n)', out)
        for problem in problems[:10]:
            print('  ' + problem.strip().replace('\n', '\n  '))
        if rc != 0 and not problems:
            print(out[-3000:])
        if rc != 0:
            alias_hints(flight, out)
        raise SystemExit(0 if rc == 0 else 1)
    from .commit import record_command
    for command in commands:
        record_command(flight, command)
    flight.event(f'bump applied for {target}: {len(commands)} composer command(s), {len(emconf_edits)} ext_emconf.php edit(s)')
    flight.save()
    print(f'\napplied and recorded for the commit. Next: upgrade-pilot composer update -W   (read "Problem 1" carefully if it fails)')


# -- local backup ------------------------------------------------------------------

def cmd_snapshot(args) -> None:
    flight = Flight.load()
    kind = flight.config['runtime']['kind']
    name = args.name or f'upgrade-pilot-{flight.log.get("phase")}'
    if kind != 'ddev':
        die('automatic snapshots only for ddev. Take and verify a database + fileadmin backup by hand, then record it with item.')
    cmd = {'take': f'ddev snapshot --name {name}', 'restore': f'ddev snapshot restore {name}', 'list': 'ddev snapshot --list'}[args.action]
    rc, out, log = flight.run_host(cmd, log_name=f'snapshot-{args.action}-{name}')
    print(out[-2000:])
    if args.action != 'list':
        flight.log.setdefault('snapshots', []).append({'action': args.action, 'name': name, 'exit': rc, 'at': now()})
        flight.event(f'snapshot {args.action} {name}: exit {rc}')
        flight.save()
    raise SystemExit(rc)
