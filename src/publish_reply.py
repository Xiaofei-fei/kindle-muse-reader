"""Fixed unprivileged callback invoked by the Muse SDK command executor."""
import argparse
import json
import socket
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default="/run/kindle-muse-bridge/publish.sock")
    args = parser.parse_args()
    data = sys.stdin.buffer.read(256001)
    if len(data) > 256000:
        raise ValueError("packet too large")
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(15 if json.loads(data).get("op") == "news_source" else 5)
        sock.connect(args.socket)
        sock.sendall(data + b"\n")
        response = json.loads(sock.makefile("rb").readline(8192))
    print(json.dumps(response))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print(json.dumps({"ok": False, "error": "Kindle reader unavailable"}))
        sys.exit(1)
