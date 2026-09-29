"""Shared plumbing: flight state, runtime execution, git helpers."""

from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

STATE_DIR = '.upgrade-pilot'
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PLUGIN_ROOT / 'data'
PHP_DIR = PLUGIN_ROOT / 'lib' / 'php'
TEMPLATE_DIR = PLUGIN_ROOT / 'data' / 'templates'


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def die(message: str, code: int = 1) -> None:
    print(f'upgrade-pilot: {message}', file=sys.stderr)
    sys.exit(code)


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    tmp.replace(path)


def extract_json(text: str):
    """Tools wrapped in a runtime may print noise around their JSON."""
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:60] or 'run'


def short_class(fqcn: str) -> str:
    return fqcn.rsplit('\\', 1)[-1]


def find_root(start: str | None = None) -> Path | None:
    path = Path(start or os.getcwd()).resolve()
    for candidate in [path, *path.parents]:
        if (candidate / STATE_DIR / 'config.json').is_file():
            return candidate
    return None


def sh(cmd: str, cwd: Path, merge: bool = True, env: dict | None = None, timeout: int | None = None):
    """Run a host shell command. Returns (exit code, stdout, stderr)."""
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge else subprocess.PIPE,
        text=True,
        env={**os.environ, **(env or {})},
        timeout=timeout,
    )
    return proc.returncode, proc.stdout or '', proc.stderr or ''


def git(root: Path, *args: str) -> str:
    rc, out, _ = sh('git ' + ' '.join(shlex.quote(a) for a in args), root, merge=False)
    return out.strip() if rc == 0 else ''


def git_branch(root: Path) -> str:
    return git(root, 'rev-parse', '--abbrev-ref', 'HEAD')


def git_head(root: Path) -> str:
    return git(root, 'rev-parse', '--short', 'HEAD')


def git_dirty(root: Path) -> list[str]:
    # Not via git(): stripping would eat the status column of the first line.
    rc, out, _ = sh('git status --porcelain --untracked-files=all', root, merge=False)
    return [line for line in out.splitlines() if line.strip()] if rc == 0 else []


class Flight:
    """One upgrade: config (how to run things) plus the flight log (what happened)."""

    def __init__(self, root: Path):
        self.root = root
        self.dir = root / STATE_DIR
        self.config = load_json(self.dir / 'config.json', {})
        self.log = load_json(self.dir / 'flightlog.json', {})
        self._add_new_checklist_items()

    def _add_new_checklist_items(self) -> None:
        """Flights opened with an older plugin version get lines added later as open items."""
        checklist = self.log.get('checklist')
        if checklist is None:
            return
        spec = load_json(DATA_DIR / 'checklist.json', {})
        for phase in spec.get('phases', {}).values():
            for section in phase['sections']:
                for item in section['items']:
                    checklist.setdefault(item['id'], {'status': 'open', 'note': '', 'evidence': '', 'at': None})

    @classmethod
    def load(cls, start: str | None = None) -> 'Flight':
        root = find_root(start)
        if root is None:
            die('no flight initialised here or above. Run: upgrade-pilot init --target <major.minor>')
        return cls(root)

    # -- persistence -----------------------------------------------------

    def save(self) -> None:
        write_json(self.dir / 'config.json', self.config)
        write_json(self.dir / 'flightlog.json', self.log)
        from . import render
        (self.dir / 'FLIGHT-LOG.md').write_text(render.flight_log(self), encoding='utf-8')

    def event(self, text: str) -> None:
        self.log.setdefault('events', []).append({
            'at': now(),
            'phase': self.log.get('phase'),
            'branch': git_branch(self.root),
            'commit': git_head(self.root),
            'text': text,
        })

    def logfile(self, name: str) -> Path:
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        path = self.dir / 'logs' / f'{stamp}-{slug(name)}.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    # -- running things --------------------------------------------------

    def runtime_cmd(self, inner: str) -> str:
        """Wrap a command so it runs where PHP runs (ddev, docker, local).

        The inner command is handed over as ONE quoted string: ddev exec joins
        separate arguments unquoted into `bash -c`, which breaks backslashes of
        class names and anything with parentheses.
        """
        template = self.config.get('runtime', {}).get('exec', '{cmd}')
        if template.strip() == '{cmd}':
            return inner
        return template.replace('{cmd}', shlex.quote(inner))

    def run_runtime(self, inner: str, log_name: str | None = None, merge: bool = True, timeout: int | None = None):
        rc, out, err = sh(self.runtime_cmd(inner), self.root, merge=merge, timeout=timeout)
        log = None
        if log_name:
            log = self.logfile(log_name)
            log.write_text(f'$ {inner}\n# exit {rc}\n\n{out}{err}', encoding='utf-8')
        return rc, out, err, log

    def run_host(self, cmd: str, log_name: str | None = None, timeout: int | None = None):
        rc, out, _ = sh(cmd, self.root, timeout=timeout)
        log = None
        if log_name:
            log = self.logfile(log_name)
            log.write_text(f'$ {cmd}\n# exit {rc}\n\n{out}', encoding='utf-8')
        return rc, out, log

    def tool(self, name: str) -> str:
        return self.config.get('tools', {}).get(name) or f'vendor/bin/{name}'

    def extensions(self) -> list[dict]:
        return self.config.get('extensions', [])

    def stamp(self) -> dict:
        # "*" marks uncommitted changes on top of the commit: measurements are taken before committing.
        commit = git_head(self.root) + ('*' if git_dirty(self.root) else '')
        return {'at': now(), 'branch': git_branch(self.root), 'commit': commit, 'phase': self.log.get('phase')}
