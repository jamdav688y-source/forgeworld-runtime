#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8080}"

echo "FORGEWORLD // POCKET CORTEX"
echo "Serving ${DIR} on http://localhost:${PORT}"
echo "Open that URL in your browser. Ctrl+C to stop."

cd "$DIR"
exec python3 -m http.server "$PORT"
