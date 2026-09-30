"""Where the project touches third-party packages, and whether each touchpoint survives the update.

Projects rarely use an extension as shipped. Local path extensions and
sitepackages extend its classes, XCLASS them, decorate its services, listen
to its events, hook into it, override its TCA, TypoScript, templates and
labels, map its models, configure its plugins in site configuration, or
patch it through composer. Every one of those is a place where an update of
the package can break the project without any error in the package itself.

`deps touchpoints` finds them, generically, from what the installed package
declares (namespaces, extension key, tables, plugins, templates, labels,
events, ViewHelpers). `--verify` compares each against the target release,
using the source repositories `deps docs` fetched: did the original of a
copied template change, does an overridden method still exist with the same
signature, do overridden label keys and used ViewHelpers and events still
exist, did the files a patch targets change.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from .contacts import plugin_registrations
from .core import Flight, die, load_json, now, sh, slug, write_json
from .init import locked_packages

TEXT_SUFFIXES = ('.php', '.typoscript', '.tsconfig', '.ts', '.txt', '.html', '.yaml', '.yml', '.xml', '.xlf', '.json', '.csv')
SKIP_PARTS = {'vendor', 'node_modules', '.Build', '.git', 'var', 'public', '.upgrade-pilot'}
KIND_ORDER = ['patch', 'xclass', 'subclass', 'service-override', 'listener', 'hook', 'tca-override', 'template-copy',
              'template-override', 'language-override', 'viewhelper-usage', 'persistence-mapping', 'site-config',
              'typoscript', 'php-usage', 'fixture']


# -- what a package declares ------------------------------------------------------------------------

def package_info(flight: Flight, name: str, lock: dict[str, dict]) -> dict:
    meta = lock.get(name) or {}
    directory = flight.root / 'vendor' / name
    namespaces = sorted({ns.strip('\\') for key in ('psr-4', 'psr-0') for ns in ((meta.get('autoload') or {}).get(key) or {})
                         if ns.strip('\\')})
    psr4 = {ns.strip('\\'): (paths if isinstance(paths, str) else paths[0]) for ns, paths in
            ((meta.get('autoload') or {}).get('psr-4') or {}).items() if ns.strip('\\')}
    ext_key = ((meta.get('extra') or {}).get('typo3/cms') or {}).get('extension-key') or name.split('/')[-1].replace('-', '_')
    info = {'name': name, 'version': meta.get('version'), 'type': meta.get('type'), 'dir': str(directory),
            'namespaces': namespaces, 'psr4': psr4, 'ext_key': ext_key, 'ts_key': 'tx_' + ext_key.replace('_', ''),
            'tables': [], 'plugins': [], 'extension_names': [], 'templates': [], 'labels': []}
    if not directory.is_dir():
        return info
    tca = directory / 'Configuration' / 'TCA'
    info['tables'] = sorted({p.stem for p in tca.glob('*.php')})
    sql = directory / 'ext_tables.sql'
    if sql.is_file():
        info['tables'] = sorted(set(info['tables']) | set(re.findall(r'CREATE TABLE\s+`?(\w+)', sql.read_text(errors='replace'), re.I)))
    plugins = plugin_registrations(directory)
    info['plugins'] = sorted({p['name'] for p in plugins if '@' not in p['name']})
    for source in (directory / 'ext_localconf.php', *sorted((directory / 'Configuration' / 'TCA' / 'Overrides').glob('*.php'))):
        if source.is_file():
            info['extension_names'] += re.findall(r'(?:configurePlugin|registerPlugin)\s*\(\s*[\'"](\w+)[\'"]', source.read_text(errors='replace'))
    info['extension_names'] = sorted(set(info['extension_names']))
    private = directory / 'Resources' / 'Private'
    info['templates'] = sorted(str(p.relative_to(private)) for p in private.glob('*/**/*.html')
                               if p.relative_to(private).parts[0] in ('Templates', 'Partials', 'Layouts'))
    info['labels'] = sorted(str(p.relative_to(directory)) for p in (private / 'Language').glob('*.xlf'))
    return info


# -- the project side ----------------------------------------------------------------------------------

def project_files(flight: Flight) -> dict[str, list[str]]:
    """Own extensions and sitepackages (every path extension), plus the project's config/ and composer.json."""
    bases = [flight.root / ext['path'] for ext in flight.extensions()] + [flight.root / 'config']
    files: dict[str, list[str]] = {}
    for base in bases:
        if not base.is_dir():
            continue
        for path in base.rglob('*'):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if any(part in SKIP_PARTS for part in path.relative_to(flight.root).parts[:-1]):
                continue
            rel = str(path.relative_to(flight.root))
            if rel not in files:
                files[rel] = path.read_text(encoding='utf-8', errors='replace').splitlines()
    root_composer = flight.root / 'composer.json'
    if root_composer.is_file():
        files.setdefault('composer.json', root_composer.read_text(encoding='utf-8', errors='replace').splitlines())
    return files


