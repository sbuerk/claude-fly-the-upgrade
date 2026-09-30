"""Reports along the way: at every gate and at the end, for two audiences.

- developer (English): the technical record of the phase, from the flight log;
- pm (English and German): status, outcome, risks and what the team has to do,
  in plain language, for project managers and customers.

Numbers and lists come from the flight log. The prose summary of each report
is written by Claude into `.upgrade-pilot/notes/<phase>-<audience>.<lang>.md`
and embedded, so re-rendering never loses it.
"""

from __future__ import annotations

from .core import DATA_DIR, Flight, die, git, load_json, now
from .render import final_developer_report, measurements_table, statements_cell

PHASES = ('preflight', 'flight', 'postflight')
VARIANTS = (('dev', 'en'), ('pm', 'en'), ('pm', 'de'))

T = {
    'en': {
        'title': {'preflight': 'Pre-flight report', 'flight': 'Upgrade report (flight)', 'postflight': 'Post-flight report',
                  'final': 'Final report'},
        'upgrade': 'TYPO3 upgrade {source} to {target}',
        'project': 'Project', 'date': 'Date', 'period': 'Period', 'status': 'Status',
        'status_go': {'preflight': 'Go: ready for the upgrade', 'flight': 'Cleared: ready for acceptance by your team',
                      'postflight': 'Landed: upgrade completed', 'final': 'Completed'},
        'status_nogo': 'Stopped (No-Go): see the reasons below',
        'status_pending': 'In progress',
        'summary': 'Summary', 'summary_missing': '_The summary for this report has not been written yet._',
        'done': 'What was done', 'results': 'Results', 'risks': 'Risks and accepted limitations',
        'team': 'What your team needs to do or decide', 'next': 'Next steps', 'timeline': 'Timeline',
        'checklist': '{answered} of {total} checklist points answered: {done} done, {no} accepted as a known risk, '
                     '{na} not applicable, {handoff} handed to your team, {open} open.',
        'tests_ok': 'Automated tests: all test suites ({n}) pass.',
        'tests_bad': 'Automated tests: {bad} of {n} test suites do not pass yet ({detail}).',
        'tests_none': 'Automated tests: no measurement in this phase.',
        'tests_change': 'At the start of the phase, {ok} of {n} test suites passed.',
        'scanner': 'Extension Scanner findings (outdated code): {first} at the start, {last} now.',
        'tca': 'Outdated table configuration (TCA) the system has to fix on the fly: {first} at the start, {last} now.',
        'rules': 'Automated code migrations: {committed} applied and reviewed one by one, {skipped} deliberately not applied.',
        'commits': '{n} prepared change(s) (commits) on branch {branch}. Nothing has been published or deployed.',
        'deps': '{n} third-party package(s) checked for documented changes, {breaking} with breaking changes noted.',
        'schema': 'Database structure: {text}.',
        'schema_text': '{n} change(s) prepared and verified in the local test environment',
        'no_risks': 'None recorded.', 'no_team': 'Nothing at the moment.',
        'next_go': {'preflight': 'The upgrade itself can start on branch {flight}. Before anything goes live, the points for your team above have to be done.',
                    'flight': 'Acceptance by your team: frontend and backend checks, staging with production-like data, editors. Then the follow-up phase.',
                    'postflight': 'Your team reviews and merges the branches and deploys them. The next upgrade is due before {next}.'},
        'next_nogo': 'The blockers above have to be resolved. Then the decision is taken again.',
        'next_pending': 'Work in this phase continues.',
        'phase_names': {'preflight': 'Pre-flight (preparation)', 'flight': 'Flight (upgrade)', 'postflight': 'Post-flight (follow-up)'},
        'key_figures': 'Key figures', 'from_to': 'from {a} to {b}',
    },
    'de': {
        'title': {'preflight': 'Bericht Vorbereitung (Pre-Flight)', 'flight': 'Bericht Durchführung (Flight)',
                  'postflight': 'Bericht Nachbereitung (Post-Flight)', 'final': 'Abschlussbericht'},
        'upgrade': 'TYPO3-Upgrade von {source} auf {target}',
        'project': 'Projekt', 'date': 'Datum', 'period': 'Zeitraum', 'status': 'Status',
        'status_go': {'preflight': 'Go: bereit für das Upgrade', 'flight': 'Freigegeben: bereit für die Abnahme durch Ihr Team',
                      'postflight': 'Gelandet: Upgrade abgeschlossen', 'final': 'Abgeschlossen'},
        'status_nogo': 'Gestoppt (No-Go): Gründe siehe unten',
        'status_pending': 'In Arbeit',
        'summary': 'Zusammenfassung', 'summary_missing': '_Die Zusammenfassung für diesen Bericht ist noch nicht geschrieben._',
        'done': 'Was erledigt wurde', 'results': 'Ergebnisse', 'risks': 'Risiken und bewusst akzeptierte Einschränkungen',
        'team': 'Was Ihr Team tun oder entscheiden muss', 'next': 'Nächste Schritte', 'timeline': 'Zeitverlauf',
        'checklist': '{answered} von {total} Checklistenpunkten beantwortet: {done} erledigt, {no} als bekanntes Risiko akzeptiert, '
                     '{na} nicht zutreffend, {handoff} an Ihr Team übergeben, {open} offen.',
        'tests_ok': 'Automatisierte Tests: Alle Testsuiten ({n}) laufen erfolgreich.',
        'tests_bad': 'Automatisierte Tests: {bad} von {n} Testsuiten laufen noch nicht erfolgreich ({detail}).',
        'tests_none': 'Automatisierte Tests: In dieser Phase wurde nicht gemessen.',
        'tests_change': 'Zu Beginn der Phase liefen {ok} von {n} Testsuiten erfolgreich.',
        'scanner': 'Befunde des Extension Scanners (veralteter Code): {first} zu Beginn, jetzt {last}.',
        'tca': 'Veraltete Tabellenkonfiguration (TCA), die das System laufend selbst korrigieren muss: {first} zu Beginn, jetzt {last}.',
        'rules': 'Automatisierte Code-Migrationen: {committed} einzeln angewendet und geprüft, {skipped} bewusst nicht angewendet.',
        'commits': '{n} vorbereitete Änderung(en) (Commits) auf dem Branch {branch}. Nichts davon ist veröffentlicht oder ausgerollt.',
        'deps': '{n} Fremdpaket(e) auf dokumentierte Änderungen geprüft, bei {breaking} sind Breaking Changes vermerkt.',
        'schema': 'Datenbankstruktur: {text}.',
        'schema_text': '{n} Änderung(en) vorbereitet und in der lokalen Testumgebung geprüft',
        'no_risks': 'Keine erfasst.', 'no_team': 'Derzeit nichts.',
        'next_go': {'preflight': 'Das eigentliche Upgrade kann auf dem Branch {flight} beginnen. Bevor etwas live geht, müssen die oben genannten Punkte für Ihr Team erledigt sein.',
                    'flight': 'Abnahme durch Ihr Team: Prüfung von Frontend und Backend, Staging mit produktionsnahen Daten, Redaktion. Danach folgt die Nachbereitung.',
                    'postflight': 'Ihr Team prüft und übernimmt die Branches und rollt sie aus. Das nächste Upgrade ist vor dem {next} fällig.'},
        'next_nogo': 'Die oben genannten Blocker müssen gelöst werden. Danach wird erneut entschieden.',
        'next_pending': 'Die Arbeit in dieser Phase geht weiter.',
        'phase_names': {'preflight': 'Pre-Flight (Vorbereitung)', 'flight': 'Flight (Upgrade)', 'postflight': 'Post-Flight (Nachbereitung)'},
        'key_figures': 'Kennzahlen', 'from_to': 'von {a} auf {b}',
    },
}


