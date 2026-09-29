"""`init`: detect the project and open a flight log."""

from __future__ import annotations

import glob
import re
import shutil
from pathlib import Path

from .core import (DATA_DIR, PHP_DIR, STATE_DIR, TEMPLATE_DIR, Flight, die, git, git_branch, load_json, now, sh,
                   write_json)


def locked_packages(root: Path) -> dict[str, dict]:
    lock = load_json(root / 'composer.lock', {}) or {}
    packages = {}
    for section in ('packages', 'packages-dev'):
        for package in lock.get(section, []):
            packages[package['name']] = {**package, '_dev': section == 'packages-dev'}
    return packages


def version_of(packages: dict, name: str) -> str | None:
    package = packages.get(name)
    if not package:
        return None
    return package['version'].lstrip('v')


def major_minor(version: str) -> str:
    parts = version.split('.')
    return '.'.join(parts[:2]) if len(parts) > 1 else f'{parts[0]}.0'


def extension_key(composer: dict, path: Path) -> str:
    key = composer.get('extra', {}).get('typo3/cms', {}).get('extension-key')
    return key or path.name


def detect_extensions(root: Path, composer: dict) -> list[dict]:
    """Own extensions: the root itself (extension repository) or local path repositories."""
    found: dict[str, dict] = {}
    if composer.get('type') == 'typo3-cms-extension':
        found['.'] = {'key': extension_key(composer, root), 'path': '.', 'package': composer.get('name')}
    for repository in composer.get('repositories', []) if isinstance(composer.get('repositories'), list) else []:
        if repository.get('type') != 'path':
            continue
        for match in sorted(glob.glob(str(root / repository.get('url', '')))):
            ext_composer = load_json(Path(match) / 'composer.json', {}) or {}
            if ext_composer.get('type') != 'typo3-cms-extension':
                continue
            rel = str(Path(match).resolve().relative_to(root))
            found[rel] = {'key': extension_key(ext_composer, Path(match)), 'path': rel, 'package': ext_composer.get('name')}
    # Classic extensions committed into the project (not symlinked by composer).
    for ext_emconf in sorted(glob.glob(str(root / 'public/typo3conf/ext/*/ext_emconf.php'))):
        ext_dir = Path(ext_emconf).parent
        if ext_dir.is_symlink():
            continue
        rel = str(ext_dir.relative_to(root))
        found.setdefault(rel, {'key': ext_dir.name, 'path': rel, 'package': None})
    return list(found.values())


def detect_runtime(root: Path, exec_override: str | None, composer_override: str | None) -> dict:
    if exec_override:
        return {'kind': 'custom', 'exec': exec_override, 'composer': composer_override or exec_override.replace('{cmd}', 'composer')}
    if (root / '.ddev' / 'config.yaml').is_file():
        return {'kind': 'ddev', 'exec': 'ddev exec {cmd}', 'composer': composer_override or 'ddev composer'}
    if shutil.which('php'):
        return {'kind': 'local', 'exec': '{cmd}', 'composer': composer_override or 'composer'}
    die('cannot tell where PHP runs. Pass --exec "docker compose exec -T php sh -c {cmd}" (or similar) and --composer')
    return {}


def detect_tests(root: Path) -> dict:
    """Prefer the project's own runner. Otherwise point at PHPUnit configs and let a human confirm."""
    runner = root / 'Build' / 'Scripts' / 'runTests.sh'
    tests: dict[str, dict] = {}
    if runner.is_file():
        text = runner.read_text(encoding='utf-8', errors='replace')
        for suite in ('unit', 'functional', 'acceptance'):
            if re.search(rf'(^|\s|\|){suite}(\)|\s|\|)', text):
                tests[suite] = {'cmd': f'Build/Scripts/runTests.sh -s {suite}', 'where': 'host', 'confirmed': False}
                if suite == 'acceptance':
                    # Browser suites need their own setup, run them on purpose, not with "all".
                    tests[suite]['exclude_from_all'] = True
        if tests:
            return tests
    patterns = {
        'unit': ['Build/phpunit/UnitTests.xml', 'Build/UnitTests.xml', 'Tests/UnitTests.xml', 'phpunit.xml', 'phpunit.xml.dist'],
        'functional': ['Build/phpunit/FunctionalTests.xml', 'Build/FunctionalTests.xml', 'Tests/FunctionalTests.xml'],
    }
    for suite, candidates in patterns.items():
        for candidate in candidates:
            if (root / candidate).is_file():
                tests[suite] = {'cmd': f'vendor/bin/phpunit -c {candidate}', 'where': 'runtime', 'confirmed': False}
                break
    return tests


def probe_platform(flight: Flight, runtime: dict) -> dict:
    platform = {}
    rc, out, _, _ = flight.run_runtime('php -r "echo PHP_VERSION;"', merge=False)
    if rc == 0:
        platform['php'] = out.strip().splitlines()[-1] if out.strip() else None
    if runtime.get('kind') == 'ddev':
        rc, out, _ = sh('ddev describe -j', flight.root, merge=False)
        if rc == 0:
            from .core import extract_json
            raw = (extract_json(out) or {}).get('raw', {})
            if raw.get('database_type'):
                platform['database'] = f"{raw.get('database_type')} {raw.get('database_version')}"
    return platform