def in_namespace(fqcn: str, namespaces: list[str]) -> bool:
    """PHP class names are case-insensitive: ACME\\Shop and Acme\\Shop are the same namespace."""
    name = fqcn.lstrip('\\').lower()
    return any(name.startswith(ns.lower() + '\\') for ns in namespaces)


def namespace_pattern(namespace: str) -> re.Pattern:
    return re.compile(r'(?<![\w\\])\\?' + re.escape(namespace).replace('\\\\', r'\\\\?') + r'\\\\?', re.I)


def short_imports(lines: list[str], namespaces: list[str]) -> dict[str, str]:
    """Short name -> FQCN for package classes imported with use statements."""
    out = {}
    for line in lines:
        match = re.match(r'^use\s+\\?([\w\\]+)(?:\s+as\s+(\w+))?;', line.strip())
        if match and in_namespace(match.group(1), namespaces):
            out[match.group(2) or match.group(1).rsplit('\\', 1)[-1]] = match.group(1)
    return out


def typoscript_paths(files: dict[str, list[str]]) -> dict[tuple[str, int], str]:
    """The object path each TypoScript line sits in, from nested braces: plugin.tx_x { view { ... } }."""
    out = {}
    for rel, lines in files.items():
        if Path(rel).suffix not in ('.typoscript', '.tsconfig', '.ts', '.txt'):
            continue
        stack: list[str] = []
        for number, line in enumerate(lines, 1):
            stripped = line.split('#')[0].strip() if not line.strip().startswith('#') else ''
            out[(rel, number)] = '.'.join(stack)
            opening = re.match(r'^([\w.\-]+)\s*\{\s*$', stripped)
            if opening:
                stack.append(opening.group(1))
            elif stripped.startswith('}'):
                if stack:
                    stack.pop()
            elif stripped.startswith('[') and stripped.endswith(']'):
                stack = []  # conditions close every open block in TypoScript
    return out


