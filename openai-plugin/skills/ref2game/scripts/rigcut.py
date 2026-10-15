#!/usr/bin/env python3
"""rigcut.py — cut an approved character drawing (rig pose: legs apart, arms clear of the torso) into cut-out rig parts
that reassemble it pixel for pixel: <name>__body, __legL, __legR, __armL, __armR, all on ONE shared canvas (trimmed whole,
scaled to --height px), plus pivots measured from alpha, merged into live/rigs.js (window.RIGS).

    python3 <skill>/scripts/rigcut.py NAME [--height 320] [--noarms] [--src art/gen] [--knee F] [--arm L=x,y;x,y;... --sh L=x,y --hand L=x,y]
Legs split at the knee into thigh + shin (two-bone IK in the scene); --knee F (or L=F,R=F) sets the knee row as a fraction of the
height (default: midway between crotch and sole). --arm cuts an arm by a polygon in rig px (for arms painted against the body).
Legs under a robe / cape / long coat: --hip Y (or L=Y,R=Y) raises the hip pivots to row Y (rig px) and --thigh L=x,y;x,y;... cuts the
visible thigh above the crotch by a polygon into that leg, so the whole visible leg swings from the real hip.
Polygon cuts leave a hole in the body behind the part: it is back-filled from the surrounding body, blurred and darkened (the
occluded side), so a limb that swings away never shows the background through the torso (--nofill to skip).
"""
import argparse, json, os, re
import numpy as np
from PIL import Image
from scipy import ndimage

ap = argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('--height', type=int, default=320)
ap.add_argument('--noarms', action='store_true'); ap.add_argument('--src', default='art/gen'); ap.add_argument('--armgap', type=int, default=2); ap.add_argument('--feet', default='')
ap.add_argument('--knee', default='0'); ap.add_argument('--hip', default=''); ap.add_argument('--thigh', action='append', default=[]); ap.add_argument('--nofill', action='store_true'); ap.add_argument('--ankle', type=float, default=0.93); ap.add_argument('--elbow', action='store_true'); ap.add_argument('--face', default='left'); ap.add_argument('--arm', action='append', default=[]); ap.add_argument('--sh', action='append', default=[]); ap.add_argument('--hand', action='append', default=[])
a = ap.parse_args()
im = Image.open(os.path.join(a.src, a.name + '.png')).convert('RGBA')
al = np.array(im)[:, :, 3]; ys, xs = np.where(al > 60)
im = im.crop((max(0, xs.min() - 3), max(0, ys.min() - 3), min(im.width, xs.max() + 4), min(im.height, ys.max() + 4)))
s = a.height / im.height; im = im.resize((max(1, round(im.width * s)), a.height), Image.LANCZOS)
P = np.array(im); A = P[:, :, 3] > 110; H, W = A.shape

# ---- feet: two biggest blobs in the bottom 10 % ----
band = int(H * 0.90); lab, n = ndimage.label(A[band:])
sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1)); order = np.argsort(-sizes)[:2]
if len(order) < 2: raise SystemExit('could not find two feet')
feet = []
for k in order:
    yy, xx = np.where(lab == k + 1); feet.append((xx.mean(), xx.min(), xx.max()))
feet.sort(); fL, fR = feet
if a.feet:
    fx = [float(v) for v in a.feet.split(',')]
    def near_blob(x):
        cols = np.where(A[band:, int(x)])[0]
        return (x, x - 10, x + 10)
    fL, fR = near_blob(fx[0]), near_blob(fx[1])
# ---- leg gap upward from the feet → crotch row ----
crotch = None; gaps = {}; prev = None
def runs(row, x0):
    out = []; i = 0
    while i < len(row):
        if not row[i]:
            j = i
            while j < len(row) and not row[j]: j += 1
            out.append((x0 + i, x0 + j - 1)); i = j
        else: i += 1
    return out
for y in range(H - 1, int(H * 0.30), -1):
    x0 = int(fL[0]); row = A[y, x0:int(fR[0]) + 1]
    rs = [r for r in runs(row, x0) if r[1] - r[0] >= 1]
    if prev is not None: rs = [r for r in rs if r[0] <= prev[1] + 1 and r[1] >= prev[0] - 1]
    if rs:
        r = max(rs, key=lambda r: r[1] - r[0]); prev = r; gaps[y] = (r[0] + r[1]) / 2
    elif y < H * 0.8: crotch = y; break
