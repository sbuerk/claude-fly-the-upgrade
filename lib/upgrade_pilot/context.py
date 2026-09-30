"""Pre-collected context: issues, documents and notes gathered before the flight.

Upgrades rarely start from nothing. Somebody already collected findings in a
YouTrack or GitHub issue, a customer listed what must keep working, a previous
attempt left notes. `init --context <ref>` registers such references,
`context add` stores a digest of each in the flight. The CLI cannot read an
issue tracker itself: Claude reads the reference with the tools the session
has (a tracker MCP server, gh, glab, a browser) and writes the digest.
Local files are copied directly.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .core import Flight, die, now, slug

ISSUE_REF = re.compile(r'^([A-Z][A-Z0-9]+-\d+|#\d+|[\w.-]+/[\w.-]+#\d+)$')


def kind_of(ref: str) -> str:
    if ISSUE_REF.match(ref):
        return 'issue'
    if re.match(r'^https?://', ref):
        return 'url'
    if Path(ref).expanduser().exists():
        return 'file'
    return 'note'


def items(flight: Flight) -> list[dict]:
    return flight.log.setdefault('context', [])


def register(flight: Flight, ref: str, title: str | None = None) -> dict:
    entry = next((i for i in items(flight) if i['ref'] == ref), None)
    if entry:
        return entry
    entry = {'ref': ref, 'kind': kind_of(ref), 'title': title or '', 'digest': None, 'at': now()}
    items(flight).append(entry)
    if entry['kind'] == 'file':
        source = Path(ref).expanduser().resolve()
        target = flight.dir / 'context' / f'{slug(source.stem)}{source.suffix}'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entry['digest'] = flight.rel(target)
        entry['title'] = entry['title'] or source.name
    return entry


def cmd_context(args) -> None:
    flight = Flight.load()
    if args.action == 'add':
        if not args.ref:
            die('context add needs a reference (issue key, URL, file path or a short name for a note)')
        entry = register(flight, args.ref, args.title)
        if args.file or args.text:
            target = flight.dir / 'context' / f'{slug(args.ref)}.md'
            target.parent.mkdir(parents=True, exist_ok=True)
            content = Path(args.file).read_text(encoding='utf-8') if args.file else args.text
            header = f'# {args.ref}' + (f': {entry["title"]}' if entry['title'] else '') + f'\n\n_Digest written {now()[:16]}._\n\n'
            target.write_text(header + content.strip() + '\n', encoding='utf-8')
            entry['digest'] = flight.rel(target)
        if args.title:
            entry['title'] = args.title
        flight.event(f'context {args.ref} ({entry["kind"]})' + (' digested' if entry.get('digest') else ' registered'))
        flight.save()
    open_items = [i for i in items(flight) if not i.get('digest')]
    for entry in items(flight):
        state = entry['digest'] or 'NOT READ YET'
        print(f'  {entry["kind"]:<6} {entry["ref"]:<28} {entry["title"][:40]:<40} {state}')
    if not items(flight):
        print('  no context registered')
    if open_items:
        print(f'{len(open_items)} reference(s) not read yet: read each with the tools available (tracker MCP server, gh, glab, '
              'browser), then: upgrade-pilot context add <ref> --title "..." --file <digest.md>')
