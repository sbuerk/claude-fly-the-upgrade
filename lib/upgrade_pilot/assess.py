"""The pre-analysis: everything that can be known before anything is changed, in one report.

`upgrade-pilot assess` runs only read-only steps (the composer probe restores what it touches) and
writes `.upgrade-pilot/assessments/<time>.json` plus three reports: developers (en) and project
management (en, de). It answers:

- which third-party packages have a released version for the target, which only a development branch
  (constraints or documentation), which nothing, and which are abandoned
- whether the target graph resolves, and which security advisories the source and the target carry
- sizing indicators: core changelog entries and dependency breaking entries that touch own code,
  touchpoints that need work or have no test, opt-in wizards, patches that fail, deployment findings
- what changed since the previous assessment (`--since`), including go-live blockers that can be
  resolved now

Decisions it asks for are not taken here: the skill asks the user, and records them as go-live blockers
(`blockers add`) or as a No-Go of the pre-flight gate (hold).
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
import sys
from pathlib import Path

from .core import PLUGIN_ROOT, Flight, die, flight_title, load_json, now, write_json
from .init import locked_packages
from .platform import vtuple

DECISIONS = {
    'released': None,
    'released-ter': 'composer has no release for the target, the TER has one: ask the maintainers, or install from another source',
    'dev-only': 'use the branch meanwhile as a go-live blocker, or put the upgrade on hold',
    'claimed': 'only documentation mentions the target: read what it says (it may point to a version elsewhere), then decide',
    'none': 'replace, drop, fork, or put the upgrade on hold',
}


# -- running the read-only steps ----------------------------------------------------------------------

def step(flight: Flight, name: str, argv: list[str]) -> dict:
    """Run one upgrade-pilot command, keep its output as evidence. A failing step is a finding, not a stop."""
    started = datetime.datetime.now()
    proc = subprocess.run([sys.executable, str(PLUGIN_ROOT / 'bin' / 'upgrade-pilot'), *argv], cwd=str(flight.root),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log = flight.logfile(f'assess-{name}')
    log.write_text(f'$ upgrade-pilot {" ".join(argv)}\n# exit {proc.returncode}\n\n{proc.stdout}', encoding='utf-8')
    seconds = (datetime.datetime.now() - started).seconds
    print(f'  {name:<22} exit {proc.returncode:<3} {seconds:>4}s  {flight.rel(log)}')
    return {'step': name, 'exit': proc.returncode, 'log': flight.rel(log)}


def inventory(flight: Flight) -> tuple[list[dict], int]:
    """Third-party packages worth a release check, and the number of plain libraries left to composer."""
    lock = locked_packages(flight.root)
    own = {e.get('package') for e in flight.extensions() if e.get('package')}
    direct = set()
    for path in [flight.root / 'composer.json'] + [flight.root / e['path'] / 'composer.json' for e in flight.extensions() if e['path'] != '.']:
        data = load_json(path, {}) or {}
        for section in ('require', 'require-dev'):
            direct |= set((data.get(section) or {}).keys())
    scope = flight.config.get('packages') or {}
    picked, libraries = [], 0
    for name, package in sorted(lock.items()):
        if name in own or name.startswith('typo3/cms-'):
            continue
        if flight.config.get('scope') == 'packages':
            if name in scope.get('names', []):
                picked.append(package)
            continue
        relevant = package.get('type') == 'typo3-cms-extension' or any(k.startswith('typo3/cms-') for k in (package.get('require') or {}))
        if relevant or name in direct:
            picked.append(package)
        else:
            libraries += 1
    return picked, libraries


def constraint_of(flight: Flight, name: str) -> str | None:
    for path in [flight.root / 'composer.json'] + [flight.root / e['path'] / 'composer.json' for e in flight.extensions() if e['path'] != '.']:
        data = load_json(path, {}) or {}
        for section in ('require', 'require-dev'):
            if name in (data.get(section) or {}):
                return data[section][name]
    return None


def core_version(flight: Flight) -> str:
    """The concrete core version releases have to support: the newest patch of the target (or the installed core)."""
    if flight.config.get('scope') == 'packages':
        return (flight.config.get('source_installed') or flight.config.get('source') or '').lstrip('v')
    facts = (flight.config.get('facts') or {}).get(flight.config['target']) or {}
    return (facts.get('core_latest') or f'{flight.config["target"]}.0').lstrip('v')


def catalog_all(flight: Flight, packages: list[dict]) -> list[dict]:
    from .catalog import assess_package, extension_key
    from .platform import COMPANIONS
    core = core_version(flight)
    php = (flight.config.get('platform') or {}).get('php')
    cache = flight.dir / 'tmp' / 'catalog'
    shutil.rmtree(cache, ignore_errors=True)  # every assessment reads the registries afresh
    out = []
    for package in packages:
        entry = assess_package(flight, package, core, php, constraint_of(flight, package['name']), cache,
                               extension_key(package) if package.get('type') == 'typo3-cms-extension' else None)
        if package['name'] in COMPANIONS:
            entry['companion'] = True  # moved by bump together with the core
        entry['decision'] = DECISIONS.get(entry['status'])
        blocker = next((b for b in flight.log.get('blockers', []) if b['package'] == package['name'] and b['status'] == 'open'), None)
        if blocker and entry['decision']:
            entry['decision'] = None  # decided already: used meanwhile, blocks the go-live
            entry['blocker'] = blocker['use']
        scope = flight.config.get('packages') or {}
        newer = entry['status'] == 'released' and entry.get('installed') and vtuple(entry['version']) > vtuple(entry['installed'])
        if scope.get('dev') and entry['status'] == 'released' and newer:
            entry['action'] = f'the flight targets {scope["to"]}, a newer release exists: {entry["version"]}. Offer it instead, or keep the development target as a go-live blocker'
        elif scope.get('dev') and entry['status'] == 'released':
            # Nothing newer than the installed version is released: the update the flight asks for exists only in development.
            entry.update({'status': 'dev-only', 'version': None,
                          'branches': [{'version': scope['to'], 'alias': None, 'reference': None, 'requires': {}}],
                          'action': f'no release newer than {entry["installed"]}: the target {scope["to"]} is a development version'})
            entry['decision'] = DECISIONS['dev-only']
        elif entry['status'] == 'released' and entry.get('in_constraint') is False:
            entry['action'] = f'constraint {entry["constraint"]} does not allow {entry["version"]}: raise it in the flight'
        out.append(entry)
        print(f'    {entry["status"]:<12} {entry["name"]:<45} installed {entry["installed"] or "-":<12} '
              + (f'-> {entry["version"]}' if entry.get('version') else ''))
    shutil.rmtree(cache, ignore_errors=True)
    return out


def catalog_target(entry: dict) -> str | None:
    """The version a package would move to: its release for the target, else its first development line."""
    if entry['status'] in ('released', 'released-ter') and entry.get('version') and entry['version'] != entry.get('installed'):
        return entry['version'] if entry['status'] == 'released' else None
    if entry['status'] == 'dev-only' and entry.get('branches'):
        return entry['branches'][0]['version']
    return None


# -- sizing --------------------------------------------------------------------------------------------

def sizing(flight: Flight) -> dict:
    log = flight.log
    out: dict = {}
    source, target = flight.config.get('source'), flight.config.get('target')
    changelog = load_json(flight.dir / f'changelog-{source}-{target}.json', None)
    if changelog and flight.config.get('scope') != 'packages':
        matches = changelog.get('matches') or []
        out['core_changelog'] = {t: {'strong': sum(1 for m in matches if m['type'] == t and m['strength'] == 'strong'),
                                     'weak': sum(1 for m in matches if m['type'] == t and m['strength'] != 'strong')}
                                 for t in ('Breaking', 'Deprecation', 'Important')}
    deps = {}
    # The newest report per package: from the dependency list, or read per package when the graph did not resolve.
    latest: dict[str, dict] = {}
    for path in sorted((flight.dir / 'deps').glob('*.json'), key=lambda p: p.stat().st_mtime):
        data = load_json(path, {}) or {}
        if data.get('name'):
            latest[data['name']] = data
    for name, data in latest.items():
        entries = data.get('typo3_changelog') or []
        deps[name] = {'from': data.get('from'), 'to': data.get('to'),
                      'breaking': sum(1 for e in entries if e.get('type') == 'Breaking'),
                      'breaking_touching': sum(1 for e in entries if e.get('type') == 'Breaking' and e.get('hits')),
                      'hits': data.get('hits', 0), 'wizards': len(data.get('wizards_new') or {}),
                      'opt_in_wizards': len(data.get('wizards_opt_in') or {})}
    if deps:
        out['dependencies'] = deps
    for key in ('touchpoints', 'patches', 'delivery'):
        runs = log.get(key) or []
        if runs:
            last = runs[-1]
            out[key] = {k: last.get(k) for k in ('total', 'findings', 'attention', 'manual', 'untested') if k in last}
    if log.get('scans'):
        last = log['scans'][-1]
        out['scanner'] = {'total': last['total'], 'strong': last['strong'], 'weak': last['weak'], 'label': last['label']}
    return out


def audits(flight: Flight) -> dict:
    out = {}
    for label in ('source', 'target'):
        data = load_json(flight.dir / 'assess' / f'audit-{label}.json', None)
        if data:
            out[label] = {'count': sum(len(v) for v in data['advisories'].values()),
                          'advisories': [{'package': p, 'id': a.get('advisoryId'), 'title': a.get('title'), 'cve': a.get('cve'),
                                          'severity': a.get('severity'), 'affected': a.get('affectedVersions'), 'link': a.get('link')}
                                         for p, items in sorted(data['advisories'].items()) for a in items],
                          'abandoned': data.get('abandoned') or {}, 'error': data.get('error')}
    return out


# -- comparing with an earlier assessment --------------------------------------------------------------

def diff(old: dict, new: dict, flight: Flight) -> dict:
    before = {p['name']: p for p in old.get('packages', [])}
    after = {p['name']: p for p in new.get('packages', [])}
    changes = []
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name), after.get(name)
        if not a or not b:
            changes.append({'package': name, 'change': 'added' if b else 'removed'})
        elif a['status'] != b['status'] or a.get('version') != b.get('version'):
            changes.append({'package': name, 'change': f'{a["status"]} {a.get("version") or ""} -> {b["status"]} {b.get("version") or ""}'.replace('  ', ' ')})
    ids = lambda data, label: {x['id'] or x['title'] for x in ((data.get('audits') or {}).get(label) or {}).get('advisories', [])}
    resolvable = [b['package'] for b in flight.log.get('blockers', []) if b['status'] == 'open'
                  and (after.get(b['package']) or {}).get('status') == 'released']
    return {'since': old.get('at'), 'packages': changes,
            'advisories_new': sorted(ids(new, 'target') - ids(old, 'target')),
            'advisories_gone': sorted(ids(old, 'target') - ids(new, 'target')),
            'probe': (old.get('probe'), new.get('probe')) if old.get('probe') != new.get('probe') else None,
            'blockers_resolvable': resolvable}


# -- reports -------------------------------------------------------------------------------------------

T = {
    'en': {
        'title': 'Assessment', 'project': 'Project', 'date': 'Date', 'summary': 'Summary',
        'summary_missing': '_The summary has not been written yet._',
        'packages': 'Third-party packages', 'decisions': 'Decisions needed', 'security': 'Security advisories',
        'size': 'Size of the work (counted, not estimated)', 'since': 'Changes since the assessment of {date}',
        'blockers': 'Go-live blockers', 'nothing': 'None.', 'resolves': 'The update resolves with composer.',
        'not_resolves': 'The update does NOT resolve with composer yet.',
        'status': {'released': 'released version available', 'released-ter': 'only in the TER', 'dev-only': 'only a development branch',
                   'claimed': 'only claimed in documentation', 'none': 'no compatible version', 'independent': 'no TYPO3 requirement'},
        'count': '{n} package(s): {detail}.',
        'decision_line': '**{name}**: {text}',
        'decision_text': {'dev-only': 'only a development version supports the target. Either use it for now, then it blocks the go-live '
                                      'until a release is used and verified, or put the upgrade on hold until the release.',
                          'claimed': 'only its documentation says the target is supported. A developer verifies it, then the same '
                                     'choice as for a development version.',
                          'none': 'no version supports the target. It has to be replaced, removed or taken over, or the upgrade waits.',
                          'released-ter': 'a release exists only in the TYPO3 Extension Repository, not for composer. The maintainers '
                                          'have to be asked, or it is installed differently.'},
        'abandoned': '**{name}** is marked as abandoned by its maintainers' ,
        'sec_line': '{label}: {n} known security advisory(ies)',
        'sec_unknown': 'After the upgrade: not known yet, the update does not resolve as a whole',
        'sec_abandoned': '{n} package(s) in use are abandoned by their maintainers and get no fixes: {names}', 'sec_source': 'Installed today', 'sec_target': 'After the upgrade',
        'size_lines': {'core': 'Core changes that touch the project code: {n} ({strong} with a clear match)',
                       'deps': 'Breaking changes in third-party packages that touch the project code: {n}',
                       'touch': 'Places where the project modifies third-party packages: {total}, {attention} need work, {untested} without a test',
                       'patches': 'Patches of third-party packages: {total}, {attention} do not apply to the new versions as they are',
                       'delivery': 'Findings in deployment and CI scripts: {findings}, {attention} need changes',
                       'wizards': 'Data migrations (upgrade wizards) of third-party packages: {n}, {optin} of them optional'},
    },
    'de': {
        'title': 'Voranalyse', 'project': 'Projekt', 'date': 'Datum', 'summary': 'Zusammenfassung',
        'summary_missing': '_Die Zusammenfassung ist noch nicht geschrieben._',
        'packages': 'Fremdpakete', 'decisions': 'Offene Entscheidungen', 'security': 'Sicherheitshinweise',
        'size': 'Umfang der Arbeit (gezählt, nicht geschätzt)', 'since': 'Änderungen seit der Voranalyse vom {date}',
        'blockers': 'Go-Live-Blocker', 'nothing': 'Keine.', 'resolves': 'Das Update lässt sich mit Composer auflösen.',
        'not_resolves': 'Das Update lässt sich mit Composer noch NICHT auflösen.',
        'status': {'released': 'veröffentlichte Version vorhanden', 'released-ter': 'nur im TER', 'dev-only': 'nur ein Entwicklungsstand',
                   'claimed': 'nur laut Dokumentation', 'none': 'keine passende Version', 'independent': 'ohne TYPO3-Abhängigkeit'},
        'count': '{n} Paket(e): {detail}.',
        'decision_line': '**{name}**: {text}',
        'decision_text': {'dev-only': 'Nur ein Entwicklungsstand unterstützt die Zielversion. Entweder wird er vorerst genutzt, dann blockiert '
                                      'er den Go-Live, bis eine veröffentlichte Version eingesetzt und geprüft ist, oder das Upgrade '
                                      'wartet auf die Veröffentlichung.',
                          'claimed': 'Nur die Dokumentation nennt die Zielversion. Die Entwicklung prüft das, danach dieselbe Wahl wie '
                                     'bei einem Entwicklungsstand.',
                          'none': 'Keine Version unterstützt die Zielversion. Das Paket muss ersetzt, entfernt oder übernommen werden, '
                                  'oder das Upgrade wartet.',
                          'released-ter': 'Eine Version gibt es nur im TYPO3 Extension Repository, nicht für Composer. Die Maintainer '
                                          'müssen gefragt werden, oder die Installation erfolgt anders.'},
        'abandoned': '**{name}** ist von seinen Maintainern als aufgegeben markiert',
        'sec_line': '{label}: {n} bekannte(r) Sicherheitshinweis(e)',
        'sec_unknown': 'Nach dem Upgrade: noch nicht bekannt, das Update lässt sich als Ganzes noch nicht auflösen',
        'sec_abandoned': '{n} eingesetzte(s) Paket(e) werden von ihren Maintainern nicht mehr gepflegt und erhalten keine Korrekturen: {names}', 'sec_source': 'Heute installiert', 'sec_target': 'Nach dem Upgrade',
        'size_lines': {'core': 'Änderungen im Core, die den Projektcode betreffen: {n} ({strong} mit eindeutigem Treffer)',
                       'deps': 'Breaking Changes in Fremdpaketen, die den Projektcode betreffen: {n}',
                       'touch': 'Stellen, an denen das Projekt Fremdpakete verändert: {total}, {attention} brauchen Arbeit, {untested} ohne Test',
                       'patches': 'Patches für Fremdpakete: {total}, {attention} passen nicht unverändert auf die neuen Versionen',
                       'delivery': 'Befunde in Deployment- und CI-Skripten: {findings}, {attention} müssen angepasst werden',
                       'wizards': 'Datenmigrationen (Upgrade-Wizards) der Fremdpakete: {n}, davon {optin} optional'},
    },
}


def size_lines(size: dict, t: dict) -> list[str]:
    lines = []
    core = size.get('core_changelog')
    if core:
        lines.append(t['size_lines']['core'].format(n=sum(v['strong'] + v['weak'] for k, v in core.items() if k != 'Deprecation'),
                                                    strong=sum(v['strong'] for k, v in core.items() if k != 'Deprecation')))
    deps = size.get('dependencies')
    if deps:
        lines.append(t['size_lines']['deps'].format(n=sum(d['breaking_touching'] for d in deps.values())))
        wizards = sum(d['wizards'] for d in deps.values())
        if wizards:
            lines.append(t['size_lines']['wizards'].format(n=wizards, optin=sum(d['opt_in_wizards'] for d in deps.values())))
    touch = size.get('touchpoints')
    if touch:
        lines.append(t['size_lines']['touch'].format(total=touch.get('total', 0), attention=touch.get('attention', 0),
                                                     untested=touch.get('untested') if touch.get('untested') is not None else '?'))
    if size.get('patches'):
        lines.append(t['size_lines']['patches'].format(**{'total': 0, 'attention': 0, **size['patches']}))
    if size.get('delivery'):
        lines.append(t['size_lines']['delivery'].format(**{'findings': 0, 'attention': 0, **size['delivery']}))
    return lines


def pm_report(flight: Flight, data: dict, lang: str) -> str:
    t = T[lang]
    stamp = data['at'][:10]
    if lang == 'de':
        stamp = '.'.join(reversed(stamp.split('-')))
    lines = [f'# {t["title"]}: {flight_title(flight.config).replace(" -> ", " → ")}', '',
             f'- {t["project"]}: {(load_json(flight.root / "composer.json", {}) or {}).get("name") or flight.root.name}',
             f'- {t["date"]}: {stamp}', '', f'## {t["summary"]}', '']
    note = flight.dir / 'notes' / f'assessment-pm.{lang}.md'
    lines += [note.read_text(encoding='utf-8').strip() if note.is_file() else t['summary_missing'], '']
    packages = [p for p in data['packages'] if p['status'] != 'independent']
    counts: dict[str, int] = {}
    for p in packages:
        counts[p['status']] = counts.get(p['status'], 0) + 1
    lines += [f'## {t["packages"]}', '', t['count'].format(n=len(packages), detail=', '.join(f'{n} {t["status"][s]}' for s, n in counts.items()) or '-'),
              '', t['resolves'] if data.get('probe') == 0 else t['not_resolves'], '']
    decisions = [p for p in packages if p['status'] in t['decision_text'] and not p.get('blocker')]
    lines += [f'## {t["decisions"]}', '']
    lines += [f'- ' + t['decision_line'].format(name=p['name'], text=t['decision_text'][p['status']]) for p in decisions]
    lines += [f'- ' + t['abandoned'].format(name=p['name']) for p in packages if p.get('abandoned')]
    if not decisions and not any(p.get('abandoned') for p in packages):
        lines.append(f'- {t["nothing"]}')
    lines.append('')
    blockers = [b for b in flight.log.get('blockers', []) if b['status'] == 'open']
    if blockers:
        lines += [f'## {t["blockers"]}', ''] + [f'- **{b["package"]}** ({b["use"]}): {b["reason"]}' for b in blockers] + ['']
    sec = data.get('audits') or {}
    if sec:
        lines += [f'## {t["security"]}', '']
        for label in ('source', 'target'):
            if label in sec:
                lines.append('- ' + t['sec_line'].format(label=t[f'sec_{label}'], n=sec[label]['count']))
            elif label == 'target':
                lines.append('- ' + t['sec_unknown'])
        abandoned = sorted((sec.get('target') or sec.get('source') or {}).get('abandoned') or {})
        if abandoned:
            lines.append('- ' + t['sec_abandoned'].format(n=len(abandoned), names=', '.join(abandoned)))
        lines.append('')
    size = size_lines(data.get('sizing') or {}, t)
    if size:
        lines += [f'## {t["size"]}', ''] + [f'- {line}' for line in size] + ['']
    change = data.get('diff')
    if change:
        since = (change.get('since') or '')[:10]
        lines += [f'## {t["since"].format(date=".".join(reversed(since.split("-"))) if lang == "de" else since)}', '']
        lines += [f'- {c["package"]}: {c["change"]}' for c in change['packages']] or [f'- {t["nothing"]}']
        lines.append('')
    return '\n'.join(lines) + '\n'


def dev_report(flight: Flight, data: dict) -> str:
    lines = [f'# Assessment (developer): {flight_title(flight.config)}', '',
             f'- At: {data["at"]}', f'- Core version releases must support: {data["core"]}',
             f'- Composer probe: ' + ('resolves' if data.get('probe') == 0 else f'does NOT resolve (exit {data.get("probe")})'),
             f'- Libraries without a TYPO3 requirement, left to composer: {data["libraries"]}', '',
             '## Summary', '']
    note = flight.dir / 'notes' / 'assessment-dev.en.md'
    lines += [note.read_text(encoding='utf-8').strip() if note.is_file() else '_Not written yet._', '']
    lines += ['## Third-party packages', '', '| Package | Installed | Constraint | Status | Version for the target | Notes |', '|---|---|---|---|---|---|']
    order = {'none': 0, 'claimed': 1, 'dev-only': 2, 'released-ter': 3, 'released': 4, 'independent': 5}
    for p in sorted(data['packages'], key=lambda p: (order.get(p['status'], 9), p['name'])):
        notes = []
        if p.get('branches'):
            notes.append('branches: ' + ', '.join(f'{b["version"]}' + (f' (alias {b["alias"]})' if b.get('alias') else '') for b in p['branches']))
        if p.get('claims'):
            notes.append('claims: ' + '; '.join(f'{c["branch"]} {c["file"]}: {c["text"][:80]}' for c in p['claims'][:3]))
        if p.get('action'):
            notes.append(p['action'])
        if p.get('php_ok') is False:
            notes.append(f'needs PHP {p["php"]}')
        if p.get('abandoned'):
            notes.append(f'ABANDONED' + (f', use {p["abandoned"]}' if isinstance(p['abandoned'], str) else ''))
        if p.get('blocker'):
            notes.append(f'decided: uses {p["blocker"]} as a go-live blocker')
        if p.get('companion'):
            notes.append('moved by bump with the core')
        if p.get('latest_release_at'):
            notes.append(f'latest release {p.get("latest_release")} {str(p["latest_release_at"])[:10]}')
        version = p.get('version') or ('branch ' + p['branches'][0]['version'] + (f' ({p["branches"][0]["alias"]})' if p['branches'][0].get('alias') else '')
                                       if p.get('branches') else '-')
        lines.append(f'| {p["name"]} | {p.get("installed") or "-"} | {p.get("constraint") or "(transitive)"} | {p["status"]} | {version} | '
                     + '. '.join(notes).replace('|', '/') + ' |')
    lines.append('')
    decisions = [p for p in data['packages'] if p.get('decision')]
    lines += ['## Decisions needed', '']
    lines += [f'- `{p["name"]}` ({p["status"]}): {p["decision"]}' for p in decisions] or ['- none']
    lines.append('')
    blockers = flight.log.get('blockers', [])
    if blockers:
        lines += ['## Go-live blockers', ''] + [f'- {b["status"]} `{b["package"]}` uses {b["use"]}: {b["reason"]}' for b in blockers] + ['']
    sec = data.get('audits') or {}
    if sec:
        lines += ['## Security advisories (composer audit)', '']
        for label in ('source', 'target'):
            if label not in sec:
                continue
            entry = sec[label]
            lines.append(f'### {"Installed (source)" if label == "source" else "Target graph"}: {entry["count"]}' + (f' ({entry["error"]})' if entry.get('error') else ''))
            lines += [f'- {a["package"]}: {a["title"]} ({a.get("cve") or a.get("id")}, {a.get("severity") or "?"}, affects {a.get("affected")})'
                      for a in entry['advisories']]
            if entry.get('abandoned'):
                lines.append('- abandoned: ' + ', '.join(f'{n}' + (f' (use {r})' if r else '') for n, r in sorted(entry['abandoned'].items())))
            lines.append('')
    size = data.get('sizing') or {}
    lines += ['## Sizing indicators', ''] + [f'- {line}' for line in size_lines(size, T['en'])]
    for name, d in sorted((size.get('dependencies') or {}).items()):
        lines.append(f'  - {name} {d.get("from")} -> {d.get("to")}: {d["breaking"]} Breaking ({d["breaking_touching"]} touch own code), {d["hits"]} hit(s), '
                     f'{d["wizards"]} new wizard(s), {d["opt_in_wizards"]} opt-in')
    if size.get('scanner'):
        s = size['scanner']
        lines.append(f'- Extension Scanner ({s["label"]}): {s["total"]} ({s["strong"]} strong, {s["weak"]} weak)')
    lines.append('')
    patches = load_json(flight.dir / 'patches.json', {}) or {}
    if patches.get('patches'):
        lines += ['## Patches', '', f'Plugin: {(patches.get("plugin") or {}).get("package")} {(patches.get("plugin") or {}).get("version")}', '']
        lines += [f'- `{r["package"]}` {r["description"][:70]}: installed {r["installed"]}, target {r.get("target_version") or "?"} {r["target"]}'
                  + (f' ({r["detail"]})' if r.get('detail') else '') for r in patches['patches']]
        lines.append('')
    delivery = load_json(flight.dir / 'delivery.json', {}) or {}
    if delivery.get('findings'):
        lines += ['## Deployment and CI', '']
        lines += [f'- {f["status"]} {f["file"]}:{f["line"]} {f["message"]}' for f in delivery['findings'] if f['status'] != 'ok']
        lines.append('')
    change = data.get('diff')
    if change:
        lines += [f'## Changes since {change.get("since")}', '']
        lines += [f'- {c["package"]}: {c["change"]}' for c in change['packages']] or ['- no package changed its status']
        if change['advisories_new']:
            lines.append('- new advisories in the target: ' + ', '.join(change['advisories_new']))
        if change['advisories_gone']:
            lines.append('- advisories gone from the target: ' + ', '.join(change['advisories_gone']))
        if change.get('probe'):
            lines.append(f'- composer probe exit {change["probe"][0]} -> {change["probe"][1]}')
        if change['blockers_resolvable']:
            lines.append('- go-live blockers that can be resolved now (a release exists): ' + ', '.join(change['blockers_resolvable']))
        lines.append('')
    lines += ['## Evidence', ''] + [f'- {s["step"]}: exit {s["exit"]}, `{s["log"]}`' for s in data['steps']]
    return '\n'.join(lines).rstrip() + '\n'


def write_reports(flight: Flight, data: dict) -> list[Path]:
    target = flight.dir / 'reports'
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (('assessment-dev.en.md', dev_report(flight, data)), ('assessment-pm.en.md', pm_report(flight, data, 'en')),
                       ('assessment-pm.de.md', pm_report(flight, data, 'de'))):
        (target / name).write_text(text, encoding='utf-8')
        written.append(target / name)
    return written


# -- command -------------------------------------------------------------------------------------------

def previous(flight: Flight, since: str | None, current: Path | None = None) -> dict | None:
    if since:
        path = Path(since) if Path(since).is_file() else flight.dir / 'assessments' / since
        if not path.is_file():
            die(f'no assessment {since} (see .upgrade-pilot/assessments/)')
        return load_json(path, None)
    runs = sorted(p for p in (flight.dir / 'assessments').glob('*.json') if p != current)
    return load_json(runs[-1], None) if runs else None


def cmd_assess(args) -> None:
    flight = Flight.load()
    if args.render:
        runs = sorted((flight.dir / 'assessments').glob('*.json'))
        if not runs:
            die('no assessment yet: run upgrade-pilot assess')
        for path in write_reports(flight, load_json(runs[-1], {})):
            print(f'  {flight.rel(path)}')
        return
    earlier = previous(flight, args.since)
    packages_scope = flight.config.get('scope') == 'packages'
    print(f'assessment: {flight_title(flight.config)} (read-only, the composer probe restores what it touches)')
    steps = [step(flight, 'versions', ['versions'])]
    flight = Flight.load()  # versions stored facts
    print('  release check of the third-party packages:')
    packages, libraries = inventory(flight)
    entries = catalog_all(flight, packages)
    from .platform import composer_audit
    audit = composer_audit(flight, 'source')
    print(f'  composer audit (installed): {sum(len(v) for v in audit["advisories"].values())} advisory(ies)')
    probe = step(flight, 'bump-probe', ['bump', 'probe', '--audit'])
    steps.append(probe)
    if probe['exit'] == 0:
        steps.append(step(flight, 'deps-list', ['deps', 'list']))
        if not args.quick:
            steps.append(step(flight, 'deps-docs', ['deps', 'docs']))
    elif not args.quick:
        # The graph does not resolve as a whole (usually because of the packages above). Each package is still read
        # at the version the release check found, so touchpoints and patches can be verified against it.
        for entry in entries:
            target = catalog_target(entry)
            if target and entry.get('installed'):
                steps.append(step(flight, f'deps-docs {entry["name"]}',
                                  ['deps', 'docs', '--package', entry['name'], '--from', entry['installed'], '--to', target]))
    steps.append(step(flight, 'touchpoints', ['deps', 'touchpoints', '--verify', '--coverage', '--label', 'assessment']))
    if not packages_scope and not args.quick:
        steps.append(step(flight, 'changelog-fetch', ['changelog', 'fetch']))
        steps.append(step(flight, 'changelog-match', ['changelog', 'match']))
    steps.append(step(flight, 'patches', ['patches', '--label', 'assessment']))
    steps.append(step(flight, 'delivery', ['delivery', '--label', 'assessment']))
    flight = Flight.load()
    stamp = now()
    data = {'at': stamp, 'scope': flight.config.get('scope', 'core'), 'title': flight_title(flight.config), 'core': core_version(flight),
            'packages': entries, 'libraries': libraries, 'probe': probe['exit'], 'audits': audits(flight),
            'sizing': sizing(flight), 'steps': steps}
    if earlier:
        data['diff'] = diff(earlier, data, flight)
    path = flight.dir / 'assessments' / (stamp[:19].replace(':', '').replace('-', '').replace('T', '-') + '.json')
    write_json(path, data)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e['status']] = counts.get(e['status'], 0) + 1
    flight.log.setdefault('assessments', []).append({'file': flight.rel(path), 'counts': counts, 'probe': probe['exit'],
                                                     'advisories_target': (data['audits'].get('target') or {}).get('count'),
                                                     **flight.stamp()})
    flight.event(f'assessment: ' + ', '.join(f'{n} {s}' for s, n in counts.items()) + f', probe exit {probe["exit"]}')
    flight.save()
    written = write_reports(flight, data)
    print('\n' + ', '.join(f'{n} {s}' for s, n in sorted(counts.items())) + f', {libraries} plain libraries left to composer')
    decisions = [e for e in entries if e.get('decision')]
    for e in decisions:
        print(f'  DECISION {e["name"]} ({e["status"]}): {e["decision"]}')
    if data.get('diff') and data['diff']['blockers_resolvable']:
        print('  go-live blockers that can be resolved now: ' + ', '.join(data['diff']['blockers_resolvable']))
    for p in written:
        print(f'  {flight.rel(p)}')
    print(f'  data: {flight.rel(path)}')
    print('summaries still to write: notes/assessment-dev.en.md, notes/assessment-pm.en.md, notes/assessment-pm.de.md, '
          'then upgrade-pilot assess --render')
