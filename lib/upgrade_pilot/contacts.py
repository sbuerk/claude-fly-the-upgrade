"""Core contact points of own extensions, and whether the tests execute them.

Static heuristics, deliberately simple: good enough to rank what needs an
instrument test before departure. Every tool in the flight reads code, only
tests run it, so an uncovered contact point is a place where the new core can
break things without anybody being told.
"""

from __future__ import annotations

import re
from pathlib import Path

from .core import Flight, now, write_json

SKIP_DIRS = {'Tests', 'vendor', '.Build', 'node_modules', 'Documentation', '.git', 'var', 'public'}
CRITICAL_KINDS = ['plugin', 'content-element', 'middleware', 'xclass', 'hook', 'event-listener', 'command',
                  'backend-module', 'controller', 'upgrade-wizard', 'scheduler-task', 'viewhelper', 'data-processor',
                  'tca', 'typoscript', 'template-override', 'service']
PATH_KINDS = [
    ('/Controller/', 'controller'), ('/ViewHelpers/', 'viewhelper'), ('/Command/', 'command'),
    ('/EventListener/', 'event-listener'), ('/Middleware/', 'middleware'), ('/Hooks/', 'hook'), ('/Hook/', 'hook'),
    ('/Updates/', 'upgrade-wizard'), ('/Task/', 'scheduler-task'), ('/DataProcessing/', 'data-processor'),
    ('/Domain/Repository/', 'service'), ('/Service/', 'service'), ('/Utility/', 'service'),
]
GLOBALS_CORE = re.compile(r"\$GLOBALS\[['\"](TSFE|TYPO3_CONF_VARS|TCA|BE_USER|LANG|TBE_STYLES|TYPO3_REQUEST|EXEC_TIME|SIM_EXEC_TIME|PAGES_TYPES)['\"]\]")


def php_files(base: Path) -> list[Path]:
    out = []
    for path in base.rglob('*.php'):
        rel_parts = path.relative_to(base).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        out.append(path)
    return sorted(out)


def parse_class(text: str) -> dict | None:
    match = re.search(r'^\s*(?:final\s+|abstract\s+|readonly\s+)*(class|interface|trait|enum)\s+(\w+)(?:\s+extends\s+([\\\w]+))?', text, re.M)
    if not match:
        return None
    namespace = re.search(r'^namespace\s+([^;]+);', text, re.M)
    imports = dict()
    for fqcn, alias in re.findall(r'^use\s+([\\\w]+)(?:\s+as\s+(\w+))?;', text, re.M):
        imports[alias or fqcn.rsplit('\\', 1)[-1]] = fqcn
    core_short = {short for short, fqcn in imports.items() if fqcn.startswith(('TYPO3\\CMS\\', 'TYPO3Fluid\\'))}
    methods = []
    positions = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(
        r'^\s*(public|protected|private)?\s*(?:static\s+)?function\s+(\w+)\s*\(', text, re.M)]
    for index, (start, visibility, name) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        body = text[start:end]
        refs = set(re.findall(r'\\?TYPO3\\CMS\\[\\\w]+', body))
        refs |= {s for s in core_short if re.search(rf'\b{re.escape(s)}\b', body)}
        refs |= {f'$GLOBALS[{g}]' for g in GLOBALS_CORE.findall(body)}
        if re.search(r'\bTYPO3_\w+\b', body):
            refs |= set(re.findall(r'\b(TYPO3_(?:mainDir|version|branch|OS|REQUESTTYPE\w*|MODE))\b', body))
        methods.append({'name': name, 'visibility': visibility or 'public', 'core_refs': sorted(refs)})
    extends = match.group(3)
    if extends and extends in imports:
        extends = imports[extends]
    return {
        'kind_keyword': match.group(1), 'name': match.group(2),
        'fqcn': (namespace.group(1) + '\\' if namespace else '') + match.group(2),
        'extends': extends, 'imports': imports, 'methods': methods,
        'attributes': re.findall(r'#\[(As\w+|Autoconfigure|Controller)\b', text),
    }