def scan(info: dict, files: dict[str, list[str]], root: Path) -> list[dict]:
    hits: list[dict] = []
    ns_patterns = [namespace_pattern(ns) for ns in info['namespaces']]
    key = info['ext_key']
    ts = re.compile(rf'\b(plugin|module|lib)\.{re.escape(info["ts_key"])}\b')
    ext_path = re.compile(rf'EXT:{re.escape(key)}/')
    table_names = [t for t in info['tables'] if len(t) > 4]
    signatures = [p for p in info['plugins'] if len(p) > 4]
    vh_namespaces = [ns.replace('\\', '/') + '/ViewHelpers' for ns in info['namespaces']] + [ns + '\\ViewHelpers' for ns in info['namespaces']]

    def hit(kind, rel, number, line, detail=''):
        hits.append({'kind': kind, 'file': rel, 'line': number, 'code': line.strip()[:200], 'detail': detail})

    ts_paths = typoscript_paths(files)
    for rel, lines in files.items():
        suffix = Path(rel).suffix
        text = '\n'.join(lines)
        imports = short_imports(lines, info['namespaces']) if suffix == '.php' else {}
        # A table override file named after one of the package's tables.
        match = re.search(r'Configuration/TCA/Overrides/([\w]+)\.php$', rel)
        if match and match.group(1) in info['tables']:
            hit('tca-override', rel, 1, lines[0] if lines else '', f'overrides TCA of {match.group(1)}')
        # A template, partial or layout that mirrors one of the package's own.
        if suffix == '.html':
            tail = next((t for t in info['templates'] if rel.endswith('/' + t)), None)
            if tail:
                hit('template-copy', rel, 1, '', f'copy of Resources/Private/{tail}')
        if rel == 'composer.json' or rel.endswith('/composer.json'):
            try:
                patches = (json.loads(text).get('extra') or {}).get('patches') or {}
            except ValueError:
                patches = {}
            for description, patch in (patches.get(info['name']) or {}).items():
                hit('patch', rel, 1, f'{description}: {patch}', patch)
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith(('//', '#', '*', '/*')) and suffix == '.php':
                continue
            namespaced = any(p.search(line) for p in ns_patterns)
            if suffix == '.php':
                extends = re.search(r'\b(extends|implements)\s+\\?([\w\\]+)', line)
                target = extends and (imports.get(extends.group(2)) or (extends.group(2).lstrip('\\') if in_namespace(extends.group(2), info['namespaces']) else None))
                if "['Objects']" in line or '["Objects"]' in line:
                    if namespaced or any(short in line for short in imports):
                        hit('xclass', rel, number, line)
                    continue
                if target and extends.group(1) == 'extends':
                    hit('subclass', rel, number, line, target)
                    continue
                if re.search(r"\[['\"](SC_OPTIONS|EXTCONF)['\"]\]", line) and (key in line or namespaced):
                    hit('hook', rel, number, line)
                    continue
                if 'locallangXMLOverride' in line and ext_path.search(line):
                    hit('language-override', rel, number, line)
                    continue
                used = [fqcn for short, fqcn in imports.items() if re.search(rf'\b{re.escape(short)}\b', line)]
                if (namespaced or used) and not line.lstrip().startswith('use '):
                    detail = ', '.join(used)
                    if 'Configuration/Extbase/Persistence' in rel:
                        hit('persistence-mapping', rel, number, line, detail)
                    elif re.search(r'AsEventListener|EventListener', text) and ('Event' in line):
                        hit('listener', rel, number, line, detail)
                    else:
                        hit('php-usage', rel, number, line, detail)
                continue
            if suffix in ('.yaml', '.yml'):
                if namespaced and re.search(r'decorates:|\bclass:|\balias:', text):
                    kind = 'service-override' if re.search(r'decorates:', text) else ('listener' if 'event.listener' in text else 'php-usage')
                    hit(kind, rel, number, line)
                elif rel.startswith('config/') and (any(s in line for s in signatures + info['extension_names']) or ext_path.search(line)
                                                    or any(re.search(rf'\b{re.escape(t)}\b', line) for t in table_names)):
                    hit('site-config', rel, number, line)
                continue
            if suffix in ('.typoscript', '.tsconfig', '.ts', '.txt'):
                path = ts_paths.get((rel, number), '')
                if ts.search(line) or ext_path.search(line) or ts.search(path):
                    kind = 'template-override' if re.search(r'(template|partial|layout)RootPaths', line) else 'typoscript'
                    hit(kind, rel, number, line, path)
                continue
            if suffix == '.html':
                if any(ns in line for ns in vh_namespaces):
                    hit('viewhelper-usage', rel, number, line)
                continue
            if suffix in ('.csv', '.xml') and (any(re.search(rf'\b{re.escape(s)}\b', line) for s in signatures)
                                               or any(re.search(rf'\b{re.escape(t)}\b', line) for t in table_names)):
                hit('fixture', rel, number, line)
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    return sorted(hits, key=lambda h: (order.get(h['kind'], 99), h['file'], h['line']))


# -- verification against the target release --------------------------------------------------------

def deps_result(flight: Flight, name: str) -> dict | None:
    candidates = sorted((flight.dir / 'deps').glob(f'{slug(name)}-*.json'), key=lambda p: p.stat().st_mtime)
    for path in reversed(candidates):
        data = load_json(path, {})
        if data.get('repo') and data.get('new_ref'):
            return data
    return None


def git_show(repo: str, ref: str, path: str) -> str | None:
    rc, out, _ = sh(f'git -C {shlex.quote(repo)} show {shlex.quote(ref + ":" + path)}', Path(repo), merge=False)
    return out if rc == 0 else None


