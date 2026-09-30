"""Commits in the project's style, the commands behind them, and issue references.

Every commit of a flight goes through `upgrade-pilot commit` (or `rules commit`,
which uses the same renderer):

- the subject and footers follow the style chosen at init (TYPO3 Core style
  without Resolves/Releases, YouTrack style `[TAG] PRJ-123: Subject`, or a
  custom template), with `Related:` lines for parent or extra issues;
- changes to composer files are only accepted when they were made by recorded
  commands (`upgrade-pilot composer ...`, `upgrade-pilot run -- jq ...`), and
  those commands end up in the message as a "Used command(s):" block;
- issue references come from the issue mode: one reference for everything,
  one issue per step (created by whoever has tracker access, registered with
  `issues set`), or `{ISSUE-nn}` placeholders that `issues apply` later
  replaces in the history of the pilot branches.

Nothing is ever pushed.
"""

from __future__ import annotations

import re
import shlex
import textwrap
from pathlib import Path

from . import gitops
from .core import Flight, die, git, git_branch, git_dirty, now, sh

PLACEHOLDER = re.compile(r'\{ISSUE-\d{2,}\}')


# -- message rendering --------------------------------------------------------------------------

def wrap_body(text: str, width: int = 72) -> str:
    """Wrap prose paragraphs, keep code blocks, tables and list structure."""
    out, in_code = [], False
    for block in re.split(r'\n{2,}', text.strip()):
        lines = block.splitlines()
        if any(line.startswith('```') for line in lines) or in_code:
            out.append(block)
            fences = sum(1 for line in lines if line.startswith('```'))
            in_code = in_code ^ (fences % 2 == 1)
            continue
        if all(re.match(r'^\s*([-*]|\d+\.)\s', line) or line.startswith(('  ', '|')) for line in lines):
            wrapped = []
            for line in lines:
                bullet = re.match(r'^(\s*(?:[-*]|\d+\.)\s+)(.*)$', line)
                if bullet:
                    wrapped.append(textwrap.fill(bullet.group(2), width, initial_indent=bullet.group(1),
                                                 subsequent_indent=' ' * len(bullet.group(1)), break_long_words=False,
                                                 break_on_hyphens=False))
                else:
                    wrapped.append(line)
            out.append('\n'.join(wrapped))
            continue
        out.append(textwrap.fill(' '.join(line.strip() for line in lines), width, break_long_words=False, break_on_hyphens=False))
    return '\n\n'.join(out)


def fold_command(command: str, width: int = 72) -> str:
    """Long commands broken at argument boundaries with backslash continuations, still valid bash."""
    if len(command) <= width or '\n' in command:
        return command
    try:
        words = shlex.split(command)
    except ValueError:
        return command
    if any(w in ('|', '&&', '||', '>', ';') for w in words):
        return command
    words = [shlex.quote(w) if re.search(r'[\s*?^|&;<>()$`"\'{}\[\]]', w) else w for w in words]
    head = []
    while words and (words[0].startswith('-') or not head or len(head) < 2):
        head.append(words.pop(0))
    return ' \\\n    '.join([' '.join(head)] + words)


def render(policy: dict, tag: str, subject: str, body: str, ref: str | None, related: list[str],
           commands: list[str], breaking: bool = False) -> tuple[str, list[str]]:
    """The full commit message and warnings about the configured limits."""
    tags = ('[!!!]' if breaking else '') + ''.join(f'[{t.strip("[]")}]' for t in tag.split(',') if t.strip())
    style = policy.get('style', 'typo3')
    footers = []
    if style == 'youtrack':
        if not ref:
            die('the youtrack style needs an issue reference for every commit')
        first = f'{tags} {ref}: {subject}'
    elif style == 'custom':
        first = policy['template'].format(tag=tags.strip('[]') if tags.count('[') == 1 else tags, tags=tags, ref=ref or '',
                                          subject=subject).strip()
    else:
        first = f'{tags} {subject}'
        if ref:
            footers.append(f'Related: {ref}')
    footers += [f'Related: {r}' for r in related if r and r != ref and f'Related: {r}' not in footers]
    parts = [first]
    if body.strip():
        parts.append(wrap_body(body, policy.get('body_wrap', 72)))
    if commands:
        parts.append('Used command(s):\n\n```bash\n' + '\n'.join(fold_command(c) for c in commands) + '\n```')
    if footers:
        parts.append('\n'.join(footers))
    warnings = []
    limit = policy.get('subject_max', 52)
    if len(first) > limit:
        warnings.append(f'subject is {len(first)} characters, the configured limit is {limit}: "{first}"')
    return '\n\n'.join(parts) + '\n', warnings


