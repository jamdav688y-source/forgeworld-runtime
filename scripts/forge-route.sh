#!/usr/bin/env bash
# Portable entrypoint for the Mission Router (works on phone/Termux and desktop).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 "$REPO_ROOT/router/mission_router.py" "$@"