if crotch is None: raise SystemExit('no crotch found')
gx = gaps[min(gaps)] if gaps else (fL[0] + fR[0]) / 2
ov = max(2, int(H * 0.035))
# ---- legs = components (below the crotch) that contain the feet ----
low = A.copy(); low[:crotch + 1] = False
lab2, n2 = ndimage.label(low)
def comp_at(fx):
    ys2 = np.where(A[:, int(fx)])[0]; yb = ys2.max() if len(ys2) else H - 1
    for yy in range(yb, crotch, -1):
        l = lab2[yy, int(fx)]
        if l: return l
    return 0
cL, cR = comp_at(fL[0]), comp_at(fR[0])
legL = (lab2 == cL); legR = (lab2 == cR)
if cL == cR:                                            # joined below the crotch (shadow / overlap): split by the gap x
    xs_ = np.arange(W)[None, :]; legL = legL & (xs_ < gx); legR = legR & (xs_ >= gx)
# hip strip above the crotch (overlap under the body)
def hip(mask, left):
    cols = np.where(mask[crotch + 1:crotch + 4].any(axis=0))[0]
    x0, x1 = (cols.min(), cols.max()) if len(cols) else (0, W)
    m = np.zeros_like(A); m[crotch - ov:crotch + 1, x0:x1 + 1] = A[crotch - ov:crotch + 1, x0:x1 + 1]
    xs_ = np.arange(W)[None, :]; m &= (xs_ < gx) if left else (xs_ >= gx)
    return m | mask, ((x0 + x1) / 2, crotch - ov * 0.5)
legL, hipL = hip(legL, True); legR, hipR = hip(legR, False)
kvs = lambda v: {q.split('=')[0]: q.split('=')[1] for q in v.split(',')} if '=' in v else {'L': v, 'R': v}
cutholes = np.zeros_like(A); thm = {}                      # polygon-cut regions inside the body (back-filled later)
if a.thigh:
    from PIL import ImageDraw
    for q in a.thigh:
        side, pts = q.split('=', 1); pp = [tuple(float(v) for v in t.split(',')) for t in pts.split(';')]
        mimg = Image.new('L', (W, H), 0); ImageDraw.Draw(mimg).polygon(pp, fill=255); tm = (np.array(mimg) > 0) & A
        if side == 'L': legL = legL | tm
        else: legR = legR | tm
        cutholes |= tm; thm[side] = tm
if a.hip:
    hv = kvs(a.hip)
    def hx(side, cur):                                      # over the cut thigh: the centre of its top rows
        if side not in thm: return cur
        yy, xx = np.where(thm[side]); return float(xx[yy <= yy.min() + 12].mean())
    hipL = (hx('L', hipL[0]), float(hv['L'])); hipR = (hx('R', hipR[0]), float(hv['R']))
body = A.copy(); body[crotch + 1:] &= ~(legL[crotch + 1:] | legR[crotch + 1:]); body &= ~cutholes
# lower-body leftovers that are not legs (hands, tails, weapon tips) stay with the body
parts = {'legL': legL, 'legR': legR}
meta = {'w': W, 'h': H, 'crotch': int(crotch), 'gap': float(gx), 'hipL': [float(hipL[0]), float(hipL[1])], 'hipR': [float(hipR[0]), float(hipR[1])],
        'footL': [float(fL[0]), float(H - 2)], 'footR': [float(fR[0]), float(H - 2)]}
# ---- arms cut by polygon (rig px): for arms painted over the body / cape ----
if a.arm:
    from PIL import ImageDraw
    kv = lambda lst: {q.split('=')[0]: q.split('=')[1] for q in lst}
    polys, shs, hds = kv(a.arm), kv(a.sh), kv(a.hand)
    for side, pts in polys.items():
        pp = [tuple(float(v) for v in q.split(',')) for q in pts.split(';')]
        mimg = Image.new('L', (W, H), 0); ImageDraw.Draw(mimg).polygon(pp, fill=255)
        armm = (np.array(mimg) > 0) & body
        parts['arm' + side] = armm; body &= ~armm; cutholes |= armm
        meta['sh' + side] = [float(v) for v in shs[side].split(',')]; meta['hand' + side] = [float(v) for v in hds[side].split(',')]
