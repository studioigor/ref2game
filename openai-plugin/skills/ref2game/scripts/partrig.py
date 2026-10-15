#!/usr/bin/env python3
"""partrig.py — assemble a cut-out rig from a PART SHEET (body without limbs, ONE complete leg, ONE complete arm, drawn
separately on one image) into the same format rigcut.py writes: <name>__body, __thighL/__shinL/__footL, __thighR/..., __uarmL/
__farmL, __uarmR/..., all on one shared canvas in the rest pose, plus pivots merged into live/rigs.js (window.RIGS).

Every limb is drawn complete (the top of the thigh under the hem, the shoulder under the sleeve), so it swings from its real
joint with no seam and no hole; both legs (and both arms) use the same drawing, the far one is shaded by the scene.

    python3 <skill>/scripts/partrig.py NAME --sheet art/gen/NAME_parts.png [--height 320] [--order body,leg,arm] [--legs 0.3,0.7]
        [--hem 0.07] [--sh L=x,y --sh R=x,y] [--knee 0.5] [--ankle 0.8] [--elbow 0.47] [--hand 0.9] [--face left] [--preview out.png]

--legs: hip x as fractions of the body's width just above the hem; --hem: how far (fraction of the body height) the leg tops
reach up under the hem; --hipy: the hip row as a fraction of the body height instead (a cape or a coat below the hips);
--sh: shoulder pivots in body-sheet fractions (x, y of the body blob) when the stubs are not found.
A 4th part named 'weapon' (--order body,leg,arm,weapon; drawn pointing down, hilt at the top) is saved as <name>_weapon.png with
its length (rig px) and grip (fraction from the top: the middle of the handle) in the rig.
"""
import argparse, json, os, re
import numpy as np
from PIL import Image
from scipy import ndimage

ap = argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('--sheet', required=True); ap.add_argument('--height', type=int, default=320)
ap.add_argument('--order', default='body,leg,arm'); ap.add_argument('--legs', default='0.3,0.7'); ap.add_argument('--hem', type=float, default=0.07)
ap.add_argument('--sh', action='append', default=[]); ap.add_argument('--knee', type=float, default=0.5); ap.add_argument('--ankle', type=float, default=0.8)
ap.add_argument('--elbow', type=float, default=0.47); ap.add_argument('--hand', type=float, default=0.9); ap.add_argument('--face', default='left')
ap.add_argument('--src', default='art/gen'); ap.add_argument('--preview', default=''); ap.add_argument('--hipy', type=float, default=0); ap.add_argument('--grip', type=float, default=0)
a = ap.parse_args()

S = np.array(Image.open(a.sheet).convert('RGBA')); M = S[:, :, 3] > 60
lab, n = ndimage.label(ndimage.binary_closing(M, iterations=2))
sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1)); keep = list(np.argsort(-sizes)[:len(a.order.split(','))] + 1)
blobs = []
for l in keep:
    yy, xx = np.where(lab == l); blobs.append((xx.min(), (yy.min(), yy.max() + 1, xx.min(), xx.max() + 1), l))
blobs.sort(); names = a.order.split(',')
P = {}
for nm, (_, (y0, y1, x0, x1), l) in zip(names, blobs):
    m = (lab[y0:y1, x0:x1] == l); img = S[y0:y1, x0:x1].copy(); mm = ndimage.binary_dilation(m, iterations=1); img[~mm] = 0
    P[nm] = img
# close the openings of cut ends (the dark inside of a sleeve / trouser top, the body's sleeve stubs): dark pixels away from the
# silhouette edge, near the cut end, take the colour of the nearest lit pixel of the same part (blurred, slightly shaded)
def close_openings(img, region):
    al = img[:, :, 3] > 60; lum = img[:, :, :3].astype(np.float32) @ np.array([0.3, 0.55, 0.15], np.float32) / 255
    inner = ndimage.binary_erosion(al, iterations=3); dark = inner & (lum < 0.2) & region
    dark = ndimage.binary_opening(dark, iterations=1)
    lab2, n2 = ndimage.label(dark); out = img.copy(); filled = 0
    for i in range(1, n2 + 1):
        m = lab2 == i
        if m.sum() < 30: continue
        m = ndimage.binary_dilation(m, iterations=1) & al
        _, (iy, ix) = ndimage.distance_transform_edt(m | ~al, return_indices=True)
        lit = al & ~m; _, (jy, jx) = ndimage.distance_transform_edt(~lit, return_indices=True)
        col = img[jy, jx, :3].astype(np.float32)
        for c in range(3): col[:, :, c] = ndimage.gaussian_filter(col[:, :, c], 1.5)
        out[m, :3] = (col[m] * 0.82).astype(np.uint8); filled += int(m.sum())
    return out, filled
