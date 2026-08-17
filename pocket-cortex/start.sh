#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8080}"

if ! command -v node >/dev/null 2>&1; then
  echo "node was not found on PATH." >&2
  echo "In Termux: pkg install nodejs" >&2
  exit 1
fi

NODE_MAJOR="$(node -e 'console.log(process.versions.node.split(".")[0])')"
if [ "$NODE_MAJOR" -lt 22 ]; then
  echo "Pocket Cortex requires Node 22+ for node:sqlite (found: $(node -v))." >&2
  echo "In Termux: pkg install nodejs (or nodejs-lts once it tracks 22+)." >&2
  exit 1
fi

echo "FORGEWORLD // POCKET CORTEX"
echo "Serving ${DIR} on http://127.0.0.1:${PORT}"
echo "Data persists at ${DIR}/data/pocket-cortex.db"
echo "Ctrl+C to stop."

cd "$DIR"
exec env PORT="$PORT" node server.js