# -- data helpers --------------------------------------------------------------------------------

def checklist_items(phase: str | None) -> list[dict]:
    spec = load_json(DATA_DIR / 'checklist.json')
    out = []
    for name, data in spec['phases'].items():
        if phase in (None, name):
            for section in data['sections']:
                out += [{**item, 'phase': name, 'section': section['title']} for item in section['items']]
    return out


def window(flight: Flight, phase: str | None) -> tuple[str | None, str | None]:
    events = [e for e in flight.log.get('events', []) if phase is None or e.get('phase') == phase]
    if not events:
        return None, None
    return events[0]['at'], events[-1]['at']


def day(value: str | None, lang: str = 'en') -> str:
    iso = (value or '')[:10]
    if lang == 'de' and len(iso) == 10:
        return f'{iso[8:10]}.{iso[5:7]}.{iso[0:4]}'
    return iso


def last_per_suite(measurements: list[dict]) -> dict[str, dict]:
    out = {}
    for m in measurements:
        out[m['suite']] = m
    return out


def first_per_suite(measurements: list[dict]) -> dict[str, dict]:
    out = {}
    for m in measurements:
        out.setdefault(m['suite'], m)
    return out


def phase_list(flight: Flight, key: str, phase: str | None) -> list[dict]:
    return [e for e in flight.log.get(key, []) if phase is None or e.get('phase') == phase]