# ---- arms: in the rows between the waist and the crotch the outermost spans left/right of the torso ----
if not a.noarms and not a.arm:
    torso_x = (hipL[0] + hipR[0]) / 2
    def spans(y):
        r = body[y]; out = []; x = 0
        while x < W:
            if r[x]:
                x0 = x
                while x < W and r[x]: x += 1
                out.append((x0, x - 1))
            else: x += 1
        return out
    for side in ('L', 'R'):
        # find rows where the arm is a separate span (gap to the torso), from the crotch upward
        rows = []
        for y in range(crotch, int(H * 0.2), -1):
            sp = [q for q in spans(y) if q[1] - q[0] >= 2]
            if len(sp) < 2: continue
            arm = sp[0] if side == 'L' else sp[-1]
            other = sp[1] if side == 'L' else sp[-2]
            if (side == 'L' and arm[1] < torso_x - 4) or (side == 'R' and arm[0] > torso_x + 4):
                gap = (other[0] - arm[1]) if side == 'L' else (arm[0] - other[1])
                if gap >= a.armgap: rows.append((y, arm, other))
        if len(rows) < 6: print('no separable arm', side); continue
        top = min(r[0] for r in rows)                   # highest row where the arm is still separate (the armpit)
        cut = [r for r in rows if r[0] == top][0]
        cutx = (cut[1][1] + cut[2][0]) / 2 if side == 'L' else (cut[1][0] + cut[2][1]) / 2
        # shoulder: go up from the armpit along the cut line until the arm's outer column ends
        colmask = np.zeros_like(A); colmask[:, :int(cutx) + 1] = True
        if side == 'R': colmask = ~colmask
        sub = body & colmask
        # arm = connected part of `sub` from armpit rows down, and rows above the armpit up to shoulder height
        yy, xx = np.where(sub[top:])
        armbot = top + (yy.max() if len(yy) else 0)
        # shoulder top: the topmost row where sub has pixels contiguous with the armpit column region
        lab3, _ = ndimage.label(sub)
        l = lab3[top, int(np.clip(cut[1][0] + 1 if side == 'L' else cut[1][1] - 1, 0, W - 1))]
        if not l: print('arm label miss', side); continue
        armm = lab3 == l
        # limit the arm upward to a band above the armpit (keeps head/hair off the arm part)
        sh_top = max(0, int(top - H * 0.13)); armm[:sh_top] = False
        if armm.sum() < 0.035 * A.sum(): print('arm too small, kept on the body', side); continue
        rr = np.where(armm.any(axis=1))[0]; cc = np.where(armm[rr.min()])[0]
        shoulder = [float(cc.mean() if side == 'L' else cc.mean()), float(rr.min() + (top - rr.min()) * 0.35)]
        yy2, xx2 = np.where(armm[armbot - 6:armbot + 1]); hand = [float(xx2.mean()) if len(xx2) else shoulder[0], float(armbot - 4)]
        parts['arm' + side] = armm; body &= ~armm
        meta['sh' + side] = shoulder; meta['hand' + side] = hand
# ---- back-fill behind polygon cuts: the hole inside the body silhouette gets the nearest body colour, blurred and darkened ----
Pbody = P.copy()
if cutholes.any() and not a.nofill:
    inside = ndimage.binary_fill_holes(ndimage.binary_closing(body, iterations=max(4, int(H * 0.02)))) & cutholes
    if inside.any():
        _, (iy, ix) = ndimage.distance_transform_edt(~body, return_indices=True)
        fill = P[iy, ix, :3].astype(np.float32)
        for c in range(3): fill[:, :, c] = ndimage.gaussian_filter(fill[:, :, c], 2.0)
        dist = ndimage.distance_transform_edt(inside); dk = 0.62 - 0.12 * np.clip(dist / 6, 0, 1)   # darker toward the middle of the hole
        Pbody[inside, :3] = (fill[inside] * dk[inside, None]).astype(np.uint8); Pbody[inside, 3] = 255
        body = body | inside; print('back-filled', int(inside.sum()), 'px behind cut parts')
