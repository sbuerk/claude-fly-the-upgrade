"""Human-readable flight log and debrief report, rendered from flightlog.json."""

from __future__ import annotations

from .core import DATA_DIR, Flight, load_json, short_class

MARK = {'open': '[ ]', 'done': '[x]', 'no': '[-]', 'na': '[~]', 'handoff': '[?]'}


def statements_cell(entry: dict) -> str:
    passes = entry.get('passes')
    if entry.get('statements') is None:
        return f'not reported ({len(passes)} pass(es))' if passes else 'not reported'
    text = str(entry['statements'])
    if passes and len(passes) > 1:
        text = ' + '.join(str(p) for p in passes)
    if entry.get('remaining'):
        text += f', {entry["remaining"]} still pending'
    return text


def measurements_table(log: dict, rows: list[dict] | None = None) -> list[str]:
    rows = log.get('measurements', []) if rows is None else rows
    if not rows:
        return ['_No measurement yet._']
    out = ['| Stage | Suite | Result | Exit | Branch @ commit |', '|---|---|---|---|---|']
    for m in rows:
        out.append(f'| {m["label"]} | {m["suite"]} | {m["summary"]} | {m["exit"]} | {m["branch"]} @ {m["commit"]} |')
    out += ['', '_`*` after a commit: measured with uncommitted changes on top of it, usually the change that the next commit records._']
    return out


def key_stages(log: dict) -> list[dict]:
    """Baseline, end of pre-flight, straight after the bump, latest: one row per suite each."""
    rows = log.get('measurements', [])
    labels = []
    for pick in (
        next((m['label'] for m in rows if m['label'] == 'baseline'), None),
        next((m['label'] for m in reversed(rows) if m.get('phase') == 'preflight'), None),
        next((m['label'] for m in rows if m.get('phase') == 'flight'), None),
        rows[-1]['label'] if rows else None,
    ):
        if pick and pick not in labels:
            labels.append(pick)
    out = []
    for label in labels:
        last_run = {}
        for m in rows:
            if m['label'] == label:
                last_run[m['suite']] = m
        out.extend(last_run.values())
    return out


