"""Audit the prospective Git checkout: document assets, file sizes and Git history.

python scripts/audit_release.py
Requires the project dependencies (markdown-it-py is provided by rich).
Does not stage files or modify Git history.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

MIB = 1024 * 1024


def git(root, *args, input=None):
    return subprocess.run(['git', '-C', str(root), *args], input=input,
                          capture_output=True, check=True).stdout


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value and (name in ('src', 'poster') or name == 'href'):
                self.links.append(value)
            if value and name == 'srcset':
                self.links.extend(item.strip().split()[0] for item in value.split(',') if item.strip())


def document_links(text):
    def walk(tokens):
        for token in tokens:
            if token.type in ('image', 'link_open'):
                yield token.attrGet('src' if token.type == 'image' else 'href')
            if token.type in ('html_inline', 'html_block'):
                parser = HTMLLinks()
                parser.feed(token.content)
                yield from parser.links
            if token.children:
                yield from walk(token.children)
    return list(walk(MarkdownIt('commonmark', {'html': True}).parse(text)))


def audit(root, max_file_mib=25, history=True):
    root = Path(root).resolve()
    names = set(git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
                .decode('utf-8').strip('\0').split('\0')) - {''}
    tracked = set(git(root, 'ls-files', '-z').decode('utf-8').strip('\0').split('\0')) - {''}
    errors, warnings, checked_links, sizes = [], [], [], []
    for name in sorted(names):
        path = root / name
        if not path.is_file():
            errors.append({'file': name, 'reason': 'missing checkout file'})
            continue
        size = path.stat().st_size
        sizes.append({'file': name, 'bytes': size})
        if size > max_file_mib * MIB:
            errors.append({'file': name, 'reason': f'exceeds {max_file_mib:g} MiB upload budget', 'bytes': size})
        if path.suffix.lower() not in ('.md', '.markdown', '.html', '.htm'):
            continue
        body = path.read_text(encoding='utf-8-sig')
        if path.suffix.lower() in ('.html', '.htm'):
            parser = HTMLLinks(); parser.feed(body); links = parser.links
        else:
            links = document_links(body)
        for link in links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            raw = unquote(parsed.path)
            target = (root / raw.lstrip('/') if raw.startswith('/') else path.parent / raw).resolve()
            row = {'document': name, 'link': link}
            checked_links.append(row)
            if not target.is_relative_to(root):
                errors.append({**row, 'reason': 'link leaves repository'})
                continue
            # Path.resolve() fixes filename case on Windows; retain the spelling in
            # Markdown so a link that breaks on Linux/GitHub cannot pass locally.
            relative = posixpath.normpath(raw.lstrip('/') if raw.startswith('/')
                                          else posixpath.join(posixpath.dirname(name), raw))
            if relative in names and target.is_file():
                continue
            if target.is_dir() and any(n.startswith(relative.rstrip('/') + '/') for n in names):
                continue
            reason = 'missing target'
            if target.exists():
                reason = ('path case differs from Git path' if relative.lower() in {n.lower() for n in names}
                          else 'target exists locally but is excluded from checkout (ignored/untracked parent)')
            errors.append({**row, 'target': relative, 'reason': reason})
    large_blobs = []
    if history:
        objects = git(root, 'rev-list', '--objects', '--all')
        if objects.strip():
            info = git(root, 'cat-file', '--batch-check=%(objecttype) %(objectsize) %(rest)', input=objects)
            for line in info.decode('utf-8').splitlines():
                kind, size, *name = line.split(' ', 2)
                if kind == 'blob' and int(size) > 50 * MIB:
                    row = {'file': name[0] if name else '', 'bytes': int(size)}
                    large_blobs.append(row)
                    (errors if int(size) > 100 * MIB else warnings).append({**row, 'reason': 'large historical Git blob'})
    return {'ok': not errors, 'candidate_files': len(names), 'untracked_candidate_files': len(names - tracked),
            'local_document_links': len(checked_links), 'max_file_mib': max_file_mib,
            'largest_files': sorted(sizes, key=lambda x: x['bytes'], reverse=True)[:10],
            'large_history_blobs': large_blobs, 'errors': errors, 'warnings': warnings,
            'scope': 'tracked + untracked, non-ignored files; local Markdown/HTML links; all reachable Git history'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--max-file-mib', type=float, default=25)
    args = parser.parse_args()
    report = audit(args.root, args.max_file_mib)
    output = args.root / 'runs/release_audit/report.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
