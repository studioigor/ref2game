#!/usr/bin/env python3
"""compare.py - compare our rendered frame (OURS) against a reference still (REF).

Both inputs are images (PNG/JPG). OURS may have a different resolution: every region
is given in REF pixels and mapped onto OURS with a scale factor --k = ours_px / ref_px
(default: ours.width / ref.width) plus an optional --offset dx,dy (OURS px) when the
render is shifted. Metric images are computed in REF space (OURS resampled onto the
REF pixel grid with nearest neighbour); display crops are taken straight from OURS.

Common options (every subcommand): [--k K] [--offset DX,DY]

Subcommands (exact CLI)
  side REF OURS x0 y0 x1 y1 [--zoom 3] --out PNG
      Side-by-side crops of the same region, nearest neighbour, labelled rulers.
      python3 compare.py side ref.png ours.png 600 380 800 470 --zoom 3 --out cmp/side_hero.png

  grid REF OURS x0 y0 x1 y1 [--zoom 3] [--step 10] --out PNG
      The two crops stacked with the same labelled coordinate grid (trace positions).
      python3 compare.py grid ref.png ours.png 600 380 800 470 --zoom 3 --step 10 --out cmp/grid_hero.png

  lowfreq REF OURS x0 y0 x1 y1 [--blur 12] --out PNG
      Both blurred (texture drops out) + brightness ratio map: grey = equal,
      red = ours brighter, blue = ours darker (+-1 stop full scale).
      python3 compare.py lowfreq ref.png ours.png 0 0 1920 1080 --blur 16 --out cmp/lowfreq.png

  tones REF OURS --at x,y[,r] [--at ...] [--out PNG]
      Colours at the 10/60/92% luminance percentiles of small windows, ref vs ours.
      python3 compare.py tones ref.png ours.png --at 735,415,10 --at 250,640 --out cmp/tones.png

  diff REF OURS [--region x0,y0,x1,y1] [--thresh 8] --out PNG
      Share of differing pixels + heat image + biggest differing blobs (exact re-render checks).
      python3 compare.py diff ref.png ours.png --thresh 8 --out cmp/diff.png

  palette REF OURS [--colors 32] [--out PNG]
      How much of OURS sits close to the reference palette; palette drift; unused reference ramps.
      python3 compare.py palette ref.png ours.png --out cmp/palette.png

  report REF OURS --out DIR [--cells 8x6] [--blur 0] [--colors 32]
      side (whole), lowfreq (whole), palette, a 3x3 grid of side crops, and a ranked list
      of regions with the biggest low-frequency / edge-density / colour mismatch
      (where to look first) -> DIR/report.json + mismatch.png + worst_N.png.
      python3 compare.py report ref.png ours.png --out cmp/
"""

import argparse
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import study as S  # noqa: E402  (shared drawing / colour / palette helpers)


# ----------------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------------

class Pair:
    def __init__(self, ref_path, ours_path, k=None, offset=None):
        r, _ = S.load_image(ref_path)
        o, _ = S.load_image(ours_path)
        self.ref_path, self.ours_path = ref_path, ours_path
        self.ref = Image.fromarray(r)
        self.ours = Image.fromarray(o)
        self.k = float(k) if k else self.ours.width / self.ref.width
        self.off = offset or (0.0, 0.0)
        ky = self.ours.height / self.ref.height
        self.aspect_warning = None
        if not k and abs(ky - self.k) > 0.01 * self.k:
            self.aspect_warning = ('aspect ratios differ (k_x=%.4f, k_y=%.4f); using k=%.4f for both axes - pass --k/--offset to override'
                                   % (self.k, ky, self.k))
        self._ref_space = None

    def ours_box(self, x0, y0, x1, y1):
        k, (dx, dy) = self.k, self.off
        return (x0 * k + dx, y0 * k + dy, x1 * k + dx, y1 * k + dy)

    def ours_crop_display(self, x0, y0, x1, y1, w, h):
        """OURS region (given in REF px) rendered at w x h display pixels, nearest neighbour."""
        return self.ours.transform((int(w), int(h)), Image.EXTENT, self.ours_box(x0, y0, x1, y1), Image.NEAREST)

    def ours_in_ref_space(self):
        """OURS resampled onto the REF pixel grid (nearest), whole frame."""
        if self._ref_space is None:
            W, H = self.ref.size
            if abs(self.k - 1) < 1e-9 and self.off == (0.0, 0.0) and self.ours.size == self.ref.size:
                self._ref_space = self.ours
            else:
                self._ref_space = self.ours.transform((W, H), Image.EXTENT, self.ours_box(0, 0, W, H), Image.NEAREST)
        return self._ref_space

    def describe(self):
        return 'REF %s %dx%d | OURS %s %dx%d | k=%.4f offset=(%g,%g)' % (
            os.path.basename(self.ref_path), self.ref.width, self.ref.height, os.path.basename(self.ours_path),
            self.ours.width, self.ours.height, self.k, self.off[0], self.off[1])


def clamp_box(box, W, H):
    x0, y0, x1, y1 = box
    x0, x1 = sorted((int(round(x0)), int(round(x1))))
    y0, y1 = sorted((int(round(y0)), int(round(y1))))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 - x0 < 1 or y1 - y0 < 1:
        raise SystemExit('region %s is empty or outside the reference (%dx%d)' % (box, W, H))
    return x0, y0, x1, y1


