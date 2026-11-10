#!/data/data/com.termux/files/usr/bin/bash
# ForgeWorld Omega -- pocket node (Android / Termux).
# Usage: scripts/omega-pocket.sh <omega command> [args...]
#   first run:  scripts/omega-pocket.sh setup
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export OMEGA_HOME="${OMEGA_HOME:-$HOME/.forgeworld-omega}"
if [ "${1:-}" = "setup" ]; then
  pkg install -y python python-cryptography sqlite
  python -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)')" \
    && echo "FTS5 available" || echo "FTS5 missing: search falls back to LIKE"
  [ -f "$OMEGA_HOME/node.json" ] || python -m omega --home "$OMEGA_HOME" init --label "${2:-pocket-phone}" --profile pocket
  exit 0
fi
cd "$HERE"
exec python -m omega "$@"