def fresh_checklist() -> dict:
    data = load_json(DATA_DIR / 'checklist.json')
    items = {}
    for phase, spec in data['phases'].items():
        for section in spec['sections']:
            for item in section['items']:
                items[item['id']] = {'status': 'open', 'note': '', 'evidence': '', 'at': None}
    return items


def exclude_state_dir(root: Path) -> None:
    exclude = git(root, 'rev-parse', '--git-path', 'info/exclude')
    if not exclude:
        return
    path = (root / exclude) if not Path(exclude).is_absolute() else Path(exclude)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding='utf-8') if path.is_file() else ''
    line = f'/{STATE_DIR}/'
    if line not in existing.splitlines():
        path.write_text(existing + ('' if existing.endswith('\n') or not existing else '\n') + line + '\n', encoding='utf-8')


def stage_helpers(flight: Flight) -> None:
    """PHP helpers must live inside the project: containers only mount the project."""
    target = flight.dir / 'bin'
    target.mkdir(parents=True, exist_ok=True)
    for helper in PHP_DIR.glob('*.php'):
        shutil.copy2(helper, target / helper.name)


def run(args) -> None:
    start = Path(args.project or '.').resolve()
    top = git(start, 'rev-parse', '--show-toplevel')
    root = Path(top) if top else start
    if not (root / 'composer.json').is_file():
        die(f'{root} has no composer.json. Composer-mode projects and extensions only.')
    if (root / STATE_DIR / 'config.json').is_file() and not args.force:
        die(f'a flight already exists in {root / STATE_DIR}. Use status, or --force to start over.')

    composer = load_json(root / 'composer.json', {})
    packages = locked_packages(root)
    installed = version_of(packages, 'typo3/cms-core')
    if not installed and not args.source:
        die('typo3/cms-core not found in composer.lock. Pass --source <major.minor>.')
    source = args.source or major_minor(installed)
    target = args.target
    if not re.fullmatch(r'\d+\.\d+', target):
        die('--target must look like 13.4')

    flight = Flight(root)
    runtime = detect_runtime(root, args.exec, args.composer)
    extensions = [
        {'key': Path(p).name, 'path': p, 'package': None} for p in args.ext
    ] if args.ext else detect_extensions(root, composer)
    if not extensions:
        die('no own extensions found. Pass --ext <path> (repeatable).')

    base = git_branch(root) or 'main'
    prefix = args.branch_prefix.rstrip('/')
    flight.config = {
        'schema': 1,
        'created': now(),
        'source': source,
        'source_installed': installed,
        'target': target,
        'base_branch': base,
        'branches': {
            'preflight': f'{prefix}/preflight-{source}',
            'flight': f'{prefix}/{target}',
        },
        'runtime': runtime,
        'gates': args.gates,
        'extensions': extensions,
        'tests': detect_tests(root),
        'tools': {
            'typo3': 'vendor/bin/typo3',
            'rector': 'vendor/bin/rector',
            'fractor': 'vendor/bin/fractor',
        },
        'installed_tools': {
            name: version_of(packages, package)
            for name, package in {
                'rector': 'rector/rector',
                'typo3-rector': 'ssch/typo3-rector',
                'fractor': 'a9f/fractor',
                'typo3-fractor': 'a9f/typo3-fractor',
                'extension-scanner-cli': 'netresearch/extension-scanner-cli',
                'testing-framework': 'typo3/testing-framework',
                'typo3-console': 'helhum/typo3-console',
            }.items()
        },
    }
    flight.config['platform'] = probe_platform(flight, runtime)
    flight.log = {
        'schema': 1,
        'phase': 'preflight',
        'checklist': fresh_checklist(),
        'gates': {},
        'measurements': [],
        'scans': [],
        'tca': [],
        'campaigns': {},
        'events': [],
    }
    (flight.dir / 'tmp').mkdir(parents=True, exist_ok=True)
    exclude_state_dir(root)
    stage_helpers(flight)
    for template in TEMPLATE_DIR.glob('*.md'):
        destination = flight.dir / template.name
        if not destination.exists():
            text = template.read_text(encoding='utf-8')
            destination.write_text(text.replace('{source}', source).replace('{target}', target), encoding='utf-8')
    flight.event(f'Flight opened: TYPO3 {installed or source} -> {target}, base branch {base}')
    flight.save()

    print(f'Flight opened in {flight.rel(flight.dir)}/ (git-excluded)')
    print(f'  TYPO3 {installed or source} -> {target}   runtime: {runtime["kind"]}   gates: {args.gates}')
    print(f'  base branch {base}, preflight branch {flight.config["branches"]["preflight"]}, flight branch {flight.config["branches"]["flight"]}')
    print('  own extensions:')
    for ext in extensions:
        print(f'    - {ext["key"]:<24} {ext["path"]}')
    print('  tests (confirm or edit in config.json -> tests):')
    for suite, spec in flight.config['tests'].items():
        print(f'    - {suite:<11} [{spec["where"]}] {spec["cmd"]}')
    if not flight.config['tests']:
        print('    - none detected. Configure tests before the baseline measurement.')
    missing = [name for name, version in flight.config['installed_tools'].items() if not version and name not in ('testing-framework', 'typo3-console')]
    if missing:
        print('  tooling not installed: ' + ', '.join(missing))
