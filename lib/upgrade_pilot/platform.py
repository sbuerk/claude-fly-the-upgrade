"""Version facts (fetched, never assumed), the composer bump, local snapshots."""

from __future__ import annotations

import json
import re
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


def version_facts(target: str) -> dict:
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
    frameworks = []
    probe = f'{target}.0'
    for version in packagist_versions('typo3/testing-framework'):
        require = version.get('require', {}).get('typo3/cms-core')
        if require and allows(require, probe):
            frameworks.append(version['version'])
    if frameworks:
        best = max(frameworks, key=vtuple)
        facts['testing_framework'] = {'latest_compatible': best, 'constraint': f'^{vtuple(best)[0]}'}
    return facts


def cmd_versions(args) -> None:
    flight = Flight.load()
    target = args.target or flight.config['target']
    facts = version_facts(target)
    source_facts = version_facts(flight.config['source']) if not args.target else None
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
        if data.get('testing_framework'):
            print(f'  typo3/testing-framework: {data["testing_framework"]["constraint"]} (latest compatible {data["testing_framework"]["latest_compatible"]})')
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


def planned_edits(flight: Flight, target: str) -> list[tuple[Path, str, str]]:
    """(file, old text, new text) for composer.json files and ext_emconf.php of own extensions."""
    edits = []
    framework = flight.config.get('facts', {}).get(target, {}).get('testing_framework', {}).get('constraint')
    files = [flight.root / 'composer.json'] + [flight.root / ext['path'] / 'composer.json' for ext in flight.extensions() if ext['path'] != '.']
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        new = text
        for match in re.finditer(r'"(typo3/cms-[\w-]+)"\s*:\s*"([^"]+)"', text):
            name, constraint = match.group(1), match.group(2)
            if name in ('typo3/cms-composer-installers', 'typo3/cms-cli'):
                continue
            bumped = bump_constraint(constraint, target)
            if bumped != constraint:
                new = new.replace(match.group(0), match.group(0).replace(f'"{constraint}"', f'"{bumped}"'), 1)
        tf = re.search(r'"typo3/testing-framework"\s*:\s*"([^"]+)"', new)
        if tf and framework and not allows(tf.group(1), flight.config['facts'][target]['testing_framework']['latest_compatible']):
            new = new.replace(tf.group(0), tf.group(0).replace(f'"{tf.group(1)}"', f'"{framework}"'))
        if new != text:
            edits.append((path, text, new))
    for ext in flight.extensions():
        emconf = flight.root / ext['path'] / 'ext_emconf.php'
        if emconf.is_file():
            text = emconf.read_text(encoding='utf-8')
            new = re.sub(r"(['\"]typo3['\"]\s*=>\s*['\"])[\d.]+-[\d.]+(['\"])", rf'\g<1>{target}.0-{target}.99\g<2>', text)
            if new != text:
                edits.append((emconf, text, new))
    return edits


def cmd_bump(args) -> None:
    flight = Flight.load()
    target = flight.config['target']
    if target not in flight.config.get('facts', {}):
        die('run upgrade-pilot versions first, the bump uses its testing-framework and PHP facts')
    edits = planned_edits(flight, target)
    if not edits:
        print('nothing to edit, constraints already on target')
    for path, old, new in edits:
        print(f'--- {flight.rel(path)}')
        for a, b in zip(old.splitlines(), new.splitlines()):
            if a != b:
                print(f'  - {a.strip()}\n  + {b.strip()}')
    if args.mode == 'show':
        return
    for path, _, new in edits:
        path.write_text(new, encoding='utf-8')
    composer = flight.config['runtime']['composer']
    if args.mode == 'probe':
        rc, out, log = flight.run_host(f'{composer} update -W --dry-run --no-interaction --no-audit', log_name='bump-probe')
        for path, old, _ in edits:
            path.write_text(old, encoding='utf-8')
        verdict = 'resolves' if rc == 0 else 'does NOT resolve'
        flight.log.setdefault('probes', []).append({'target': target, 'exit': rc, 'log': flight.rel(log), 'at': now()})
        flight.event(f'bump probe to {target}: {verdict} (exit {rc})')
        flight.save()
        print(f'\nbump probe: the target graph {verdict} (exit {rc}). Files restored. Log: {flight.rel(log)}')
        problems = re.findall(r'(Problem \d+[\s\S]*?)(?=\n\s*Problem \d+|\n\n)', out)
        for problem in problems[:10]:
            print('  ' + problem.strip().replace('\n', '\n  '))
        if rc != 0 and not problems:
            print(out[-3000:])
        raise SystemExit(0 if rc == 0 else 1)
    flight.event(f'bump applied: {len(edits)} file(s) edited for {target}')
    flight.save()
    print(f'\n{len(edits)} file(s) edited. Now run: {composer} update -W   (read "Problem 1" carefully if it fails)')


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