def plugin_registrations(ext_path: Path) -> list[dict]:
    plugins = []
    sources = [ext_path / 'ext_localconf.php', ext_path / 'ext_tables.php', *sorted((ext_path / 'Configuration' / 'TCA' / 'Overrides').glob('*.php'))]
    for source in sources:
        if not source.is_file():
            continue
        text = source.read_text(encoding='utf-8', errors='replace')
        for call in re.finditer(r'(configurePlugin|registerPlugin)\s*\(\s*[\'"]([\w]+)[\'"]\s*,\s*[\'"]([\w]+)[\'"]', text):
            extension_name, plugin = call.group(2), call.group(3)
            signature = extension_name.replace('_', '').lower() + '_' + plugin.lower()
            tail = text[call.end():call.end() + 600]
            ctype = 'PLUGIN_TYPE_CONTENT_ELEMENT' in tail or bool(re.search(r"'CType'|CType", tail))
            plugins.append({'kind': 'plugin', 'name': signature, 'file': source.name, 'via': call.group(1),
                            'registration': 'CType' if ctype else 'list_type (default before v13)'})
        for call in re.finditer(r'addPlugin\s*\(', text):
            plugins.append({'kind': 'plugin', 'name': f'addPlugin@{source.name}:{text[:call.start()].count(chr(10)) + 1}', 'file': source.name, 'via': 'addPlugin'})
    return plugins


def config_points(ext_path: Path, ext_key: str) -> list[dict]:
    points = []
    conf = ext_path / 'Configuration'
    for table_file in sorted((conf / 'TCA').glob('*.php')):
        points.append({'kind': 'tca', 'name': table_file.stem, 'file': str(table_file.relative_to(ext_path))})
    for override in sorted((conf / 'TCA' / 'Overrides').glob('*.php')):
        points.append({'kind': 'tca', 'name': f'override:{override.stem}', 'file': str(override.relative_to(ext_path))})
    for pattern in ('TypoScript/**/*.typoscript', 'TypoScript/**/*.ts', 'TypoScript/**/*.txt', 'Sets/**/*.typoscript'):
        for ts in sorted(conf.glob(pattern)):
            points.append({'kind': 'typoscript', 'name': str(ts.relative_to(ext_path)), 'file': str(ts.relative_to(ext_path))})
            text = ts.read_text(encoding='utf-8', errors='replace')
            for override in re.findall(r'(?:template|partial|layout)RootPaths[^=\n]*=\s*(EXT:[\w/.-]+)', text):
                if override.split('/')[0] != f'EXT:{ext_key}':
                    points.append({'kind': 'template-override', 'name': override, 'file': str(ts.relative_to(ext_path))})
    for name, kind in (('RequestMiddlewares.php', 'middleware'), ('Backend/Modules.php', 'backend-module'),
                       ('Backend/Routes.php', 'backend-module'), ('Backend/AjaxRoutes.php', 'backend-module')):
        if (conf / name).is_file():
            points.append({'kind': kind, 'name': name, 'file': f'Configuration/{name}'})
    localconf = ext_path / 'ext_localconf.php'
    if localconf.is_file():
        text = localconf.read_text(encoding='utf-8', errors='replace')
        for line_no, line in enumerate(text.splitlines(), 1):
            if "['Objects']" in line or '["Objects"]' in line:
                points.append({'kind': 'xclass', 'name': f'ext_localconf.php:{line_no}', 'file': 'ext_localconf.php', 'code': line.strip()})
            elif re.search(r"\[['\"](SC_OPTIONS|EXTCONF)['\"]\]", line) and ('::class' in line or '->' in line or '::' in line):
                points.append({'kind': 'hook', 'name': f'ext_localconf.php:{line_no}', 'file': 'ext_localconf.php', 'code': line.strip()})
    return points


def service_tags(ext_path: Path) -> dict[str, str]:
    """Class -> kind for listeners and commands registered in Services.yaml."""
    tags = {}
    services = ext_path / 'Configuration' / 'Services.yaml'
    if services.is_file():
        current = None
        for line in services.read_text(encoding='utf-8', errors='replace').splitlines():
            key = re.match(r'^\s{2}([\\\w]+):\s*$', line)
            if key:
                current = key.group(1)
            if current and 'event.listener' in line:
                tags[current] = 'event-listener'
            if current and 'console.command' in line:
                tags[current] = 'command'
    return tags


