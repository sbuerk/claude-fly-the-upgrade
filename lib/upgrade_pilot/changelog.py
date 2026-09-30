"""Changelog triage: which Breaking / Deprecation entries touch own code.

`fetch` sparse-clones only Documentation/Changelog of the target core branch.
`match` pulls the :php: and :typoscript: literals out of every entry between
source and target and searches own extensions for them. A heuristic, it will
produce weak hits and it will miss string-built class names, but it turns
hundreds of entries into a short list worth reading first.
"""

from __future__ import annotations

import re
from pathlib import Path

from .core import Flight, die, now, sh, write_json

REPO = 'https://github.com/TYPO3/typo3.git'
CHANGELOG = 'typo3/sysext/core/Documentation/Changelog'
TYPES = ('Breaking', 'Deprecation', 'Feature', 'Important')
GENERIC = {'get', 'set', 'add', 'run', 'init', 'main', 'render', 'process', 'handle', 'create', 'getinstance',
           'execute', 'build', 'load', 'fetch', 'remove', 'update', 'delete', 'insert', 'count', 'find', 'has',
           'is', 'with', 'start', 'reset', 'clear', 'getvalue', 'setvalue'}
SEARCH_SUFFIXES = ('.php', '.typoscript', '.tsconfig', '.html', '.yaml', '.yml', '.xml', '.xlf', '.ts', '.txt')


def cache_dir(flight: Flight, version: str) -> Path:
    return flight.dir / 'cache' / f'changelog-{version}'


def cmd_fetch(args) -> None:
    flight = Flight.load()
    version = args.version or flight.config['target']
    target = cache_dir(flight, version)
    if (target / CHANGELOG).is_dir() and not args.refresh:
        print(f'already fetched: {flight.rel(target / CHANGELOG)}')
        return
    if target.exists():
        sh(f'rm -rf {target}', flight.root)
    target.parent.mkdir(parents=True, exist_ok=True)
    branch = version
    rc, out, _ = sh(f'git ls-remote --heads {REPO} {branch}', flight.root)
    if rc != 0 or not out.strip():
        branch = 'main'
    steps = [
        f'git clone --quiet --depth 1 --filter=blob:none --sparse --branch {branch} {REPO} {target}',
        f'git -C {target} sparse-checkout set {CHANGELOG}',
    ]
    for step in steps:
        rc, out, _ = sh(step, flight.root)
        if rc != 0:
            die(f'{step}\n{out}')
    flight.event(f'changelog {version} fetched from branch {branch}')
    flight.save()
    print(f'fetched changelog of {version} (branch {branch}) into {flight.rel(target / CHANGELOG)}')


def version_key(name: str) -> tuple:
    parts = [int(p) for p in re.findall(r'\d+', name)]
    return tuple(parts + [99 if name.endswith('.x') else 0])


def in_range(name: str, source: str, target: str, include_source_major: bool) -> bool:
    if not re.match(r'^\d+\.\d+(\.x)?$', name):
        return False
    key = version_key(name)[:2]
    src = version_key(source)[:2]
    tgt = version_key(target)[:2]
    if src < key <= tgt:
        return True
    return include_source_major and key[0] == src[0] and key <= src


def parse_entry(path: Path) -> dict:
    return parse_entry_text(path.name, path.read_text(encoding='utf-8', errors='replace'))


def parse_entry_text(name: str, text: str) -> dict:
    """One TYPO3-style changelog rst: type from the file name, title, :php: and :typoscript: literals."""
    lines = text.splitlines()
    title = ''
    for index, line in enumerate(lines[:-1]):
        if re.match(r'^[=]{5,}$', lines[index + 1]) and line.strip() and not line.startswith('..'):
            title = line.strip()
            break
    php = set()
    for literal in re.findall(r':php:`([^`]+)`', text):
        php.add(literal.strip())
    typoscript = {t.strip() for t in re.findall(r':typoscript:`([^`]+)`', text)}
    return {'file': name, 'type': name.split('-')[0], 'title': title, 'php': sorted(php), 'typoscript': sorted(typoscript)}


PHP_BUILTIN = re.compile(r'^(E_[A-Z_]+|PHP_[A-Z_]+|DIRECTORY_SEPARATOR|PATH_SEPARATOR|JSON_[A-Z_]+|LC_[A-Z]+)$')
GENERIC_GLOBALS = {'TCA', 'TYPO3_CONF_VARS', 'BE_USER', 'LANG', 'TYPO3_REQUEST', 'TSFE'}
COMMENT = re.compile(r'^\s*(\*|//|#|/\*)')


