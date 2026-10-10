#!/usr/bin/env python3
"""pack.py — deliverables from the live project (run from the project root).

    python3 pack.py [--name my-game] [--out dist] [--zip]

Writes dist/<name>/:
  game/      a static playable build (index.html + js + only the textures the manifest lists); open via any static host
             (or `python3 -m http.server` inside game/). Hot-reload polling and the dev overlay are disabled.
  assets/    every engine-ready texture (live/assets) + manifest.json (sizes, crops, walk lines) + the source art (art/gen)
  README.md  what is inside, the controls (SIM.HINT), the view size (SIM.VIEW), how to run, how to regenerate
With --zip also dist/<name>.zip. Never edits the project.
"""
import argparse, json, os, re, shutil, subprocess

ap = argparse.ArgumentParser(); ap.add_argument('--name', default=os.path.basename(os.getcwd())); ap.add_argument('--out', default='dist'); ap.add_argument('--zip', action='store_true')
a = ap.parse_args()
root = os.path.join(a.out, a.name); game = os.path.join(root, 'game'); assets = os.path.join(root, 'assets')
shutil.rmtree(root, ignore_errors=True); os.makedirs(os.path.join(game, 'assets')); os.makedirs(os.path.join(assets, 'textures')); os.makedirs(os.path.join(assets, 'source'))
manifest = json.loads(re.sub(r'^window\.ASSETS = |;\s*$', '', open('live/assets.js').read().strip()))
try:                                                        # view size and controls hint come from the sim (node is a setup dependency)
    sim = json.loads(subprocess.run(['node', '-e', "const S = require(require('path').resolve('live/sim.js')); "
                                     "console.log(JSON.stringify({ view: S.VIEW || null, hint: S.HINT || null }))"],
                                    capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[-1])
except Exception: sim = {}
view = sim.get('view') or {'W': 1920, 'H': 1080}
hint = sim.get('hint') or 'arrows / WASD move, Space jump, X action, R restart, Esc back to the demo; any key starts play.'
# every module the page may load (project-specific ones like batch.js / atlas.js too) and bundled fonts; never the dev tools (*.cjs)
for f in sorted(os.listdir('live')):
    if f.endswith('.js'): shutil.copy(os.path.join('live', f), game)
for d in ['fonts', 'audio']:
    if os.path.isdir(os.path.join('live', d)): shutil.copytree(os.path.join('live', d), os.path.join(game, d))
html = open('live/index.html').read().replace('<script>\n', '<script>window.__STATIC__ = 1;</script>\n<script>\n', 1)
open(os.path.join(game, 'index.html'), 'w').write(html)
for f in os.listdir('live/assets'):                                    # textures not in the manifest (a packed atlas) are loaded too
    if f.endswith('.png') and f[:-4] not in manifest: shutil.copy(os.path.join('live/assets', f), os.path.join(game, 'assets'))
for n in manifest:
    shutil.copy(os.path.join('live/assets', n + '.png'), os.path.join(game, 'assets'))
    shutil.copy(os.path.join('live/assets', n + '.png'), os.path.join(assets, 'textures'))
    src = os.path.join('art/gen', n + '.png')
    if os.path.exists(src): shutil.copy(src, os.path.join(assets, 'source'))
json.dump(manifest, open(os.path.join(assets, 'manifest.json'), 'w'), indent=1)
for extra in ['study/STYLE.md', 'study/PLAN.md', 'art/style_bible.txt']:
    if os.path.exists(extra): shutil.copy(extra, root)
open(os.path.join(root, 'README.md'), 'w').write(f"""# {a.name}

- `game/` — playable build. Serve the folder statically (`cd game && python3 -m http.server`) and open index.html.
  Controls: {hint}
- `assets/textures/` — engine-ready PNGs (premultiplied on upload, trimmed, edge-bled); `assets/manifest.json` — per texture
  w, h, crop (box in the source), scale, and walk/bottom lines for platform pieces.
- `assets/source/` — full-resolution generated sources (art/gen).
- `STYLE.md`, `PLAN.md`, `style_bible.txt` — the style passport, the layer/asset/interaction plan, and the prompt block
  that generated every asset (reuse it verbatim to extend the set).

{len(manifest)} textures. Rendering: WebGL2, {view['W']}x{view['H']} internal, everything after art (effects, rigs, wind, reactions)
is code in game/*.js; the sim is deterministic at 120 Hz.
""")
if a.zip: shutil.make_archive(root, 'zip', a.out, a.name); print('zip', root + '.zip')
print('packed', root, len(manifest), 'textures')