# -- commands behind composer changes ------------------------------------------------------------

def composer_paths(flight: Flight) -> set[str]:
    paths = {'composer.json', 'composer.lock'}
    for ext in flight.extensions():
        if ext['path'] != '.':
            paths.add(f'{ext["path"]}/composer.json')
    return paths


def quote_word(word: str) -> str:
    return shlex.quote(word) if re.search(r'[\s*?^|&;<>()$`"\'{}\[\]]', word) else word


def record_command(flight: Flight, command: str) -> None:
    flight.log.setdefault('pending_commands', []).append({'cmd': command, 'at': now(), 'branch': git_branch(flight.root)})


def cmd_composer(args) -> None:
    """Run composer where the project runs it, and remember the command for the next commit."""
    flight = Flight.load()
    arguments = ' '.join(quote_word(a) for a in args.args if a != '--')
    if not arguments:
        die('composer arguments missing')
    rc, out, _ = sh(f'{flight.config["runtime"]["composer"]} {arguments}', flight.root)
    print(out[-6000:])
    if rc == 0 and not args.no_record:
        record_command(flight, f'composer {arguments}')
        flight.event(f'composer {arguments}')
        flight.save()
    raise SystemExit(rc)


def cmd_run(args) -> None:
    """Run a host command (for example jq on composer.json) and remember it for the next commit."""
    flight = Flight.load()
    parts = [a for a in args.args if a != '--']
    # One argument is a shell string (pipes, redirects). Several are words: re-quote what needs it.
    command = parts[0] if len(parts) == 1 else ' '.join(quote_word(a) for a in parts)
    if not command:
        die('command missing')
    rc, out, _ = sh(command, flight.root)
    print(out[-6000:])
    if rc == 0:
        record_command(flight, command)
        flight.event(f'run: {command}')
        flight.save()
    raise SystemExit(rc)


# -- issues ------------------------------------------------------------------------------------------

def issues_of(flight: Flight) -> list[dict]:
    return flight.log.setdefault('issues', [])


def issue_for_step(flight: Flight, step: str, title: str, description: str) -> str | None:
    policy = flight.config.get('commit', {})
    mode = policy.get('issue_mode', 'none')
    if mode == 'none':
        return None
    if mode == 'single':
        return policy['issue']
    if not step:
        die(f'issue mode {mode} needs --step <slug> (commits of one logical step share one issue)')
    registry = issues_of(flight)
    entry = next((i for i in registry if i['step'] == step), None)
    if mode == 'per-step':
        if not entry or not entry.get('number'):
            die(f'no issue registered for step "{step}". Create it in {policy.get("tracker") or "the tracker"}'
                + (f' as a child of {policy["issue"]}' if policy.get('issue') else '')
                + f' (title: "{title}"), then: upgrade-pilot issues set --step {step} --number <REF> --title "{title}"')
        return entry['number']
    if not entry:
        entry = {'placeholder': f'{{ISSUE-{len(registry) + 1:02d}}}', 'step': step, 'title': title,
                 'description': description, 'number': None, 'commits': [], 'at': now()}
        registry.append(entry)
    return entry.get('number') or entry['placeholder']