def needles(entry: dict) -> list[dict]:
    """Search patterns from the literals of one entry.

    strength "strong" means the entry names exactly this symbol and own code uses
    it. Members (->method, ::CONST) are strong only in files that also reference
    the class. A bare class name is strong only when the entry is about the class
    itself (it names no member of it), otherwise it is context, not a hit.
    """
    out = []
    members_of: dict[str, set] = {}
    parsed = []
    for literal in entry['php']:
        literal = literal.strip().lstrip('\\').rstrip(';')
        fq = re.match(r'^([A-Z][\w]*(?:\\[\w]+)+)(?:(->|::)\$?(\w+))?', literal)
        parsed.append((literal, fq))
        if fq and fq.group(3):
            members_of.setdefault(fq.group(1), set()).add(fq.group(3))
    for literal, fq in parsed:
        if fq:
            fqcn, sep, member = fq.group(1), fq.group(2), fq.group(3)
            short = fqcn.rsplit('\\', 1)[-1]
            if member:
                pattern = rf'\b{re.escape(short)}::{re.escape(member)}\b' if sep == '::' else rf'->{re.escape(member)}\s*\('
                if sep == '->' and (member.lower() in GENERIC or len(member) <= 4):
                    strength = 'context'
                else:
                    strength = 'strong'
                out.append({'label': f'{short}{sep}{member}', 'pattern': re.compile(pattern), 'class': short, 'strength': strength})
            elif fqcn not in members_of:
                about_class = re.search(rf'\b{re.escape(short)}\b', entry['title']) is not None
                out.append({'label': fqcn, 'pattern': re.compile(r'\\?' + re.escape(fqcn)), 'class': None,
                            'strength': 'strong' if about_class else 'weak'})
            continue
        if re.match(r"^\$GLOBALS\[.+\]", literal):
            keys = re.findall(r"\[['\"]?([\w-]+)", literal)
            generic = len(keys) == 1 and keys[0] in GENERIC_GLOBALS
            out.append({'label': literal, 'pattern': re.compile(re.escape(literal).replace("'", "['\"]")), 'class': None,
                        'strength': 'weak' if generic else 'strong'})
            continue
        constant = re.match(r'^([A-Z][A-Z0-9_]{5,})$', literal)
        if constant and not PHP_BUILTIN.match(literal):
            out.append({'label': literal, 'pattern': re.compile(rf'\b{re.escape(literal)}\b'), 'class': None,
                        'strength': 'strong' if '_' in literal else 'weak'})
            continue
        method = re.match(r'^(?:->|::)?(\w{6,})\(\)$', literal)
        if method and method.group(1).lower() not in GENERIC:
            out.append({'label': literal, 'pattern': re.compile(rf'(->|::){re.escape(method.group(1))}\s*\('), 'class': None, 'strength': 'weak'})
    for literal in entry['typoscript']:
        literal = literal.strip()
        if len(literal) > 8:
            out.append({'label': literal, 'pattern': re.compile(re.escape(literal)), 'class': None, 'strength': 'weak'})
    return out


def own_files(flight: Flight) -> dict[str, list[str]]:
    files = {}
    for ext in flight.extensions():
        base = flight.root / ext['path']
        for path in base.rglob('*'):
            parts = path.relative_to(base).parts
            if any(p in ('vendor', '.Build', 'node_modules', '.git', 'var', 'public', '.upgrade-pilot') for p in parts):
                continue
            if path.is_file() and path.suffix in SEARCH_SUFFIXES:
                files[str(path.relative_to(flight.root))] = path.read_text(encoding='utf-8', errors='replace').splitlines()
    return files


def cmd_match(args) -> None:
    flight = Flight.load()
    source, target = args.source or flight.config['source'], args.target or flight.config['target']
    base = cache_dir(flight, target) / CHANGELOG
    if not base.is_dir():
        die(f'changelog for {target} not fetched. Run: upgrade-pilot changelog fetch')
    dirs = sorted([d for d in base.iterdir() if d.is_dir() and in_range(d.name, source, target, not args.no_source_deprecations)],
                  key=lambda d: version_key(d.name))
    files = own_files(flight)
    counts: dict[str, dict[str, int]] = {}
    matches = []
    for directory in dirs:
        for path in sorted(directory.glob('*.rst')):
            entry = parse_entry(path)
            if entry['type'] not in TYPES:
                continue
            in_source_major = version_key(directory.name)[:2] <= version_key(source)[:2]
            if in_source_major and entry['type'] != 'Deprecation':
                continue
            counts.setdefault(directory.name, {t: 0 for t in TYPES})[entry['type']] += 1
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
            if hits:
                strong = any(h['strength'] == 'strong' for h in hits)
                matches.append({'version': directory.name, **{k: entry[k] for k in ('type', 'file', 'title')},
                                'strength': 'strong' if strong else 'weak', 'hits': hits[:25]})
    print(f'changelog entries between {source} and {target} (plus {source.split(".")[0]}.x deprecations):')
    for version, per_type in counts.items():
        print(f'  {version:<7} ' + '  '.join(f'{t} {n}' for t, n in per_type.items()))
    order = {'Breaking': 0, 'Deprecation': 1, 'Important': 2, 'Feature': 3}
    matches.sort(key=lambda m: (order[m['type']] > 1, m['strength'] != 'strong', order[m['type']], version_key(m['version'])))
    print(f'\n{len(matches)} entries mention something found in own code '
          f'({sum(1 for m in matches if m["strength"] == "strong")} strong):')
    for match in matches:
        if args.strong_only and match['strength'] != 'strong':
            continue
        print(f'  [{match["strength"]}] {match["version"]:<6} {match["file"]}\n      {match["title"]}')
        seen = set()
        for hit in match['hits']:
            key = (hit['file'], hit['line'])
            if key in seen:
                continue
            seen.add(key)
            print(f'      {hit["file"]}:{hit["line"]}  ({hit["needle"]})  {hit["code"]}')
            if len(seen) >= args.hits:
                break
    report = flight.dir / f'changelog-{source}-{target}.json'
    write_json(report, {'at': now(), 'source': source, 'target': target, 'counts': counts, 'matches': matches})
    flight.event(f'changelog match {source}->{target}: {len(matches)} entries touch own code')
    flight.save()
    print(f'\nfull report: {flight.rel(report)}')
