"""Database schema updates: TYPO3 Console when available, the core otherwise.

The core's only CLI schema step is `extension:setup`. It applies the safe
statements (create and alter, never drop or rename) and has no dry run.
TYPO3 Console (helhum/typo3-console) adds `database:updateschema` with update
types and `--dry-run`, which is what makes the point of no return reviewable:
you see the statements before they run, on every environment. Console 7.x
shipped it on its own `typo3cms` binary, from 8.0 it runs through `typo3`.
"""

from __future__ import annotations

import re

from .core import Flight, die, now
from .init import locked_packages, version_of
from .platform import version_facts, vtuple

CONSOLE = 'helhum/typo3-console'
SAFE_TYPES = {'safe', '*.add', '*.change', 'field.add', 'field.change', 'table.add', 'table.change'}


def is_safe(types: str) -> bool:
    return all(part.strip() in SAFE_TYPES for part in types.split(',') if part.strip())


def detect(flight: Flight) -> dict:
    """Which schema tooling this project really has, confirmed by the runtime."""
    version = version_of(locked_packages(flight.root), CONSOLE)
    info = {'console_version': version, 'provider': 'core', 'bin': flight.tool('typo3'), 'command': 'extension:setup'}
    candidates = [flight.tool('typo3')]
    if version:
        major = vtuple(version)[0] if version[:1].isdigit() else None
        candidates = ['vendor/bin/typo3cms', flight.tool('typo3')] if major is not None and major < 8 \
            else [flight.tool('typo3'), 'vendor/bin/typo3cms']
    for binary in candidates:
        rc, out, _, _ = flight.run_runtime(f'{binary} list --raw', merge=False)
        if rc == 0 and re.search(r'^database:updateschema\s', out, re.M):
            info.update({'provider': 'typo3-console' if version else 'typo3 (command found)', 'bin': binary,
                         'command': 'database:updateschema'})
            break
    else:
        if version:
            info['warning'] = f'{CONSOLE} {version} is locked, but no binary offers database:updateschema'
    return info


def suggestion(flight: Flight) -> str:
    target = flight.config['target']
    facts = flight.config.get('facts', {}).get(target)
    if not facts or 'companions' not in facts:
        facts = version_facts(target, flight.config.get('source_installed'), flight.config.get('platform', {}).get('php'))
        flight.config.setdefault('facts', {})[target] = facts
    console = facts.get('companions', {}).get(CONSOLE)
    if not console:
        return f'No release of {CONSOLE} supports TYPO3 {target} yet.'
    composer = flight.config['runtime']['composer']
    if console.get('bridge'):
        return (f'{console["bridge"]["constraint"]} supports the installed {flight.config.get("source_installed")} and {target} '
                f'(newest such release {console["bridge"]["latest"]}): {composer} require "{CONSOLE}:{console["bridge"]["constraint"]}"')
    return (f'No release supports both {flight.config.get("source_installed")} and {target}. Add it together with the bump: '
            f'"{CONSOLE}:{console["constraint"]}" (newest {console["latest_compatible"]})')


def record(flight: Flight, entry: dict) -> None:
    flight.log.setdefault('schema_runs', []).append({**entry, **flight.stamp()})
    flight.event(f'schema {entry["action"]} [{entry["label"]}] via {entry["provider"]}: exit {entry["exit"]}'
                 + (f', {entry["statements"]} statement(s)' if entry.get('statements') is not None else ''))
    flight.save()


def statements_of(output: str) -> list[str]:
    parts = (s.strip().rstrip(';').strip() for s in re.split(r';\s*\n', output.strip()))
    return [s for s in parts if s and not s.startswith('[')]


def dry_run(flight: Flight, info: dict, types: str, label: str) -> tuple[int, list[str], str]:
    cmd = f"{info['bin']} database:updateschema '{types}' --dry-run --raw"
    rc, out, err, log = flight.run_runtime(cmd, log_name=f'schema-plan-{label}', merge=False)
    if rc != 0:
        print(err[-1500:])
    return rc, statements_of(out) if rc == 0 else [], flight.rel(log)