def issues_markdown(flight: Flight) -> str:
    policy = flight.config.get('commit', {})
    lines = [f'# Issues for the upgrade TYPO3 {flight.config.get("source_installed")} -> {flight.config["target"]}', '',
             f'Mode: {policy.get("issue_mode")}' + (f', parent {policy["issue"]}' if policy.get('issue') else '')
             + (f', tracker {policy.get("tracker")}' if policy.get('tracker') and policy.get('tracker') != 'none' else ''), '']
    if policy.get('issue_mode') == 'placeholder':
        lines += ['Create one issue per row, write its number into the "Issue" column, then run',
                  '`upgrade-pilot issues apply`: it replaces the placeholders in the commits of the pilot branches.', '']
    lines += ['| Placeholder | Issue | Step | Title | Commits |', '|---|---|---|---|---|']
    for entry in issues_of(flight):
        lines.append(f'| {entry.get("placeholder") or "-"} | {entry.get("number") or ""} | {entry["step"]} | {entry["title"]} | '
                     f'{", ".join(c[:10] for c in entry.get("commits", []))} |')
    for entry in issues_of(flight):
        lines += ['', f'## {entry.get("placeholder") or entry.get("number")}: {entry["title"]}', '', entry.get('description') or '_no description_']
    return '\n'.join(lines) + '\n'


def read_filled_numbers(flight: Flight) -> None:
    """Pick up numbers a human wrote into the Issue column of ISSUES.md."""
    path = flight.dir / 'ISSUES.md'
    if not path.is_file():
        return
    for placeholder, number in re.findall(r'^\|\s*(\{ISSUE-\d+\})\s*\|\s*([^|]*?)\s*\|', path.read_text(encoding='utf-8'), re.M):
        entry = next((i for i in issues_of(flight) if i.get('placeholder') == placeholder), None)
        if entry and number and not entry.get('number'):
            entry['number'] = number


def write_issues(flight: Flight) -> None:
    if flight.config.get('commit', {}).get('issue_mode', 'none') in ('none', 'single'):
        return
    read_filled_numbers(flight)
    (flight.dir / 'ISSUES.md').write_text(issues_markdown(flight), encoding='utf-8')


def pilot_branches(flight: Flight) -> list[str]:
    names = [flight.config['branches']['preflight'], flight.config['branches']['flight']]
    names += [c['branch'] for c in flight.log.get('commits', [])]
    existing = []
    for name in dict.fromkeys(names):
        if name and name != flight.config['base_branch'] and git(flight.root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}'):
            existing.append(name)
    return existing


def remap(flight: Flight, mapping: dict[str, str]) -> None:
    """Keep recorded commit ids valid after a history rewrite."""
    changed = {old: new for old, new in mapping.items() if old != new}
    if not changed:
        return

    def new_id(value: str | None) -> str | None:
        if not value:
            return value
        clean = value.rstrip('*')
        for old, new in changed.items():
            if old.startswith(clean):
                return new[:len(clean)] + value[len(clean):]
        return value

    for commit in flight.log.get('commits', []):
        commit['sha'] = new_id(commit['sha'])
    for branch in flight.log.get('branches', {}).values():
        branch['composer_commit'] = new_id(branch.get('composer_commit'))
    for campaign in flight.log.get('campaigns', {}).values():
        for rule in campaign['rules'].values():
            if rule.get('commit'):
                rule['commit'] = new_id(rule['commit'])
    for entry in issues_of(flight):
        entry['commits'] = [new_id(c) for c in entry.get('commits', [])]
    for measurement in flight.log.get('measurements', []):
        measurement['commit'] = new_id(measurement.get('commit'))


