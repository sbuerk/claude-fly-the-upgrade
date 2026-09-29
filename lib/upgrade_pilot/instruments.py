"""Instruments: test measurements, Extension Scanner, TCA migration check."""

from __future__ import annotations

import re

from .core import Flight, die, extract_json

COUNT_KEYS = ['tests', 'assertions', 'errors', 'failures', 'warnings', 'deprecations', 'phpunit_deprecations',
              'notices', 'skipped', 'incomplete', 'risky']

PROBLEM_START = re.compile(
    r'^(There (was|were) \d+ \w+|\d+ tests? triggered \d+ |No tests executed|PHP Fatal error|Fatal error|'
    r'An error occurred|Error: )', re.M)


def parse_phpunit(text: str) -> dict:
    result: dict = {}
    ok = list(re.finditer(r'^OK \((\d+) tests?, (\d+) assertions?\)', text, re.M))
    detailed = list(re.finditer(r'^Tests: (\d+), Assertions: (\d+)(.*)$', text, re.M))
    if detailed and (not ok or detailed[-1].start() > ok[-1].start()):
        match = detailed[-1]
        result['tests'] = int(match.group(1))
        result['assertions'] = int(match.group(2))
        for key, value in re.findall(r'([A-Za-z ]+): (\d+)', match.group(3)):
            name = key.strip().lower().replace(' ', '_')
            result[name] = int(value)
        before = text[:match.start()].rstrip().splitlines()
        result['status'] = before[-1].strip() if before else ''
    elif ok:
        result['tests'] = int(ok[-1].group(1))
        result['assertions'] = int(ok[-1].group(2))
        result['status'] = 'OK'
    elif 'No tests executed' in text:
        result['status'] = 'No tests executed'
    return result


def summarize(counts: dict) -> str:
    if not counts.get('tests') and not counts.get('status'):
        return 'no PHPUnit summary found'
    parts = [f'{counts.get("tests", 0)} tests', f'{counts.get("assertions", 0)} assertions']
    for key in COUNT_KEYS[2:]:
        if counts.get(key):
            parts.append(f'{counts[key]} {key.replace("_", " ")}')
    prefix = 'OK - ' if counts.get('status', '').startswith('OK') and len(parts) == 2 else ''
    return prefix + ' · '.join(parts)


def problems(text: str, limit: int) -> str:
    match = PROBLEM_START.search(text)
    if not match:
        return ''
    lines = text[match.start():].splitlines()
    cut = []
    for line in lines:
        if re.match(r'^(ERRORS!|FAILURES!|OK, but|Tests: \d+)', line):
            break
        cut.append(line)
    if len(cut) > limit:
        cut = cut[:limit] + [f'... ({len(cut) - limit} more lines in the log)']
    return '\n'.join(cut)


def suites_for(flight: Flight, suite: str) -> list[str]:
    tests = flight.config.get('tests', {})
    if not tests:
        die('no test suites configured. Edit .upgrade-pilot/config.json -> tests, e.g. '
            '{"unit": {"cmd": "Build/Scripts/runTests.sh -s unit", "where": "host"}}')
    if suite == 'all':
        return [name for name, spec in tests.items() if not spec.get('exclude_from_all')]
    if suite not in tests:
        die(f'unknown suite {suite}. Configured: {", ".join(tests)}')
    return [suite]


def measure(flight: Flight, suite: str, label: str, extra: str = '', show: int = 60, record: bool = True) -> list[dict]:
    results = []
    for name in suites_for(flight, suite):
        spec = flight.config['tests'][name]
        cmd = spec['cmd'] + (f' {extra}' if extra else '')
        if spec.get('where') == 'runtime':
            rc, out, err, log = flight.run_runtime(cmd, log_name=f'{name}-{label}')
            out += err
        else:
            rc, out, log = flight.run_host(cmd, log_name=f'{name}-{label}')
        counts = parse_phpunit(out)
        entry = {
            'label': label, 'suite': name, 'exit': rc, **{k: counts.get(k, 0) for k in COUNT_KEYS},
            'status': counts.get('status', ''), 'summary': summarize(counts), 'log': flight.rel(log),
            'extra': extra, **flight.stamp(),
        }
        results.append(entry)
        if record:
            flight.log.setdefault('measurements', []).append(entry)
        print(f'--- {name}: exit {rc} · {entry["status"] or "?"} · {entry["summary"]}')
        print(f'    log: {entry["log"]}')
        detail = problems(out, show) if rc != 0 else ''
        if detail:
            print('\n'.join('    ' + line for line in detail.splitlines()))
    if record:
        flight.event(f'measure {label}: ' + '; '.join(f'{r["suite"]} exit {r["exit"]} ({r["summary"]})' for r in results))
        flight.save()
    return results


