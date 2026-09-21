"""Check the explicit public file boundary, portable links and native hashes.

Reports paths/categories, never matching secret values. Does not inspect ignored
runtime data, upstream game files or private development directories.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {'.gba', '.elf', '.sav', '.sqlite', '.db', '.log', '.jsonl', '.o', '.pyc'}
PATTERNS = {
    'private-key': rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----',
    'provider-token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:or-v1-)?[A-Za-z0-9_-]{32,}|AKIA[A-Z0-9]{16})',
    'personal-machine-path': rb'(?:/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/|[A-Z]:\\Users\\)',
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root: Path, name: str) -> Path:
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('unsafe-path')
    result = root
    for part in Path(name).parts:
        result = result / part
        if result.is_symlink():
            raise ValueError('symlink')
    if not result.resolve().is_relative_to(root):
        raise ValueError('path-escape')
    return result


def main() -> int:
    failures: list[str] = []
    listed = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    files = {path for path in listed if path}
    allowlist = safe_path(ROOT, 'public-files.txt').read_text().splitlines()
    allowed = {path for path in allowlist if path and not path.startswith('#')}
    if files != allowed:
        failures.extend('file-boundary: ' + path for path in sorted(files ^ allowed))
    for name in sorted(files):
        try:
            path = safe_path(ROOT, name)
        except ValueError as exc:
            failures.append(str(exc) + ': ' + name)
            continue
        if not path.is_file():
            failures.append('missing: ' + name)
            continue
        parts = path.relative_to(ROOT).parts
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or parts[0] in {'game', '.local', 'artifacts', 'assets', 'data'}:
            failures.append('excluded-material: ' + name)
        raw = path.read_bytes()
        if len(raw) > 5_000_000:
            failures.append('oversize-review-required: ' + name)
        for category, pattern in PATTERNS.items():
            if re.search(pattern, raw):
                failures.append(category + ': ' + name)
        if path.suffix == '.md':
            source = re.sub(r'```.*?```', '', raw.decode(), flags=re.S)
            links = re.findall(r'\]\(([^)]+)\)|(?:src|href)="([^"]+)"', source)
            for pair in links:
                link = next(value for value in pair if value).split(' "', 1)[0].strip('<>')
                target = urlsplit(link)
                if target.scheme or link.startswith('#'):
                    continue
                dest = (path.parent / unquote(target.path)).resolve()
                if not dest.is_relative_to(ROOT) or not dest.exists():
                    failures.append('broken-local-link: ' + name + ' -> ' + target.path)
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        return 1
    bundle = ROOT / 'rom-source'
    manifest = json.loads((bundle / 'manifest.json').read_text())
    for name, record in manifest['bundle_files'].items():
        if 'rom-source/' + name not in files:
            failures.append('untracked-native-manifest-input')
            continue
        try:
            path = safe_path(bundle, name)
        except ValueError:
            failures.append('native-manifest-symlink: ' + name)
            continue
        if not path.is_file() or digest(path) != record['sha256']:
            failures.append('native-bundle-hash: ' + name)
    if digest(ROOT / 'scripts/bootstrap-game.py') != manifest['bootstrap_sha256']:
        failures.append('native-bootstrap-hash: scripts/bootstrap-game.py')
    for name in ('helix_genesis', 'aurora_adventure'):
        raw = (bundle / 'overlay/include/constants' / (name + '_content.h')).read_text()
        if not re.search(r'#define ' + name.upper() + r'_ENABLED 0\b', raw):
            failures.append('native-package-must-stay-disabled: ' + name)
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        return 1
    print(f'Public boundary OK: {len(files)} allowlisted files; links and native bundle hashes verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