parts['body'] = body
# ---- knees: split each leg into thigh (hip → knee) and shin (knee → sole), overlapping a little ----
ko = max(2, int(H * 0.012))
for side in ('L', 'R'):
    m = parts.pop('leg' + side); yb = int(np.where(m.any(axis=1))[0].max())          # this leg's sole (the far foot sits higher in 3/4 views)
    meta['foot' + side][1] = float(yb)
    kf = float(kvs(a.knee)[side]); ky = int(crotch + (kf * H - crotch if kf else 0.48 * (yb - crotch)))
    th = m.copy(); th[ky + ko + 1:] = False; sh_ = m.copy(); sh_[:ky - ko] = False
    cols = np.where(m[ky])[0]; kx = float(cols.mean()) if len(cols) else meta['hip' + side][0]
    # ankle: the foot is its own piece (kept level, rolls heel → toe); toe = the forward end of the sole
    ay_ = int(yb - (1 - a.ankle) * H); ft = sh_.copy(); ft[:ay_ - ko] = False; sh_[ay_ + ko + 1:] = False
    ca = np.where(m[ay_])[0]; ax_ = float(ca.mean()) if len(ca) else kx
    parts['thigh' + side] = th; meta['knee' + side] = [kx, float(ky)]
    if ft.sum() < 20:                                        # no foot below the ankle row (hidden by a robe / cape): shin to the sole
        sh_ = m.copy(); sh_[:ky - ko] = False; parts['shin' + side] = sh_; print('no foot piece', side); continue
    yy, xx = np.where(ft); sole = ft.copy(); sole[:int(yy.max() - max(3, (yy.max() - ay_) * 0.35))] = False; sy_, sx_ = np.where(sole)
    toe, heel = (float(sx_.min()), float(sx_.max())) if a.face == 'left' else (float(sx_.max()), float(sx_.min()))
    parts['shin' + side] = sh_; parts['foot' + side] = ft
    meta['ankle' + side] = [ax_, float(ay_)]; meta['toe' + side] = [toe, float(yy.max())]; meta['heel' + side] = [heel, float(yy.max())]
# elbows (optional): upper arm + forearm, split halfway between shoulder and hand
if a.elbow:
    for side in ('L', 'R'):
        if 'arm' + side not in parts: continue
        m = parts.pop('arm' + side); sh0, hd0 = meta['sh' + side], meta['hand' + side]; ey = int((sh0[1] + hd0[1]) / 2)
        cols = np.where(m[ey])[0]; ex = float(cols.mean()) if len(cols) else (sh0[0] + hd0[0]) / 2
        up = m.copy(); up[ey + ko + 1:] = False; fo = m.copy(); fo[:ey - ko] = False
        parts['uarm' + side] = up; parts['farm' + side] = fo; meta['elbow' + side] = [ex, float(ey)]
# head and top (for the joint trace): the topmost row and the centroid of the top 13 %
yy, xx = np.where(A); top = int(yy.min()); meta['top'] = [float(xx[yy == top].mean()), float(top)]
band = A.copy(); band[:top] = False; band[int(top + 0.13 * H):] = False; by_, bx_ = np.where(band); meta['head'] = [float(bx_.mean()), float(by_.mean())]
meta['face'] = a.face
os.makedirs(a.src, exist_ok=True)
import glob
for f in glob.glob(os.path.join(a.src, a.name + '__*.png')): os.remove(f)
for k, m in parts.items():
    # soft edges: keep the original alpha only where the hard mask (dilated 1 px) allows
    src = Pbody if k == 'body' else P
    mm = ndimage.binary_dilation(m, iterations=1); Q = src.copy(); Q[~mm] = 0; Q[mm & ~m, 3] = (Q[mm & ~m, 3] * 0.5).astype(np.uint8)
    Image.fromarray(Q).save(os.path.join(a.src, f'{a.name}__{k}.png'))
meta['parts'] = sorted(parts)
rp = 'live/rigs.js'; R = {}
if os.path.exists(rp):
    try: R = json.loads(re.sub(r'^window\.RIGS = |;\s*$', '', open(rp).read().strip()))
    except Exception: R = {}
R[a.name] = meta
open(rp, 'w').write('window.RIGS = ' + json.dumps(R) + ';\n')
print(a.name, json.dumps(meta))
