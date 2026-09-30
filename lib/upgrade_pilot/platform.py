"""Version facts (fetched, never assumed), the composer bump, local snapshots."""

from __future__ import annotations

import json
import re
import shlex
import urllib.request
from pathlib import Path

from .core import Flight, die, git, load_json, now, sh, write_json

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


def cmd_versions(args) -> None:
    flight = Flight.load()
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


def run_composer(flight: Flight, command: str) -> tuple[int, str]:
    """command starts with "composer": run it through the configured composer of the runtime."""
    rc, out, _ = sh(flight.config['runtime']['composer'] + command[len('composer'):], flight.root)
    return rc, out


def cmd_bump(args) -> None:
    flight = Flight.load()
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
    for command in commands:
        rc, out = run_composer(flight, command)
        if rc != 0:
            sh('git checkout -- ' + ' '.join(shlex.quote(t) for t in touched), flight.root)
            die(f'{command} failed, files restored:\n{out[-2000:]}')
    for path, _, new in emconf_edits:
        path.write_text(new, encoding='utf-8')
    composer = flight.config['runtime']['composer']
    if args.mode == 'probe':
        rc, out, log = flight.run_host(f'{composer} update -W --dry-run --no-interaction --no-audit', log_name='bump-probe')
        sh('git checkout -- ' + ' '.join(shlex.quote(t) for t in touched), flight.root)
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
