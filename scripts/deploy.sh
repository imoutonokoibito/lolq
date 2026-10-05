#!/bin/bash
# Deploy only this app; never sync user configurations or unrelated gateway files.
set -euo pipefail
TAG="${1:?Usage: scripts/deploy.sh v1.0.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
gh release download "$TAG" --repo imoutonokoibito/lolq --pattern 'LoLQ-Setup.exe' --pattern 'SHA256SUMS.txt' --dir "$STAGE"
python3 - "$STAGE" <<'VERIFY'
import hashlib
from pathlib import Path
import sys
root = Path(sys.argv[1])
expected = (root / 'SHA256SUMS.txt').read_text(encoding='utf-8-sig').split()[0]
actual = hashlib.sha256((root / 'LoLQ-Setup.exe').read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit('Installer checksum mismatch')
print('Installer SHA-256 verified')
VERIFY
ssh imoutosuki 'mkdir -p /root/lolq/static /root/lolq/downloads /var/run/imoutosuki'
rsync -az "$STAGE/LoLQ-Setup.exe" "$STAGE/SHA256SUMS.txt" imoutosuki:/root/lolq/downloads/
rsync -az "$ROOT/static/" imoutosuki:/root/lolq/static/
rsync -az "$ROOT/web.js" "$ROOT/app.json" imoutosuki:/root/lolq/
ssh imoutosuki 'SOCKET_PATH=/var/run/imoutosuki/lolq.sock pm2 restart lolq-web --update-env 2>/dev/null || SOCKET_PATH=/var/run/imoutosuki/lolq.sock pm2 start /root/lolq/web.js --name lolq-web; pm2 save >/dev/null; touch /root/lolq'
