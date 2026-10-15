#!/usr/bin/env python3
"""variantfix.py — make a generated VARIANT (eyes closed, mouth open, damaged state, lit window...) differ from its BASE
ONLY where it should, so swapping the two textures in the engine does not pop in colour, scale or position.

    python3 variantfix.py BASE.png VARIANT.png [--out OUT.png] [--regions 2] [--thresh 40] [--min 150] [--feather 10]

Why: an edit call ("same image, eyes closed") always drifts a little — shifted by a few px, scaled ~1-3%, tinted.
Swapped at runtime that reads as a flash of colour or a jitter. This script:
  1. normalises both to their alpha boxes, then searches scale (±3%) and offset (±14 px) for the best alpha match;
  2. colour-matches the aligned variant to the base (per-channel mean/std over their common opaque area);
  3. finds the changed region(s) = the largest blobs of strong difference inside the body (`regions` of them);
  4. pastes ONLY those regions into a copy of the base through a feathered mask. Output alpha == base alpha.
Write the result back to art/gen/ (the source folder), never only to live/assets (prep would overwrite it).
Prints the changed region in uv of the base, handy for a shader-side effect at the same spot.
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage

ap = argparse.ArgumentParser()
ap.add_argument('base'); ap.add_argument('variant'); ap.add_argument('--out')
ap.add_argument('--regions', type=int, default=2); ap.add_argument('--thresh', type=float, default=40)
ap.add_argument('--min', type=int, default=150); ap.add_argument('--feather', type=int, default=10)
a = ap.parse_args()
base = Image.open(a.base).convert('RGBA'); var = Image.open(a.variant).convert('RGBA')
B = np.array(base).astype(np.float32)
bb, vb = base.getchannel('A').point(lambda v: 255 if v > 24 else 0).getbbox(), var.getchannel('A').point(lambda v: 255 if v > 24 else 0).getbbox()
# 1. coarse: put the variant's alpha box onto the base's alpha box
vc = var.crop(vb).resize((bb[2] - bb[0], bb[3] - bb[1]), Image.LANCZOS)
canvas = Image.new('RGBA', base.size, (0, 0, 0, 0)); canvas.paste(vc, (bb[0], bb[1])); var = canvas
best = None
for sc in np.linspace(0.97, 1.03, 7):
    w, h = round(base.width * sc), round(base.height * sc)
    b2 = np.array(var.resize((w, h), Image.LANCZOS)).astype(np.float32)
    pad = np.zeros((h + 60, w + 60, 4), np.float32); pad[30:30 + h, 30:30 + w] = b2
    for dx in range(-14, 15, 2):
        for dy in range(-14, 15, 2):
            x0 = (w - base.width) // 2 + dx + 30; y0 = (h - base.height) // 2 + dy + 30
            if x0 < 0 or y0 < 0 or x0 + base.width > pad.shape[1] or y0 + base.height > pad.shape[0]: continue
            c = pad[y0:y0 + base.height, x0:x0 + base.width]
            err = np.abs(B[:, :, 3] - c[:, :, 3]).mean()
            if best is None or err < best[0]: best = (err, sc, dx, dy, c.copy())
err, sc, dx, dy, C = best
print('align err', round(float(err), 2), 'scale', round(float(sc), 3), 'offset', dx, dy)
# 2. colour match
m = (B[:, :, 3] > 200) & (C[:, :, 3] > 200)
for ch in range(3):
    x, y = B[:, :, ch][m], C[:, :, ch][m]
    C[:, :, ch] = np.clip((C[:, :, ch] - y.mean()) / (y.std() + 1e-3) * x.std() + x.mean(), 0, 255)
# 3. changed regions
d = ndimage.gaussian_filter(np.abs(B[:, :, :3] - C[:, :, :3]).mean(2) * m, 3)
lab, k = ndimage.label(d > a.thresh)
sizes = ndimage.sum(np.ones_like(d), lab, range(1, k + 1)) if k else []
keep = np.zeros_like(d, bool)
for i in np.argsort(sizes)[::-1][:a.regions]:
    if sizes[i] > a.min: keep |= lab == i + 1
if not keep.any(): raise SystemExit('no changed region found: lower --thresh / --min, or the variant did not change')
mask = ndimage.gaussian_filter(ndimage.binary_dilation(keep, iterations=a.feather).astype(np.float32), a.feather / 2)[:, :, None]
# 4. paste
out = B.copy(); out[:, :, :3] = B[:, :, :3] * (1 - mask) + C[:, :, :3] * mask
Image.fromarray(out.astype(np.uint8)).save(a.out or a.variant)
ys, xs = np.where(keep)
print('changed region uv', round(xs.min() / base.width, 3), round(ys.min() / base.height, 3), round(xs.max() / base.width, 3), round(ys.max() / base.height, 3))
