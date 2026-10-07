"""Save an SDK token through hidden terminal input; never use a command argument."""
import getpass
import os
from pathlib import Path
import re
import tempfile


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo on the Linux bridge host.')
    if not os.isatty(0):
        raise SystemExit('An interactive terminal is required; input will be hidden.')
    token = getpass.getpass('Muse SDK token (hidden): ').strip()
    if not re.fullmatch(r'mgst_[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]', token):
        raise SystemExit('Invalid SDK token format; no file changed.')
    directory = Path('/var/lib/musegadget')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix='.sdk-token-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(token + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, directory / 'sdk_token')
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print('Token saved with private permissions. Restart musegadget before pairing.')


if __name__ == '__main__':
    main()
