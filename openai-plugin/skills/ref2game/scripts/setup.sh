#!/usr/bin/env bash
# ref2game project setup (idempotent: never overwrites files you edited).
#   bash <skill>/scripts/setup.sh <project-dir> [--genre side|top|blank] [--ref IMAGE|VIDEO] [--refresh-engine] [--deps-only]
# 1. checks Python dependencies (REF2GAME_PYTHON), node and ffmpeg; installs Playwright/Chromium only if missing;
# 2. creates the project: art/{gen,raw,logs,prompts,requests}  live/  study/{crops,critique}  frames/  ref2game.json;
#    --ref copies the user's reference to <project>/ref.png (the generator's style_ref): images converted to PNG, a video
#    gives its middle frame (ffmpeg). Given explicitly, it replaces an existing ref.png;
# 3. copies the live template (index.html, gl.js, lib.js, sim.js, scene.js, tune.cjs) — missing files only, or the
#    engine files (gl.js, lib.js) again with --refresh-engine. --genre picks the starting sim.js/scene.js: side (side view),
#    top (top-down / 3/4), blank (an empty stage with pointer input). It is only a starting point for the game;
# 4. draws placeholder art and preps it, so the live page runs before the first generation.
set -euo pipefail
SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REF2GAME_PYTHON:-python3}"
PROJ="${1:-}"; shift || true
REFRESH=0; DEPS_ONLY=0; GENRE=side; GSET=0; REF=""; prev=""
for a in "$@"; do case "$a" in --refresh-engine) REFRESH=1;; --deps-only) DEPS_ONLY=1;; esac
  [ "$prev" = "--genre" ] && { GENRE="$a"; GSET=1; }; [ "$prev" = "--ref" ] && REF="$a"; prev="$a"; done
[ -n "$PROJ" ] || { echo "usage: setup.sh <project-dir> [--genre side|top|blank] [--ref IMAGE|VIDEO] [--refresh-engine] [--deps-only]"; exit 1; }
[ -z "$REF" ] || [ -f "$REF" ] || { echo "--ref: no such file: $REF"; exit 1; }

# ---------------------------------------------------------------- dependencies
command -v node >/dev/null || { echo "node is required (Node.js 18+)"; exit 1; }
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found: video renders and video study need it (brew install ffmpeg / apt install ffmpeg)"
if ! "$PYTHON" -c 'import PIL, numpy, scipy'; then
  echo "Python dependencies missing. Use a project-local environment with Pillow, NumPy and SciPy."
  echo "Re-run with REF2GAME_PYTHON=/absolute/path/to/that/python3."
  exit 1
fi
if ! (cd "$SKILL/scripts" && node -e "require.resolve('playwright')" 2>/dev/null); then
  echo "installing Playwright into the skill (once)"; (cd "$SKILL/scripts" && npm install --silent --no-audit --no-fund)
fi
if ! (cd "$SKILL/scripts" && node -e "const fs = require('fs'); const {chromium} = require('playwright'); if (!fs.existsSync(chromium.executablePath())) process.exit(1)" 2>/dev/null); then
  (cd "$SKILL/scripts" && npx --no-install playwright install chromium) || { echo "Chromium installation failed"; exit 1; }
fi
[ "$DEPS_ONLY" = 1 ] && { echo "deps OK"; exit 0; }

# ---------------------------------------------------------------- project skeleton
mkdir -p "$PROJ"/{art/gen,art/raw,art/logs,art/prompts,art/requests,live/assets,study/crops,study/critique,frames}
cp_new() { [ -e "$2" ] || cp "$1" "$2"; }
case "$GENRE" in side) GT="$SKILL/templates/live";; top) GT="$SKILL/templates/live-topdown";; blank) GT="$SKILL/templates/live-blank";;
  *) echo "--genre must be side, top or blank"; exit 1;; esac
