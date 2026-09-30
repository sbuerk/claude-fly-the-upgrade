"""Rendered extension documentation on docs.typo3.org, read the way the host asks for.

https://docs.typo3.org/llms.txt: use the machine-readable artifacts to find
pages (toc.json, else objects.inv.json), read pages as Markdown (same URL,
.md instead of .html), fall back to _sources/*.rst.txt only where no Markdown
is published yet, request with gzip, never crawl HTML or search, and respect
robots.txt. Markdown is rolled out per manual and per version, so a 404 is
not a verdict about the format.

Extension manuals live under /p/<vendor>/<package>/<version>/en-us/. Version
identifiers are major.minor for releases, `main` (or a branch name) for
development. Which pages are new is decided by comparing the manual of the
target with the manual of the installed version.
"""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .core import slug

BASE = 'https://docs.typo3.org'
USER_AGENT = 'upgrade-pilot (Claude Code plugin; +https://github.com/sbuerk/claude-fly-the-upgrade)'
RELEVANT = re.compile(r'upgrad|migrat|breaking|deprecat|changelog|important|update', re.I)
CHANGELOG_DIR = re.compile(r'(?:^|/)Changelog/(\d+(?:\.\d+)*(?:\.x)?)/')
MAX_PAGES = 60
PAGE_LIMIT = 40000


def fetch(url: str, cache: Path) -> tuple[int, str]:
    target = cache / (slug(url.replace(BASE, '')) + '.txt')
    if target.is_file():
        status, _, body = target.read_text(encoding='utf-8').partition('\n')
        return int(status), body
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            if response.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            status, body = response.status, raw.decode('utf-8', errors='replace')
    except urllib.error.HTTPError as error:
        status, body = error.code, ''
    except (urllib.error.URLError, TimeoutError):
        return 0, ''
    time.sleep(0.2)  # be a polite client
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'{status}\n{body}', encoding='utf-8')
    return status, body


def docs_versions(version: str, alias: str | None = None) -> list[str]:
    """Manual versions worth trying for a composer version. dev-main -> main, 2.x-dev -> 2, 3.0.7 -> 3.0."""
    v = version.strip().lstrip('vV').split('@')[0]
    out = []
    if v.startswith('dev-'):
        out.append(v[4:])
    elif v.endswith('-dev'):
        out.append(re.sub(r'(\.x)?-dev$', '', v))
    else:
        match = re.match(r'^(\d+)\.(\d+)', v)
        if match:
            out.append(f'{match.group(1)}.{match.group(2)}')
    if alias:
        match = re.match(r'^(\d+)\.(\d+)', alias)
        if match:
            out.append(f'{match.group(1)}.{match.group(2)}')
    return [x for x in dict.fromkeys(out) if x]


def pages_of(base: str, cache: Path) -> tuple[list[dict], str]:
    """Pages of a manual: path, title, whether Markdown is announced. Source: toc.json or objects.inv.json."""
    status, body = fetch(f'{base}/toc.json', cache)
    if status == 200 and body.strip():
        pages = []

        def walk(nodes):
            for node in nodes or []:
                pages.append({'path': node.get('path'), 'title': node.get('title') or '', 'md': node.get('md')})
                walk(node.get('pages'))
        data = json.loads(body)
        walk(data.get('pages'))
        return [p for p in pages if p['path']], 'toc.json'
    status, body = fetch(f'{base}/objects.inv.json', cache)
    if status == 200 and body.strip():
        docs = (json.loads(body).get('std:doc') or {})
        return [{'path': path, 'title': (value[3] if len(value) > 3 else ''), 'md': None} for path, value in docs.items()], 'objects.inv.json'
    return [], ''


def page_text(base: str, page: dict, cache: Path) -> tuple[str, str]:
    """(text, format): Markdown when published, else the reStructuredText source, flagged."""
    status, body = fetch(f'{base}/{page.get("md") or page["path"] + ".md"}', cache)
    if status == 200 and body.strip():
        return body[:PAGE_LIMIT], 'markdown'
    status, body = fetch(f'{base}/_sources/{page["path"]}.rst.txt', cache)
    if status == 200 and body.strip():
        return body[:PAGE_LIMIT], 'rst source (may be incomplete, no Markdown published yet)'
    return '', 'unavailable'


def read_manual(name: str, installed: str | None, target: str, alias: str | None, in_range, cache: Path,
                skip_changelog: bool = False) -> dict:
    """Relevant pages of the target's manual that are new against the installed version's manual."""
    result = {'manual': None, 'version': None, 'source': None, 'compared_with': None, 'pages': [], 'tried': []}
    new_pages, base = [], None
    for version in docs_versions(target, alias):
        candidate = f'{BASE}/p/{name}/{version}/en-us'
        result['tried'].append(candidate)
        pages, source = pages_of(candidate, cache)
        if pages:
            new_pages, base = pages, candidate
            result.update({'manual': candidate, 'version': version, 'source': source})
            break
    if not base:
        return result
    old_paths: set[str] | None = None
    for version in docs_versions(installed or ''):
        if version == result['version']:
            continue
        old_base = f'{BASE}/p/{name}/{version}/en-us'
        pages, _ = pages_of(old_base, cache)
        if pages:
            old_paths = {p['path'] for p in pages}
            result['compared_with'] = old_base
            break
    effective = alias or target
    picked = []
    for page in new_pages:
        text = f'{page["path"]} {page["title"]}'
        if not RELEVANT.search(text):
            continue
        is_changelog = bool(CHANGELOG_DIR.search(page['path'])) or page['path'].lower().startswith('changelog')
        if is_changelog and skip_changelog:
            continue  # the repository's changelog files were read already, the rendered pages are the same entries
        if is_changelog:
            if old_paths is not None:
                if page['path'] in old_paths:
                    continue
            else:
                match = CHANGELOG_DIR.search(page['path'])
                if installed and in_range and not in_range(match.group(1), installed, effective):
                    continue
        picked.append(page)
    def priority(page: dict) -> int:
        text = f'{page["path"]} {page["title"]}'.lower()
        if not CHANGELOG_DIR.search(page['path']) and re.search(r'upgrad|migrat', text):
            return 0
        for rank, word in enumerate(('breaking', 'deprecat', 'important'), 1):
            if word in text:
                return rank
        return 9
    picked.sort(key=priority)
    result['skipped_changelog'] = skip_changelog
    for page in picked[:MAX_PAGES]:
        body, fmt = page_text(base, page, cache)
        result['pages'].append({'path': page['path'], 'title': page['title'], 'format': fmt, 'text': body,
                                'url': f'{base}/{page["path"]}.html'})
    if len(picked) > MAX_PAGES:
        result['truncated'] = len(picked) - MAX_PAGES
    return result