def class_path(info: dict, fqcn: str) -> str | None:
    fqcn = fqcn.lstrip('\\')
    for namespace, base in sorted(info['psr4'].items(), key=lambda kv: -len(kv[0])):
        if fqcn.lower().startswith(namespace.lower() + '\\'):
            return base.rstrip('/') + '/' + fqcn[len(namespace) + 1:].replace('\\', '/') + '.php'
    return None


def signature_methods(source: str) -> dict[str, str]:
    out = {}
    for match in re.finditer(r'(?:public|protected)\s+(?:static\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*([\w\\?|]+))?', source or ''):
        out[match.group(1)] = re.sub(r'\s+', ' ', f'{match.group(1)}({match.group(2)}): {match.group(3) or ""}').strip()
    return out


def own_class_file(files: dict[str, list[str]], fqcn: str) -> str | None:
    """The project file that declares a class, by namespace and class name."""
    namespace, _, short = fqcn.lstrip('\\').rpartition('\\')
    for rel, lines in files.items():
        if not rel.endswith(f'/{short}.php'):
            continue
        text = '\n'.join(lines)
        if re.search(rf'^namespace\s+{re.escape(namespace)}\s*;', text, re.M | re.I):
            return rel
    return None


def normalise_signature(signature: str) -> str:
    """Comparable form: no namespaces, no whitespace differences, no trailing commas."""
    signature = re.sub(r'\\?(?:[A-Za-z_]\w*\\)+', '', signature)
    signature = re.sub(r'\s+', ' ', signature)
    return re.sub(r',\s*\)', ')', signature.replace('( ', '(')).strip()


def compare_methods(own_source: str, old_src: str | None, new_src: str) -> list[str]:
    problems = []
    if re.search(r'^\s*final\s+(?:readonly\s+)?class\b', new_src, re.M) and not re.search(r'^\s*final\s+(?:readonly\s+)?class\b', old_src or '', re.M):
        problems.append('the class became FINAL in the target, it can no longer be extended or XCLASSed')
    own = signature_methods(own_source)
    target_new, target_old = signature_methods(new_src), signature_methods(old_src or '')
    for method in own:
        if method.startswith('__') and method != '__construct':
            continue
        if method in target_old and method not in target_new:
            problems.append(f'{method}() removed')
        elif method in target_new and method in target_old and target_new[method] != target_old[method]:
            if normalise_signature(own[method]) != normalise_signature(target_new[method]):
                problems.append(f'{method}() signature changed: {target_new[method]}')
    return problems