for f in index.html tune.cjs; do cp_new "$SKILL/templates/live/$f" "$PROJ/live/$f"; done
# stubs the page always loads: display sizes (written later from the art scale) and the sound module
[ -e "$PROJ/live/sizes.js" ] || printf '// in-game sprite sizes in view px: { name: [w, h] } (engine.md §7 "Display size vs texture size")\nwindow.SIZES = window.SIZES || {};\n' > "$PROJ/live/sizes.js"
[ -e "$PROJ/live/audio.js" ] || printf '// live/audio.js: sound driven by the sim event bus (S.ev). Stub until the game gets sound.\n' > "$PROJ/live/audio.js"
[ "$GSET" = 1 ] && [ -e "$PROJ/live/sim.js" ] && echo "note: kept the existing live/sim.js and live/scene.js; to switch the base to --genre $GENRE, move them aside and re-run"
for f in sim.js scene.js; do cp_new "$GT/$f" "$PROJ/live/$f"; done
if [ -n "$REF" ]; then                                     # the user's reference → ref.png (style_ref of every generation)
  case "$(echo "${REF##*.}" | tr '[:upper:]' '[:lower:]')" in
    mp4|mov|webm|mkv|avi|m4v|mpg|mpeg)
      command -v ffmpeg >/dev/null || { echo "--ref is a video: ffmpeg is required"; exit 1; }
      D="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$REF" 2>/dev/null || echo 0)"
      ffmpeg -y -v error -ss "$("$PYTHON" -c "import sys; d = sys.argv[1]; print(float(d) / 2 if d.replace('.', '', 1).isdigit() else 0)" "$D")" -i "$REF" -frames:v 1 "$PROJ/ref.png";;
    png) [ "$REF" -ef "$PROJ/ref.png" ] || cp "$REF" "$PROJ/ref.png";;
    *) "$PYTHON" -c "import sys; from PIL import Image; im = Image.open(sys.argv[1]); im.convert('RGBA' if 'A' in im.getbands() or 'transparency' in im.info else 'RGB').save(sys.argv[2])" "$REF" "$PROJ/ref.png";;
  esac
  [ -s "$PROJ/ref.png" ] || { echo "--ref: could not write $PROJ/ref.png from $REF"; exit 1; }
  echo "reference: $REF -> $PROJ/ref.png"
fi
for f in gl.js lib.js; do if [ "$REFRESH" = 1 ]; then cp "$SKILL/templates/live/$f" "$PROJ/live/$f"; else cp_new "$SKILL/templates/live/$f" "$PROJ/live/$f"; fi; done
[ -f "$PROJ/ref2game.json" ] || cat > "$PROJ/ref2game.json" <<'JSON'
{
  "generator": { "tool": "imagegen", "size": "1536x1024", "alpha": "auto", "opaque": ["bg_sky*", "*_tex"] },
  "style_bible": "art/style_bible.txt",
  "style_ref": ["ref.png"],
  "view": [1920, 1080],
  "prep": { "src": "art/gen", "dst": "live/assets", "manifest": "live/assets.js",
            "notrim": ["bg_*", "*_tex"], "skip": ["*_sheet", "*_raw"], "max": 2048,
            "walk": { "ground": 0.6, "ledge*": 0.45 } }
}
JSON
[ -f "$PROJ/art/style_bible.txt" ] || cat > "$PROJ/art/style_bible.txt" <<'TXT'
STYLE BIBLE (replace after the study; keep it short, measured from the reference, verbatim on every call):
<style family> 2D game art matching Image 1: <shape language>; <shading: tones, terminator>; <palette and temperature>;
<line: weight, colour, where>; <texture/brushwork>; detail only at focal points, big quiet shapes elsewhere.
Light: <one fixed light sentence: key direction and colour, fill colour, no cast shadow>.
Strict <projection/view>. No text, no logos, no watermark, no glow, no light rays, no cast shadows.
TXT
(cd "$PROJ" && "$PYTHON" "$SKILL/scripts/placeholders.py" --out art/gen --set "$GENRE" >/dev/null && "$PYTHON" "$SKILL/scripts/prep.py" >/dev/null)
echo "project ready: $PROJ"
echo "  live preview : (cd $PROJ && bash $SKILL/scripts/serve.sh)      # prints the URL; keep it open while you work"
echo "  headless test: (cd $PROJ && node $SKILL/scripts/livecheck.mjs --shots 1,3)"
echo "  stills       : (cd $PROJ && node $SKILL/scripts/render.mjs stills 0,2,4 --out frames/check)"
echo "  imagegen files: (cd \"$PROJ\" && \"$PYTHON\" \"$SKILL/scripts/gen.py\" check)"
