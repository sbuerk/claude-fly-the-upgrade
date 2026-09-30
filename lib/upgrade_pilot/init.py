"""`init`: detect the project and open a flight log."""

from __future__ import annotations

import glob
import json
import re
import shlex
import shutil
from pathlib import Path

from .core import (DATA_DIR, PHP_DIR, STATE_DIR, TEMPLATE_DIR, Flight, checklist_file, die, flight_title, git, git_branch,
                   load_json, now, sh, slug, write_json)


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


DIRENV_STATES = {'0': 'allowed', 'true': 'allowed', '1': 'not allowed yet', 'false': 'not allowed yet', '2': 'denied'}


def envrc_dir(root: Path) -> Path | None:
    """direnv applies an .envrc of the project folder or of a parent. Look in the root and one level up."""
    for candidate in (root, root.parent):
        if (candidate / '.envrc').is_file():
            return candidate
    return None


ANSI = re.compile(r'\x1b\[[0-9;]*m')


def first_line(text: str, prefer: str | None = None) -> str | None:
    """The meaningful line of a tool's output: the one containing prefer, else the last one. No colours, no direnv noise."""
    lines = [ANSI.sub('', line).strip() for line in text.strip().splitlines()]
    lines = [line for line in lines if line and not line.startswith('direnv:')]
    if prefer:
        match = next((line for line in lines if prefer in line), None)
        if match:
            return match
    return lines[-1] if lines else None


def probe_direnv(root: Path) -> dict:
    """Is an .envrc there, is direnv installed, is the .envrc allowed, do php and composer work inside it?"""
    directory = envrc_dir(root)
    info = {'envrc': str(directory / '.envrc') if directory else None, 'installed': bool(shutil.which('direnv')),
            'allowed': None, 'php': None, 'composer': None, 'usable': False}
    if not directory or not info['installed']:
        return info
    prefix = f'direnv exec {shlex.quote(str(directory))}'
    # The exit code of "direnv exec" does not tell: a denied .envrc is skipped silently. Ask direnv status.
    rc, out, _ = sh('direnv status', directory)
    match = re.search(r'^Found RC allowed (\S+)', ANSI.sub('', out), re.M)
    state = DIRENV_STATES.get(match.group(1), f'unknown ({match.group(1)})') if match else 'unknown'
    info['state'] = state
    info['allowed'] = state == 'allowed'
    if not info['allowed']:
        info['error'] = f'{info["envrc"]} is {state}'
        return info
    rc, out, _ = sh(f"{prefix} php -r 'echo PHP_VERSION;'", root)
    info['php'] = first_line(out) if rc == 0 else None
    rc, out, _ = sh(f'{prefix} composer --version --no-ansi', root)
    info['composer'] = first_line(out, 'Composer') if rc == 0 else None
    info['usable'] = bool(info['php'] and info['composer'])
    info['exec'] = f'{prefix} sh -c {{cmd}}'
    info['composer_cmd'] = f'{prefix} composer'
    return info


def probe_local() -> dict:
    info = {'php': None, 'composer': None}
    if shutil.which('php'):
        rc, out, _ = sh("php -r 'echo PHP_VERSION;'", Path('.'))
        info['php'] = first_line(out) if rc == 0 else None
    if shutil.which('composer'):
        rc, out, _ = sh('composer --version --no-ansi', Path('.'))
        info['composer'] = first_line(out, 'Composer') if rc == 0 else None
    return info


def commit_evidence(root: Path, limit: int = 200) -> dict:
    """How this repository writes commit messages, to suggest a commit style."""
    rc, out, _ = sh(f'git log -n {limit} --format=%s%x1f%b%x1e', root, merge=False)
    subjects, bodies = [], []
    for record in out.split('\x1e'):
        if '\x1f' in record:
            subject, body = record.split('\x1f', 1)
            subjects.append(subject.strip())
            bodies.append(body)
    tag = re.compile(r'^\[(!!!|TASK|BUGFIX|FEATURE|DOCS|SECURITY|CLEANUP|WIP|RELEASE)\]', re.I)
    keyed = re.compile(r'^(?:\[[^\]]+\]\s*)+([A-Z][A-Z0-9]+-\d+):')
    keys: dict[str, int] = {}
    for subject in subjects:
        match = keyed.match(subject)
        if match:
            key = match.group(1).split('-')[0]
            keys[key] = keys.get(key, 0) + 1
    joined = '\n'.join(bodies)
    return {
        'commits_read': len(subjects),
        'typo3_tags': sum(1 for s in subjects if tag.match(s)),
        'issue_key_in_subject': sum(keys.values()),
        'project_keys': dict(sorted(keys.items(), key=lambda kv: -kv[1])),
        'footers': {name: len(re.findall(rf'^{name}:', joined, re.M)) for name in ('Resolves', 'Releases', 'Related', 'Fixes', 'Refs')},
        'examples': subjects[:5],
    }