def cmd_measure(args) -> None:
    flight = Flight.load()
    results = measure(flight, args.suite, args.label, args.extra or '', args.show, record=not args.no_record)
    if any(r['exit'] != 0 for r in results):
        raise SystemExit(1)


# -- Extension Scanner -------------------------------------------------------

def cmd_scan(args) -> None:
    flight = Flight.load()
    typo3 = flight.tool('typo3')
    targets = args.target or []
    if not targets:
        for ext in flight.extensions():
            targets.append(f'--path={ext["path"]}' if ext['path'] == '.' else ext['key'])
    cmd = f'{typo3} extension:scan {" ".join(targets)} --no-progress --format=json'
    rc, out, err, log = flight.run_runtime(cmd, log_name=f'scan-{args.label}', merge=False)
    data = extract_json(out)
    if data is None or 'summary' not in data:
        print(out[-3000:] + err[-2000:])
        die('the Extension Scanner CLI did not return JSON. Is netresearch/extension-scanner-cli installed '
            '(composer require --dev netresearch/extension-scanner-cli, from its VCS repository)?')
    matches = []
    for ext in data.get('extensions', []):
        for match in ext.get('matches', []):
            matches.append({
                'ext': ext.get('key'), 'file': match.get('file'), 'line': match.get('line'),
                'indicator': match.get('indicator'), 'message': match.get('message'),
                'rest': match.get('restFiles', []),
            })
    summary = data['summary']
    previous = flight.log['scans'][-1] if flight.log.get('scans') else None
    entry = {'label': args.label, 'total': summary.get('total', 0), 'strong': summary.get('strong', 0),
             'weak': summary.get('weak', 0), 'matches': matches, 'log': flight.rel(log), **flight.stamp()}
    flight.log.setdefault('scans', []).append(entry)
    flight.event(f'scan {args.label}: {entry["total"]} findings ({entry["strong"]} strong, {entry["weak"]} weak)')
    flight.save()
    print(f'Extension Scanner [{args.label}]: {entry["total"]} findings ({entry["strong"]} strong, {entry["weak"]} weak)')
    for match in sorted(matches, key=lambda m: (m['indicator'] != 'strong', m['ext'] or '', m['file'] or '', m['line'] or 0)):
        rest = ', '.join(match['rest'])
        print(f'  {match["indicator"]:<6} {match["ext"]}:{match["file"]}:{match["line"]}  {match["message"]}  [{rest}]')
    if previous:
        key = lambda m: (m['ext'], m['file'], m['message'])
        before = {key(m) for m in previous['matches']}
        after = {key(m) for m in matches}
        print(f'  vs [{previous["label"]}]: {len(before - after)} gone, {len(after - before)} new')
        for item in sorted(after - before, key=str):
            print(f'    new: {item[0]}:{item[1]} {item[2]}')


# -- TCA migrations ------------------------------------------------------------

def cmd_tca(args) -> None:
    flight = Flight.load()
    from .init import stage_helpers
    stage_helpers(flight)
    helper = flight.rel(flight.dir / 'bin' / 'tca-migrations.php')
    rc, out, err, log = flight.run_runtime(f'php {helper}', log_name=f'tca-{args.label}', merge=False)
    data = extract_json(out)
    if data is None:
        print(out[-3000:] + err[-3000:])
        die('the TCA migration helper failed. It needs a bootable TYPO3 instance (config/system/settings.php).')
    own = {ext['key'] for ext in flight.extensions()}
    messages = data.get('messages', [])
    own_messages = [m for m in messages if m.get('extension') in own or own & set(m.get('overriddenBy') or [])]
    previous = flight.log['tca'][-1] if flight.log.get('tca') else None
    entry = {'label': args.label, 'typo3': data.get('typo3'), 'count': len(messages), 'own': len(own_messages),
             'messages': messages, 'log': flight.rel(log), **flight.stamp()}
    flight.log.setdefault('tca', []).append(entry)
    flight.event(f'tca {args.label}: {len(messages)} migration messages, {len(own_messages)} in own extensions')
    flight.save()
    print(f'TCA migrations [{args.label}] on TYPO3 {data.get("typo3")}: {len(messages)} messages, {len(own_messages)} in own extensions')
    for message in messages:
        marker = '*' if message in own_messages else ' '
        print(f' {marker} [{message.get("extension") or "?"}:{message.get("table") or "?"}] {message["message"]}')
    if previous:
        print(f'  vs [{previous["label"]}]: {previous["count"]} -> {len(messages)}')