def load_tests(root: Path, ext_path: Path) -> dict[str, str]:
    tests = {}
    for base in {ext_path / 'Tests', root / 'Tests'}:
        if base.is_dir():
            for path in base.rglob('*'):
                if path.is_file() and path.suffix in ('.php', '.csv', '.xml', '.yaml', '.typoscript', '.json', '.html'):
                    tests[str(path.relative_to(root))] = path.read_text(encoding='utf-8', errors='replace')
    return tests


def frontend_tests(tests: dict[str, str]) -> list[str]:
    return [f for f, t in tests.items() if 'executeFrontendSubRequest' in t or 'InternalRequest' in t]


def analyse_extension(flight: Flight, ext: dict) -> dict:
    root = flight.root
    ext_path = (root / ext['path']).resolve()
    tests = load_tests(root, ext_path)
    fe_tests = frontend_tests(tests)
    tags = service_tags(ext_path)
    all_text = {str(p.relative_to(ext_path)): p.read_text(encoding='utf-8', errors='replace') for p in php_files(ext_path)}
    for extra in ('Configuration/Services.yaml',):
        if (ext_path / extra).is_file():
            all_text[extra] = (ext_path / extra).read_text(encoding='utf-8', errors='replace')

    classes = []
    for rel, text in all_text.items():
        if not rel.startswith('Classes/') or not rel.endswith('.php'):
            continue
        info = parse_class(text)
        if not info:
            continue
        kind = tags.get(info['fqcn'])
        attributes = set(info['attributes'])
        if not kind:
            if 'AsEventListener' in attributes:
                kind = 'event-listener'
            elif 'AsCommand' in attributes:
                kind = 'command'
            elif info['extends'] and info['extends'].endswith(('ActionController', 'AbstractController')):
                kind = 'controller'
            elif info['extends'] and 'ViewHelper' in (info['extends'] or ''):
                kind = 'viewhelper'
            else:
                kind = next((k for marker, k in PATH_KINDS if marker in '/' + rel), 'class')
        referenced_in = [f for f, t in tests.items() if re.search(rf'\b{re.escape(info["name"])}\b', t)]
        registered_elsewhere = any(
            re.search(rf'\b{re.escape(info["name"])}\b', t) for f, t in all_text.items() if f != rel
        ) or bool(attributes) or info['fqcn'] in tags
        methods = []
        for method in info['methods']:
            if method['visibility'] != 'public' or method['name'].startswith('__'):
                continue
            called = any(re.search(rf'(->|::){re.escape(method["name"])}\s*\(', tests[f]) for f in referenced_in)
            if not called and kind == 'controller' and fe_tests and method['name'].endswith('Action'):
                called = 'frontend'
            methods.append({'name': method['name'], 'core_refs': method['core_refs'], 'covered': called})
        core_refs = sorted({r for m in info['methods'] for r in m['core_refs']})
        classes.append({
            'kind': kind, 'name': info['fqcn'], 'file': rel, 'core_refs': core_refs,
            'tests': referenced_in, 'registered': registered_elsewhere, 'methods': methods,
        })

    points = plugin_registrations(ext_path) + config_points(ext_path, ext['key'])
    for point in points:
        needle = point['name'].split(':', 1)[-1] if point['kind'] == 'tca' else point['name']
        direct = [f for f, t in tests.items() if needle and needle in t] if point['kind'] not in ('hook', 'xclass') else []
        if point['kind'] == 'plugin':
            rendered = [f for f in fe_tests if f in direct] or ([f for f in fe_tests] if any(needle in t for t in tests.values()) else [])
            point['covered'] = 'rendered' if rendered else ('referenced' if direct else 'none')
            point['tests'] = rendered or direct
        elif point['kind'] == 'typoscript':
            ts_hit = [f for f, t in tests.items() if Path(needle).name in t]
            point['covered'] = 'loaded' if ts_hit else 'none'
            point['tests'] = ts_hit
        elif point['kind'] == 'middleware':
            point['covered'] = 'indirect' if fe_tests else 'none'
            point['tests'] = fe_tests
        else:
            point['covered'] = 'direct' if direct else 'none'
            point['tests'] = direct
    # TypoScript pulled in by a loaded file (@import, INCLUDE_TYPOSCRIPT, directory includes) is loaded too.
    changed = True
    while changed:
        changed = False
        loaded = [p for p in points if p['kind'] == 'typoscript' and p['covered'] == 'loaded']
        for point in points:
            if point['kind'] != 'typoscript' or point['covered'] != 'none':
                continue
            path = Path(point['name'])
            for parent in loaded:
                text = (ext_path / parent['name']).read_text(encoding='utf-8', errors='replace')
                if path.name in text or f'{path.parent.as_posix()}/' in text or f'{path.parent.as_posix()}"' in text:
                    point['covered'] = 'loaded'
                    point['tests'] = parent['tests']
                    point['via'] = parent['name']
                    changed = True
                    break
    return {'key': ext['key'], 'path': ext['path'], 'tests_found': len(tests), 'frontend_tests': fe_tests,
            'classes': classes, 'points': points}


