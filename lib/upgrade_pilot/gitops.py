"""History rewrites through git plumbing: no checkout, no working-tree changes.

Used for two things: replacing issue placeholders in commit messages once
the real issue numbers exist, and folding composer-only changes into the
branch's composer commit. Authors, author dates and committers are kept.
Only local pilot branches are ever rewritten, and nothing is pushed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run(root: Path, *args: str, stdin: str | None = None, env: dict | None = None) -> str:
    proc = subprocess.run(['git', *args], cwd=str(root), input=stdin, text=True, capture_output=True,
                          env={**os.environ, **(env or {})})
    if proc.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)}: {proc.stderr.strip()}')
    return proc.stdout


def full(root: Path, ref: str) -> str:
    return run(root, 'rev-parse', '--verify', f'{ref}^{{commit}}').strip()


def commits_between(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    """Oldest first, parents before children."""
    args = ['rev-list', '--reverse', '--topo-order', *include, *[f'^{e}' for e in exclude]]
    return [line for line in run(root, *args).splitlines() if line]


def info(root: Path, sha: str) -> dict:
    fmt = '%T%x00%P%x00%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd'
    parts = run(root, 'show', '-s', '--date=raw', f'--pretty=format:{fmt}', sha).split('\x00')
    raw = run(root, 'cat-file', 'commit', sha)
    message = raw.split('\n\n', 1)[1] if '\n\n' in raw else ''
    return {'tree': parts[0], 'parents': parts[1].split(), 'author': parts[2:5], 'committer': parts[5:8], 'message': message}


def changed_paths(root: Path, sha: str) -> set[str]:
    return {line for line in run(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', '--root', sha).splitlines() if line}


def tree_with(root: Path, tree: str, blobs: dict[str, str | None]) -> str:
    """tree with some paths replaced by blobs (None removes the path)."""
    git_dir = Path(run(root, 'rev-parse', '--absolute-git-dir').strip())
    index = git_dir / 'upgrade-pilot-index'
    env = {'GIT_INDEX_FILE': str(index)}
    try:
        run(root, 'read-tree', tree, env=env)
        for path, blob in blobs.items():
            if blob is None:
                run(root, 'update-index', '--force-remove', path, env=env)
            else:
                run(root, 'update-index', '--add', '--cacheinfo', f'100644,{blob},{path}', env=env)
        return run(root, 'write-tree', env=env).strip()
    finally:
        if index.exists():
            index.unlink()


def rewrite(root: Path, branches: list[str], exclude: list[str], message=None, tree=None) -> dict[str, str]:
    """Recreate the commits of branches (not reachable from exclude). Returns old -> new commit ids.

    message(sha, text) and tree(sha, tree_id) may return a replacement. Commits whose tree,
    message and parents stay the same keep their id.
    """
    mapping: dict[str, str] = {}
    sign = run(root, 'config', '--bool', '--default', 'false', 'commit.gpgsign').strip() == 'true'
    for sha in commits_between(root, branches, exclude):
        data = info(root, sha)
        new_tree = tree(sha, data['tree']) if tree else data['tree']
        new_message = message(sha, data['message']) if message else data['message']
        parents = [mapping.get(p, p) for p in data['parents']]
        if new_tree == data['tree'] and new_message == data['message'] and parents == data['parents']:
            mapping[sha] = sha
            continue
        env = {
            'GIT_AUTHOR_NAME': data['author'][0], 'GIT_AUTHOR_EMAIL': data['author'][1], 'GIT_AUTHOR_DATE': data['author'][2],
            'GIT_COMMITTER_NAME': data['committer'][0], 'GIT_COMMITTER_EMAIL': data['committer'][1],
            'GIT_COMMITTER_DATE': data['committer'][2],
        }
        args = ['commit-tree', new_tree] + (['-S'] if sign else [])
        for parent in parents:
            args += ['-p', parent]
        mapping[sha] = run(root, *args, '-F', '-', stdin=new_message, env=env).strip()
    for branch in branches:
        old = full(root, branch)
        new = mapping.get(old, old)
        if new != old:
            run(root, 'update-ref', '-m', 'upgrade-pilot rewrite', f'refs/heads/{branch}', new, old)
    return mapping
