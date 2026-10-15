#!/usr/bin/env python3
"""softbones.py — weight maps for 'soft bones' in a single painted sprite (an animal's neck, a tail, a branch).
Each bone is a region (polygon, sprite px) with a root and a tip: its weight rises smoothly from 0 at the root to 1 (t0..t1 of
the root→tip axis) and fades out at the region's edge. The scene bends the sprite in the shader (lib.js sprite u_bone0..2):
every pixel rotates about the bone's root by angle × weight, so the bone bends with no cut, gap or seam.
  - t0..t1 decides where the bend happens: a ramp spread over the whole region curls all of it into one arc, while a ramp
    that ends near where the real anatomy flexes keeps the bend there. Judge it on the posed sprite, not on the numbers.
  - 'seam': [[x, y], [x, y]] + 'ramp' (px): the weight also fades to 0 over ramp px at the line where the bone leaves the body,
    so the body there stretches over the gap instead of tearing open a notch. Without t0/t1, the weight is the seam distance
    alone (a hinge, such as where a head meets its neck).
  - Bone 2 (B channel) is a child of bone 0: it turns first (e.g. a head about its hinge), then rides on bone 0 (e.g. the neck).
  - The region must leave out legs, attached props and anything else that has to stay put; it may include the background
    around it.
Output: art/gen/<name>_w.png (R, G, B = bones 0..2, opaque), aligned with the PREPPED sprite live/assets/<name>.png.
usage: python3 <skill>/scripts/softbones.py art/softbones.json [name ...]
  (json: { name: { bones: [{ poly, root, tip, t0, t1, seam, ramp, feather }] } })"""
import json, re, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
cfg = json.load(open(sys.argv[1])); names = sys.argv[2:] or list(cfg)
meta = json.loads(re.sub(r'^window\.ASSETS = |;\s*$', '', open('live/assets.js').read().strip()))
RIGS = json.loads(re.sub(r'^window\.RIGS = |;\s*$', '', open('live/rigs.js').read().strip()))
ss = lambda a, b, x: np.clip((x - a) / (b - a), 0, 1) ** 2 * (3 - 2 * np.clip((x - a) / (b - a), 0, 1))
for nm in names:
    m = meta[nm]; cx, cy = m['crop'][0], m['crop'][1]; s = m['scale']; W, H = m['w'], m['h']
    P = lambda p: ((p[0] - cx) * s, (p[1] - cy) * s)
    out = np.zeros((H, W, 4), np.float32); out[:, :, 3] = 1
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for bi, b in enumerate(cfg[nm]['bones']):
        mk = Image.new('L', (W, H), 0); ImageDraw.Draw(mk).polygon([P(p) for p in b['poly']], fill=255)
        mk = np.array(mk.filter(ImageFilter.GaussianBlur(b.get('feather', 5)))).astype(np.float32) / 255
        r, tp = np.array(P(b['root'])), np.array(P(b['tip'])); ax = tp - r; L2 = (ax ** 2).sum()
        t = ((xx - r[0]) * ax[0] + (yy - r[1]) * ax[1]) / L2
        w = ss(b.get('t0', 0.0), b.get('t1', 0.9), t) if ('t1' in b or 'seam' not in b) else 1.0
        if 'seam' in b:
            a, c = np.array(P(b['seam'][0])), np.array(P(b['seam'][1])); n = np.array([a[1] - c[1], c[0] - a[0]]); n /= np.linalg.norm(n)
            if ((tp - a) * n).sum() < 0: n = -n
            w = w * ss(0, 1, ((xx - a[0]) * n[0] + (yy - a[1]) * n[1]) / (b['ramp'] * s))
        out[:, :, bi] = w * mk
    Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(f'art/gen/{nm}_w.png')
    roots = [[round(v, 1) for v in P(b['root'])] for b in cfg[nm]['bones']]
    tips = [[round(v, 1) for v in P(b['tip'])] for b in cfg[nm]['bones']]
    RIGS[nm] = { 'bones': roots, 'tips': tips, 'w': W, 'h': H }      # the scene reads RIGS[name].bones (roots) / tips (prepped px)
    print(nm, 'roots (prepped px):', roots)
open('live/rigs.js', 'w').write('window.RIGS = ' + json.dumps(RIGS) + ';\n')
