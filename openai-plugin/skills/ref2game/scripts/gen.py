#!/usr/bin/env python3
"""Prepare/import built-in imagegen output; offline alpha/pixel utilities.

Run from a ref2game project root. This script never generates an image and has
no network, provider, subprocess or manual-drop backend. Codex calls imagegen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np
from PIL import Image


class GenError(Exception):
    """Invalid local input or output from built-in imagegen."""


def parse_hex(s):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(s).strip())
    if not m:
        raise GenError(f"bad key colour {s!r}: use RRGGBB, e.g. ff00ff")
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]], np.float32)
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]], np.float32)


def oklab(rgb):
    """sRGB floats in [0,1] (..., 3) -> OKLab (..., 3)."""
    rgb = np.asarray(rgb, np.float32)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return np.cbrt(lin @ _M1.T) @ _M2.T


def _kdist(lab, labk):
    d = lab - labk
    return np.sqrt((0.6 * d[..., 0]) ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)


def _shift(a, dy, dx, fill=0):
    """out[y+dy, x+dx] = a[y, x]; uncovered cells = fill."""
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = a[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _dilate(mask, r):
    m = mask.copy()
    for _ in range(r):
        m = m | _shift(m, 1, 0, False) | _shift(m, -1, 0, False) | _shift(m, 0, 1, False) | _shift(m, 0, -1, False)
    return m


def _choke(a, n):
    for _ in range(n):
        a = np.minimum.reduce([a] + [_shift(a, dy, dx, 1.0) for dy, dx in _N4])
    return a


def _gdilate(a, n):
    for _ in range(n):
        a = np.maximum.reduce([a] + [_shift(a, dy, dx, 0.0) for dy, dx in _N4])
    return a


def contract_edge(a, n=1):
    """Contract the matte by n px: a grey min filter shifts the anti-aliased ramp inward and drops
    the contaminated outer fringe. Applied only around regions >= ~5 px thick, so thin structures
    (whiskers, stems, 1-3 px outlines sticking out) are kept instead of erased."""
    if n <= 0:
        return a
    solid = (a >= 0.98).astype(np.float32)
    thick = _dilate(_choke(solid, 2) > 0.5, n + 3)
    return np.where(thick, _choke(a, n), a)


def _propagate(col, known, iters):
    """Push colours of `known` pixels outward `iters` px (mean of known 4-neighbours)."""
    F = np.where(known[..., None], col, 0).astype(np.float32)
    have = known.copy()
    for _ in range(iters):
        acc = np.zeros_like(F)
        cnt = np.zeros(have.shape, np.float32)
        for dy, dx in _N4:
            hv = _shift(have, dy, dx, False)
            acc += _shift(F, dy, dx, 0) * hv[..., None]
            cnt += hv
        new = (~have) & (cnt > 0)
        if not new.any():
            break
        F[new] = acc[new] / cnt[new][:, None]
        have |= new
    return F, have


def drop_specks(a, min_area=16, thr=0.1):
    """Zero 8-connected blobs (alpha > thr) smaller than min_area px. Run-length union-find."""
    if min_area <= 1:
        return a
    mask = a > thr
    parent, runs, prev = [], [], []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(mask.shape[0]):
        row = mask[y]
        if not row.any():
            prev = []
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        starts, ends = np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()
        cur, j = [], 0
        for s, e in zip(starts, ends):
            idx = len(runs)
            runs.append((y, s, e))
            parent.append(idx)
            cur.append(idx)
            while j < len(prev) and runs[prev[j]][2] < s:
                j += 1
            k = j
            while k < len(prev) and runs[prev[k]][1] <= e:
                ra, rb = find(idx), find(prev[k])
                if ra != rb:
                    parent[ra] = rb
                k += 1
        prev = cur
    if not runs:
        return a
    area = {}
    roots = [find(i) for i in range(len(runs))]
    for (y, s, e), r in zip(runs, roots):
        area[r] = area.get(r, 0) + (e - s)
    out = a.copy()
    for (y, s, e), r in zip(runs, roots):
        if area[r] < min_area:
            out[y, s:e] = 0
    return out


def _border(arr, band):
    h, w = arr.shape[:2]
    b = max(1, min(band, h // 4, w // 4))
    c = arr.shape[2] if arr.ndim == 3 else 1
    parts = [arr[:b], arr[-b:], arr[b:-b, :b], arr[b:-b, -b:]]
    return np.concatenate([p.reshape(-1, c) for p in parts])


def flat_border_color(rgb_u8, near_key=None):
    """If the image border is one flat colour (a forgotten key background), return it (0-255 floats)."""
    I = rgb_u8.astype(np.float32) / 255
    B = _border(I, max(2, min(I.shape[:2]) // 64))
    med = np.median(B, axis=0)
    LB, lm = oklab(B), oklab(med[None])[0]
    flat = (_kdist(LB, lm) < 0.05).mean()
    chroma = float(np.hypot(lm[1], lm[2]))
    close_to_key = near_key is not None and _kdist(lm[None], oklab(np.array(near_key, np.float32)[None] / 255))[0] < 0.2
    if flat >= 0.8 and (chroma > 0.08 or close_to_key):
        return tuple(float(x) * 255 for x in med)
    return None


def chroma_key(rgb_u8, key=(255, 0, 255), pixel=False, choke=1, speck=16, soft=0.11):
    """Remove a flat key-colour background. Returns (rgba_u8, info).
    Soft matte from OKLab distance to the key (lightness weighted 0.6) with thresholds set from the
    border noise; edge alpha refined by projecting onto (F - K) with F = nearby opaque colour; only
    pixels within 3 px of clear background may be partial (interior protection); un-mix
    C = (I - (1-a)K)/a; despill (key channels capped to the others) in the edge band; 1 px choke;
    blobs < speck px^2 dropped. pixel=True: hard binary key, no un-mix/despill/choke."""
    I = rgb_u8[..., :3].astype(np.float32) / 255
    h, w = I.shape[:2]
    kreq = np.array(key, np.float32) / 255
    B = _border(I, max(2, min(h, w) // 64))
    LB = oklab(B)
    near = _kdist(LB, oklab(kreq[None])[0]) < 0.2
    frac = float(near.mean())
    info = {"key_requested": "#%02X%02X%02X" % tuple(key), "border_match": round(frac, 3)}
    if frac >= 0.2:
        K = np.median(B[near], axis=0)
        noise = float(np.percentile(_kdist(LB[near], oklab(K[None])[0]), 98))
    else:
        K, noise = kreq, 0.03
        info["warning"] = f"only {frac:.0%} of the border matches the key colour; result may be poor"
    info["key_used"] = "#%02X%02X%02X" % tuple(int(round(x * 255)) for x in K)
    lab = oklab(I)
    d = _kdist(lab, oklab(K[None])[0])
    t0 = float(np.clip(noise + 0.02, 0.035, 0.15))
    t1 = t0 + soft
    info["thresholds"] = [round(t0, 3), round(t1, 3)]
    if pixel:
        a = (d > (t0 + t1) / 2).astype(np.float32)
        C = I
    else:
        x = np.clip((d - t0) / (t1 - t0), 0, 1)
        a = x * x * (3 - 2 * x)
        clear = a < 0.02
        near_bg = _dilate(clear, 3)
        a = np.where(near_bg, a, 1.0).astype(np.float32)             # interior protection
        sure = _choke((a >= 0.995).astype(np.float32), 1) > 0.5          # 1 px inside the coverage ramp
        band = near_bg & ~clear & ~sure
        F, have = None, None
        if band.any() and sure.any():
            F, have = _propagate(I, sure, 4)
            FK = F - K
            den = (FK * FK).sum(-1)
            ok = band & have & (den > 0.04)
            ap = np.clip(((I - K) * FK).sum(-1) / np.maximum(den, 1e-6), 0, 1)
            a = np.where(ok, ap, a)
        am = np.maximum(a, 0.02)[..., None]
        C = np.where((a > 0.004)[..., None], np.clip((I - (1 - am) * K) / am, 0, 1), I)
        hi = [c for c in range(3) if K[c] >= K.max() - 0.25 and K[c] >= 0.5]
        lo = [c for c in range(3) if c not in hi]
        if hi and lo:
            # spill = key-channel dominance beyond what the nearby solid colour F already has
            # (a green leaf on a green key keeps its green; a red edge loses the magenta cast)
            edge = _dilate(a < 0.995, 3) & (a > 0)
            dom = lambda X: X[..., hi].min(-1) - X[..., lo].max(-1)
            allow = np.where(have, np.clip(dom(F), 0, None), 0) if F is not None else 0
            s = np.clip(dom(C) - allow, 0, None) * edge
            C = C.copy()
            for c in hi:
                C[..., c] -= s
        if choke:
            a = contract_edge(a, choke)
    a = drop_specks(a, speck)
    a = np.where(a < 0.004, 0, a)
    if not pixel:
        Fb, hv = _propagate(C, a > 0, 8)                              # colour bleed into clear pixels
        C = np.where(((a == 0) & hv)[..., None], Fb, C)
    rgba = np.dstack([np.clip(C, 0, 1), a])
    info["transparent_frac"] = round(float((a == 0).mean()), 4)
    info["partial_frac"] = round(float(((a > 0) & (a < 1)).mean()), 4)
    return (rgba * 255 + 0.5).astype(np.uint8), info


_LUMA = np.array([0.299, 0.587, 0.114], np.float32)


def lum_key(rgb_u8, paper=(255, 255, 255), pixel=False, speck=16):
    """Strokes on flat paper (watercolour, ink, silhouettes on white or black paper) -> (rgba_u8, info).
    Paper P = border median when it is near the requested colour (generated paper is rarely exact).
    Alpha = luminance distance from P toward the strokes (darker on light paper, lighter on dark paper) over
    the room on that side, raised per channel where needed so the un-multiplied colour C = (I - (1-a)P)/a
    stays in gamut (a light saturated wash keeps its hue instead of fading); the border's grain sets a noise
    floor that is cut and the rest re-stretched. pixel=True: binary alpha, colours untouched."""
    I = rgb_u8[..., :3].astype(np.float32) / 255
    preq = np.array(paper, np.float32) / 255
    B = _border(I, max(2, min(I.shape[:2]) // 64))
    near = _kdist(oklab(B), oklab(preq[None])[0]) < 0.12
    frac = float(near.mean())
    P = np.median(B[near], axis=0) if frac >= 0.2 else preq
    info = {"paper_requested": "#%02X%02X%02X" % tuple(paper), "paper_used": "#%02X%02X%02X" % tuple(int(round(x * 255)) for x in P),
            "border_match": round(frac, 3)}
    if frac < 0.2:
        info["warning"] = f"only {frac:.0%} of the border matches the paper colour; result may be poor"

    dark = float(P @ _LUMA) < 0.5                                  # black paper: strokes are lighter, else darker
    room = (1 - P) if dark else P                                   # how far a stroke can go from the paper per channel
    info["paper_kind"] = "dark" if dark else "light"

    def alpha(X):                                                   # grain on the other side of the paper is ignored
        s = (X - P) if dark else (P - X)
        al = (s @ _LUMA) / max(float(room @ _LUMA), 1e-3)
        ac = (np.clip(s, 0, None) / np.maximum(room, 1e-3)).max(-1)
        return np.clip(np.maximum(al, ac), 0, 1)
    a0 = alpha(I)
    floor = float(np.clip(np.percentile(alpha(B[near]) if near.any() else a0[:1], 98) + 0.02, 0.02, 0.3))
    info["floor"] = round(floor, 3)
    if pixel:
        a = (a0 > max(0.5, floor)).astype(np.float32)
        C = I
    else:                                                          # un-mix with the raw alpha (exact colour), then cut the floor
        am = np.maximum(a0, 0.02)[..., None]
        C = np.where((a0 > 0.004)[..., None], np.clip((I - (1 - am) * P) / am, 0, 1), I)
        a = np.clip((a0 - floor) / (1 - floor), 0, 1)
    a = drop_specks(a, speck)
    a = np.where(a < 0.004, 0, a)
    if not pixel:
        Fb, hv = _propagate(C, a > 0, 8)                              # colour bleed into clear pixels
        C = np.where(((a == 0) & hv)[..., None], Fb, C)
    info["transparent_frac"] = round(float((a == 0).mean()), 4)
    info["partial_frac"] = round(float(((a > 0) & (a < 1)).mean()), 4)
    return (np.dstack([np.clip(C, 0, 1), a]) * 255 + 0.5).astype(np.uint8), info


def looks_checker(rgb_u8):
    """Detect a baked grey/white 'transparency' checkerboard along the image border."""
    g = rgb_u8[..., :3].astype(np.float32).mean(-1)
    sat = rgb_u8[..., :3].max(-1).astype(np.int16) - rgb_u8[..., :3].min(-1)
    h, w = g.shape
    b = max(8, min(h, w) // 12)
    votes = 0
    for G, S in ((g[:b], sat[:b]), (g[-b:], sat[-b:]), (g[:, :b].T, sat[:, :b].T), (g[:, -b:].T, sat[:, -b:].T)):
        if (S < 18).mean() < 0.85:
            continue
        lo, hi = np.percentile(G, 10), np.percentile(G, 90)
        if not 8 <= hi - lo <= 140:
            continue
        if ((np.abs(G - lo) < 12) | (np.abs(G - hi) < 12)).mean() < 0.75:
            continue
        row = G[G.shape[0] // 2] > (lo + hi) / 2
        runs = np.diff(np.flatnonzero(np.diff(row.astype(np.int8)) != 0))
        if len(runs) < 6:
            continue
        med = float(np.median(runs))
        if 3 <= med <= 128 and np.mean(np.abs(runs - med) <= max(1.0, 0.15 * med)) >= 0.7:
            votes += 1
    return votes >= 2


def validate_alpha(im, allow_hard=False):
    """-> (ok, kind, info). kind: ok | opaque | checkerboard | empty | hard-edges."""
    has_alpha = im.mode in ("RGBA", "LA", "PA", "RGBa") or "transparency" in im.info
    rgba = np.asarray(im.convert("RGBA"))
    a = rgba[..., 3]
    info = {"has_alpha_channel": bool(has_alpha), "clear_frac": round(float((a < 8).mean()), 4)}
    if not has_alpha or info["clear_frac"] < 0.003:
        kind = "checkerboard" if looks_checker(rgba) else "opaque"
        return False, kind, info
    fg = a >= 8
    if fg.mean() < 0.0005:
        return False, "empty", info
    bg = ~fg
    edge = fg & (_shift(bg, 1, 0, False) | _shift(bg, -1, 0, False) | _shift(bg, 0, 1, False) | _shift(bg, 0, -1, False))
    soft = int(((a >= 8) & (a <= 240)).sum())
    ratio = soft / max(1, int(edge.sum()))
    info["soft_edge_ratio"] = round(ratio, 3)
    if looks_checker(np.where((a >= 250)[..., None], rgba[..., :3], 0).astype(np.uint8)) and (a >= 250).mean() > 0.9:
        return False, "checkerboard", info
    if ratio < 0.3 and not allow_hard:
        return False, "hard-edges", info
    return True, "ok", info


def clean_native(rgba_u8, pixel=False, speck=16):
    """Tidy real alpha: snap near-opaque (>=248) / near-clear (<=3) values, drop specks, bleed colour."""
    rgba = rgba_u8.astype(np.float32) / 255
    a = rgba[..., 3]
    if pixel:
        a = (a >= 0.5).astype(np.float32)
    else:
        a = np.where(a >= 248 / 255, 1.0, np.where(a <= 3 / 255, 0.0, a))
    a = drop_specks(a, speck)
    C = rgba[..., :3]
    if not pixel:
        Fb, hv = _propagate(C, a > 0, 8)
        C = np.where(((a == 0) & hv)[..., None], Fb, C)
    return (np.dstack([C, a]) * 255 + 0.5).astype(np.uint8)


def _grid_1d(edge_profile, kmax=32):
    """-> (cell size, score, phase): largest k whose edges mostly fall on one phase mod k."""
    tot = edge_profile.sum()
    if tot <= 0:
        return 1, 0.0, 0
    best = (1, 1.0, 0)
    for k in range(2, kmax + 1):
        sums = [edge_profile[p::k].sum() for p in range(k)]
        p = int(np.argmax(sums))
        if sums[p] / tot >= 0.72:
            best = (k, sums[p] / tot, (p + 1) % k)   # an edge after column p -> cells start at p+1
    return best


def pixel_snap(im, grid="auto", colors=16, scale=1):
    """Snap AI 'pixel-looking' art to its real grid: detect cell size, take the most common colour
    per cell (after palette quantisation), binarise alpha. Returns (image, grid)."""
    rgba = im.convert("RGBA")
    arr = np.asarray(rgba)
    if grid == "auto":
        g = arr[..., :3].astype(np.int16)
        ex = (np.abs(np.diff(g, axis=1)).sum(-1) > 24).sum(0).astype(np.float64)
        ey = (np.abs(np.diff(g, axis=0)).sum(-1) > 24).sum(1).astype(np.float64)
        (kx, sx, px), (ky, sy, py) = _grid_1d(ex), _grid_1d(ey)
        k = kx if sx >= sy else ky
        px, py = (px if kx == k else 0), (py if ky == k else 0)
    else:
        k, px, py = int(grid), 0, 0
    k = max(1, k)
    h, w = (arr.shape[0] - py) // k, (arr.shape[1] - px) // k
    arr = arr[py: py + h * k, px: px + w * k]
    a = arr[..., 3]
    q = Image.fromarray(arr[..., :3]).quantize(colors=int(colors), method=Image.Quantize.MEDIANCUT,
                                                dither=Image.Dither.NONE, kmeans=3)
    idx = np.asarray(q).reshape(h, k, w, k).transpose(0, 2, 1, 3).reshape(h, w, k * k)
    P = int(idx.max()) + 1
    counts = np.stack([(idx == i).sum(-1) for i in range(P)], -1)
    small = counts.argmax(-1)
    pal = np.array(q.getpalette()[: P * 3], np.uint8).reshape(P, 3)
    alpha = (a.reshape(h, k, w, k).transpose(0, 2, 1, 3).reshape(h, w, k * k) >= 128).mean(-1) >= 0.5
    out = np.dstack([pal[small], (alpha * 255).astype(np.uint8)])
    res = Image.fromarray(out, "RGBA")
    if scale and int(scale) > 1:
        res = res.resize((w * int(scale), h * int(scale)), Image.NEAREST)
    return res, k


# ----------------------------------------------------------------------------------------------
# CLI



def config():
    path = Path('ref2game.json')
    cfg = json.loads(path.read_text()) if path.exists() else {}
    generator = cfg.get('generator', {})
    if generator.get('tool', 'imagegen') != 'imagegen' or 'provider' in generator:
        raise GenError('Use generator.tool = "imagegen"; remove legacy provider configuration.')
    return cfg


def asset_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
        raise argparse.ArgumentTypeError('Asset names may contain letters, digits, _ and -.')
    return value


def size_text(value):
    if not re.fullmatch(r'[1-9][0-9]*x[1-9][0-9]*', value):
        raise argparse.ArgumentTypeError('Use positive dimensions such as 1536x1024.')
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def prepare(a):
    cfg = config()
    gen = cfg.get('generator', {})
    bible = Path(cfg.get('style_bible', 'art/style_bible.txt')).read_text().strip()
    if not bible or 'replace after the study' in bible.lower() or '<style family>' in bible:
        raise GenError('Complete art/style_bible.txt from the reference first.')
    asset = Path(a.prompt_file).read_text().strip()
    if not asset:
        raise GenError('Asset prompt is empty.')
    refs = []
    style_refs = cfg.get('style_ref', ['ref.png'])
    if isinstance(style_refs, str):
        style_refs = [style_refs]
    for path in style_refs:
        refs.append((Path(path), 'style reference: match style, palette, rendering and light; do not copy composition'))
    for value in a.ref:
        path, sep, label = value.partition('=')
        refs.append((Path(path), label if sep else 'supporting reference for this asset'))
    if not refs:
        raise GenError('ref2game requires a style reference; set style_ref in ref2game.json.')
    for path, _ in refs:
        if not path.is_file():
            raise GenError(f'Reference does not exist: {path}')
    alpha = a.alpha or gen.get('alpha', 'auto')
    if alpha not in ('auto', 'native', 'none'):
        raise GenError('Alpha must be auto, native or none; use native transparency for new sprites.')
    if alpha == 'auto':
        opaque = any(fnmatch.fnmatch(a.name, pat) for pat in gen.get('opaque', ['bg_sky*', '*_tex']))
        alpha = 'none' if opaque else 'native'
    transparent = alpha == 'native'
    size = size_text(a.size or gen.get('size', '1536x1024'))
    labels = '\n'.join(f'Image {i}: {label}.' for i, (_, label) in enumerate(refs, 1))
    background = ('Real transparent alpha outside the asset; clean edges, no painted checkerboard, no extra ground or cast shadow.'
                  if transparent else 'Opaque image, composed edge to edge as described in the asset prompt.')
    prompt = f'STYLE BIBLE (verbatim):\n{bible}\n\nINPUT IMAGES:\n{labels}\n\nASSET:\n{asset}\n\nBACKGROUND:\n{background}\n\nTarget canvas/aspect: {size}. Keep important content within safe margins.'
    arguments = {'prompt': prompt, 'referenced_image_paths': [str(p.resolve()) for p, _ in refs],
                 'transparent_background': transparent}
    request = {'name': a.name, 'tool': 'imagegen', 'arguments': arguments, 'requested_size': size,
               'prompt_file': str(Path(a.prompt_file).resolve()), 'pixel': a.pixel,
               'note': 'Prepared only. Codex must inspect references, call built-in imagegen directly, and import the returned local image.'}
    destination = Path('art/requests') / f'{a.name}.json'
    write_json(destination, request)
    print(f'Prepared {destination}; no generation was performed.')
    print(json.dumps(arguments, ensure_ascii=False, indent=2))


def import_image(a):
    config()
    request = json.loads((Path('art/requests') / f'{a.name}.json').read_text())
    if request.get('tool') != 'imagegen' or request.get('name') != a.name:
        raise GenError('Request does not match this built-in imagegen asset.')
    source = Path(a.source).resolve(strict=True)
    with Image.open(source) as opened:
        opened.load()
        im = opened.copy()
    alpha_report = None
    if request['arguments']['transparent_background']:
        ok, kind, info = validate_alpha(im, allow_hard=bool(request.get('pixel')))
        alpha_report = {'ok': ok, 'kind': kind, **info}
        if not ok:
            raise GenError(f'Required native alpha is invalid ({kind}). Correct with built-in imagegen and import again.')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    final = Path('art/gen') / f'{a.name}.png'
    raw = Path('art/raw') / f'{a.name}{source.suffix.lower() or ".png"}'
    log = Path('art/logs') / f'{a.name}.json'
    existing = [p for p in list(Path('art/raw').glob(f'{a.name}.*')) + [final, log] if p.exists()]
    if existing and not a.replace:
        raise GenError(f'Asset {a.name} exists. Use a versioned name or --replace for an intended replacement (backups are kept).')
    if existing:
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
        backup = Path('art/old') / a.name / stamp
        for path in existing:
            target = backup / path.parent.name / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    raw.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    if source != raw.resolve():
        shutil.copy2(source, raw)
    im.save(final, format='PNG')
    write_json(log, {'name': a.name, 'tool': 'imagegen', 'source_path': str(source),
                     'source_sha256': source_hash, 'raw': str(raw), 'final': str(final),
                     'actual_size': list(im.size), 'alpha': alpha_report, 'request': request,
                     'imported_at': dt.datetime.now(dt.timezone.utc).isoformat()})
    print(f'Imported {final} ({im.width}x{im.height}); raw output and prompt log saved.')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Built-in imagegen preparation/import; offline asset utilities. No generation backend.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('check', help='check local inputs, not tool availability')
    p = sub.add_parser('prepare', help='write arguments for a direct built-in imagegen call')
    p.add_argument('name', type=asset_name)
    p.add_argument('prompt_file')
    p.add_argument('--ref', action='append', default=[], help='extra IMG=role reference')
    p.add_argument('--size', type=size_text, help='canvas/aspect hint, not an exact tool parameter')
    p.add_argument('--alpha', choices=['auto', 'native', 'none'])
    p.add_argument('--pixel', action='store_true', help='allow hard native alpha for pixel art')
    p = sub.add_parser('import', help='import an actual returned built-in imagegen output')
    p.add_argument('name', type=asset_name)
    p.add_argument('source')
    p.add_argument('--replace', action='store_true', help='back up and replace an intended asset')
    p = sub.add_parser('validate', help='validate native alpha without editing')
    p.add_argument('image')
    p.add_argument('--pixel', action='store_true')
    p = sub.add_parser('key', help='offline keying of keyed or paper art (--lum: alpha from the paper colour)')
    p.add_argument('inp')
    p.add_argument('out')
    p.add_argument('--key')
    p.add_argument('--lum', action='store_true')
    p.add_argument('--pixel', action='store_true')
    p.add_argument('--choke', type=int, default=1)
    p.add_argument('--speck', type=int, default=16)
    p = sub.add_parser('pixel', help='offline grid/palette processing for pixel-art integration')
    p.add_argument('inp')
    p.add_argument('out')
    p.add_argument('--grid', default='auto')
    p.add_argument('--colors', type=int, choices=range(1, 257), default=16)
    p.add_argument('--scale', type=int, default=1)
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'check':
            cfg = config()
            paths = [cfg.get('style_bible', 'art/style_bible.txt')]
            refs = cfg.get('style_ref', ['ref.png'])
            paths += [refs] if isinstance(refs, str) else refs
            missing = [p for p in paths if not Path(p).is_file()]
            print(json.dumps({'tool': 'imagegen', 'local_inputs_ok': not missing, 'missing': missing,
                              'note': 'Only the Codex session can verify tool availability; this script never generates images.'}, indent=2))
            return 1 if missing else 0
        if a.cmd == 'prepare':
            prepare(a)
        elif a.cmd == 'import':
            import_image(a)
        elif a.cmd == 'validate':
            with Image.open(a.image) as im:
                ok, kind, info = validate_alpha(im, allow_hard=a.pixel)
            print(json.dumps({'ok': ok, 'kind': kind, **info}, indent=2))
            return 0 if ok else 2
        elif a.cmd == 'key':
            rgb = np.asarray(Image.open(a.inp).convert('RGB'))
            arr, info = (lum_key(rgb, parse_hex(a.key or 'ffffff'), a.pixel, a.speck) if a.lum
                         else chroma_key(rgb, parse_hex(a.key or 'ff00ff'), a.pixel, a.choke, a.speck))
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(arr).save(a.out)
            print(json.dumps(info))
        elif a.cmd == 'pixel':
            if a.scale < 1 or (a.grid != 'auto' and int(a.grid) < 1):
                raise GenError('Pixel grid and scale must be positive.')
            result, grid = pixel_snap(Image.open(a.inp), a.grid, a.colors, a.scale)
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            result.save(a.out)
            print(json.dumps({'grid': grid, 'size': list(result.size)}))
        return 0
    except (GenError, OSError, ValueError, KeyError, TypeError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