def cmd_issues(args) -> None:
    flight = Flight.load()
    read_filled_numbers(flight)
    if args.action == 'set':
        entry = next((i for i in issues_of(flight) if (args.step and i['step'] == args.step)
                      or (args.placeholder and i.get('placeholder') == args.placeholder)), None)
        if not entry:
            if not args.step:
                die('unknown placeholder, pass --step to register a new step')
            entry = {'placeholder': None, 'step': args.step, 'title': args.title or args.step, 'description': args.description or '',
                     'number': None, 'commits': [], 'at': now()}
            issues_of(flight).append(entry)
        entry['number'] = args.number
        if args.title:
            entry['title'] = args.title
        flight.event(f'issue {entry.get("placeholder") or entry["step"]} -> {args.number}')
    elif args.action == 'apply':
        replace = {i['placeholder']: i['number'] for i in issues_of(flight) if i.get('placeholder') and i.get('number')}
        if not replace:
            die('no placeholder has a number yet. Fill the Issue column of .upgrade-pilot/ISSUES.md or use issues set')
        if git_dirty(flight.root):
            die('commit or stash your changes first, the rewrite updates the checked-out branch')
        branches = pilot_branches(flight)

        def message(_sha: str, text: str) -> str:
            return PLACEHOLDER.sub(lambda m: replace.get(m.group(0), m.group(0)), text)

        mapping = gitops.rewrite(flight.root, branches, [flight.config['base_branch']], message=message)
        remap(flight, mapping)
        rewritten = sum(1 for old, new in mapping.items() if old != new)
        for entry in issues_of(flight):
            if entry.get('placeholder') in replace:
                entry['applied'] = now()
        flight.event(f'issues apply: {len(replace)} placeholder(s) replaced in {rewritten} commit(s) on {", ".join(branches)}')
        print(f'{len(replace)} placeholder(s) replaced in {rewritten} commit(s) on {", ".join(branches)}. Nothing was pushed.')
        left = [i['placeholder'] for i in issues_of(flight) if i.get('placeholder') and not i.get('number')]
        if left:
            print(f'still without a number: {", ".join(left)}')
    write_issues(flight)
    flight.save()
    if args.action == 'list' or args.action == 'set':
        for entry in issues_of(flight):
            print(f'  {entry.get("placeholder") or "-":<12} {entry.get("number") or "(open)":<12} {entry["step"]:<24} {entry["title"]}')
        print(f'file: {flight.rel(flight.dir / "ISSUES.md")}' if (flight.dir / 'ISSUES.md').is_file() else '')


# -- committing ------------------------------------------------------------------------------------

def changed_files(flight: Flight) -> list[str]:
    return [line[3:].split(' -> ')[-1].strip('"') for line in git_dirty(flight.root)]


def fold_into_composer_commit(flight: Flight, commands: list[str]) -> str | None:
    """Put composer-only changes into the branch's composer commit. None when that is not safe."""
    branch = git_branch(flight.root)
    target = flight.log.get('branches', {}).get(branch, {}).get('composer_commit')
    if not target:
        print('  no composer commit recorded on this branch yet, committing normally')
        return None
    paths = set(changed_files(flight))
    allowed = composer_paths(flight)
    if not paths or not paths <= allowed:
        print(f'  not only composer files changed ({", ".join(sorted(paths - allowed))}), committing normally')
        return None
    root = flight.root
    try:
        target_full = gitops.full(root, target)
        later = gitops.commits_between(root, ['HEAD'], [target_full])
        if any(gitops.changed_paths(root, sha) & allowed for sha in later):
            print('  a later commit changed composer files too, committing normally')
            return None
        others = [b for b in pilot_branches(flight) if b != branch
                  and sh(f'git merge-base --is-ancestor {target_full} {b}', root)[0] == 0]
        if others:
            print(f'  the composer commit is also part of {", ".join(others)}, committing normally')
            return None
        blobs = {}
        for path in sorted(allowed):
            file = root / path
            blobs[path] = gitops.run(root, 'hash-object', '-w', str(file)).strip() if file.is_file() else None
        affected = set(later) | {target_full}
        block = '\n'.join(commands)

        def message(sha: str, text: str) -> str:
            if sha != target_full or not block:
                return text
            if '```bash\n' in text and 'Used command(s):' in text:
                return re.sub(r'(Used command\(s\):\n\n```bash\n.*?)(\n```)', lambda m: m.group(1) + '\n' + block + m.group(2), text,
                              count=1, flags=re.S)
            body, _, footers = text.rstrip('\n').rpartition('\n\n')
            if footers.startswith('Related:'):
                return f'{body}\n\nUsed command(s):\n\n```bash\n{block}\n```\n\n{footers}\n'
            return text.rstrip('\n') + f'\n\nUsed command(s):\n\n```bash\n{block}\n```\n'

        def tree(sha: str, tree_id: str) -> str:
            # Later commits never touch composer files (checked above), so every affected commit gets the new state.
            return gitops.tree_with(root, tree_id, blobs) if sha in affected else tree_id

        mapping = gitops.rewrite(root, [branch], [flight.config['base_branch']], message=message, tree=tree)
        gitops.run(root, 'reset', '-q')
    except RuntimeError as error:
        print(f'  rewrite failed ({error}), committing normally')
        return None
    remap(flight, mapping)
    new_target = mapping.get(target_full, target_full)
    flight.event(f'composer changes folded into {new_target[:10]} on {branch}: {"; ".join(commands)}')
    return new_target