def auto_zoom(w, h, zoom, max_w=2400, max_h=2400, panels=2, vertical=False):
    z = float(zoom)
    while z > 1 and ((w * z * (1 if vertical else panels)) > max_w or (h * z * (panels if vertical else 1)) > max_h):
        z = max(1, z - 1) if z > 1.5 else 1
        if z == 1:
            break
    return z


# ----------------------------------------------------------------------------
# side / grid
# ----------------------------------------------------------------------------

def make_side(P, box, zoom, grid=True, major=None, max_w=2400):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    z = auto_zoom(w, h, zoom, max_w=max_w)
    if z < 1:
        z = min(1.0, max_w / (2 * w))
    dw, dh = max(1, int(round(w * z))), max(1, int(round(h * z)))
    rz = P.ref.crop((x0, y0, x1, y1)).resize((dw, dh), Image.NEAREST if z >= 1 else Image.LANCZOS)
    oz = P.ours_crop_display(x0, y0, x1, y1, dw, dh)
    a = S.add_ruler(rz, x0, y0, z, major=major, title='REFERENCE  x %d-%d  y %d-%d' % (x0, x1, y0, y1), grid=grid)
    ob = P.ours_box(x0, y0, x1, y1)
    b = S.add_ruler(oz, x0, y0, z, major=major, title='OURS  (k=%.4f: ours x %.0f-%.0f y %.0f-%.0f)' % (P.k, ob[0], ob[2], ob[1], ob[3]), grid=grid)
    return S.hstack([a, b], gap=12), z


def make_grid(P, box, zoom, step):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    z = auto_zoom(w, h, zoom, panels=2, vertical=True, max_w=2000, max_h=2600)
    dw, dh = max(1, int(round(w * z))), max(1, int(round(h * z)))
    rz = P.ref.crop((x0, y0, x1, y1)).resize((dw, dh), Image.NEAREST if z >= 1 else Image.LANCZOS)
    oz = P.ours_crop_display(x0, y0, x1, y1, dw, dh)
    out = []
    for img, name in ((rz, 'REFERENCE'), (oz, 'OURS (k=%.4f)' % P.k)):
        img = img.convert('RGB')
        d = ImageDraw.Draw(img, 'RGBA')
        fnt = S.font(11)
        g = math.ceil(x0 / step) * step
        while g <= x1:
            px = (g - x0) * z
            d.line([(px, 0), (px, dh)], fill=(255, 255, 255, 120) if g % (step * 5) else (255, 230, 80, 200), width=1)
            g += step
        g = math.ceil(y0 / step) * step
        while g <= y1:
            py = (g - y0) * z
            d.line([(0, py), (dw, py)], fill=(255, 255, 255, 120) if g % (step * 5) else (255, 230, 80, 200), width=1)
            g += step
        # inline labels every 5 steps so positions can be read anywhere on the crop
        gy = math.ceil(y0 / (step * 5)) * step * 5
        while gy <= y1:
            gx = math.ceil(x0 / (step * 5)) * step * 5
            while gx <= x1:
                S.label(d, ((gx - x0) * z + 2, (gy - y0) * z + 2), '%d,%d' % (gx, gy), fnt, fg=(255, 240, 150), bg=(0, 0, 0, 170))
                gx += step * 5
            gy += step * 5
        maj = step * max(1, int(math.ceil(40 / (step * z))))
        out.append(S.add_ruler(img, x0, y0, z, major=maj, title='%s  x %d-%d  y %d-%d   grid %d px (yellow every %d)' % (name, x0, x1, y0, y1, step, step * 5), grid=False))
    return S.vstack(out, gap=14), z


# ----------------------------------------------------------------------------
# low frequency
# ----------------------------------------------------------------------------

def lowfreq_maps(P, box, blur):
    x0, y0, x1, y1 = box
    r = np.asarray(P.ref.crop(box)).astype(np.float32)
    o = np.asarray(P.ours_in_ref_space().crop(box)).astype(np.float32)
    Yr = S.rgb_to_Y(r)
    Yo = S.rgb_to_Y(o)
    sig = max(0.5, float(blur))
    Yrb = ndi.gaussian_filter(Yr, sig)
    Yob = ndi.gaussian_filter(Yo, sig)
    eps = 0.003
    lr = np.log2((Yob + eps) / (Yrb + eps))
    rb = np.stack([ndi.gaussian_filter(r[..., c], sig) for c in range(3)], -1)
    ob = np.stack([ndi.gaussian_filter(o[..., c], sig) for c in range(3)], -1)
    return r, o, rb, ob, lr, Yrb, Yob


def lowfreq_stats(lr, rb, ob):
    lab_r = S.rgb_to_lab(rb)
    lab_o = S.rgb_to_lab(ob)
    dE = np.sqrt(((lab_r - lab_o) ** 2).sum(-1))
    return {'mean_log2_ratio': round(float(lr.mean()), 3),
            'mean_abs_log2_ratio': round(float(np.abs(lr).mean()), 3),
            'ours_brighter_gt_0.3stop_share': round(float((lr > 0.3).mean()), 4),
            'ours_darker_gt_0.3stop_share': round(float((lr < -0.3).mean()), 4),
            'mean_deltaE_blurred': round(float(dE.mean()), 2),
            'mean_L_ref': round(float(lab_r[..., 0].mean()), 2), 'mean_L_ours': round(float(lab_o[..., 0].mean()), 2)}