def remote_host(root: Path) -> str | None:
    url = git(root, 'remote', 'get-url', 'origin')
    match = re.match(r'^(?:https?://(?:[^@/]+@)?|git@|ssh://git@)([^/:]+)', url or '')
    return match.group(1) if match else None


def detect(root: Path) -> dict:
    return {
        'root': str(root),
        'ddev': {'config': (root / '.ddev' / 'config.yaml').is_file(), 'installed': bool(shutil.which('ddev'))},
        'direnv': probe_direnv(root),
        'local': probe_local(),
        'git_remote_host': remote_host(root),
        'commit_style_evidence': commit_evidence(root),
        'agent_instructions': [name for name in ('CLAUDE.md', 'AGENTS.md', '.claude/CLAUDE.md', 'CONTRIBUTING.md') if (root / name).is_file()],
    }


def detect_runtime(root: Path, choice: str | None, exec_override: str | None, composer_override: str | None) -> dict:
    """ddev, direnv, local or custom. An explicit choice wins, otherwise ddev > usable direnv > local PHP."""
    if exec_override or choice == 'custom':
        if not exec_override:
            die('--runtime custom needs --exec "<wrapper with {cmd}>" and --composer')
        return {'kind': 'custom', 'exec': exec_override, 'composer': composer_override or exec_override.replace('{cmd}', 'composer')}
    direnv = probe_direnv(root) if choice in (None, 'direnv') else {}
    if choice == 'ddev' or (choice is None and (root / '.ddev' / 'config.yaml').is_file()):
        if not shutil.which('ddev'):
            die('ddev is not installed')
        return {'kind': 'ddev', 'exec': 'ddev exec {cmd}', 'composer': composer_override or 'ddev composer'}
    if choice == 'direnv' or (choice is None and direnv.get('usable')):
        if not direnv.get('envrc'):
            die('no .envrc in the project folder or one level above')
        if not direnv.get('installed'):
            die('an .envrc exists, but direnv is not installed')
        if not direnv.get('allowed'):
            die(f'{direnv["envrc"]} is {direnv.get("state", "not allowed")}. Review it, then run "direnv allow" yourself. '
                'The pilot never allows an .envrc.')
        if not direnv.get('usable'):
            die(f'php or composer does not work inside the direnv environment (php: {direnv.get("php")}, composer: {direnv.get("composer")})')
        return {'kind': 'direnv', 'envrc': direnv['envrc'], 'exec': direnv['exec'], 'composer': composer_override or direnv['composer_cmd']}
    if choice in (None, 'local') and shutil.which('php'):
        if not shutil.which('composer') and not composer_override:
            die('local PHP found, but no composer on PATH. Pass --composer or choose another runtime')
        return {'kind': 'local', 'exec': '{cmd}', 'composer': composer_override or 'composer'}
    die('cannot tell where PHP runs. Choose --runtime ddev|direnv|local, or --runtime custom with --exec and --composer')
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


def fresh_checklist(config: dict) -> dict:
    data = load_json(checklist_file(config))
    items = {}
    for phase, spec in data['phases'].items():
        for section in spec['sections']:
            for item in section['items']:
                items[item['id']] = {'status': 'open', 'note': '', 'evidence': '', 'at': None}
    return items


# Kept across flights: downloads that do not depend on the flight, and earlier flights.
KEEP_ON_RESTART = {'cache', 'archive'}


def archive_previous(state: Path) -> Path | None:
    """Move the state of a replaced flight aside, so reports, logs and notes of the old flight never mix with the new one."""
    old = load_json(state / 'config.json', None)
    if not old:
        return None
    stamp = now()[:19].replace('-', '').replace(':', '').replace('T', '-')
    target = state / 'archive' / f'{stamp}-{slug(flight_title(old, plain=True))}'
    target.mkdir(parents=True, exist_ok=True)
    for entry in state.iterdir():
        if entry.name not in KEEP_ON_RESTART:
            shutil.move(str(entry), str(target / entry.name))
    return target


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


COMMIT_STYLES = ('typo3', 'youtrack', 'custom')
ISSUE_MODES = ('none', 'single', 'per-step', 'placeholder')


def commit_policy(args) -> dict:
    style = args.commit_style
    if style == 'custom' and not args.commit_template:
        die('--commit-style custom needs --commit-template, e.g. "[{tag}] {ref}: {subject}"')
    if args.issue_mode in ('single', 'per-step') and not args.issue:
        die(f'--issue-mode {args.issue_mode} needs --issue <REF> (the ticket, or the parent ticket for per-step)')
    if style == 'youtrack' and args.issue_mode == 'none':
        die('the youtrack style puts an issue reference into every subject: choose an --issue-mode other than none')
    return {
        'style': style,
        'template': args.commit_template,
        'tracker': args.tracker,
        'project_key': args.project_key,
        'issue_mode': args.issue_mode,
        'issue': args.issue,
        'subject_max': 52,
        'body_wrap': 72,
    }