def commits_of(flight: Flight, phase: str | None) -> tuple[str, list[str]]:
    branches = flight.config['branches']
    if phase == 'preflight':
        branch, exclude = branches['preflight'], flight.config['base_branch']
    elif phase in ('flight', 'postflight'):
        branch, exclude = branches['flight'], branches['preflight']
    else:
        branch, exclude = branches['flight'], flight.config['base_branch']
    if not git(flight.root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}'):
        return branch, []
    start, end = window(flight, phase) if phase == 'postflight' else (None, None)
    args = ['log', '--format=%h %s', f'{exclude}..{branch}'] + ([f'--since={start}'] if start else [])
    out = git(flight.root, *args)
    return branch, [line for line in out.splitlines() if line]


def campaigns_of(flight: Flight, phase: str | None) -> dict:
    return {name: c for name, c in flight.log.get('campaigns', {}).items() if phase is None or name.startswith(phase + '-')}


def narrative(flight: Flight, phase: str, audience: str, lang: str) -> str | None:
    path = flight.dir / 'notes' / f'{phase}-{audience}.{lang}.md'
    return path.read_text(encoding='utf-8').strip() if path.is_file() else None


def project_name(flight: Flight) -> str:
    composer = load_json(flight.root / 'composer.json', {}) or {}
    return composer.get('name') or flight.root.name


# -- pm report --------------------------------------------------------------------------------------

def status_line(flight: Flight, phase: str, t: dict) -> str:
    if phase == 'final':
        return t['status_go']['final'] if flight.log.get('phase') == 'landed' else t['status_pending']
    gate = flight.log.get('gates', {}).get(phase)
    if not gate:
        return t['status_pending']
    return t['status_go'][phase] if gate['decision'] == 'go' else t['status_nogo']


def test_lines(measurements: list[dict], t: dict) -> list[str]:
    if not measurements:
        return [t['tests_none']]
    last = last_per_suite(measurements)
    bad = {s: m for s, m in last.items() if m['exit'] != 0}
    lines = [t['tests_ok'].format(n=len(last)) if not bad else
             t['tests_bad'].format(bad=len(bad), n=len(last), detail=', '.join(f'{s}: {m["summary"]}' for s, m in bad.items()))]
    first = first_per_suite(measurements)
    ok_first = sum(1 for m in first.values() if m['exit'] == 0)
    if ok_first != len(last) - len(bad):
        lines.append(t['tests_change'].format(ok=ok_first, n=len(first)))
    return lines