def make_lowfreq(P, box, blur, panel_w=560):
    x0, y0, x1, y1 = box
    r, o, rb, ob, lr, Yrb, Yob = lowfreq_maps(P, box, blur)
    st = lowfreq_stats(lr, rb, ob)
    w, h = x1 - x0, y1 - y0
    dw, dh, s = S.fit_size(w, h, panel_w, 700)
    ps = []
    for arr, ttl in ((rb, 'REFERENCE blurred (sigma %g px)' % blur), (ob, 'OURS blurred')):
        ps.append(S.title_panel(S.add_ruler(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).resize((dw, dh), Image.BILINEAR), x0, y0, s, grid=False), ttl, size=13))
    rm = Image.fromarray(S.diverge_cmap(lr)).resize((dw, dh), Image.BILINEAR)
    # contour hints: label 4x3 cells with their mean ratio in stops
    d = ImageDraw.Draw(rm)
    for ry in range(3):
        for rx in range(4):
            sub = lr[ry * h // 3:(ry + 1) * h // 3, rx * w // 4:(rx + 1) * w // 4]
            if sub.size:
                v = float(sub.mean())
                S.label(d, ((rx + 0.5) * dw / 4, (ry + 0.5) * dh / 3), '%+.2f' % v, S.font(13), bg=(0, 0, 0), anchor='mm')
    ps.append(S.title_panel(S.add_ruler(rm, x0, y0, s, grid=False), 'ratio ours/ref in stops (cell means)', size=13))
    top = S.hstack(ps, gap=10)
    cb = S.colorbar(min(top.width, 900), [(0, '-1 stop (ours x0.5, darker)'), (0.5, 'equal'), (1, '+1 stop (ours x2, brighter)')],
                    lambda v: S.diverge_cmap(v * 2 - 1), title='brightness ratio')
    txt = ('mean ratio %+.2f stops | mean |ratio| %.2f | ours brighter >0.3 stop on %.0f%%, darker on %.0f%% | mean dE (blurred) %.1f | L* ref %.1f ours %.1f'
           % (st['mean_log2_ratio'], st['mean_abs_log2_ratio'], 100 * st['ours_brighter_gt_0.3stop_share'], 100 * st['ours_darker_gt_0.3stop_share'],
              st['mean_deltaE_blurred'], st['mean_L_ref'], st['mean_L_ours']))
    img = S.title_panel(S.vstack([top, cb], gap=6), 'LOW FREQUENCY  x %d-%d y %d-%d  |  %s' % (x0, x1, y0, y1, txt), size=13)
    return img, st


# ----------------------------------------------------------------------------
# tones
# ----------------------------------------------------------------------------

def tone_colours(arr, pcts=(10, 60, 92)):
    px = arr.reshape(-1, 3).astype(np.float32)
    L = S.rgb_to_Lstar(px)
    out = []
    for p in pcts:
        lo, hi = np.percentile(L, max(0, p - 4)), np.percentile(L, min(100, p + 4))
        sel = (L >= lo) & (L <= hi)
        c = np.median(px[sel], 0) if sel.any() else px[np.argmin(np.abs(L - np.percentile(L, p)))]
        out.append(c)
    return out


def cmd_tones(a):
    P = Pair(a.ref, a.ours, a.k, parse_off(a.offset))
    W, H = P.ref.size
    O = P.ours_in_ref_space()
    rows = []
    for spec in a.at:
        v = [float(t) for t in spec.split(',')]
        x, y = v[0], v[1]
        r = v[2] if len(v) > 2 else 8
        box = clamp_box((x - r, y - r, x + r + 1, y + r + 1), W, H)
        rc = tone_colours(np.asarray(P.ref.crop(box)))
        oc = tone_colours(np.asarray(O.crop(box)))
        ent = {'at': [x, y, r], 'tones': []}
        for p, c1, c2 in zip((10, 60, 92), rc, oc):
            l1, l2 = S.rgb_to_lab(np.array(c1, np.float32)), S.rgb_to_lab(np.array(c2, np.float32))
            dE = float(np.sqrt(((l1 - l2) ** 2).sum()))
            ent['tones'].append({'pct': p, 'ref': S.hexc(c1), 'ours': S.hexc(c2), 'dL': round(float(l2[0] - l1[0]), 1), 'dE': round(dE, 1),
                                 'ref_hue': S.hue_name(c1), 'ours_hue': S.hue_name(c2)})
        rows.append(ent)
    print('TONES  ' + P.describe())
    if P.aspect_warning:
        print('  warning: ' + P.aspect_warning)
    for e in rows:
        x, y, r = e['at']
        parts = ['p%d ref %s ours %s dL*%+5.1f dE %4.1f' % (t['pct'], t['ref'], t['ours'], t['dL'], t['dE']) for t in e['tones']]
        print('  (%4d,%4d r%-3d) ' % (x, y, r) + ' | '.join(parts))
    if a.out:
        sw, rh = 60, 34
        img = Image.new('RGB', (190 + 3 * (2 * sw + 70), 30 + len(rows) * (rh + 20)), (22, 22, 26))
        d = ImageDraw.Draw(img)
        d.text((8, 6), 'tones at 10 / 60 / 92 %% luminance percentiles: left swatch = REF, right = OURS', font=S.font(13), fill=(235, 235, 235))
        for i, e in enumerate(rows):
            y = 30 + i * (rh + 20)
            d.text((8, y + 8), '(%d,%d) r%d' % tuple(int(v) for v in e['at']), font=S.font(13), fill=(230, 230, 230))
            for j, t in enumerate(e['tones']):
                x = 190 + j * (2 * sw + 70)
                c1 = tuple(int(t['ref'][k:k + 2], 16) for k in (1, 3, 5))
                c2 = tuple(int(t['ours'][k:k + 2], 16) for k in (1, 3, 5))
                d.rectangle([x, y, x + sw, y + rh], fill=c1, outline=(90, 90, 90))
                d.rectangle([x + sw, y, x + 2 * sw, y + rh], fill=c2, outline=(90, 90, 90))
                d.text((x, y + rh + 2), 'p%d dL%+.0f dE%.0f' % (t['pct'], t['dL'], t['dE']), font=S.font(11), fill=(190, 190, 190))
        S.ensure_dir(os.path.dirname(os.path.abspath(a.out)))
        img.save(a.out)
        print('  -> ' + a.out)
    return rows


# ----------------------------------------------------------------------------
# diff
# ----------------------------------------------------------------------------

def cmd_diff(a):
    P = Pair(a.ref, a.ours, a.k, parse_off(a.offset))
    W, H = P.ref.size
    box = clamp_box(parse_box(a.region), W, H) if a.region else (0, 0, W, H)
    r = np.asarray(P.ref.crop(box)).astype(np.int16)
    o = np.asarray(P.ours_in_ref_space().crop(box)).astype(np.int16)
    dd = np.abs(r - o).max(2)
    chg = dd > a.thresh
    share = float(chg.mean())
    mse = float(((r - o).astype(np.float32) ** 2).mean())
    psnr = 99.0 if mse == 0 else 10 * math.log10(255 ** 2 / mse)
    lab, nl = ndi.label(ndi.binary_dilation(chg, iterations=2))
    objs = ndi.find_objects(lab)
    sizes = ndi.sum(chg, lab, range(1, nl + 1)) if nl else []
    blobs = sorted([(float(sizes[i]), objs[i]) for i in range(nl)], key=lambda t: -t[0])[:10]
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    grey = S.luma8(r.astype(np.float32)) * 0.35
    heat = S.heat_cmap(np.clip(dd / max(1.0, float(np.percentile(dd[chg], 99)) if chg.any() else 1.0), 0, 1)).astype(np.float32)
    img = np.where(chg[..., None], heat, grey[..., None].repeat(3, -1)).astype(np.uint8)
    dw, dh, s = S.fit_size(w, h, 1400, 1400)
    if s > 1:
        s = max(1, int(s))
        dw, dh = w * s, h * s
    im = Image.fromarray(img).resize((dw, dh), Image.NEAREST if s >= 1 else Image.BOX)
    d = ImageDraw.Draw(im)
    for i, (sz, ob) in enumerate(blobs):
        bx0, by0, bx1, by1 = ob[1].start * s, ob[0].start * s, ob[1].stop * s, ob[0].stop * s
        d.rectangle([bx0, by0, bx1, by1], outline=(0, 255, 255))
        S.label(d, (bx0, by1 + 1), '#%d %d,%d' % (i + 1, ob[1].start + x0, ob[0].start + y0), S.font(11), bg=(0, 0, 0))
    im = S.add_ruler(im, x0, y0, s, grid=False, title='DIFF max-channel > %d: %.3f%% of pixels differ, PSNR %.1f dB  (%s)' % (a.thresh, 100 * share, psnr, P.describe()))
    S.ensure_dir(os.path.dirname(os.path.abspath(a.out)))
    im.save(a.out)
    print('DIFF  ' + P.describe())
    if P.aspect_warning:
        print('  warning: ' + P.aspect_warning)
    print('  region %d,%d-%d,%d: %.3f%% pixels differ (> %d), mean abs %.2f, PSNR %.1f dB, %d blobs' % (x0, y0, x1, y1, 100 * share, a.thresh, float(dd.mean()), psnr, nl))
    for i, (sz, ob) in enumerate(blobs[:8]):
        print('    #%d x %d-%d y %d-%d: %d px' % (i + 1, ob[1].start + x0, ob[1].stop + x0, ob[0].start + y0, ob[0].stop + y0, sz))
    print('  -> ' + a.out)


# ----------------------------------------------------------------------------
# palette
# ----------------------------------------------------------------------------

def sample_px(img, n=200000, seed=0):
    a = np.asarray(img).reshape(-1, 3)
    if len(a) > n:
        a = a[np.random.default_rng(seed).choice(len(a), n, replace=False)]
    return a


def palette_compare(P, k=32, drift_dE=12.0):
    rref = np.asarray(P.ref)
    cols_r, sh_r, _, meth_r, _ = S.extract_palette(rref, None, k=k)
    ramps, _, _, _ = S.group_ramps(cols_r, sh_r)
    cols_o, sh_o, _, meth_o, _ = S.extract_palette(np.asarray(P.ours), None, k=k)
    lab_r = S.rgb_to_lab(cols_r.astype(np.float32))
    po = sample_px(P.ours)
    lab_po = S.rgb_to_lab(po.astype(np.float32))
    nn, dist = S.assign_nearest(lab_po, lab_r)
    within = {str(t): round(float((dist <= t).mean()), 4) for t in (5, 10, 20)}
    use = np.bincount(nn[dist <= drift_dE], minlength=len(cols_r)) / max(1, len(po))
    # our palette colours far from every reference colour
    lab_o = S.rgb_to_lab(cols_o.astype(np.float32))
    _, d_o = S.assign_nearest(lab_o, lab_r)
    drift = [{'hex': S.hexc(cols_o[i]), 'share': round(float(sh_o[i]), 4), 'nearest_ref_dE': round(float(d_o[i]), 1), 'hue': S.hue_name(cols_o[i])}
             for i in np.argsort(-sh_o) if d_o[i] > drift_dE]
    ramp_use = []
    for rp in ramps:
        rs = float(sum(sh_r[i] for i in rp['members']))
        us = float(sum(use[i] for i in rp['members']))
        ramp_use.append({'id': rp['id'], 'name': rp['name'], 'ref_share': round(rs, 4), 'ours_share': round(us, 4),
                         'dark': rp['dark'], 'light': rp['light'], 'members': [S.hexc(cols_r[i]) for i in rp['members']],
                         'unused': bool(rs >= 0.01 and us < 0.1 * rs)})
    unused_cols = [{'hex': S.hexc(cols_r[i]), 'ref_share': round(float(sh_r[i]), 4), 'ours_share': round(float(use[i]), 4)}
                   for i in np.argsort(-sh_r) if sh_r[i] >= 0.01 and use[i] < 0.1 * sh_r[i]]
    return {'ref_palette_method': meth_r, 'ours_palette_method': meth_o, 'ours_pixels_within_dE': within,
            'ours_far_from_ref_share': round(float((dist > drift_dE).mean()), 4), 'drift_colours': drift,
            'ramps': ramp_use, 'unused_ref_colours': unused_cols,
            '_cols_r': cols_r, '_sh_r': sh_r, '_use': use, '_ramps': ramps, '_cols_o': cols_o, '_sh_o': sh_o, '_d_o': d_o}


def draw_palette_compare(pc, path, drift_dE=12.0):
    cols_r, sh_r, use, ramps = pc['_cols_r'], pc['_sh_r'], pc['_use'], pc['_ramps']
    sw, shh = 62, 34
    maxlen = max([len(r['members']) for r in ramps] + [6])
    W = 220 + maxlen * (sw + 6) + 20
    drift = pc['drift_colours'][:maxlen]
    H = 60 + len(ramps) * (shh + 50) + 120
    img = Image.new('RGB', (max(W, 900), H), (22, 22, 26))
    d = ImageDraw.Draw(img)
    w = pc['ours_pixels_within_dE']
    d.text((8, 6), 'PALETTE: reference ramps with share in REF (grey bar) vs OURS (cyan bar); ours within dE 5/10/20 of the ref palette: %.0f%% / %.0f%% / %.0f%%'
           % (100 * w['5'], 100 * w['10'], 100 * w['20']), font=S.font(13), fill=(235, 235, 235))
    y = 34
    for rp, ru in zip(ramps, pc['ramps']):
        d.text((8, y + 4), 'R%d %s' % (rp['id'], rp['name']), font=S.font(13), fill=(240, 240, 240))
        d.text((8, y + 22), 'ref %.1f%%  ours %.1f%%%s' % (100 * ru['ref_share'], 100 * ru['ours_share'], '  UNUSED' if ru['unused'] else ''),
               font=S.font(12), fill=(255, 120, 100) if ru['unused'] else (170, 170, 170))
        x = 220
        mx = max(1e-6, max(max(sh_r), max(use)))
        for i in rp['members']:
            c = tuple(int(v) for v in cols_r[i])
            d.rectangle([x, y, x + sw, y + shh], fill=c, outline=(70, 70, 70))
            bw1 = sw * min(1, sh_r[i] / mx * 3)
            bw2 = sw * min(1, use[i] / mx * 3)
            d.rectangle([x, y + shh + 3, x + bw1, y + shh + 8], fill=(150, 150, 150))
            d.rectangle([x, y + shh + 10, x + bw2, y + shh + 15], fill=(60, 220, 230))
            d.text((x, y + shh + 18), S.hexc(c), font=S.font(10), fill=(200, 200, 200))
            x += sw + 6
        y += shh + 50
    d.text((8, y + 6), 'OURS colours far from every ref colour (dE > %g), largest first:' % drift_dE, font=S.font(13), fill=(240, 240, 240))
    y += 28
    x = 8
    for dc in drift:
        c = tuple(int(dc['hex'][k:k + 2], 16) for k in (1, 3, 5))
        d.rectangle([x, y, x + sw, y + shh], fill=c, outline=(200, 80, 80))
        d.text((x, y + shh + 3), '%s %.1f%%' % (dc['hex'], 100 * dc['share']), font=S.font(10), fill=(200, 200, 200))
        d.text((x, y + shh + 16), 'dE %.0f' % dc['nearest_ref_dE'], font=S.font(10), fill=(255, 140, 120))
        x += sw + 30
    if not drift:
        d.text((8, y + 4), 'none', font=S.font(12), fill=(160, 220, 160))
    img.save(path)


def print_palette(pc):
    w = pc['ours_pixels_within_dE']
    print('  ours pixels within dE 5/10/20 of the ref palette: %.1f%% / %.1f%% / %.1f%%' % (100 * w['5'], 100 * w['10'], 100 * w['20']))
    if pc['drift_colours']:
        print('  drift (our colours far from any ref colour): ' + ', '.join('%s %.1f%% (dE %.0f, %s)' % (d['hex'], 100 * d['share'], d['nearest_ref_dE'], d['hue']) for d in pc['drift_colours'][:8]))
    else:
        print('  drift: none (every OURS palette colour is near a REF colour)')
    for r in pc['ramps']:
        print('    ramp R%d %-8s ref %5.1f%%  ours %5.1f%%%s' % (r['id'], r['name'], 100 * r['ref_share'], 100 * r['ours_share'], '   <- unused by OURS' if r['unused'] else ''))
    if pc['unused_ref_colours']:
        print('  unused ref colours (>=1% of ref): ' + ', '.join('%s %.1f%%' % (c['hex'], 100 * c['ref_share']) for c in pc['unused_ref_colours'][:10]))


def public(pc):
    return {k: v for k, v in pc.items() if not k.startswith('_')}


# ----------------------------------------------------------------------------
# report
# ----------------------------------------------------------------------------

def cell_metrics(P, cells, blur):
    W, H = P.ref.size
    r = np.asarray(P.ref).astype(np.float32)
    o = np.asarray(P.ours_in_ref_space()).astype(np.float32)
    sig = blur
    Yr, Yo = S.rgb_to_Y(r), S.rgb_to_Y(o)
    lr = np.log2((ndi.gaussian_filter(Yo, sig) + 0.003) / (ndi.gaussian_filter(Yr, sig) + 0.003))
    Lr, Lo = S.rgb_to_Lstar(r), S.rgb_to_Lstar(o)
    er = np.hypot(ndi.sobel(Lr, 1), ndi.sobel(Lr, 0)) / 8 > 6
    eo = np.hypot(ndi.sobel(Lo, 1), ndi.sobel(Lo, 0)) / 8 > 6
    cx, cy = cells
    out = []
    for j in range(cy):
        for i in range(cx):
            x0, x1 = i * W // cx, (i + 1) * W // cx
            y0, y1 = j * H // cy, (j + 1) * H // cy
            sl = (slice(y0, y1), slice(x0, x1))
            lf = float(lr[sl].mean())
            lfa = float(np.abs(lr[sl]).mean())
            edr, edo = float(er[sl].mean()), float(eo[sl].mean())
            el = math.log2((edo + 0.01) / (edr + 0.01))
            mr = S.rgb_to_lab(r[sl].reshape(-1, 3).mean(0))
            mo = S.rgb_to_lab(o[sl].reshape(-1, 3).mean(0))
            dE = float(np.sqrt(((mr - mo) ** 2).sum()))
            score = lfa + 0.5 * abs(el) + dE / 30.0
            why = []
            if abs(lf) >= 0.15:
                why.append('ours %s by %.2f stops (x%.2f)' % ('brighter' if lf > 0 else 'darker', abs(lf), 2 ** lf))
            elif lfa >= 0.3:
                why.append('light distribution differs (mean |%.2f| stops, net %+.2f)' % (lfa, lf))
            if abs(el) >= 0.35:
                why.append('edge detail x%.2f (%s)' % (2 ** el, 'busier' if el > 0 else 'flatter / less texture'))
            if dE >= 8:
                why.append('mean colour off dE %.0f (ref %s -> ours %s)' % (dE, S.hexc(r[sl].reshape(-1, 3).mean(0)), S.hexc(o[sl].reshape(-1, 3).mean(0))))
            out.append({'row': j, 'col': i, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1, 'score': round(score, 3),
                        'lowfreq_log2': round(lf, 3), 'lowfreq_abs_log2': round(lfa, 3), 'edge_density_ref': round(edr, 4),
                        'edge_density_ours': round(edo, 4), 'edge_log2_ratio': round(el, 3), 'mean_dE': round(dE, 2),
                        'why': '; '.join(why) or 'minor'})
    return sorted(out, key=lambda c: -c['score'])


def cmd_report(a):
    t0 = time.time()
    P = Pair(a.ref, a.ours, a.k, parse_off(a.offset))
    out = S.ensure_dir(a.out)
    W, H = P.ref.size
    blur = a.blur or max(6.0, round(math.hypot(W, H) / 100.0, 1))
    files = []
    # side, whole image (each panel <= 800 px wide)
    side, z = make_side(P, (0, 0, W, H), 800 / W, grid=False, max_w=1700)
    p = os.path.join(out, 'side_full.png')
    side.save(p)
    files.append('side_full.png')
    # lowfreq whole
    lf_img, lf_stats = make_lowfreq(P, (0, 0, W, H), blur, panel_w=540)
    lf_img.save(os.path.join(out, 'lowfreq_full.png'))
    files.append('lowfreq_full.png')
    # palette
    pc = palette_compare(P, k=a.colors)
    draw_palette_compare(pc, os.path.join(out, 'palette.png'))
    files.append('palette.png')
    # 3x3 side crops
    crops = []
    for j in range(3):
        for i in range(3):
            box = (i * W // 3, j * H // 3, (i + 1) * W // 3, (j + 1) * H // 3)
            zz = max(1, int(round(700 / (box[2] - box[0]))))
            img, _ = make_side(P, box, zz)
            pth = os.path.join(out, 'side_r%d_c%d.png' % (j, i))
            img.save(pth)
            crops.append({'row': j, 'col': i, 'box': list(box), 'file': os.path.basename(pth)})
            files.append(os.path.basename(pth))
    # mismatch ranking
    cx, cy = parse_grid(a.cells)
    ranked = cell_metrics(P, (cx, cy), blur)
    mm = P.ref.convert('RGB').copy()
    dw, dh, s = S.fit_size(W, H, 1400)
    mm = mm.resize((dw, dh), Image.LANCZOS if s < 1 else Image.NEAREST)
    d = ImageDraw.Draw(mm, 'RGBA')
    top = ranked[:8]
    smax = max(1e-6, ranked[0]['score'])
    for c in ranked:
        a_ = int(150 * c['score'] / smax)
        d.rectangle([c['x0'] * s, c['y0'] * s, c['x1'] * s, c['y1'] * s], fill=(255, 40, 40, max(0, a_ - 60)) if c in top else None,
                    outline=(255, 255, 255, 50))
    for n, c in enumerate(top):
        d.rectangle([c['x0'] * s, c['y0'] * s, c['x1'] * s, c['y1'] * s], outline=(255, 230, 60, 255), width=2)
        S.label(d, (c['x0'] * s + 4, c['y0'] * s + 4), '#%d  %.2f' % (n + 1, c['score']), S.font(15), fg=(255, 240, 120), bg=(0, 0, 0, 200))
    mm = S.add_ruler(mm, 0, 0, s, grid=False, title='where to look first: top %d mismatch cells (%dx%d grid; score = |lowfreq stops| + 0.5|edge log2| + dE/30)' % (len(top), cx, cy))
    mm.save(os.path.join(out, 'mismatch.png'))
    files.append('mismatch.png')
    worst = []
    for n, c in enumerate(ranked[:3]):
        pad_x, pad_y = (c['x1'] - c['x0']) // 4, (c['y1'] - c['y0']) // 4
        box = clamp_box((c['x0'] - pad_x, c['y0'] - pad_y, c['x1'] + pad_x, c['y1'] + pad_y), W, H)
        zz = max(1, int(round(650 / (box[2] - box[0]))))
        img, _ = make_side(P, box, zz)
        img = S.title_panel(img, '#%d  %s' % (n + 1, c['why']), size=14)
        pth = os.path.join(out, 'worst_%d.png' % (n + 1))
        img.save(pth)
        worst.append(os.path.basename(pth))
        files.append(os.path.basename(pth))
    rep = {'ref': os.path.abspath(a.ref), 'ours': os.path.abspath(a.ours), 'k': P.k, 'offset': list(P.off),
           'aspect_warning': P.aspect_warning, 'blur': blur, 'lowfreq_whole': lf_stats, 'palette': public(pc),
           'cells': {'cols': cx, 'rows': cy, 'ranked': ranked}, 'side_crops_3x3': crops, 'worst_crops': worst,
           'files': files, 'seconds': round(time.time() - t0, 2)}
    with open(os.path.join(out, 'report.json'), 'w') as f:
        json.dump(S.jsonable(rep), f, indent=1)
    print('REPORT  ' + P.describe())
    if P.aspect_warning:
        print('  warning: ' + P.aspect_warning)
    print('  low freq   : mean %+.2f stops (|%.2f|), ours brighter >0.3 stop on %.0f%%, darker on %.0f%%, blurred dE %.1f, L* ref %.1f / ours %.1f'
          % (lf_stats['mean_log2_ratio'], lf_stats['mean_abs_log2_ratio'], 100 * lf_stats['ours_brighter_gt_0.3stop_share'],
             100 * lf_stats['ours_darker_gt_0.3stop_share'], lf_stats['mean_deltaE_blurred'], lf_stats['mean_L_ref'], lf_stats['mean_L_ours']))
    print('  palette    :')
    print_palette(pc)
    print('  where to look first (%dx%d cells, ref px):' % (cx, cy))
    for n, c in enumerate(ranked[:8]):
        print('    #%d r%dc%d x %d-%d y %d-%d  score %.2f: %s' % (n + 1, c['row'], c['col'], c['x0'], c['x1'], c['y0'], c['y1'], c['score'], c['why']))
    print('  files      : %s' % ', '.join(files))
    print('  json       : %s  (%.1fs)' % (os.path.join(out, 'report.json'), rep['seconds']))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def parse_off(s):
    if not s:
        return (0.0, 0.0)
    v = [float(t) for t in s.split(',')]
    return (v[0], v[1])


def parse_box(s):
    v = [float(t) for t in s.replace(' ', '').split(',')]
    if len(v) != 4:
        raise SystemExit('region must be x0,y0,x1,y1')
    return tuple(v)


def parse_grid(s):
    a, b = s.lower().split('x')
    return int(a), int(b)


def add_common(p, region=False):
    p.add_argument('ref')
    p.add_argument('ours')
    if region:
        for n in ('x0', 'y0', 'x1', 'y1'):
            p.add_argument(n, type=float)
    p.add_argument('--k', type=float, default=None, help='ours px per ref px (default ours.width/ref.width)')
    p.add_argument('--offset', default=None, help='dx,dy in OURS px added after scaling')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Compare a rendered frame against a reference. See the module docstring for examples.')
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('side', help='side-by-side crops')
    add_common(p, True)
    p.add_argument('--zoom', type=float, default=3)
    p.add_argument('--out', required=True)
    p = sp.add_parser('grid', help='stacked crops with the same labelled grid')
    add_common(p, True)
    p.add_argument('--zoom', type=float, default=3)
    p.add_argument('--step', type=int, default=10)
    p.add_argument('--out', required=True)
    p = sp.add_parser('lowfreq', help='blurred comparison + brightness ratio map')
    add_common(p, True)
    p.add_argument('--blur', type=float, default=12)
    p.add_argument('--out', required=True)
    p = sp.add_parser('tones', help='luminance-percentile colours at points')
    add_common(p)
    p.add_argument('--at', action='append', required=True, help='x,y[,r] in ref px (default r=8); repeatable')
    p.add_argument('--out', default=None)
    p = sp.add_parser('diff', help='pixel difference share + heat image')
    add_common(p)
    p.add_argument('--region', default=None, help='x0,y0,x1,y1 in ref px')
    p.add_argument('--thresh', type=int, default=8)
    p.add_argument('--out', required=True)
    p = sp.add_parser('palette', help='palette closeness / drift / unused ramps')
    add_common(p)
    p.add_argument('--colors', type=int, default=32)
    p.add_argument('--out', default=None)
    p = sp.add_parser('report', help='everything a visual critic needs, ranked')
    add_common(p)
    p.add_argument('--out', required=True)
    p.add_argument('--cells', default='8x6')
    p.add_argument('--blur', type=float, default=0, help='low-frequency blur sigma in ref px (default ~1%% of the diagonal)')
    p.add_argument('--colors', type=int, default=32)
    a = ap.parse_args(argv)
    if a.cmd in ('side', 'grid', 'lowfreq'):
        P = Pair(a.ref, a.ours, a.k, parse_off(a.offset))
        box = clamp_box((a.x0, a.y0, a.x1, a.y1), *P.ref.size)
        S.ensure_dir(os.path.dirname(os.path.abspath(a.out)))
        if a.cmd == 'side':
            img, z = make_side(P, box, a.zoom)
            img.save(a.out)
            print('SIDE  %s  box %d,%d-%d,%d  zoom %g -> %s (%dx%d)' % (P.describe(), *box, z, a.out, img.width, img.height))
        elif a.cmd == 'grid':
            img, z = make_grid(P, box, a.zoom, a.step)
            img.save(a.out)
            print('GRID  %s  box %d,%d-%d,%d  zoom %g step %d -> %s (%dx%d)' % (P.describe(), *box, z, a.step, a.out, img.width, img.height))
        else:
            img, st = make_lowfreq(P, box, a.blur)
            img.save(a.out)
            print('LOWFREQ  %s  box %d,%d-%d,%d  blur %g' % (P.describe(), *box, a.blur))
            print('  mean ratio %+.2f stops (|%.2f|); ours brighter >0.3 stop on %.1f%%, darker on %.1f%%; blurred dE %.1f; L* ref %.1f ours %.1f -> %s'
                  % (st['mean_log2_ratio'], st['mean_abs_log2_ratio'], 100 * st['ours_brighter_gt_0.3stop_share'], 100 * st['ours_darker_gt_0.3stop_share'],
                     st['mean_deltaE_blurred'], st['mean_L_ref'], st['mean_L_ours'], a.out))
        if P.aspect_warning:
            print('  warning: ' + P.aspect_warning)
    elif a.cmd == 'tones':
        cmd_tones(a)
    elif a.cmd == 'diff':
        cmd_diff(a)
    elif a.cmd == 'palette':
        P = Pair(a.ref, a.ours, a.k, parse_off(a.offset))
        pc = palette_compare(P, k=a.colors)
        print('PALETTE  ' + P.describe())
        print('  ref palette: %s | ours palette: %s' % (pc['ref_palette_method'], pc['ours_palette_method']))
        print_palette(pc)
        if a.out:
            S.ensure_dir(os.path.dirname(os.path.abspath(a.out)))
            draw_palette_compare(pc, a.out)
            print('  -> ' + a.out)
    elif a.cmd == 'report':
        cmd_report(a)


if __name__ == '__main__':
    main()