def flight_log(flight: Flight) -> str:
    config, log = flight.config, flight.log
    spec = load_json(DATA_DIR / 'checklist.json')
    lines = [
        f'# Flight log: TYPO3 {config.get("source_installed") or config.get("source")} -> {config.get("target")}',
        '',
        '_Rendered by upgrade-pilot from flightlog.json. Do not edit, it is overwritten._',
        '',
        f'- Phase: **{log.get("phase")}**',
        f'- Base branch: `{config.get("base_branch")}`, pre-flight branch `{config["branches"]["preflight"]}`, '
        f'flight branch `{config["branches"]["flight"]}`',
        f'- Runtime: {config["runtime"]["kind"]}, PHP {config.get("platform", {}).get("php")}, '
        f'database {config.get("platform", {}).get("database", "unknown")}',
        f'- Own extensions: ' + ', '.join(f'`{e["key"]}` ({e["path"]})' for e in config.get('extensions', [])),
        f'- Gate mode: {config.get("gates")}',
        '',
        'Legend: `[x]` done · `[-]` answered no (accepted, with reason) · `[~]` not applicable · `[?]` waiting for a human · `[ ]` open',
        '',
    ]
    for phase, phase_spec in spec['phases'].items():
        lines += [f'## {phase_spec["title"]}', '']
        for section in phase_spec['sections']:
            lines += [f'### {section["title"]}', '']
            for item in section['items']:
                state = log['checklist'].get(item['id'], {'status': 'open'})
                note = f': {state["note"]}' if state.get('note') else ''
                evidence = f' (evidence: {state["evidence"]})' if state.get('evidence') else ''
                lines.append(f'- {MARK[state["status"]]} **{item["title"]}** `{item["id"]}` _{item["owner"]}_{note}{evidence}')
            lines.append('')
        gate = log.get('gates', {}).get(phase)
        if gate:
            forced = f' Forced over: {", ".join(gate["forced_over"])}.' if gate.get('forced_over') else ''
            lines += [f'**Gate {gate["gate"]}: {gate["decision"].upper()}** by {gate["by"]}, {gate["at"][:16]}. {gate["note"]}{forced}', '']
        else:
            lines += [f'**Gate {phase_spec["gate"]["title"]}: pending**', '']
    lines += ['## Instruments', '', '### Test suites', ''] + measurements_table(log) + ['']
    if log.get('scans'):
        lines += ['### Extension Scanner', '', '| Stage | Total | Strong | Weak | Branch @ commit |', '|---|---|---|---|---|']
        lines += [f'| {s["label"]} | {s["total"]} | {s["strong"]} | {s["weak"]} | {s["branch"]} @ {s["commit"]} |' for s in log['scans']]
        lines.append('')
    if log.get('tca'):
        lines += ['### TCA migrations', '', '| Stage | TYPO3 | Messages | In own extensions |', '|---|---|---|---|']
        lines += [f'| {t["label"]} | {t["typo3"]} | {t["count"]} | {t["own"]} |' for t in log['tca']]
        lines.append('')
    deps_log = log.get('dependencies') or {}
    if deps_log.get('docs'):
        lines += ['### Third-party dependencies', '', f'Moves from {deps_log.get("origin")}: {len(deps_log.get("moves", []))} package(s).', '',
                  '| Package | From | To | Documented | New wizards | Report |', '|---|---|---|---|---|---|']
        lines += [f'| {name} | {d["from"] or "(new)"} | {d["to"]} | {d["summary"]} | {", ".join(d["wizards_new"]) or "-"} | {d["report"]} |'
                  for name, d in sorted(deps_log['docs'].items())]
        lines.append('')
    if log.get('schema_runs'):
        lines += ['### Database schema', '', '| Stage | Action | Via | Types | Statements | Exit |', '|---|---|---|---|---|---|']
        lines += [f'| {e["label"]} | {e["action"]} | {e["provider"]} | {e["types"]} | '
                  f'{statements_cell(e)} | {e["exit"]} |' for e in log['schema_runs']]
        lines.append('')
    for name, campaign in log.get('campaigns', {}).items():
        lines += [f'### Campaign `{name}` ({campaign["tool"]}, `{campaign["config"]}`)', '',
                  '| Rule | Status | Files | Commit | Notes |', '|---|---|---|---|---|']
        for rule, entry in sorted(campaign['rules'].items(), key=lambda kv: kv[1].get('order', 99999)):
            notes = []
            if entry.get('new_files'):
                notes.append('new: ' + ', '.join(entry['new_files']))
            if entry.get('markers'):
                notes.append(f'{len(entry["markers"])} marker(s)')
            if entry.get('note'):
                notes.append(entry['note'].strip())
            files = len(entry.get('changed') or entry.get('files') or [])
            lines.append(f'| `{short_class(rule)}` | {entry["status"]} | {files} | {entry.get("commit", "")} | {"; ".join(notes)} |')
        lines.append('')
    lines += ['## Journal', '']
    for event in log.get('events', [])[-200:]:
        lines.append(f'- {event["at"][:16]} [{event.get("phase")}] `{event.get("branch")}@{event.get("commit")}` {event["text"]}')
    return '\n'.join(lines) + '\n'


