#!/usr/bin/env bash
# ForgeWorld Omega -- physical proof on Android (Termux) or any Linux/macOS machine.
#   scripts/omega-proof.sh "Pixel 7, Android 14, Termux 0.118 (owner's phone)" [model ...]
# Writes docs/omega/proofs/<platform>-<date>.proof.json (signed). Nothing is uploaded.
set -euo pipefail
cd "$(dirname "$0")/.."
DEVICE="${1:?usage: scripts/omega-proof.sh \"<device description>\" [ollama-model ...]}"; shift || true
if [ -n "${PREFIX:-}" ] && [[ "$PREFIX" == *com.termux* ]]; then
  pkg install -y python python-cryptography sqlite >/dev/null
  TAG=android
else
  TAG=$(uname -s | tr A-Z a-z)
fi
python -m pip install --quiet pytest 2>/dev/null || python -m pip install --quiet --user pytest
OUT="docs/omega/proofs/${TAG}-$(date +%Y%m%d-%H%M).proof.json"
ARGS=(); for m in "$@"; do ARGS+=(--ollama-model "$m"); done
set +e
python -m omega.proof run --device "$DEVICE" --out "$OUT" "${ARGS[@]}"
RC=$?
set -e
python -m omega.proof verify "$OUT"
echo "Proof written to $OUT (exit $RC). Nothing was uploaded."
exit $RC
