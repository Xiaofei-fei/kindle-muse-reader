# Kindle Muse Reader

A private-LAN, monochrome technology news reader for the Kindle's built-in browser. A bridge computer polls AIHOT's anonymous API; an optional Linux Muse Gadget SDK adapter provides questions and complete text answers.

## Quick start

Python 3.10+ on macOS or Linux, no third-party runtime dependencies for news mode:

```sh
python3 src/bridge.py --state-dir ./state
cat state/access_code
```

Open `http://127.0.0.1:8766/` and enter your private access code. To use a Kindle, bind `--host` to the computer's own LAN IPv4 address and open that address on the Kindle. Do not expose this HTTP service to the internet.

```sh
python3 scripts/demo.py                         # original offline layout samples
python3 -m unittest discover -s tests -v        # no credentials or network needed
python3 scripts/check_public_tree.py
```

See the [Chinese README](../README.md), [installation](INSTALL.md), [configuration](CONFIGURATION.md), [architecture](ARCHITECTURE.md), and [security policy](../SECURITY.md).

The homepage refreshes once per minute; reading and question pages do not refresh. Long text is paginated. This is polling, not instant push. It cannot wake a sleeping Kindle. News mode works without Muse; the SDK integration requires Linux, Bluetooth LE, a working Muse account and token, and phone pairing. The adapter registers only `kindle.publish`, `kindle.notify`, and `kindle.news_source`.

Tested user flows include real questions and news summary reading on a Paperwhite 4. Other devices and firmware need verification. There is no automatic book access, selected-text plugin, native fullscreen release, voice or image input. Backend inbox support remains available by direct route, but is not on the news homepage. Personal schedules are not included.

Code: [Apache-2.0](../LICENSE). News data and Muse cloud services have separate terms. AIHOT permits personal non-commercial, public-interest non-commercial and organization-internal use; public mirrors, bulk redistribution and external commercial products need prior written permission. Read [AIHOT terms](https://aihot.news/terms) and [Muse SDK terms](https://gadgets.muse.ai/sdk-terms). No live news datasets or third-party branding assets are bundled. This is an independent community project.
