#!/usr/bin/env bash
# ForgeWorld Cinema Player launcher -- Linux/macOS.
#
# This is the ONE launch path actually executed and verified in the
# environment this release was built in (see launcher_validation.md).
# Resolves paths relative to this script's own location so it works
# regardless of the caller's current directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CINEMA_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLAYER_APP="$CINEMA_ROOT/player/app.py"

if [ ! -f "$PLAYER_APP" ]; then
  echo "[ForgeWorld Cinema Player] ERROR: could not find $PLAYER_APP" >&2
  exit 1
fi

PYCMD="python3"
if ! command -v "$PYCMD" >/dev/null 2>&1; then
  echo "[ForgeWorld Cinema Player] ERROR: python3 not found on PATH." >&2
  exit 1
fi

echo "[ForgeWorld Cinema Player] Starting local player at http://127.0.0.1:5099 ..."
echo "[ForgeWorld Cinema Player] Press Ctrl+C to stop."

cd "$CINEMA_ROOT"
exec "$PYCMD" "$PLAYER_APP"