def pm_report(flight: Flight, phase: str, lang: str) -> str:
    t = T[lang]
    config, log = flight.config, flight.log
    scope = None if phase == 'final' else phase
    start, end = window(flight, scope)
    title_key = 'title_de' if lang == 'de' else 'title'
    lines = [f'# {t["title"][phase]}: {t["upgrade"].format(source=config.get("source_installed"), target=config["target"])}', '',
             f'- {t["project"]}: {project_name(flight)}',
             f'- {t["date"]}: {day(now(), lang)}',
             f'- {t["period"]}: {day(start, lang)} - {day(end, lang)}',
             f'- {t["status"]}: **{status_line(flight, phase, t)}**', '',
             f'## {t["summary"]}', '', narrative(flight, phase, 'pm', lang) or t['summary_missing'], '']

    items = checklist_items(scope)
    states = {i['id']: log['checklist'].get(i['id'], {'status': 'open'}) for i in items}
    counts = {k: sum(1 for s in states.values() if s['status'] == k) for k in ('done', 'no', 'na', 'handoff', 'open')}
    measurements = phase_list(flight, 'measurements', scope)
    done = [t['checklist'].format(answered=len(items) - counts['open'], total=len(items), **counts)]
    done += test_lines(measurements, t)
    scans, tca = phase_list(flight, 'scans', scope), phase_list(flight, 'tca', scope)
    if scans:
        done.append(t['scanner'].format(first=scans[0]['total'], last=scans[-1]['total']))
    if tca:
        done.append(t['tca'].format(first=tca[0]['count'], last=tca[-1]['count']))
    campaigns = campaigns_of(flight, scope)
    if campaigns:
        rules = [r for c in campaigns.values() for r in c['rules'].values()]
        done.append(t['rules'].format(committed=sum(1 for r in rules if r['status'] == 'committed'),
                                      skipped=sum(1 for r in rules if r['status'] == 'skipped')))
    branch, commits = commits_of(flight, scope)
    if commits:
        done.append(t['commits'].format(n=len(commits), branch=branch))
    deps = (log.get('dependencies') or {}).get('docs', {})
    if deps and phase in ('preflight', 'flight', 'final'):
        done.append(t['deps'].format(n=len(deps), breaking=sum(1 for d in deps.values() if 'Breaking' in d['summary'] or 'breaking' in d['summary'])))
    schema = [e for e in phase_list(flight, 'schema_runs', scope) if e['action'] == 'apply']
    if schema:
        done.append(t['schema'].format(text=t['schema_text'].format(n=sum(e.get('statements') or 0 for e in schema))))
    lines += [f'## {t["done"]}', ''] + [f'- {line}' for line in done] + ['']

    risks = [(i, states[i['id']]) for i in items if states[i['id']]['status'] == 'no']
    lines += [f'## {t["risks"]}', '']
    lines += [f'- **{i.get(title_key) or i["title"]}**: {s.get("note") or ""}' for i, s in risks] or [f'- {t["no_risks"]}']
    lines.append('')
    team = [(i, states[i['id']]) for i in items if states[i['id']]['status'] == 'handoff']
    lines += [f'## {t["team"]}', '']
    lines += [f'- **{i.get(title_key) or i["title"]}**' + (f': {s["note"]}' if s.get('note') else '') for i, s in team] or [f'- {t["no_team"]}']
    lines.append('')

    lines += [f'## {t["next"]}', '']
    gate = log.get('gates', {}).get(phase) if phase != 'final' else None
    next_date = day(config.get('facts', {}).get(config['target'], {}).get('support', {}).get('maintained_until'), lang)
    if phase == 'final':
        key = 'postflight' if log.get('phase') == 'landed' else None
        lines.append(t['next_go'][key].format(flight=config['branches']['flight'], next=next_date) if key else t['next_pending'])
    elif not gate:
        lines.append(t['next_pending'])
    elif gate['decision'] == 'go':
        lines.append(t['next_go'][phase].format(flight=config['branches']['flight'], next=next_date))
    else:
        lines.append(t['next_nogo'])
    if phase == 'final':
        lines += ['', f'## {t["timeline"]}', '']
        for name in PHASES:
            s, e = window(flight, name)
            if s:
                g = log.get('gates', {}).get(name)
                lines.append(f'- {t["phase_names"][name]}: {day(s, lang)} - {day(e, lang)}' + (f', {g["gate"]}: {g["decision"].upper()}' if g else ''))
    return '\n'.join(lines) + '\n'


# -- developer report ---------------------------------------------------------------------------------

