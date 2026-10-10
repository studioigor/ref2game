#!/usr/bin/env python3
"""jointr.py — measure each rig's limb half-width at its elbows and knees (rig px) into live/rigs.js as r.jr.
A bent joint is drawn with a round cap of this radius (a disc of the upper segment's texture) so the elbow / knee stays
round instead of showing the corner gap between two straight cut pieces.
usage: python3 <skill>/scripts/jointr.py [rig ...]   (default: every rig with elbows or knees)"""
import json, re, sys, os
import numpy as np
from PIL import Image
RP = 'live/rigs.js'
R = json.loads(re.sub(r'^window\.RIGS = |;\s*$', '', open(RP).read().strip()))
def half_width(png, joint, toward):
    if not os.path.exists(png): return None
    a = np.array(Image.open(png).convert('RGBA'))[:, :, 3] > 60
    jx, jy = joint; tx, ty = toward; L = max(1e-6, ((tx - jx) ** 2 + (ty - jy) ** 2) ** 0.5); ux, uy = (tx - jx) / L, (ty - jy) / L
    ws = []
    for d in (3, 6, 9, 12):                              # a few cross-sections just inside the upper segment
        cx, cy = jx + ux * d, jy + uy * d; px, py = -uy, ux; n = 0
        for s in range(-60, 61):
            x, y = int(round(cx + px * s)), int(round(cy + py * s))
            if 0 <= y < a.shape[0] and 0 <= x < a.shape[1] and a[y, x]: n += 1
        if n: ws.append(n)
    return round(float(np.median(ws)) / 2, 1) if ws else None
names = sys.argv[1:] or list(R)
for nm in names:
    r = R[nm]; jr = {}
    for sd in 'LR':
        if r.get('elbow' + sd): jr['elbow' + sd] = half_width(f'art/gen/{nm}__uarm{sd}.png', r['elbow' + sd], r['sh' + sd])
        if r.get('knee' + sd): jr['knee' + sd] = half_width(f'art/gen/{nm}__thigh{sd}.png', r['knee' + sd], r['hip' + sd])
    r['jr'] = {k: v for k, v in jr.items() if v}
    print(nm, r['jr'])
open(RP, 'w').write('window.RIGS = ' + json.dumps(R) + ';\n')
