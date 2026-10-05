# LoLQ

Your League champions, spells and runes, ready for every queue.

**[Open LoLQ](https://imoutosuki.com/lolq/)** · **[Download for Windows](https://imoutosuki.com/lolq/downloads/LoLQ-Setup.exe)**

## Setup

1. Download and run **LoLQ-Setup.exe**. Python and all dependencies are included; administrator access is not required.
2. The LoLQ page opens. Allow the browser's local-device connection prompt if shown.
3. Add your champions, choose roles, spells, runes and bans, then turn **Automation** on.

The connector runs in the Windows tray and can start when you sign in. Open the page, pause, or quit from its tray menu. You can close the browser while playing; the connector keeps your saved configuration and handles champion select. The page offers updates when its version differs from the installed connector. Run the new installer to update without losing settings.

Windows 10/11 x64. The current installer is unsigned; Windows may show a publisher/SmartScreen warning. Check the download source before running it. Uninstall through Windows Settings → Apps. Uninstall removes the connector, startup entry and URL handler, and preserves your configuration for reinstalling.

## How it works

The hosted page talks to a small connector at `http://127.0.0.1:17653`. Only the approved website origins and the local editor can bootstrap a session. Requests require a custom header and, after bootstrap, a random process-local bearer token. The connector checks Host and Origin, binds only to loopback, validates bounded configuration writes and saves atomically. It exposes configuration and status, **not an unrestricted LCU proxy**. Riot credentials never go to the website.

`desktop.py` supervises the existing `main.py` picker, serves `bridge.py` and supplies tray controls. A fresh install starts paused. Settings and logs live under `%LOCALAPPDATA%\LoLQ`; upgrades preserve them. `lolq://open` opens the hosted page through the installed app. Startup is an optional per-user installer task.

Direct hosted-page LCU access was tested in Firefox on macOS on 6 October 2026: the LCU rejects cross-origin HTTP preflight and rejects the hosted WebSocket origin even with valid credentials. The connector avoids those restrictions without importing certificates or changing browser security settings.

## Development and release

```sh
python -m pip install -r requirements.txt
python desktop.py
python -m unittest discover -s tests -v
```

Source-only legacy commands remain available: `python start.py --editor` for the original local editor on port 5005 and `python start.py --picker` for the picker. These use the repository's config.json. The desktop launcher uses separate user data; `LOLQ_DATA_DIR` can override its directory for development.

GitHub Actions builds the Windows app with PyInstaller and the installer with Inno Setup. It tests silent install, picker startup, duplicate launches, upgrade persistence and uninstall on Windows before uploading `LoLQ-Windows`. A matching `v<version>` tag publishes the tested installer and SHA-256 checksum as a GitHub release. Version lives in `runtime.py`, `static/release.json` and the installer default; keep them aligned.

`web.js` serves only public assets and release downloads through the existing imoutosuki gateway (`app.json`). It sets a page-specific CSP allowing the connector's one loopback port, without `upgrade-insecure-requests`. `scripts/deploy.sh <release-tag>` downloads the release, verifies its checksum, then deploys the page and installer. No League runtime, user settings or secrets are deployed to the website.

See [SPEC.md](SPEC.md) for picker behavior and constraints. An independent community project; not affiliated with Riot Games.
