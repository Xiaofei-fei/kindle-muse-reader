#!/bin/sh
# New Linux installation only. Never downloads SDKs or touches the Kindle.
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "${1:-}" = "--dry-run" ] && [ "$#" -eq 1 ]; then
    printf '%s\n' 'Plan: create a no-login kindle-muse account; install src/ and deployment templates under /opt/kindle-muse-bridge; install loopback-only config and reader systemd service; start reader. No existing installation, reader data, SDK credentials, or Kindle files are overwritten.'
    exit 0
fi
if [ "$#" -ne 0 ]; then
    printf '%s\n' 'Usage: sudo sh deploy/install-reader.sh [--dry-run]' >&2
    exit 2
fi
test "$(id -u)" -eq 0 || { printf '%s\n' 'Run as root with sudo.' >&2; exit 1; }
test ! -e /opt/kindle-muse-bridge || { printf '%s\n' 'Existing installation found; use the documented manual upgrade path.' >&2; exit 1; }
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
command -v systemctl >/dev/null
command -v useradd >/dev/null
if ! id kindle-muse >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/kindle-muse-bridge --no-create-home --shell /usr/sbin/nologin kindle-muse
fi
test "$(id -u kindle-muse)" -ne 0 || { printf '%s\n' 'Reader account must not have UID 0.' >&2; exit 1; }
getent group kindle-muse >/dev/null
case " $(id -nG kindle-muse) " in
    *' sudo '*|*' wheel '*) printf '%s\n' 'Reader account must not be a sudo/wheel member.' >&2; exit 1 ;;
esac
install -d -m 0755 /opt/kindle-muse-bridge/src /opt/kindle-muse-bridge/deploy
install -m 0644 "$repo_dir"/src/*.py /opt/kindle-muse-bridge/src/
install -m 0644 "$repo_dir"/deploy/*.service "$repo_dir"/deploy/*.conf /opt/kindle-muse-bridge/deploy/
if [ ! -e /etc/kindle-muse-bridge.conf ]; then
    install -m 0644 "$repo_dir/deploy/reader.conf.example" /etc/kindle-muse-bridge.conf
fi
install -m 0644 "$repo_dir/deploy/kindle-muse-bridge.service" /etc/systemd/system/kindle-muse-bridge.service
systemctl daemon-reload
systemctl enable --now kindle-muse-bridge.service
printf '%s\n' 'Reader installed on loopback by default. Set your own LAN IPv4 address in /etc/kindle-muse-bridge.conf, then restart the reader. See docs/INSTALL.md.'
