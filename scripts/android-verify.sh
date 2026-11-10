#!/data/data/com.termux/files/usr/bin/bash
# ForgeWorld Omega -- non-destructive install + verification on Android (Termux).
#
#   bash android-verify.sh [EXPECTED_COMMIT]
#
# Touches only $HOME/omega-verify (created if absent). It never edits other
# Termux files, never runs `pkg install` itself (it prints the command if
# something is missing), and installs pytest only into a private venv.
# Rollback: rm -rf "$HOME/omega-verify"
set -u
BASE="$HOME/omega-verify"
REPO_URL="https://github.com/jamdav688y-source/forgeworld-runtime.git"
BRANCH="ccr-0aad6294-t51qv4"
EXPECTED="${1:-}"
say(){ printf '\n== %s\n' "$*"; }

say "1. Environment"
echo "android_release: $(getprop ro.build.version.release 2>/dev/null || echo unknown)"
echo "device_model:    $(getprop ro.product.model 2>/dev/null || echo unknown)"
echo "termux_version:  ${TERMUX_VERSION:-unknown}"
echo "arch:            $(uname -m)"
case "${PREFIX:-}" in *com.termux*) echo "termux:          yes";; *) echo "termux:          NO (this script targets Termux)";; esac

say "2. Required tools"
missing=""
for t in git python; do command -v "$t" >/dev/null 2>&1 && echo "$t: $(command -v $t)" || missing="$missing $t"; done
if command -v python >/dev/null 2>&1; then
  python -V
  python -c "import cryptography; print('cryptography', cryptography.__version__)" 2>/dev/null || missing="$missing python-cryptography"
  python -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)'); print('sqlite', sqlite3.sqlite_version, 'fts5 yes')" 2>/dev/null \
    || echo "sqlite fts5: NO (supported fallback: slower LIKE search)"
fi
if [ -n "$missing" ]; then
  echo "MISSING:$missing"
  echo "Run this, then re-run the script:   pkg install -y git python python-cryptography"
  exit 2
fi

say "3. Isolated checkout in $BASE"
mkdir -p "$BASE"
if [ -d "$BASE/forgeworld-runtime/.git" ]; then
  cd "$BASE/forgeworld-runtime" || exit 3
  if [ -n "$(git status --porcelain)" ]; then echo "Local changes in $PWD -- refusing to touch them."; exit 3; fi
  git fetch -q origin "$BRANCH" || { echo "fetch failed (network?)"; exit 4; }
  git checkout -q --detach FETCH_HEAD
else
  git clone -q --branch "$BRANCH" "$REPO_URL" "$BASE/forgeworld-runtime" || { echo "clone failed (network?)"; exit 4; }
  cd "$BASE/forgeworld-runtime" || exit 3
fi
HEAD=$(git rev-parse HEAD); echo "installed commit: $HEAD"
if [ -n "$EXPECTED" ] && [ "${HEAD#$EXPECTED}" = "$HEAD" ]; then echo "COMMIT MISMATCH: expected $EXPECTED"; exit 5; fi

say "4. Private venv for pytest (uses the system cryptography)"
[ -d "$BASE/venv" ] || python -m venv --system-site-packages "$BASE/venv"
"$BASE/venv/bin/python" -m pip install -q pytest || echo "pytest install failed: tests skipped, proof still runs"

say "5. Test suite"
"$BASE/venv/bin/python" -m pytest -q -p no:cacheprovider omega/tests 2>&1 | tail -3

say "6. Signed proof (key bytes, restart persistence, end-to-end, tests)"
mkdir -p "$BASE/evidence"
OUT="$BASE/evidence/android-$(date +%Y%m%d-%H%M).proof.json"
case "${PREFIX:-}" in
  *com.termux*) DEVICE="Android $(getprop ro.build.version.release 2>/dev/null) $(getprop ro.product.model 2>/dev/null) / Termux ${TERMUX_VERSION:-?} (owner's phone)";;
  *)            DEVICE="NOT Termux: $(uname -sm) -- android-verify.sh dry run, not a phone result";;
esac
"$BASE/venv/bin/python" -m omega.proof run --device "$DEVICE" --out "$OUT"
RC=$?
"$BASE/venv/bin/python" -m omega.proof verify "$OUT"
echo
echo "proof file: $OUT   (exit $RC; nothing was uploaded)"
exit $RC