def create_commit(flight: Flight, tag: str, subject: str, body: str, step: str | None = None, step_title: str | None = None,
                  related: list[str] | None = None, breaking: bool = False, into_composer: bool = False,
                  dry_run: bool = False) -> str | None:
    changes = changed_files(flight)
    if not changes:
        die('nothing to commit')
    composer_touched = sorted(set(changes) & composer_paths(flight))
    pending = [c['cmd'] for c in flight.log.get('pending_commands', []) if c.get('branch') == git_branch(flight.root)]
    if composer_touched and not pending:
        die('composer files changed without a recorded command: ' + ', '.join(composer_touched)
            + '. Make composer changes with "upgrade-pilot composer <args>" or "upgrade-pilot run -- jq ..." so the commit can name them.')
    if into_composer and not dry_run:
        folded = fold_into_composer_commit(flight, pending)
        if folded:
            flight.log['pending_commands'] = [c for c in flight.log.get('pending_commands', []) if c['cmd'] not in pending]
            flight.save()
            print(f'folded into the composer commit {folded[:10]} (history of {git_branch(flight.root)} rewritten locally, nothing pushed)')
            return folded
    policy = flight.config.get('commit', {'style': 'typo3', 'issue_mode': 'none'})
    title = step_title or subject
    description = body.strip().split('\n\n')[0] if body.strip() else subject
    ref = issue_for_step(flight, step or '', title, description)
    parent = policy.get('issue') if policy.get('issue_mode') in ('per-step', 'placeholder') else None
    message, warnings = render(policy, tag, subject, body, ref, [parent] + list(related or []), pending, breaking)
    for warning in warnings:
        print(f'  WARNING: {warning}')
    if dry_run:
        print(message)
        return None
    message_file = flight.dir / 'tmp' / 'commit-message.txt'
    message_file.parent.mkdir(parents=True, exist_ok=True)
    message_file.write_text(message, encoding='utf-8')
    rc, out, _ = sh('git add -A', flight.root)
    if rc != 0:
        die(out)
    rc, out, _ = sh(f'git commit -q -F {message_file}', flight.root)
    if rc != 0:
        die(out)
    sha = gitops.full(flight.root, 'HEAD')
    branch = git_branch(flight.root)
    flight.log.setdefault('commits', []).append({'sha': sha, 'branch': branch, 'subject': message.splitlines()[0], 'step': step,
                                                 'ref': ref, 'commands': pending, 'composer': bool(composer_touched), 'at': now()})
    branches = flight.log.setdefault('branches', {})
    if composer_touched and not branches.get(branch, {}).get('composer_commit'):
        branches.setdefault(branch, {})['composer_commit'] = sha
    for entry in issues_of(flight):
        if step and entry['step'] == step:
            entry.setdefault('commits', []).append(sha)
    flight.log['pending_commands'] = [c for c in flight.log.get('pending_commands', []) if c['cmd'] not in pending]
    write_issues(flight)
    flight.event(f'commit {sha[:10]} on {branch}: {message.splitlines()[0]}')
    flight.save()
    print(f'{sha[:10]} {message.splitlines()[0]}')
    return sha


def read_body(args) -> str:
    if getattr(args, 'body_file', None):
        return Path(args.body_file).read_text(encoding='utf-8')
    return getattr(args, 'body', None) or ''


def cmd_commit(args) -> None:
    flight = Flight.load()
    create_commit(flight, args.tag, args.subject, read_body(args), args.step, args.step_title, args.related or [],
                  args.breaking, args.into_composer_commit, args.dry_run)
