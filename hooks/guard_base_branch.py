#!/usr/bin/env python3
"""PreToolUse guard: while a flight is open, nothing lands on the base branch.

Blocks merge, commit, rebase, cherry-pick, am, revert, ref moves and pushes
that target the base branch recorded in .upgrade-pilot/config.json, and
`gh pr merge`. A seatbelt for mistakes, not a security boundary.
Disable per flight with "guard": false in config.json.
"""

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

WRITES_ON_CURRENT = {'merge', 'commit', 'rebase', 'cherry-pick', 'am', 'revert', 'pull'}


def flight_root(start: Path):
    for candidate in [start, *start.parents]:
        if (candidate / '.upgrade-pilot' / 'config.json').is_file():
            return candidate
    return None


def current_branch(root: Path) -> str:
    try:
        return subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=root, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return ''


def segments(command: str):
    for part in re.split(r'&&|\|\||;|\n|\|', command):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        if words:
            yield words


def git_args(words):
    """Return (subcommand, args) for a git invocation, skipping global options."""
    if not words or Path(words[0]).name != 'git':
        return None, []
    rest = words[1:]
    while rest and rest[0].startswith('-'):
        option = rest.pop(0)
        if option in ('-C', '-c', '--git-dir', '--work-tree') and rest:
            rest.pop(0)
    return (rest[0], rest[1:]) if rest else (None, [])


def verdict(command: str, base: str, branch: str):
    for words in segments(command):
        if words[:3] == ['gh', 'pr', 'merge']:
            return 'gh pr merge would merge into a protected branch during an open flight'
        sub, args = git_args(words)
        if not sub:
            continue
        positional = [a for a in args if not a.startswith('-')]
        if sub in ('checkout', 'switch'):
            create = next((i for i, a in enumerate(args) if a in ('-b', '-B', '-c', '-C', '--create', '--force-create')), None)
            if create is not None and create + 1 < len(args):
                branch = args[create + 1]
            elif positional and '--' not in args:
                branch = positional[0]
            continue
        if sub in WRITES_ON_CURRENT and branch == base:
            return f'git {sub} on the base branch "{base}"'
        if sub == 'reset' and branch == base and positional and '--' not in args:
            return f'git reset to another commit on the base branch "{base}"'
        if sub == 'branch' and ('-f' in args or '--force' in args or '-D' in args) and base in positional:
            return f'moving or deleting the base branch "{base}"'
        if sub == 'update-ref' and any(p.endswith(f'refs/heads/{base}') for p in positional):
            return f'moving the base branch "{base}"'
        if sub == 'push':
            if '--all' in args or '--mirror' in args:
                return 'git push --all/--mirror would push the base branch'
            refspecs = positional[1:]
            if any(r == base or r.endswith(f':{base}') or r.endswith(f'refs/heads/{base}') for r in refspecs):
                return f'git push to the base branch "{base}"'
            if not refspecs and branch == base:
                return f'git push while on the base branch "{base}"'
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    command = payload.get('tool_input', {}).get('command', '')
    if 'git' not in command and 'gh ' not in command:
        return
    root = flight_root(Path(payload.get('cwd') or '.').resolve())
    if root is None:
        return
    try:
        config = json.loads((root / '.upgrade-pilot' / 'config.json').read_text(encoding='utf-8'))
        log = json.loads((root / '.upgrade-pilot' / 'flightlog.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return
    if config.get('guard') is False or log.get('phase') == 'landed':
        return
    base = config.get('base_branch') or 'main'
    reason = verdict(command, base, current_branch(root))
    if reason:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                f'fly-the-upgrade: {reason}. A flight is open in {root}. Upgrade work stays on the '
                f'pre-flight and flight branches, integration into "{base}" is a human decision after the '
                'gates. If a human explicitly asked for this, they can set "guard": false in '
                '.upgrade-pilot/config.json.'),
        }}))


if __name__ == '__main__':
    main()