DEV_VERSION = re.compile(r'(^dev-|-dev$|\.x-dev$|@dev$)')


def resolve_packages(packages: dict[str, dict], patterns: list[str]) -> dict[str, str]:
    """Installed packages matching names or globs (acme/shop-*), with their installed versions."""
    import fnmatch
    found = {}
    for pattern in patterns:
        matches = [name for name in packages if fnmatch.fnmatch(name, pattern)]
        if not matches:
            die(f'{pattern} matches no installed package in composer.lock')
        for name in matches:
            found[name] = packages[name]['version']
    return dict(sorted(found.items()))


def package_scope(args, packages: dict[str, dict]) -> dict:
    if not args.package or not args.to:
        die('--scope packages needs --package <name or glob> (repeatable) and --to <version, constraint or branch>')
    installed = resolve_packages(packages, args.package)
    dev = bool(DEV_VERSION.search(args.to))
    if dev and not args.dev_stability:
        die(f'{args.to} is a development version. Decide how the project allows it: --dev-stability minimum-stability '
            '(composer config minimum-stability dev + prefer-stable, recorded, to be reverted once released) or '
            '--dev-stability none (the project already allows it)')
    return {'patterns': args.package, 'names': list(installed), 'installed': installed, 'to': args.to, 'dev': dev,
            'dev_stability': args.dev_stability if dev else None}


def run(args) -> None:
    start = Path(args.project or '.').resolve()
    top = git(start, 'rev-parse', '--show-toplevel')
    root = Path(top) if top else start
    if args.detect:
        print(json.dumps(detect(root), indent=2))
        return
    if args.scope == 'core' and not args.target:
        die('--target is required (or --scope packages, or --detect to see what the project offers)')
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
    scope = package_scope(args, packages) if args.scope == 'packages' else None
    target = args.target if not scope else (installed and major_minor(installed)) or source
    if not scope and not re.fullmatch(r'\d+\.\d+', target):
        die('--target must look like 13.4')
    label = args.label or (slug(f'{scope["patterns"][0].split("/")[-1].rstrip("*-")}-{scope["to"]}') if scope else None)

    flight = Flight(root)
    runtime = detect_runtime(root, args.runtime, args.exec, args.composer)
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
            'preflight': f'{prefix}/preflight-{label or source}',
            'flight': f'{prefix}/{label or target}',
        },
        'scope': args.scope,
        'mode': 'check' if args.check_only else 'upgrade',
        'packages': scope,
        'runtime': runtime,
        'gates': args.gates,
        'commit': commit_policy(args),
        'allow_push': args.allow_push,
        'rector_sets': ['typo3'] + (['php'] if args.php_set else []),
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
    archived = archive_previous(flight.dir) if args.force else None
    flight.log = {
        'schema': 1,
        'phase': 'preflight',
        'checklist': fresh_checklist(flight.config),
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
            destination.write_text(text.replace('{title}', flight_title(flight.config)), encoding='utf-8')
    from .context import register
    for ref in args.context:
        register(flight, ref)
    flight.event(f'Flight opened: {flight_title(flight.config)} ({args.scope} scope, {flight.config["mode"]}), base branch {base}')
    flight.save()

    print(f'Flight opened in {flight.rel(flight.dir)}/ (git-excluded)')
    if archived:
        print(f'  previous flight moved to {flight.rel(archived)}/')
    print(f'  {flight_title(flight.config)}   scope: {args.scope}{" (check only)" if args.check_only else ""}   runtime: {runtime["kind"]}   gates: {args.gates}')
    if scope:
        print('  packages: ' + ', '.join(f'{n} {v}' for n, v in scope['installed'].items()))
        if scope['dev']:
            print(f'  development target, stability: {scope["dev_stability"]}')
    policy = flight.config['commit']
    print(f'  commits: style {policy["style"]}, issues {policy["issue_mode"]}' + (f' ({policy["issue"]})' if policy.get('issue') else '')
          + f', push {"allowed" if args.allow_push else "blocked while the flight is open"}'
          + f', rector sets: {" + ".join(flight.config["rector_sets"])}')
    print(f'  base branch {base}, preflight branch {flight.config["branches"]["preflight"]}, flight branch {flight.config["branches"]["flight"]}')
    print('  own extensions:')
    for ext in extensions:
        print(f'    - {ext["key"]:<24} {ext["path"]}')
    print('  tests (confirm or edit in config.json -> tests):')
    for suite, spec in flight.config['tests'].items():
        print(f'    - {suite:<11} [{spec["where"]}] {spec["cmd"]}')
    if not flight.config['tests']:
        print('    - none detected. Configure tests before the baseline measurement.')
    if args.context:
        print(f'  context to read first: {", ".join(args.context)} (upgrade-pilot context list)')
    missing = [name for name, version in flight.config['installed_tools'].items() if not version and name not in ('testing-framework', 'typo3-console')]
    if missing:
        print('  tooling not installed: ' + ', '.join(missing))