def final_developer_report(flight: Flight) -> str:
    """The complete technical record of the flight, all phases."""
    config, log = flight.config, flight.log
    commits = []
    for branch_key in ('preflight', 'flight'):
        from .core import git
        branch = config['branches'][branch_key]
        base = config['base_branch'] if branch_key == 'preflight' else config['branches']['preflight']
        out = git(flight.root, 'log', '--reverse', '--format=%h %s', f'{base}..{branch}')
        commits.append((branch_key, branch, out.splitlines() if out else []))
    first = next((m for m in log.get('measurements', []) if m['label'] == 'baseline' and m['suite'] == 'functional'), None) \
        or next((m for m in log.get('measurements', []) if m['label'] == 'baseline'), None)
    lines = [
        f'# Upgrade report: TYPO3 {config.get("source_installed")} -> {config["target"]}', '',
        '## Key stages', '',
        *measurements_table(log, key_stages(log)), '',
        '## Every measurement', '',
        *measurements_table(log), '',
    ]
    if log.get('scans'):
        lines += ['## Extension Scanner over time', '']
        lines += [f'- {s["label"]}: {s["total"]} ({s["strong"]} strong, {s["weak"]} weak)' for s in log['scans']]
        lines.append('')
    if log.get('tca'):
        lines += ['## TCA migrations over time', '']
        lines += [f'- {t["label"]} (TYPO3 {t["typo3"]}): {t["count"]} messages, {t["own"]} in own extensions' for t in log['tca']]
        lines.append('')
    deps_log = log.get('dependencies') or {}
    if deps_log.get('docs'):
        lines += ['## Third-party dependencies', '']
        lines += [f'- {name} {d["from"] or "(new)"} -> {d["to"]}: {d["summary"]} ({d["report"]})' for name, d in sorted(deps_log['docs'].items())]
        lines.append('')
    if log.get('schema_runs'):
        lines += ['## Database schema', '']
        lines += [f'- {e["label"]}: {e["action"]} via {e["provider"]} ({e["types"]}), '
                  f'{statements_cell(e)}, exit {e["exit"]}'
                  for e in log['schema_runs']]
        lines.append('')
    for name, campaign in log.get('campaigns', {}).items():
        statuses = {}
        for entry in campaign['rules'].values():
            statuses[entry['status']] = statuses.get(entry['status'], 0) + 1
        lines.append(f'- Campaign `{name}`: ' + ', '.join(f'{v} {k}' for k, v in sorted(statuses.items())))
        for rule, entry in campaign['rules'].items():
            if entry.get('new_files') or entry.get('markers') or entry['status'] == 'skipped':
                lines.append(f'  - `{short_class(rule)}` {entry["status"]}: '
                             + '; '.join(filter(None, [
                                 'generated ' + ', '.join(entry.get('new_files', [])) if entry.get('new_files') else '',
                                 'markers: ' + ' | '.join(entry.get('markers', [])[:3]) if entry.get('markers') else '',
                                 entry.get('note', '').strip()])))
    lines += ['', '## Commits', '']
    for key, branch, entries in commits:
        lines.append(f'### {key}: `{branch}` ({len(entries)} commits)')
        lines += [f'- {e}' for e in entries] or ['- none']
        lines.append('')
    lines += ['## Gates', '']
    for phase, gate in log.get('gates', {}).items():
        lines.append(f'- {gate["gate"]} ({phase}): {gate["decision"].upper()} by {gate["by"]}. {gate["note"]}')
    open_items = [(i, s) for i, s in log['checklist'].items() if s['status'] in ('open', 'handoff')]
    lines += ['', '## Left for humans', '']
    lines += [f'- `{i}` {s["status"]}{": " + s["note"] if s.get("note") else ""}' for i, s in open_items] or ['- nothing']
    accepted = [(i, s) for i, s in log['checklist'].items() if s['status'] == 'no']
    if accepted:
        lines += ['', '## Accepted risks (answered "no")', '']
        lines += [f'- `{i}`: {s["note"]}' for i, s in accepted]
    debrief = flight.dir / 'DEBRIEF.md'
    lines += ['', '## Debrief', '']
    if debrief.is_file():
        lines += [debrief.read_text(encoding='utf-8').strip(), '']
    else:
        lines += ['_Not written yet: predicted versus actual, what took longest, what only the tests caught, '
                  'new checklist lines. Write `.upgrade-pilot/DEBRIEF.md` and run `upgrade-pilot report` again._', '']
    if first:
        lines.insert(2, f'Baseline before departure ({first["suite"]}): {first["summary"]} (exit {first["exit"]}).\n')
    return '\n'.join(lines) + '\n'
