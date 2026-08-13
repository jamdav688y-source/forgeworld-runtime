#!/data/data/com.termux/files/usr/bin/bash
#
# Next Right Move — self-locating launcher.
#
# Fixes the class of bug where the server gets started from the wrong
# working directory (one level too high) and /index.html then 404s even
# though the file exists one directory down. This script never trusts the
# caller's $PWD — it resolves its own location on disk and serves that.
#
# Works from Termux (shebang above) or a plain Linux shell
# (invoke as: bash start-next-right-move.sh).

set -u

# Resolve the real directory this script lives in, regardless of symlinks
# or how/where it was invoked from. This directory IS the project root,
# since this script ships inside next-right-move/.
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
PROJECT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
PORT="${1:-8080}"

echo "NEXT RIGHT MOVE"
echo "Project: $PROJECT_DIR"
echo "Port:    $PORT"
echo

if [ ! -f "$PROJECT_DIR/index.html" ]; then
  echo "ERROR: index.html not found in $PROJECT_DIR" >&2
  echo "This script's own directory should be the project root — something is wrong with the install." >&2
  exit 1
fi

# Detect a port conflict instead of silently starting a second server.
PORT_OWNER=""
if command -v fuser >/dev/null 2>&1; then
  PORT_OWNER="$(fuser -n tcp "$PORT" 2>/dev/null | tr -d ' ')"
elif command -v lsof >/dev/null 2>&1; then
  PORT_OWNER="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)"
fi

if [ -n "$PORT_OWNER" ]; then
  echo "Port $PORT is already in use by PID $PORT_OWNER:"
  ps -p "$PORT_OWNER" -o pid,cmd 2>/dev/null || ps -ef 2>/dev/null | grep "^[^ ]* *$PORT_OWNER "
  echo
  echo "If that's an old/stale copy of this same app, stop it first, e.g.:"
  echo "  kill $PORT_OWNER"
  echo "Then re-run this script. Refusing to start a second server on the same port."
  exit 1
fi

PY="python3"
command -v python3 >/dev/null 2>&1 || PY="python"

echo "URL: http://localhost:$PORT/"
echo "(Ctrl+C to stop)"
echo

# Best-effort: once the server responds, try to open it automatically if
# Termux:API is installed. This never blocks the server from starting and
# never installs anything on its own.
if command -v termux-open-url >/dev/null 2>&1; then
  (
    for _ in $(seq 1 20); do
      if command -v curl >/dev/null 2>&1 && curl -s -o /dev/null "http://localhost:$PORT/"; then
        termux-open-url "http://localhost:$PORT/" >/dev/null 2>&1
        break
      fi
      sleep 0.5
    done
  ) &
fi

exec "$PY" -m http.server "$PORT" --directory "$PROJECT_DIR"