def dev_report(flight: Flight, phase: str) -> str:
    if phase == 'final':
        text = final_developer_report(flight)
        extra = narrative(flight, 'final', 'dev', 'en')
        return text.replace('\n', f'\n\n## Summary\n\n{extra}\n', 1) if extra else text
    config, log = flight.config, flight.log
    t = T['en']
    start, end = window(flight, phase)
    gate = log.get('gates', {}).get(phase)
    lines = [f'# {t["title"][phase]} (developer): TYPO3 {config.get("source_installed")} -> {config["target"]}', '',
             f'- Period: {start or "-"} to {end or "-"}',
             f'- Gate: ' + (f'{gate["gate"]} {gate["decision"].upper()} by {gate["by"]}: {gate["note"]}' if gate else 'pending'), '',
             '## Summary', '', narrative(flight, phase, 'dev', 'en') or '_Not written yet._', '',
             '## Checklist', '', '| Item | Status | Owner | Note / evidence |', '|---|---|---|---|']
    for item in checklist_items(phase):
        state = log['checklist'].get(item['id'], {'status': 'open'})
        note = ' '.join(filter(None, [state.get('note'), f'({state["evidence"]})' if state.get('evidence') else None])).replace('|', '/')
        lines.append(f'| `{item["id"]}` {item["title"]} | {state["status"]} | {item["owner"]} | {note} |')
    lines += ['', '## Measurements', ''] + measurements_table(log, phase_list(flight, 'measurements', phase)) + ['']
    scans, tca = phase_list(flight, 'scans', phase), phase_list(flight, 'tca', phase)
    if scans or tca:
        lines += ['## Scanner and TCA', '']
        lines += [f'- scan {s["label"]}: {s["total"]} ({s["strong"]} strong, {s["weak"]} weak) @ {s["commit"]}' for s in scans]
        lines += [f'- tca {e["label"]}: {e["count"]} messages, {e["own"]} own @ {e["commit"]}' for e in tca]
        lines.append('')
    for name, campaign in campaigns_of(flight, phase).items():
        lines += [f'## Campaign `{name}`', '']
        lines += [f'- {entry["status"]} `{rule.rsplit(chr(92), 1)[-1]}`' + (f' {entry["commit"]}' if entry.get('commit') else '')
                  + (f': {entry["note"].strip()}' if entry.get('note') else '') for rule, entry in campaign['rules'].items()]
        lines.append('')
    branch, commits = commits_of(flight, phase)
    lines += [f'## Commits on `{branch}` ({len(commits)})', ''] + [f'- {c}' for c in commits] + ['']
    deps = (log.get('dependencies') or {}).get('docs', {})
    if deps and phase in ('preflight', 'flight'):
        lines += ['## Third-party dependencies', '']
        lines += [f'- {n} {d["from"] or "(new)"} -> {d["to"]}: {d["summary"]} ({d["report"]})' for n, d in sorted(deps.items())]
        lines.append('')
    schema = phase_list(flight, 'schema_runs', phase)
    if schema:
        lines += ['## Database schema', ''] + [f'- {e["label"]}: {e["action"]} via {e["provider"]} ({e["types"]}): {statements_cell(e)}, exit {e["exit"]}'
                                                for e in schema] + ['']
    if phase == 'preflight' and log.get('context'):
        lines += ['## Context', ''] + [f'- {c["ref"]} ({c["kind"]}): {c.get("title") or ""} {c.get("digest") or "NOT READ"}' for c in log['context']] + ['']
    issues = log.get('issues', [])
    if issues:
        lines += ['## Issues', ''] + [f'- {i.get("placeholder") or "-"} {i.get("number") or "(open)"} {i["step"]}: {i["title"]}' for i in issues] + ['']
    for name in ('QRH.md', 'MEL.md', 'BRIEFING.md'):
        if phase == 'preflight' and (flight.dir / name).is_file():
            lines += [f'- see `{flight.rel(flight.dir / name)}`']
    return '\n'.join(lines).rstrip() + '\n'


def cmd_report(args) -> None:
    flight = Flight.load()
    phases = PHASES + ('final',) if args.phase == 'all' else (args.phase,)
    target = flight.dir / 'reports'
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for phase in phases:
        if phase != 'final' and not phase_list(flight, 'events', phase) and not flight.log.get('gates', {}).get(phase):
            continue
        for audience, lang in VARIANTS:
            text = dev_report(flight, phase) if audience == 'dev' else pm_report(flight, phase, lang)
            path = target / f'{phase}-{audience}.{lang}.md'
            path.write_text(text, encoding='utf-8')
            written.append(path)
        if phase == 'final':
            (flight.dir / 'UPGRADE-REPORT.md').write_text(dev_report(flight, 'final'), encoding='utf-8')
    if not written:
        die(f'nothing to report for {args.phase} yet')
    missing = [f'notes/{p.stem.split(".")[0]}.{p.stem.split(".")[1]}.md' for p in written
               if not (flight.dir / 'notes' / f'{p.stem.split(".")[0]}.{p.stem.split(".")[1]}.md').is_file() and '-pm.' in p.name]
    flight.event(f'reports rendered: {", ".join(p.name for p in written)}')
    flight.save()
    for path in written:
        print(f'  {flight.rel(path)}')
    if missing:
        print('summaries still to write (plain language, pm ones for non-developers): ' + ', '.join(sorted(set(missing))))