def verify(flight: Flight, info: dict, hits: list[dict], files: dict[str, list[str]]) -> None:
    result = deps_result(flight, info['name'])
    if not result:
        for h in hits:
            h['verify'] = 'not verified: run upgrade-pilot deps docs for this package first'
        return
    repo, old, new = result['repo'], result.get('old_ref'), result['new_ref']
    for h in sorted(hits, key=lambda x: x['kind'] == 'template-override'):
        kind = h['kind']
        if kind == 'template-copy':
            original = 'Resources/Private/' + h['detail'].split('Resources/Private/', 1)[1]
            new_text, old_text = git_show(repo, new, original), git_show(repo, old, original) if old else None
            own_text = '\n'.join(files.get(h['file'], []))
            if new_text is not None and own_text.strip() == new_text.strip():
                h['verify'] = 'original unchanged' if old and old_text == new_text else 'identical to the target original (re-based)'
                continue
            h['verify'] = ('REMOVED in target' if new_text is None else
                           'original CHANGED in target, re-base the copy' if old and old_text != new_text else
                           'original unchanged' if old else 'present in target (installed release not readable)')
        elif kind in ('subclass', 'xclass'):
            classes = re.findall(r'([\w\\]+)::class', h['code'])
            target = h['detail'] if kind == 'subclass' else next((c for c in classes if in_namespace(c, info['namespaces'])), None)
            path = class_path(info, target.lstrip('\\')) if target else None
            if not path:
                h['verify'] = 'check by hand: package class not resolved'
                continue
            new_src, old_src = git_show(repo, new, path), git_show(repo, old, path) if old else None
            if new_src is None:
                h['verify'] = f'CLASS REMOVED in target ({path})'
                continue
            own_file = h['file'] if kind == 'subclass' else next(
                (own_class_file(files, c) for c in classes if not in_namespace(c, info['namespaces']) and own_class_file(files, c)), None)
            if not own_file:
                h['verify'] = 'replacement class not found in the project, check by hand'
                continue
            problems = compare_methods('\n'.join(files.get(own_file, [])), old_src, new_src)
            h['verify'] = ', '.join(problems) if problems else f'overridden methods unchanged ({own_file})'
        elif kind == 'template-override':
            copies = [x for x in hits if x['kind'] == 'template-copy']
            changed = [x['file'] for x in copies if 'CHANGED' in x.get('verify', '') or 'REMOVED' in x.get('verify', '')]
            h['verify'] = (f'{len(changed)} copied template(s) need re-basing, see the template-copy entries' if changed else
                           'copied templates are unchanged in target' if copies else 'no copied templates found for this path')
        elif kind == 'language-override':
            refs = re.findall(r'EXT:[\w]+/([^\'"]+\.xlf)', h['code'])
            package_file = refs[0] if refs else None
            own_ref = re.findall(r'\]\s*(?:\[\])?\s*=\s*[\'"]EXT:([\w]+)/([^\'"]+\.xlf)', h['code'])
            if not package_file or not own_ref:
                h['verify'] = 'check by hand'
                continue
            ext = next((e for e in flight.extensions() if e['key'] == own_ref[0][0]), None)
            own_file = flight.root / ext['path'] / own_ref[0][1] if ext else None
            package_xlf = git_show(repo, new, package_file)
            if package_xlf is None:
                h['verify'] = f'label file REMOVED in target ({package_file})'
            elif own_file and own_file.is_file():
                own_ids = set(re.findall(r'<trans-unit[^>]*\bid="([^"]+)"', own_file.read_text(errors='replace')))
                missing = sorted(own_ids - set(re.findall(r'<trans-unit[^>]*\bid="([^"]+)"', package_xlf)))
                h['verify'] = f'{len(missing)} overridden key(s) no longer exist: {", ".join(missing[:10])}' if missing else 'all overridden keys exist'
            else:
                h['verify'] = 'override file not found in the project'
        elif kind == 'viewhelper-usage':
            h['verify'] = 'namespace used, see the ViewHelper tags in the file'
            prefix = re.search(r'xmlns:(\w+)=', h['code']) or re.search(r'\{namespace\s+(\w+)=', h['code'])
            if prefix:
                tags = set(re.findall(rf'<{prefix.group(1)}:([\w.]+)', '\n'.join(files.get(h['file'], []))))
                ns = next((ns for ns in info['namespaces'] if ns.replace('\\', '/') in h['code'] or ns in h['code']), None)
                if not ns:
                    continue
                missing = []
                for tag in sorted(tags):
                    fqcn = ns + '\\ViewHelpers\\' + '\\'.join(p[0].upper() + p[1:] for p in tag.split('.')) + 'ViewHelper'
                    path = class_path(info, fqcn)
                    if path and git_show(repo, new, path) is None:
                        missing.append(tag)
                h['verify'] = f'ViewHelper(s) missing in target: {", ".join(missing)}' if missing else f'{len(tags)} ViewHelper(s) exist in target'
        elif kind in ('listener', 'service-override', 'php-usage', 'persistence-mapping'):
            found = re.findall(r'\\?([A-Z][\w]*(?:\\\w+)+)', h['code']) + [c.strip() for c in (h['detail'] or '').split(',') if c.strip()]
            classes = sorted({c.lstrip('\\') for c in found if in_namespace(c, info['namespaces'])})
            gone = [c for c in classes if class_path(info, c) and git_show(repo, new, class_path(info, c)) is None]
            h['verify'] = f'class(es) missing in target: {", ".join(gone)}' if gone else ('referenced classes exist in target' if classes else 'check by hand')
        elif kind == 'patch':
            patch_file = flight.root / h['detail'] if not re.match(r'^https?://', h['detail']) else None
            targets = re.findall(r'^\+\+\+ b/(\S+)', patch_file.read_text(errors='replace'), re.M) if patch_file and patch_file.is_file() else []
            if not targets:
                h['verify'] = 'check: composer update reports whether the patch still applies'
                continue
            changed = [t for t in targets if old and git_show(repo, old, t) != git_show(repo, new, t)]
            h['verify'] = f'patched file(s) CHANGED in target: {", ".join(changed)}' if changed else 'patched files unchanged in target'
        else:
            h['verify'] = 'review against the changelog of the package'
    for h in hits:
        h['status'] = verdict(h.get('verify', ''))