def top_band(img, f):
    r = np.zeros(img.shape[:2], bool); ys = np.where(img[:, :, 3].any(axis=1))[0]; r[ys.min():ys.min() + int(f * (ys.max() - ys.min()))] = True; return r
P['leg'], n1 = close_openings(P['leg'], top_band(P['leg'], 0.16)); P['arm'], n2 = close_openings(P['arm'], top_band(P['arm'], 0.2))
bb = P['body']; reg = np.zeros(bb.shape[:2], bool); reg[int(bb.shape[0] * 0.2):int(bb.shape[0] * 0.62)] = True
xs_ = np.where(bb[:, :, 3].any(axis=0))[0]; wB = xs_.max() - xs_.min(); side = np.zeros_like(reg); side[:, :xs_.min() + int(0.3 * wB)] = True; side[:, xs_.max() - int(0.3 * wB):] = True
P['body'], n3 = close_openings(bb, reg & side)
print('closed openings (px): leg', n1, 'arm', n2, 'body', n3)
body, leg, arm = P['body'], P['leg'], P['arm']
def rows(img, f):                                      # mean x of the opaque pixels in the row at fraction f of the height
    y = min(img.shape[0] - 1, max(0, int(f * img.shape[0]))); xs = np.where(img[y, :, 3] > 60)[0]
    return (float(xs.mean()) if len(xs) else img.shape[1] / 2, float(y))
def extent(img, f):
    y = min(img.shape[0] - 1, max(0, int(f * img.shape[0]))); xs = np.where(img[y, :, 3] > 60)[0]
    return (float(xs.min()), float(xs.max())) if len(xs) else (0.0, float(img.shape[1]))

# ---- measure (sheet px, each part's own frame) ----
bh, bw = body.shape[:2]; lh = leg.shape[0]; ah = arm.shape[0]
hf = a.hipy if a.hipy else 1 - a.hem; xl, xr = extent(body, hf - a.hem * 0.5); fl = [float(v) for v in a.legs.split(',')]
hipY = bh * hf; hips = {'L': (xl + fl[0] * (xr - xl), hipY), 'R': (xl + fl[1] * (xr - xl), hipY)}
sh = {}
if a.sh:
    for q in a.sh: s_, v = q.split('='); fx, fy = (float(t) for t in v.split(',')); sh[s_] = (fx * bw, fy * bh)
else:                                                 # the widest row in the upper torso: the sleeve stubs
    best = (0, 0.3)
    for f in np.linspace(0.22, 0.5, 30):
        e = extent(body, f); best = max(best, (e[1] - e[0], f))
    e = extent(body, best[1]); w = e[1] - e[0]; sh = {'L': (e[0] + 0.09 * w, best[1] * bh - 0.03 * bh), 'R': (e[1] - 0.09 * w, best[1] * bh - 0.03 * bh)}
LH = rows(leg, 0.03); LK = rows(leg, a.knee); LA = rows(leg, a.ankle); sole = float(np.where(leg[:, :, 3].any(axis=1))[0].max())
bot = leg[int(sole) - max(2, int(lh * 0.04)):int(sole) + 1, :, 3] > 60; bx = np.where(bot.any(axis=0))[0]
toe, heel = (float(bx.min()), float(bx.max())) if a.face == 'left' else (float(bx.max()), float(bx.min()))
AS = rows(arm, 0.05); AE = rows(arm, a.elbow); AHd = rows(arm, a.hand)

# ---- assemble the rest pose: legs straight down from the hips, arms hanging from the shoulders ----
place = {'body': (0.0, 0.0)}
for s_ in 'LR': place['leg' + s_] = (hips[s_][0] - LH[0], hips[s_][1] - LH[1]); place['arm' + s_] = (sh[s_][0] - AS[0], sh[s_][1] - AS[1])
imgs = {'body': body, 'legL': leg, 'legR': leg, 'armL': arm, 'armR': arm}
x0 = min(place[k][0] for k in place); y0 = min(place[k][1] for k in place)
x1 = max(place[k][0] + imgs[k].shape[1] for k in place); y1 = max(place[k][1] + imgs[k].shape[0] for k in place)
sc = a.height / (y1 - y0 + 4); W = int(np.ceil((x1 - x0 + 4) * sc)); H = a.height
T = lambda p, k: ((p[0] + place[k][0] - x0 + 2) * sc, (p[1] + place[k][1] - y0 + 2) * sc)   # part px → rig px
def canvas(img, k, keep=None):                        # the part (optionally only rows keep=(r0, r1) of its own frame) on the rig canvas
    im = Image.fromarray(img); w, h = img.shape[1], img.shape[0]
    if keep: m = np.zeros((h, w), bool); m[max(0, int(keep[0])):int(keep[1])] = True; arr = img.copy(); arr[~m] = 0; im = Image.fromarray(arr)
    im = im.resize((max(1, round(w * sc)), max(1, round(h * sc))), Image.LANCZOS)
    c = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ox, oy = T((0, 0), k); c.alpha_composite(im, (int(round(ox)), int(round(oy)))); return c
