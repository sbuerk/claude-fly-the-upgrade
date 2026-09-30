"""Checklist items, gates and the status overview."""

from __future__ import annotations

from .core import DATA_DIR, Flight, die, git_branch, load_json, now

PHASES = ['preflight', 'flight', 'postflight']
NEXT_PHASE = {'preflight': 'flight', 'flight': 'postflight', 'postflight': 'landed'}
STATUSES = ['open', 'done', 'no', 'na', 'handoff']
MARK = {'open': '[ ]', 'done': '[x]', 'no': '[-]', 'na': '[~]', 'handoff': '[?]'}


def spec() -> dict:
    return load_json(DATA_DIR / 'checklist.json')


def items_of(phase: str) -> list[tuple[str, dict]]:
    out = []
    for section in spec()['phases'][phase]['sections']:
        for item in section['items']:
            out.append((section['title'], item))
    return out


def phase_of(item_id: str) -> str:
    return {'pf': 'preflight', 'fl': 'flight', 'pst': 'postflight'}[item_id.split('.')[0]]


def resolve_id(flight: Flight, wanted: str) -> str:
    ids = list(flight.log['checklist'].keys())
    if wanted in ids:
        return wanted
    matches = [i for i in ids if i.endswith(wanted) or i.startswith(wanted)]
    if len(matches) == 1:
        return matches[0]
    die(f'unknown or ambiguous checklist id "{wanted}". Candidates: {", ".join(matches) or "none"}')
    return ''


def cmd_item(args) -> None:
    flight = Flight.load()
    item_id = resolve_id(flight, args.id)
    if args.status not in STATUSES:
        die(f'status must be one of {", ".join(STATUSES)}')
    if args.status in ('no', 'na') and not args.note:
        die('"no" and "na" need --note with a reason. That is the difference between an accepted risk and a forgotten one.')
    entry = flight.log['checklist'][item_id]
    entry.update({'status': args.status, 'at': now()})
    if args.note:
        entry['note'] = args.note
    if args.evidence:
        entry['evidence'] = args.evidence
    flight.event(f'{item_id} -> {args.status}' + (f': {args.note}' if args.note else ''))
    flight.save()
    print(f'{MARK[args.status]} {item_id}')


def blockers(flight: Flight, phase: str) -> list[tuple[str, dict]]:
    return [(item['id'], item) for _, item in items_of(phase) if flight.log['checklist'][item['id']]['status'] == 'open']


def cmd_gate(args) -> None:
    flight = Flight.load()
    phase = args.phase
    gate = spec()['phases'][phase]['gate']
    if args.decision == 'show':
        print(f'Gate "{gate["title"]}" ({phase})')
        print('  GO when:')
        for line in gate['go']:
            print(f'    + {line}')
        print('  NO-GO when:')
        for line in gate['nogo']:
            print(f'    - {line}')
        open_items = blockers(flight, phase)
        print(f'  open checklist items: {len(open_items)}')
        for item_id, item in open_items:
            print(f'    {item_id:<28} ({item["owner"]}) {item["title"]}')
        handoff = [i for _, i in items_of(phase) if flight.log['checklist'][i['id']]['status'] == 'handoff']
        if handoff:
            print(f'  waiting for a human: {", ".join(i["id"] for i in handoff)}')
        return
    if not args.note:
        die('a gate decision needs --note: the reason, in one or two sentences')
    open_items = blockers(flight, phase)
    if args.decision == 'go' and open_items and not args.force:
        print('Refusing GO, open items:')
        for item_id, item in open_items:
            print(f'  {item_id:<28} ({item["owner"]}) {item["title"]}')
        die('answer them (done / no / na / handoff) or pass --force with a note explaining why.')
    by = args.by or ('pilot' if flight.config.get('gates') == 'auto' else 'human')
    flight.log['gates'][phase] = {
        'gate': gate['title'], 'decision': args.decision, 'by': by, 'note': args.note,
        'forced_over': [i for i, _ in open_items] if args.force else [], 'at': now(),
        'branch': git_branch(flight.root),
    }
    if args.decision == 'go':
        flight.log['phase'] = NEXT_PHASE[phase]
    flight.event(f'Gate {gate["title"]}: {args.decision.upper()} by {by}. {args.note}')
    flight.save()
    print(f'Gate "{gate["title"]}": {args.decision.upper()} ({by}). Phase is now {flight.log["phase"]}.')


def cmd_phase(args) -> None:
    flight = Flight.load()
    flight.log['phase'] = args.phase
    flight.event(f'Phase set to {args.phase}')
    flight.save()
    print(f'phase: {args.phase}')


def cmd_status(args) -> None:
    flight = Flight.load()
    config, log = flight.config, flight.log
    phase = log.get('phase')
    print(f'TYPO3 {config.get("source_installed") or config["source"]} -> {config["target"]}   phase: {phase}   branch: {git_branch(flight.root)}')
    print(f'flight log: {flight.rel(flight.dir / "FLIGHT-LOG.md")}')
    for name in PHASES:
        items = items_of(name)
        counts = {s: 0 for s in STATUSES}
        for _, item in items:
            counts[log['checklist'][item['id']]['status']] += 1
        gate = log['gates'].get(name)
        gate_text = f'gate {gate["decision"].upper()} ({gate["by"]})' if gate else 'gate pending'
        print(f'  {name:<11} done {counts["done"]:>2}  no {counts["no"]:>2}  na {counts["na"]:>2}  handoff {counts["handoff"]:>2}  open {counts["open"]:>2}   {gate_text}')
    if phase in PHASES:
        open_items = blockers(flight, phase)
        if open_items:
            print(f'\nopen in {phase}:')
            for item_id, item in open_items:
                print(f'  {item_id:<28} {item["owner"]:<7} {item["title"]}')
                if args.verbose:
                    print(f'  {"":<28} how: {item["how"]}')
    unread = [c['ref'] for c in log.get('context', []) if not c.get('digest')]
    if unread:
        print(f'\ncontext not read yet: {", ".join(unread)} (upgrade-pilot context list)')
    if log.get('measurements'):
        print('\nlast measurements:')
        for m in log['measurements'][-4:]:
            print(f'  {m["label"]:<40} {m["suite"]:<11} exit {m["exit"]}  {m.get("summary", "")}')
    for name, campaign in log.get('campaigns', {}).items():
        rules = campaign['rules'].values()
        counts = {}
        for rule in rules:
            counts[rule['status']] = counts.get(rule['status'], 0) + 1
        print(f'\ncampaign {name} ({campaign["tool"]}): ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