# Verdicts of verify() that need nothing, or a human look. Everything else is a finding.
VERIFIED = re.compile(r'^(identical to the target original|original unchanged|overridden methods unchanged|copied templates are unchanged'
                      r'|all overridden keys exist|\d+ ViewHelper\(s\) exist|referenced classes exist|patched files unchanged'
                      r'|no copied templates found)')
BY_HAND = re.compile(r'^(not verified|check|review|namespace used|present in target|replacement class not found|override file not found)')


def verdict(text: str) -> str:
    """ok, manual (a human has to look) or attention (the target breaks or changes what the project relies on)."""
    if VERIFIED.search(text):
        return 'ok'
    if BY_HAND.search(text):
        return 'manual'
    return 'attention'


# -- command -------------------------------------------------------------------------------------------

def default_packages(flight: Flight) -> list[str]:
    if flight.config.get('scope') == 'packages':
        return flight.config['packages']['names']
    moves = (flight.log.get('dependencies') or {}).get('moves') or []
    if moves:
        return [m['name'] for m in moves if m.get('type') == 'typo3-cms-extension' and m.get('to')]
    own = {e.get('package') for e in flight.extensions()}
    return [n for n, p in locked_packages(flight.root).items() if p.get('type') == 'typo3-cms-extension'
            and not n.startswith('typo3/cms-') and n not in own]


def cmd_touchpoints(args) -> None:
    flight = Flight.load()
    names = args.package or default_packages(flight)
    if not names:
        die('no third-party TYPO3 extension to check. Pass --package <name>')
    lock = locked_packages(flight.root)
    files = project_files(flight)
    report = {'at': now(), 'verified': bool(args.verify), 'packages': {}}
    total = 0
    for name in names:
        info = package_info(flight, name, lock)
        hits = scan(info, files, flight.root)
        if args.verify:
            verify(flight, info, hits, files)
        report['packages'][name] = {'info': {k: v for k, v in info.items() if k not in ('templates', 'labels')}, 'touchpoints': hits}
        total += len(hits)
        kinds: dict[str, int] = {}
        for h in hits:
            kinds[h['kind']] = kinds.get(h['kind'], 0) + 1
        print(f'{name} {info["version"]}: {len(hits)} touchpoint(s)' + (': ' + ', '.join(f'{v} {k}' for k, v in kinds.items()) if kinds else ''))
        for h in hits:
            where = f'{h["file"]}:{h["line"]}'
            print(f'  {h["kind"]:<19} {where:<60} {h["detail"] or h["code"][:80]}')
            if args.verify:
                print(f'  {"":<19} -> {h["verify"]}' + ('' if h['status'] == 'ok' else f'  [{h["status"]}]'))
    path = flight.dir / 'touchpoints.json'
    write_json(path, report)
    flight.log.setdefault('touchpoints', []).append({'label': args.label, 'verified': bool(args.verify), 'total': total,
                                                     'packages': {n: len(p['touchpoints']) for n, p in report['packages'].items()},
                                                     'attention': sum(1 for p in report['packages'].values() for h in p['touchpoints']
                                                                      if h.get('status') == 'attention'),
                                                     'manual': sum(1 for p in report['packages'].values() for h in p['touchpoints']
                                                                   if h.get('status') == 'manual'),
                                                     **flight.stamp()})
    entry = flight.log['touchpoints'][-1]
    flight.event(f'touchpoints {args.label}: {total} in {len(names)} package(s)' + (' (verified against the target)' if args.verify else ''))
    flight.save()
    if args.verify:
        print(f'\nverified: {total - entry["attention"] - entry["manual"]} ok, {entry["attention"]} need attention, {entry["manual"]} need a human look')
    print(f'\nfull report: {flight.rel(path)}')