def gaps(report: dict) -> list[dict]:
    """Uncovered contact points, most critical first."""
    out = []
    for point in report['points']:
        if point['covered'] == 'none':
            out.append({'kind': point['kind'], 'what': point['name'], 'file': point['file'], 'why': 'no test touches it'})
    for cls in report['classes']:
        uncovered = [m for m in cls['methods'] if not m['covered'] and m['core_refs']]
        if not cls['core_refs']:
            continue
        if not cls['tests'] and not any(m['covered'] for m in cls['methods']):
            out.append({'kind': cls['kind'], 'what': cls['name'], 'file': cls['file'],
                        'why': f'class never referenced by a test, {len(cls["core_refs"])} core reference(s)'
                               + ('' if cls['registered'] else ', not registered anywhere (dead code?)')})
        elif uncovered:
            for method in uncovered:
                out.append({'kind': cls['kind'], 'what': f'{cls["name"]}::{method["name"]}()', 'file': cls['file'],
                            'why': 'core API in an untested method: ' + ', '.join(method['core_refs'][:5])})
    rank = {kind: i for i, kind in enumerate(CRITICAL_KINDS)}
    return sorted(out, key=lambda g: rank.get(g['kind'], len(rank)))


def cmd_contacts(args) -> None:
    flight = Flight.load()
    reports = [analyse_extension(flight, ext) for ext in flight.extensions()]
    all_gaps = []
    for report in reports:
        report_gaps = gaps(report)
        all_gaps.extend({**g, 'ext': report['key']} for g in report_gaps)
        print(f'== {report["key"]} ({report["path"]}): {len(report["classes"])} classes, {len(report["points"])} registration points, '
              f'{report["tests_found"]} test files, {len(report["frontend_tests"])} frontend-request tests')
        for point in report['points']:
            extra = f' [{point["registration"]}]' if point.get('registration') else ''
            print(f'  {point["covered"]:<10} {point["kind"]:<17} {point["name"]}{extra}')
        for cls in report['classes']:
            covered = sum(1 for m in cls['methods'] if m['covered'])
            state = 'tested' if cls['tests'] else ('rendered' if any(m['covered'] == 'frontend' for m in cls['methods']) else 'untested')
            print(f'  {state:<10} {cls["kind"]:<17} {cls["name"]}  core refs {len(cls["core_refs"])}, '
                  f'public methods covered {covered}/{len(cls["methods"])}' + ('' if cls['registered'] else '  (unregistered)'))
    print(f'\nGAPS, most critical first ({len(all_gaps)}):')
    for gap in all_gaps:
        print(f'  [{gap["ext"]}] {gap["kind"]:<15} {gap["what"]}\n      {gap["file"]}: {gap["why"]}')
    write_json(flight.dir / 'contacts.json', {'at': now(), 'extensions': reports, 'gaps': all_gaps})
    flight.log.setdefault('contacts', []).append({'label': args.label, 'gaps': len(all_gaps), **flight.stamp()})
    flight.event(f'contacts {args.label}: {len(all_gaps)} uncovered contact points')
    flight.save()
    print(f'\nfull report: {flight.rel(flight.dir / "contacts.json")}')
