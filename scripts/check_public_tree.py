"""Heuristic pre-release scan. Print paths/rule names only, never matched secrets."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'state', 'work', 'outputs', 'backups', 'vendor', '.venv', 'venv', '__pycache__'}
PATTERNS = {
    'SDK credential': re.compile(rb'mgst_[A-Za-z0-9_-]{43}'),
    'GitHub credential': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'absolute workstation path': re.compile(rb'/Users/[A-Za-z0-9._-]+/'),
}


def candidates():
    # Include ignored files accidentally force-added to Git as well as clean source.
    paths = {p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts
             and not (set(p.relative_to(ROOT).parts) & PRIVATE)}
    result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True)
    if result.returncode == 0:
        paths.update(ROOT / name for name in result.stdout.decode().split('\0') if name)
    return sorted(paths)


def main():
    problems = []
    files = candidates()
    for path in files:
        rel = path.relative_to(ROOT)
        if path.is_symlink():
            problems.append((str(rel), 'symlink not allowed in public source'))
            continue
        if set(rel.parts) & PRIVATE or path.name in {'access_code', 'sdk_token', 'pairing.json', 'identity.json', '.env'} or path.suffix in {'.db', '.sqlite', '.sqlite3', '.key', '.pem'}:
            problems.append((str(rel), 'private runtime file'))
            continue
        data = path.read_bytes()
        for rule, pattern in PATTERNS.items():
            if pattern.search(data):
                problems.append((str(rel), rule))
    for path, rule in problems:
        print(f'{path}: {rule}')
    print(f'Public-tree scan: {len(files)} files checked, {len(problems)} findings. Runtime directories excluded unless tracked.')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
