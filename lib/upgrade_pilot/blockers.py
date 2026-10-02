"""Go-live blockers: a decision to fly with something that must not go live, and the proof that it is gone.

The typical one is a third-party package used from a development branch because no release supports
the target yet. The flight can continue and land with it, but the result is not releasable until the
blocker is resolved: a release that supports the target exists, the project uses it, the tests were
green afterwards, and the package's touchpoints were verified on it.
"""

from __future__ import annotations

from .core import Flight, die, git, load_json, now
from .init import locked_packages


def open_blockers(flight: Flight) -> list[dict]:
    return [b for b in flight.log.get('blockers', []) if b['status'] == 'open']


def find(flight: Flight, package: str) -> dict:
    entry = next((b for b in open_blockers(flight) if b['package'] == package), None)
    if not entry:
        die(f'no open blocker for {package}. upgrade-pilot blockers list shows them')
    return entry


def lock_changed_at(flight: Flight) -> str | None:
    """When composer.lock last changed in git, or None while it is uncommitted or untracked."""
    if git(flight.root, 'status', '--porcelain', '--', 'composer.lock'):
        return None
    return git(flight.root, 'log', '-1', '--format=%cI', '--', 'composer.lock') or None


def resolution_checks(flight: Flight, entry: dict) -> list[tuple[str, bool, str]]:
    """(check, passed, detail) for every condition a blocker has to meet."""
    from .catalog import is_stable
    from .platform import allows
    checks = []
    locked = locked_packages(flight.root).get(entry['package'])
    version = (locked or {}).get('version', '')
    stable = bool(locked) and is_stable(version)
    checks.append(('a released version is installed', stable, f'composer.lock: {version or "not installed"}'))
    target = entry.get('core')
    core_ok = False
    if stable and target:
        requires = {k: v for k, v in (locked.get('require') or {}).items() if k.startswith('typo3/cms-')}
        core_ok = bool(requires) and all(allows(c, target) for c in requires.values())
        checks.append((f'it supports TYPO3 {target}', core_ok, ', '.join(f'{k} {v}' for k, v in requires.items()) or 'no core requirement'))
    changed = lock_changed_at(flight)
    checks.append(('the change is committed', bool(changed), f'composer.lock last committed {changed}' if changed else 'composer.lock has uncommitted changes'))
    suites = flight.config.get('tests', {})
    measured = {}
    for m in flight.log.get('measurements', []):
        if changed and m['at'] >= changed:
            measured[m['suite']] = m
    missing = [s for s in suites if s not in measured]
    red = [s for s, m in measured.items() if m['exit'] != 0]
    detail = ('no test suite configured (config.json -> tests)' if not suites else
              'missing: ' + ', '.join(missing) if missing else ('red: ' + ', '.join(red) if red else 'all green'))
    checks.append(('every suite measured green after it', bool(changed) and bool(suites) and not missing and not red, detail))
    report = load_json(flight.dir / 'touchpoints.json', {}) or {}
    hits = ((report.get('packages') or {}).get(entry['package']) or {}).get('touchpoints')
    runs = [t for t in flight.log.get('touchpoints', []) if t.get('verified') and changed and t['at'] >= changed]
    if hits is None and not runs:
        checks.append(('touchpoints verified after it', False, 'run upgrade-pilot deps touchpoints --verify --package ' + entry['package']))
    else:
        attention = [h for h in hits or [] if h.get('status') == 'attention']
        checks.append(('touchpoints verified after it, nothing needs attention', bool(runs) and not attention,
                       f'{len(attention)} need attention' if attention else ('verified' if runs else 'not verified since the change')))
    return checks


def cmd_blockers(args) -> None:
    flight = Flight.load()
    blockers = flight.log.setdefault('blockers', [])
    if args.action == 'list':
        if not blockers:
            print('no go-live blockers recorded')
        for b in blockers:
            print(f'{b["status"]:<9} {b["package"]:<40} uses {b["use"]:<14} {b["reason"]}')
            if b['status'] == 'open' and b.get('waits_for'):
                print(f'          waits for: {b["waits_for"]}')
            if b['status'] != 'open':
                print(f'          {b["status"]} {b.get("closed_at", "")[:10]}: {b.get("note") or ""}')
        return
    if not args.package:
        die('--package is required')
    if args.action == 'add':
        if any(b['package'] == args.package for b in open_blockers(flight)):
            die(f'{args.package} already has an open blocker')
        if not args.use or not args.reason:
            die('add needs --use (the branch or version used meanwhile) and --reason')
        core = (flight.config.get('facts', {}).get(flight.config.get('target'), {}) or {}).get('core_latest', '').lstrip('v') \
            or flight.config.get('target')
        if flight.config.get('scope') == 'packages':
            core = (flight.config.get('source_installed') or core)
        blockers.append({'package': args.package, 'use': args.use, 'reason': args.reason, 'waits_for': args.waits_for or '',
                         'core': core, 'status': 'open', 'opened_at': now(), **{'phase': flight.log.get('phase')}})
        flight.event(f'go-live blocker added: {args.package} uses {args.use} ({args.reason})')
        flight.save()
        print(f'go-live blocker recorded for {args.package}. The flight can land, the result is not releasable until it is resolved.')
        return
    entry = find(flight, args.package)
    if args.action == 'check' or args.action == 'resolve':
        checks = resolution_checks(flight, entry)
        for name, passed, detail in checks:
            print(f'  [{"x" if passed else " "}] {name}: {detail}')
        if args.action == 'check':
            return
        if not all(p for _, p, _ in checks):
            die('not resolved: every check has to pass. The blocker stays open')
        entry.update({'status': 'resolved', 'closed_at': now(), 'note': args.note or '',
                      'evidence': [f'{n}: {d}' for n, _, d in checks]})
        flight.event(f'go-live blocker resolved: {args.package}')
        flight.save()
        print(f'resolved: {args.package}')
        return
    if args.action == 'drop':
        if not args.note:
            die('drop needs --note: why the blocker no longer applies (package removed, replaced, decision)')
        entry.update({'status': 'dropped', 'closed_at': now(), 'note': args.note})
        flight.event(f'go-live blocker dropped: {args.package} ({args.note})')
        flight.save()
        print(f'dropped: {args.package}')
