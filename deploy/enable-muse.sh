#!/bin/sh
# Explicitly switches an installed upstream service to the restricted adapter.
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "${1:-}" = "--dry-run" ] && [ "$#" -eq 1 ]; then
    printf '%s\n' 'Plan: verify SDK import and dedicated account; stop musegadget; install restricted Kindle drop-in; restart SDK and reader. Does not write tokens, change pairing, or touch Kindle files.'
    exit 0
fi
test "$#" -eq 0 || { printf '%s\n' 'Usage: sudo sh deploy/enable-muse.sh [--dry-run]' >&2; exit 2; }
test "$(id -u)" -eq 0
test -f /opt/kindle-muse-bridge/src/muse_service.py
test -x /opt/musegadget/venv/bin/python
test -f /etc/systemd/system/kindle-muse-bridge.service
id kindle-muse >/dev/null
test "$(id -u kindle-muse)" -ne 0
case " $(id -nG kindle-muse) " in
    *' sudo '*|*' wheel '*) printf '%s\n' 'Reader account must not be a sudo/wheel member.' >&2; exit 1 ;;
esac
/opt/musegadget/venv/bin/python -c 'import sys; sys.path.insert(0,"/opt/kindle-muse-bridge/src"); import muse_service'
systemctl stop musegadget.service
install -d -m 0755 /etc/systemd/system/musegadget.service.d
install -m 0644 "$repo_dir/deploy/musegadget-kindle.conf" /etc/systemd/system/musegadget.service.d/kindle.conf
systemctl daemon-reload
systemctl restart musegadget.service
systemctl restart kindle-muse-bridge.service
printf '%s\n' 'Restricted adapter active. Set your SDK token using scripts/configure_muse_token.py, then pair with the phone as described in docs/INSTALL.md.'
