#!/usr/bin/env python3
"""prep.py — art/gen/*.png (sources of truth) → live/assets/*.png (engine-ready) + live/assets.js (window.ASSETS manifest).

    python3 prep.py [--all] [--only name1,name2]

Per image: alpha cleaned (crushes near-0 / near-1 noise), edge colour bled outward (no dark or key-coloured halos under
mipmaps and blur), trimmed to the alpha box + 4 px (unless listed in notrim), capped at `max` px, and measured:
  w, h, crop (box in the source), scale, plus for names matched by `walk`: walk (first row whose opaque fraction > f)
  and bottom (last such row) — the walkable top line of platform pieces, so colliders come from data, not guesses.

Config: ref2game.json → "prep": { "src": "art/gen", "dst": "live/assets", "manifest": "live/assets.js",
  "notrim": ["bg_*", "*_tex"], "skip": ["*_sheet"], "max": 2048, "walk": { "ground": 0.6, "ledge*": 0.45 } }
Incremental: unchanged sources are skipped (use --all after changing the rules). prep is a PURE function of art/gen:
anything you fix by hand or by script (variant alignment, seam repair) must be written back into art/gen, never into
live/assets, or the next prep run silently undoes it.
"""
import argparse, fnmatch, json, os, re
import numpy as np
from PIL import Image, ImageFilter

DEF = {'src': 'art/gen', 'dst': 'live/assets', 'manifest': 'live/assets.js', 'notrim': ['bg_*', '*_tex'], 'skip': ['*_sheet', '*_raw'],
       'max': 2048, 'walk': {}}


def match(n, pats): return any(fnmatch.fnmatch(n, p) for p in pats)


def prep_one(src, n, cfg):
    im = Image.open(src).convert('RGBA'); a = np.array(im).astype(np.float32)
    al = np.clip((a[:, :, 3] - 8) / (245 - 8), 0, 1)
    rgb = Image.fromarray(a[:, :, :3].astype(np.uint8)); m = Image.fromarray((al > 0.5).astype(np.uint8) * 255)
    rb = np.array(rgb.filter(ImageFilter.GaussianBlur(4))).astype(np.float32)
    mb = np.array(m.filter(ImageFilter.GaussianBlur(4))).astype(np.float32)[:, :, None] / 255
    fill = np.where(mb > 0.02, rb / np.maximum(mb, 0.02), a[:, :, :3])
    out = np.where(al[:, :, None] > 0.5, a[:, :, :3], fill)
    im = Image.fromarray(np.dstack([np.clip(out, 0, 255), al * 255]).astype(np.uint8))
    box = (0, 0, im.width, im.height)
    if not match(n, cfg['notrim']):
        bb = Image.fromarray(((al > 0.08) * 255).astype(np.uint8)).getbbox()
        if bb: box = (max(0, bb[0] - 4), max(0, bb[1] - 4), min(im.width, bb[2] + 4), min(im.height, bb[3] + 4)); im = im.crop(box)
    s = min(1.0, cfg['max'] / max(im.size))
    if s < 1: im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    d = {'w': im.width, 'h': im.height, 'crop': list(box), 'scale': round(s, 5)}
    for pat, f in cfg['walk'].items():
        if fnmatch.fnmatch(n, pat):
            A = np.array(im)[:, :, 3] > 128; rows = np.where(A.mean(axis=1) > f)[0]
            if len(rows): d['walk'] = int(rows[0]); d['bottom'] = int(rows[-1])
            break
    return im, d


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--all', action='store_true'); ap.add_argument('--only', default='')
    a = ap.parse_args()
    cfg = dict(DEF)
    if os.path.exists('ref2game.json'): cfg.update(json.load(open('ref2game.json')).get('prep', {}))
    os.makedirs(cfg['dst'], exist_ok=True)
    meta = {}
    if os.path.exists(cfg['manifest']):
        try: meta = json.loads(re.sub(r'^window\.ASSETS = |;\s*$', '', open(cfg['manifest']).read().strip()))
        except Exception: meta = {}
    only = set(filter(None, a.only.split(',')))
    names = []
    for f in sorted(os.listdir(cfg['src'])):
        if not f.endswith('.png'): continue
        n = f[:-4]
        if match(n, cfg['skip']): continue
        names.append(n)
        if only and n not in only: continue
        src, dst = os.path.join(cfg['src'], f), os.path.join(cfg['dst'], f)
        if not a.all and not only and n in meta and os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src): continue
        im, d = prep_one(src, n, cfg); im.save(dst); meta[n] = d; print(n, d)
    meta = {n: meta[n] for n in names if n in meta}                       # drop entries whose source is gone
    open(cfg['manifest'], 'w').write('window.ASSETS = ' + json.dumps(meta) + ';\n')
    print(f'{len(meta)} assets → {cfg["manifest"]}')


if __name__ == '__main__':
    main()