def cmd_schema(args) -> None:
    flight = Flight.load()
    info = detect(flight)
    flight.config['schema'] = {**info, 'detected': now()}

    if args.action == 'check':
        flight.event(f'schema tooling: {info["provider"]} ({info["bin"]} {info["command"]})')
        flight.save()
        print(f'schema tooling: {info["provider"]}, {info["bin"]} {info["command"]}'
              + (f' (TYPO3 Console {info["console_version"]})' if info.get('console_version') else ''))
        if info.get('warning'):
            print(f'  WARNING: {info["warning"]}')
        if info['provider'] == 'core':
            print('  The core applies safe schema changes with extension:setup, without a dry run, and cannot drop or rename.')
            print('  Reviewing the statements before the point of no return, on every environment, needs TYPO3 Console')
            print('  (database:updateschema --dry-run). It is a production dependency, adding it is the team\'s decision.')
            print(f'  Suggestion: {suggestion(flight)}')
            flight.save()
        return

    label = args.label or args.action
    if args.action == 'apply' and not args.passes:
        args.passes = 2 if info['provider'] == 'core' else 3
    types = args.types or ('destructive' if args.action == 'plan' and args.destructive else 'safe')

    if args.action == 'plan':
        if info['provider'] == 'core':
            print('The core has no CLI dry run for schema changes. Review them in Admin Tools > Maintenance > '
                  'Analyze Database Structure, or add TYPO3 Console:')
            print(f'  {suggestion(flight)}')
            raise SystemExit(2)
        rc, statements, log = dry_run(flight, info, types, label)
        record(flight, {'action': 'plan', 'label': label, 'provider': info['provider'], 'types': types,
                        'exit': rc, 'statements': len(statements), 'sql': statements[:200], 'log': log})
        print(f'schema plan [{label}] types "{types}": {len(statements)} statement(s), exit {rc}. Log: {log}')
        for statement in statements[:60]:
            print(f'  {statement[:200]}')
        if len(statements) > 60:
            print(f'  ... {len(statements) - 60} more in the log')
        raise SystemExit(0 if rc == 0 else 1)

    # apply
    if not is_safe(types) and not args.allow_destructive:
        die(f'"{types}" drops or renames. Destructive schema changes run only on an explicit human decision, '
            'after the rollback window: pass --allow-destructive when that decision is recorded.')
    if info['provider'] == 'core':
        if types != 'safe':
            die('the core only applies safe changes (extension:setup). Specific update types need TYPO3 Console.')
        # One pass does not always converge (observed 12.4 -> 13.4: a second pass still changes columns).
        # extension:setup is idempotent, so run it twice. Without a dry run the result cannot be verified.
        codes, logs = [], []
        for number in range(1, args.passes + 1):
            rc, out, _, log = flight.run_runtime(f"{info['bin']} extension:setup", log_name=f'schema-apply-{label}-pass{number}')
            codes.append(rc)
            logs.append(flight.rel(log))
            if rc != 0:
                print(out[-2000:])
                break
        rc = max(codes)
        record(flight, {'action': 'apply', 'label': label, 'provider': 'core', 'types': 'safe', 'exit': rc,
                        'statements': None, 'passes': [None] * len(codes), 'remaining': None, 'log': logs[-1]})
        print(f'schema apply [{label}] via extension:setup, {len(codes)} pass(es): exit {rc}. '
              'Statements and convergence cannot be verified without TYPO3 Console.')
        raise SystemExit(0 if rc == 0 else 1)

    # TYPO3 Console: plan, apply, re-plan until the dry run is empty.
    passes, all_statements, logs = [], [], []
    remaining: list[str] = []
    rc = 0
    number = 0
    while True:
        number += 1
        plan_rc, statements, plan_log = dry_run(flight, info, types, f'{label}-pass{number}')
        if plan_rc != 0:
            die(f'dry run failed (exit {plan_rc}), nothing more applied. Log: {plan_log}')
        if not statements or len(passes) >= args.passes:
            remaining = statements  # empty: converged. Otherwise: pass limit reached.
            break
        rc, out, _, log = flight.run_runtime(f"{info['bin']} database:updateschema '{types}'", log_name=f'schema-apply-{label}-pass{number}')
        passes.append(len(statements))
        all_statements.extend(statements)
        logs.append(flight.rel(log))
        if rc != 0:
            print(out[-2000:])
            break
    converged = rc == 0 and not remaining
    record(flight, {'action': 'apply', 'label': label, 'provider': info['provider'], 'types': types,
                    'exit': rc if converged or rc != 0 else 3, 'statements': sum(passes), 'passes': passes,
                    'remaining': len(remaining), 'sql': all_statements[:300], 'log': logs[-1] if logs else None})
    shape = ' + '.join(str(p) for p in passes) or '0'
    if not passes:
        print(f'schema apply [{label}] types "{types}": nothing to do, the dry run is empty')
    elif converged:
        print(f'schema apply [{label}] types "{types}": {len(passes)} pass(es) ({shape} statements), converged: dry run empty')
    elif rc != 0:
        print(f'schema apply [{label}] failed in pass {len(passes)} (exit {rc}). Logs: {", ".join(logs)}')
    else:
        print(f'schema apply [{label}] did NOT converge after {len(passes)} pass(es) ({shape}), {len(remaining)} statement(s) '
              'still pending. Stop and find out why (charset/collation drift, conflicting definitions) before any other environment.')
    raise SystemExit(0 if converged or not passes else (rc or 3))