ko = max(2, int(lh * 0.02))
parts = {'body': canvas(body, 'body')}
meta = {'w': W, 'h': H, 'face': a.face}
for s_ in 'LR':
    k = 'leg' + s_
    parts['thigh' + s_] = canvas(leg, k, (0, LK[1] + ko)); parts['shin' + s_] = canvas(leg, k, (LK[1] - ko, LA[1] + ko)); parts['foot' + s_] = canvas(leg, k, (LA[1] - ko, lh))
    ka = 'arm' + s_
    parts['uarm' + s_] = canvas(arm, ka, (0, AE[1] + ko)); parts['farm' + s_] = canvas(arm, ka, (AE[1] - ko, ah))
    meta['hip' + s_] = list(T(LH, k)); meta['knee' + s_] = list(T(LK, k)); meta['ankle' + s_] = list(T(LA, k))
    meta['foot' + s_] = list(T((LA[0], sole), k)); meta['toe' + s_] = list(T((toe, sole), k)); meta['heel' + s_] = list(T((heel, sole), k))
    meta['sh' + s_] = list(T(AS, ka)); meta['elbow' + s_] = list(T(AE, ka)); meta['hand' + s_] = list(T(AHd, ka))
meta['crotch'] = int(round(T((0, hipY), 'body')[1])); meta['gap'] = (meta['hipL'][0] + meta['hipR'][0]) / 2
whole = Image.new('RGBA', (W, H), (0, 0, 0, 0))
for k in ['thighL', 'shinL', 'footL', 'uarmL', 'farmL', 'thighR', 'shinR', 'footR', 'body', 'uarmR', 'farmR']: whole.alpha_composite(parts[k])
A = np.array(whole)[:, :, 3] > 60; yy, xx = np.where(A); top = int(yy.min()); meta['top'] = [float(xx[yy == top].mean()), float(top)]
band = A.copy(); band[:top] = False; band[int(top + 0.13 * H):] = False; by_, bx_ = np.where(band); meta['head'] = [float(bx_.mean()), float(by_.mean())]
os.makedirs(a.src, exist_ok=True)
import glob
for f in glob.glob(os.path.join(a.src, a.name + '__*.png')): os.remove(f)
for k, im in parts.items(): im.save(os.path.join(a.src, f'{a.name}__{k}.png'))
whole.save(os.path.join(a.src, a.name + '.png'))
meta['parts'] = sorted(parts)
if 'weapon' in P:                                      # held item: its own sprite (hilt up), length and grip for the scene
    wpn = P['weapon']; wh = wpn.shape[0]; wa = wpn[:, :, 3] > 60
    widths = wa.sum(axis=1); gy = int(np.argmax(widths[:int(wh * 0.35)]))           # the crossguard: the widest row near the top
    meta['weaponLen'] = round(wh * sc, 1); meta['weaponGrip'] = a.grip or round(gy * 0.5 / wh, 3)   # --grip for spears, bows, hammers
    Image.fromarray(wpn).save(os.path.join(a.src, a.name + '_weapon.png'))
rp = 'live/rigs.js'; R = {}
if os.path.exists(rp):
    try: R = json.loads(re.sub(r'^window\.RIGS = |;\s*$', '', open(rp).read().strip()))
    except Exception: R = {}
R[a.name] = meta
open(rp, 'w').write('window.RIGS = ' + json.dumps(R) + ';\n')
if a.preview:
    from PIL import ImageDraw
    pv = Image.new('RGBA', (W * 2, H * 2), (60, 60, 60, 255)); pv.alpha_composite(whole.resize((W * 2, H * 2), Image.NEAREST)); d = ImageDraw.Draw(pv)
    for kk in ('hipL', 'hipR', 'kneeL', 'kneeR', 'ankleL', 'ankleR', 'toeL', 'toeR', 'heelL', 'heelR', 'shL', 'shR', 'elbowL', 'elbowR', 'handL', 'handR', 'head'):
        x, y = meta[kk]; d.ellipse([x * 2 - 4, y * 2 - 4, x * 2 + 4, y * 2 + 4], outline=(255, 0, 255), width=2)
    pv.save(a.preview)
print(a.name, json.dumps({k: (v if not isinstance(v, list) or len(v) != 2 else [round(v[0], 1), round(v[1], 1)]) for k, v in meta.items() if k != 'parts'}))
