#!/usr/bin/env bash
# ForgeWorld Evolution Clip — launch command.
#
# Minimum viable cinematic proof: generates dark/gold vertical title-card
# frames from real ForgeWorld repo content, then assembles them into a
# short crossfaded MP4 with ffmpeg. No network calls, no found footage —
# every visual is generated and every source cited in output/MANIFEST.md.
#
# Usage:
#   ./run_evolution_clip.sh                # frames + preview render (fast)
#   ./run_evolution_clip.sh --final         # also render full-quality final.mp4
#   ./run_evolution_clip.sh --final --skip-preview   # only final (skip preview step)
#
# Termux: pkg install python python-pillow ffmpeg git
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS="$HERE/assets"

DO_FINAL=0
SKIP_PREVIEW=0
for arg in "$@"; do
  case "$arg" in
    --final) DO_FINAL=1 ;;
    --skip-preview) SKIP_PREVIEW=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 1; }
}
need python3
need ffmpeg
python3 -c "import PIL" 2>/dev/null || { echo "Missing Python package: Pillow (pip install Pillow / pkg install python-pillow)" >&2; exit 1; }

echo "== 1/4  generating frames from repo content =="
python3 "$ASSETS/generate_frames.py"

if [ "$SKIP_PREVIEW" -eq 0 ]; then
  echo "== 2/4  rendering preview (fast, low-res) =="
  python3 "$ASSETS/render.py" --mode preview
else
  echo "== 2/4  skipped (--skip-preview) =="
fi

if [ "$DO_FINAL" -eq 1 ]; then
  echo "== 3/4  rendering final (1080x1920, higher quality — slower) =="
  python3 "$ASSETS/render.py" --mode final
else
  echo "== 3/4  skipped (pass --final to render the high-quality export) =="
fi

echo "== 4/4  writing provenance manifest =="
python3 "$ASSETS/generate_manifest.py"

echo ""
echo "Done. Outputs in $HERE/output/"
ls -la "$HERE/output"
