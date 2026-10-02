"""Deployment and CI: what the scripts that build, test and ship the project assume about it.

An upgrade is not done when the code runs locally. CI images pin PHP versions, deployment recipes call
CLI commands that may not exist on the target, and the `typo3cms` binary of TYPO3 Console disappears
with Console 8. This module finds those places and checks them against facts the flight already has:

- PHP versions in CI and deployment files against the PHP range of the target core
- `typo3cms` against the TYPO3 Console version the flight moves to (or its absence)
- `typo3 <command>` calls against the command list of the instance (`typo3 list --format=json`): in the
  pre-flight that is the source version, after the upgrade the target version
- composer calls that switch off platform checks
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .core import Flight, extract_json, load_json, now, write_json
from .platform import allows, vtuple

CANDIDATES = [
    '.github/workflows/*.yml', '.github/workflows/*.yaml', '.gitlab-ci.yml', '.gitlab/**/*.yml', '.gitlab/**/*.yaml',
    'bitbucket-pipelines.yml', 'Jenkinsfile', 'Jenkinsfile.*', '.circleci/config.yml', 'azure-pipelines.yml', '.drone.yml',
    '.woodpecker.yml', '.woodpecker/*.yml', 'deploy.php', 'deploy.yaml', 'deploy.yml', 'hosts.yml', '.deployer/**/*.php',
    '.surf/**/*.php', 'Build/Surf/**/*.php', '.mage.yml', '.mage/**/*.yml', 'Makefile', 'Dockerfile', 'Dockerfile.*',
    '**/Dockerfile', 'docker-compose*.yml', 'docker-compose*.yaml', 'compose*.yml', 'compose*.yaml', '.ddev/config.yaml',
    '.ddev/config.*.yaml', '.platform.app.yaml', '.upsun/config.yaml', '.platform/*.yaml', 'scripts/**/*.sh',
    'bin/*.sh', 'deploy/**/*', 'Build/**/*.sh', '*.sh', '.env.dist', 'ansible/**/*.yml',
]
SKIP_PARTS = {'vendor', 'node_modules', '.git', 'public', 'var', '.upgrade-pilot', '.Build'}
PHP_VERSION = [
    re.compile(r'php[-_]?version["\']?\s*[:=]\s*["\']?(\d\.\d+)', re.I),            # setup-php, ddev php_version
    re.compile(r'\bphp(?:-fpm|-cli|-apache)?:(\d\.\d+)'),                              # image: php:8.2-fpm
    re.compile(r'\bphp(\d)(\d)\b(?!\d)'),                                               # core-testing-php82, php82
    re.compile(r'\bphp(\d\.\d+)(?:-fpm|-cli)?\b'),                                       # php8.2, php8.2-fpm
    re.compile(r'PHP_VERSION\s*[:=]\s*["\']?(\d\.\d+)'),
    re.compile(r'php:\s*\[\s*((?:["\']?\d\.\d+["\']?\s*,?\s*)+)\]'),                     # matrix php: ['8.1', '8.2']
]
# A call: the binary by path (vendor/bin/typo3), or by name with a namespaced command (typo3 cache:flush).
# Prose such as "typo3 is upgraded" matches neither.
TYPO3_CALL = re.compile(r'(?:(?P<path>[\w./{}-]*bin/)|(?:^|(?<=[\s"\';&|(])))(?P<bin>typo3cms|typo3)(?:\.php)?\s+(?P<cmd>[a-z][\w-]*(?::[\w:-]+)?)')


def typo3_calls(line: str) -> list[tuple[str, str]]:
    return [(m.group('bin'), m.group('cmd')) for m in TYPO3_CALL.finditer(line) if m.group('path') or ':' in m.group('cmd')]
PLATFORM_FLAGS = re.compile(r'--ignore-platform-reqs?\b(=[\w*-]+)?')


def files(root: Path) -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in CANDIDATES:
        for path in root.glob(pattern):
            rel = path.relative_to(root)
            if path.is_file() and not set(rel.parts[:-1]) & SKIP_PARTS and path.stat().st_size < 512_000:
                found[str(rel)] = path
    return [found[k] for k in sorted(found)]


def php_versions(line: str) -> list[str]:
    out = []
    for pattern in PHP_VERSION:
        for match in pattern.finditer(line):
            if pattern.pattern.startswith(r'\bphp(\d)(\d)'):
                out.append(f'{match.group(1)}.{match.group(2)}')
            elif pattern.pattern.startswith('php:\\s*\\['):
                out += re.findall(r'\d\.\d+', match.group(1))
            else:
                out.append(match.group(1))
    return sorted(set(v for v in out if 5 <= int(v.split('.')[0]) <= 9), key=vtuple)


def php_range(flight: Flight) -> str | None:
    target = flight.config.get('target')
    facts = (flight.config.get('facts') or {}).get(target) or {}
    return facts.get('core_php')


def console_target(flight: Flight) -> dict:
    """What happens to TYPO3 Console: installed now, and the constraint the flight moves it to."""
    from .init import locked_packages
    installed = (locked_packages(flight.root).get('helhum/typo3-console') or {}).get('version')
    facts = ((flight.config.get('facts') or {}).get(flight.config.get('target')) or {}).get('companions', {}).get('helhum/typo3-console')
    return {'installed': installed, 'target': facts and facts.get('constraint')}


def command_list(flight: Flight) -> list[str] | None:
    """Commands the instance knows right now, from `typo3 list --format=json`."""
    rc, out, _, _ = flight.run_runtime(f'{flight.tool("typo3")} list --format=json', merge=False)
    data = extract_json(out) if rc == 0 else None
    if not isinstance(data, dict):
        return None
    return sorted(c['name'] for c in data.get('commands', []) if c.get('name'))


def scan(flight: Flight, known: list[str] | None) -> list[dict]:
    php_req = php_range(flight)
    console = console_target(flight)
    console_major = vtuple(console['target'].lstrip('^~'))[0] if console.get('target') else None
    findings = []

    def add(kind, path, number, line, verdict, message):
        findings.append({'kind': kind, 'file': str(path.relative_to(flight.root)), 'line': number, 'code': line.strip()[:200],
                         'status': verdict, 'message': message})

    for path in files(flight.root):
        text = path.read_text(encoding='utf-8', errors='replace')
        for number, line in enumerate(text.splitlines(), 1):
            for version in php_versions(line):
                if php_req:
                    ok = allows(php_req, f'{version}.99') or allows(php_req, f'{version}.0')
                    add('php', path, number, line, 'ok' if ok else 'attention',
                        f'PHP {version}: ' + ('within' if ok else 'OUTSIDE') + f' the target core range {php_req}')
                else:
                    add('php', path, number, line, 'manual', f'PHP {version}: run upgrade-pilot versions to compare with the target')
            for binary, command in typo3_calls(line):
                if binary == 'typo3cms':
                    if console.get('installed') and not (flight.root / 'vendor' / 'bin' / 'typo3cms').exists():
                        add('binary', path, number, line, 'attention',
                            f'typo3cms does not exist with the installed TYPO3 Console {console["installed"]} (no vendor/bin/typo3cms): '
                            f'this call fails today already, call typo3 {command}')
                    elif console_major is not None and console_major >= 8:
                        add('binary', path, number, line, 'attention',
                            f'typo3cms is gone in TYPO3 Console 8 and later (the flight moves to {console["target"]}): call typo3 {command}')
                    elif not console.get('installed'):
                        add('binary', path, number, line, 'attention', 'typo3cms needs TYPO3 Console, which is not installed')
                    else:
                        add('binary', path, number, line, 'manual', f'typo3cms {command}: check the Console version on the target')
                if known is not None:
                    status = 'ok' if command in known else 'attention'
                    add('command', path, number, line, status,
                        f'{binary} {command}: ' + ('known to this instance' if status == 'ok'
                                                   else 'NOT known to this instance (removed, renamed, or from a package that is not installed)'))
            for match in PLATFORM_FLAGS.finditer(line):
                add('platform', path, number, line, 'manual',
                    f'composer {match.group(0)}: platform checks are switched off here, the target PHP range is not enforced')
    return findings


def run(flight: Flight, label: str) -> dict:
    known = command_list(flight)
    findings = scan(flight, known)
    commands = sorted({f['message'].split(':')[0] for f in findings if f['kind'] == 'command'})
    report = {'at': now(), 'label': label, 'files': [str(p.relative_to(flight.root)) for p in files(flight.root)],
              'commands_known': known is not None, 'commands_used': commands, 'php_range': php_range(flight),
              'console': console_target(flight), 'findings': findings}
    write_json(flight.dir / 'delivery.json', report)
    flight.log.setdefault('delivery', []).append({'label': label, 'files': len(report['files']), 'findings': len(findings),
                                                  'attention': sum(1 for f in findings if f['status'] == 'attention'),
                                                  'manual': sum(1 for f in findings if f['status'] == 'manual'), **flight.stamp()})
    return report


def cmd_delivery(args) -> None:
    flight = Flight.load()
    report = run(flight, args.label)
    print(f'deployment and CI files: {len(report["files"])}' + (f' ({", ".join(report["files"][:8])}{" ..." if len(report["files"]) > 8 else ""})' if report['files'] else ''))
    if not report['commands_known']:
        print('  WARNING: the instance did not list its commands (typo3 list --format=json failed), commands are not checked')
    print(f'  target core PHP range: {report["php_range"] or "unknown, run upgrade-pilot versions"}   '
          f'TYPO3 Console: installed {report["console"]["installed"] or "no"}, target {report["console"]["target"] or "-"}')
    for f in report['findings']:
        if f['status'] == 'ok' and not args.verbose:
            continue
        print(f'  {f["status"]:<9} {f["file"]}:{f["line"]}  {f["message"]}')
    attention = sum(1 for f in report['findings'] if f['status'] == 'attention')
    print(f'\n{len(report["findings"])} finding(s), {attention} need attention. Full report: {flight.rel(flight.dir / "delivery.json")}')
    flight.event(f'delivery {args.label}: {len(report["findings"])} finding(s), {attention} need attention')
    flight.save()
