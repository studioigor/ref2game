#!/usr/bin/env python3
"""slice.py — cut a generated sheet (kit-mates or character parts on transparent background) into separate pieces
by connected alpha components.

    python3 slice.py SHEET [name1,name2,...] [--out DIR] [--order reading|x|y|size] [--dilate 6] [--alpha 24] [--min 400]

Without names it only LISTS the components (index, box, area) so you can decide names and count.
With N names it keeps the N largest components, orders them (reading = row bands top→bottom, then left→right), and writes
DIR/<name>.png (DIR defaults to the sheet's folder). Pieces keep only their own pixels (neighbours that poke into the box
are cleared). `dilate` merges a piece's detached bits (leaf tips, sparkles) into it; raise it if a piece splits, lower it
if neighbours merge. Ask the generator for wide empty gutters between pieces — that is what makes slicing reliable.
"""
import argparse, os
import numpy as np
from PIL import Image
from scipy import ndimage

ap = argparse.ArgumentParser()
ap.add_argument('sheet'); ap.add_argument('names', nargs='?', default='')
ap.add_argument('--out'); ap.add_argument('--order', default='reading'); ap.add_argument('--dilate', type=int, default=6)
ap.add_argument('--alpha', type=int, default=24); ap.add_argument('--min', type=int, default=400)
a = ap.parse_args()
im = Image.open(a.sheet).convert('RGBA'); A = np.array(im)
lab, n = ndimage.label(ndimage.binary_dilation(A[:, :, 3] > a.alpha, iterations=a.dilate))
objs = ndimage.find_objects(lab)
comps = [(i, o, int((lab[o] == i + 1).sum())) for i, o in enumerate(objs)]
comps = [c for c in comps if c[2] >= a.min]
names = [s for s in a.names.split(',') if s]
if not names:
    for k, (i, o, ar) in enumerate(sorted(comps, key=lambda c: -c[2])):
        print(f'#{k} x {o[1].start}-{o[1].stop} y {o[0].start}-{o[0].stop} area {ar}')
    raise SystemExit
keep = sorted(comps, key=lambda c: -c[2])[:len(names)]
if len(keep) < len(names): print(f'WARNING: only {len(keep)} components for {len(names)} names')
if a.order == 'reading':                                         # cluster rows by vertical overlap, then sort by x
    keep.sort(key=lambda c: c[1][0].start); rows = []
    for c in keep:
        cy = (c[1][0].start + c[1][0].stop) / 2
        if rows and rows[-1][0][1][0].start <= cy <= rows[-1][0][1][0].stop: rows[-1].append(c)
        else: rows.append([c])
    keep = [c for r in rows for c in sorted(r, key=lambda c: c[1][1].start)]
elif a.order == 'x': keep.sort(key=lambda c: c[1][1].start)
elif a.order == 'y': keep.sort(key=lambda c: c[1][0].start)
out = a.out or os.path.dirname(os.path.abspath(a.sheet)); os.makedirs(out, exist_ok=True)
for (i, sl, ar), nm in zip(keep, names):
    piece = A[sl].copy(); piece[lab[sl] != i + 1] = 0
    Image.fromarray(piece).save(os.path.join(out, nm + '.png'))
    print(nm, 'x', sl[1].start, sl[1].stop, 'y', sl[0].start, sl[0].stop, 'area', ar)
