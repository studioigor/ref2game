#!/usr/bin/env python3
"""study.py - study a 2D art reference (still image or video) in detail.

Every subcommand writes its images into its output directory, merges machine-readable
results into DIR/study.json (study[section][file key], merged across runs) and prints a
short human summary. Coordinates are reference pixels (x right, y down, origin top-left)
unless a field says "native" (pixel-art native resolution) or "analysis".

Subcommands (exact CLI)

  probe FILE [--out DIR]
      Image: size, mode, distinct colours, alpha. Video: duration, fps, size, codec, frames.
      python3 study.py probe shot.png
      python3 study.py probe clip.mp4 --out study/

  image FILE --out DIR [--grid COLSxROWS] [--overlap F] [--zoom N] [--colors K]
      Still references (screenshots, concept art, sprite sheets). Defaults: --grid 6x4,
      --overlap 0.08, --zoom 0 (auto 2-6), --colors 32 (k-means size when >256 colours).
      Writes native.png (pixel art only), palette.png, palette.json, values.png, light.png,
      edges.png, overview_grid.png, tiles/tile_r{row}_c{col}.png.
      python3 study.py image shot.png --out study/
      python3 study.py image sheet.png --out study/ --grid 4x3 --colors 48

  video FILE --out DIR [--fps F] [--cols N] [--cells COLSxROWS] [--cut T]
               [--region x0,y0,x1,y1 ...] [--keyframes N] [--noise T] [--no-keyframe-analysis]
      Video references. Defaults: --fps 4 (contact sheets), --cols 6, --cells 8x6 (rate map),
      --cut 0.3 (colour-histogram jump), --keyframes 3, --noise auto. --region is repeatable.
      Writes sheets/sheet_NN.png, keyframes/*.png, rate_map.png, rate_blocks.png, motion.png,
      boil.png, region_K.png, keyframe_analysis/rep_K/ (image study of representative frames).
      python3 study.py video clip.mp4 --out study/
      python3 study.py video clip.mp4 --out study/ --region 820,560,900,660 --region 40,40,200,160

  crop FILE x0 y0 x1 y1 --out PNG [--zoom Z] [--grid STEP] [--t SECONDS] [--clean]
      One zoomed crop with labelled rulers and a dashed grid every STEP reference px.
      Defaults: --zoom 4, --grid 10; --t picks the video frame. --clean: the bare crop, no rulers,
      grid or labels (zoom default 1) — for crops used as generator refs.
      python3 study.py crop shot.png 600 380 800 470 --zoom 4 --grid 10 --out study/crop_hero.png
      python3 study.py crop clip.mp4 600 380 800 470 --t 12.5 --out study/crop_t12.png

  track FILE --region x0,y0,x1,y1 --out DIR [--from S] [--to S] [--zoom N] [--noise T]
      Every unique drawing of one video region (walk cycle, attack, effect, flame loop) as
      labelled strip sheets track_NN.png: time, frame, hold, repeats, and the drawing cycle.
      python3 study.py track clip.mp4 --region 680,380,800,480 --out study/track_hero --from 2 --to 6

  tiles FILE [--region x0,y0,x1,y1] [--t SECONDS] --out DIR [--tile N] [--max-unique N]
      Level grid of the environment, measured on the native-resolution image: tile size and
      phase (candidates 8/12/16/24/32/48/64 native px for pixel art, arbitrary periods for
      HD art), texture repeat period, unique tiles (near-duplicate groups) with counts,
      coverage by repeated tiles, and a 3/4-view wall face height guess. Point --region at a
      floor/wall area for the cleanest reading. Writes tiles_grid.png, tiles_unique.png.
      python3 study.py tiles shot.png --region 560,360,1100,560 --out study/
      python3 study.py tiles clip.mp4 --t 2 --out study/
"""

import argparse
import collections
import colorsys
import json
import math
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.mpg', '.mpeg', '.wmv', '.flv', '.ts'}

# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------

_FONTS = {}


def font(size=14):
    if size not in _FONTS:
        f = None
        try:
            f = ImageFont.load_default(size=size)
        except Exception:
            f = None
        if f is None:
            for p in ('DejaVuSans.ttf', 'Arial.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
                      '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf'):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except Exception:
                    continue
        if f is None:
            f = ImageFont.load_default()
        _FONTS[size] = f
    return _FONTS[size]


def text_wh(draw, text, fnt):
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    return r - l, b - t


def label(draw, xy, text, fnt, fg=(255, 255, 255), bg=(0, 0, 0), pad=2, anchor='la'):
    l, t, r, b = draw.textbbox(xy, text, font=fnt, anchor=anchor)
    if bg is not None:
        draw.rectangle([l - pad, t - pad, r + pad, b + pad], fill=bg)
    draw.text(xy, text, font=fnt, fill=fg, anchor=anchor)
    return r + pad


def hexc(c):
    c = [int(round(float(v))) for v in c[:3]]
    return '#%02x%02x%02x' % tuple(max(0, min(255, v)) for v in c)


def is_video(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return True
    if ext == '.gif':
        try:
            with Image.open(path) as im:
                return getattr(im, 'n_frames', 1) > 1
        except Exception:
            return False
    return False


def ensure_dir(d):
    if d:
        os.makedirs(d, exist_ok=True)
    return d


def rel(path, base):
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return round(v, 5) if math.isfinite(v) else None
    if isinstance(o, float):
        return round(o, 5) if math.isfinite(o) else None
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def merge_study_json(out_dir, section, key, data):
    """Merge one result into OUT/study.json under study[section][key]."""
    ensure_dir(out_dir)
    path = os.path.join(out_dir, 'study.json')
    study = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                study = json.load(f)
        except Exception:
            study = {}
    study.setdefault(section, {})[key] = jsonable(data)
    study['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(path, 'w') as f:
        json.dump(study, f, indent=1)
    return path


def fmt_t(t):
    m = int(t // 60)
    return '%02d:%05.2f' % (m, t - 60 * m)


# ----------------------------------------------------------------------------
# colour science
# ----------------------------------------------------------------------------

_M_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                       [0.2126729, 0.7151522, 0.0721750],
                       [0.0193339, 0.1191920, 0.9503041]], np.float32)


def srgb_to_linear(c):
    c = np.asarray(c, np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _f_lab(t):
    return np.where(t > 216 / 24389, np.cbrt(t), (24389 / 27 * t + 16) / 116)


def rgb_to_lab(rgb):
    lin = srgb_to_linear(rgb)
    xyz = lin @ _M_RGB2XYZ.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = _f_lab(xyz)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], -1).astype(np.float32)


def rgb_to_Y(rgb):
    lin = srgb_to_linear(rgb)
    return (lin @ _M_RGB2XYZ[1]).astype(np.float32)


def rgb_to_Lstar(rgb):
    Y = rgb_to_Y(rgb)
    return (116 * _f_lab(Y) - 16).astype(np.float32)


def luma8(rgb):
    """Fast perceptual-ish luma 0..255 (Rec.601 on gamma values)."""
    a = np.asarray(rgb, np.float32)
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


HUE_NAMES = [(12, 'red'), (40, 'orange'), (68, 'yellow'), (160, 'green'), (195, 'cyan'),
             (255, 'blue'), (290, 'purple'), (335, 'magenta'), (361, 'red')]


def hsv_of(c):
    r, g, b = [float(v) / 255 for v in c[:3]]
    return colorsys.rgb_to_hsv(r, g, b)


def hue_name(c):
    h, s, v = hsv_of(c)
    if v < 0.06:
        return 'black'
    if s < 0.12:
        return 'grey' if v < 0.92 else 'white'
    hd = h * 360
    for lim, name in HUE_NAMES:
        if hd < lim:
            return name
    return 'red'


def hue_delta(h_from, h_to):
    """Signed shortest difference in degrees (to - from)."""
    return (h_to - h_from + 180) % 360 - 180


# ----------------------------------------------------------------------------
# k-means (numpy)
# ----------------------------------------------------------------------------

def assign_nearest(X, C, chunk=262144):
    X = np.asarray(X, np.float32)
    C = np.asarray(C, np.float32)
    out = np.empty(len(X), np.int32)
    dist = np.empty(len(X), np.float32)
    cc = (C ** 2).sum(1)
    for i in range(0, len(X), chunk):
        x = X[i:i + chunk]
        d = cc[None, :] - 2 * x @ C.T
        j = d.argmin(1)
        out[i:i + chunk] = j
        dist[i:i + chunk] = np.sqrt(np.maximum(0, d[np.arange(len(x)), j] + (x ** 2).sum(1)))
    return out, dist


def kmeans(X, k, iters=30, seed=0, sample=60000):
    rng = np.random.default_rng(seed)
    X = np.asarray(X, np.float32)
    Xs = X[rng.choice(len(X), sample, replace=False)] if len(X) > sample else X
    k = max(1, min(k, len(Xs)))
    C = np.empty((k, X.shape[1]), np.float32)
    C[0] = Xs[rng.integers(len(Xs))]
    d2 = ((Xs - C[0]) ** 2).sum(1)
    for j in range(1, k):
        tot = d2.sum()
        if tot <= 0:
            C = C[:j]
            break
        i = rng.choice(len(Xs), p=d2 / tot)
        C[j] = Xs[i]
        d2 = np.minimum(d2, ((Xs - Xs[i]) ** 2).sum(1))
    for _ in range(iters):
        lab, _ = assign_nearest(Xs, C)
        cnt = np.bincount(lab, minlength=len(C)).astype(np.float32)
        newC = np.stack([np.bincount(lab, weights=Xs[:, d], minlength=len(C)) for d in range(X.shape[1])], 1)
        ok = cnt > 0
        newC[ok] /= cnt[ok, None]
        newC[~ok] = C[~ok]
        shift = np.abs(newC - C).max()
        C = newC.astype(np.float32)
        if shift < 0.05:
            break
    return C


# ----------------------------------------------------------------------------
# drawing helpers: colour maps, rulers, panels
# ----------------------------------------------------------------------------

_HEAT = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66],
                  [245, 125, 21], [250, 193, 39], [252, 255, 164]], np.float32)


def heat_cmap(v):
    v = np.clip(np.asarray(v, np.float32), 0, 1) * (len(_HEAT) - 1)
    i = np.minimum(v.astype(np.int32), len(_HEAT) - 2)
    t = (v - i)[..., None]
    return (_HEAT[i] * (1 - t) + _HEAT[i + 1] * t).astype(np.uint8)


def diverge_cmap(v):
    """v in [-1, 1]: -1 blue, 0 grey, +1 red."""
    v = np.clip(np.asarray(v, np.float32), -1, 1)[..., None]
    grey = np.array([128, 128, 128], np.float32)
    red = np.array([235, 40, 30], np.float32)
    blue = np.array([30, 90, 240], np.float32)
    out = np.where(v >= 0, grey * (1 - v) + red * v, grey * (1 + v) + blue * (-v))
    return out.astype(np.uint8)


def nice_steps(zoom, min_minor_px=7, min_major_px=58):
    cands = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000]
    minor = next((c for c in cands if c * zoom >= min_minor_px), cands[-1])
    major = next((c for c in cands if c * zoom >= min_major_px and c % minor == 0), cands[-1])
    return minor, major


def add_ruler(img, x0, y0, zoom, major=None, title=None, grid=True, bg=(22, 22, 26)):
    """Frame a zoomed crop with labelled rulers. The crop's top-left pixel is
    reference coordinate (x0, y0); one reference pixel = `zoom` output pixels."""
    img = img.convert('RGB')
    W, H = img.size
    fnt = font(12)
    tfnt = font(14)
    if major is None:
        minor, major = nice_steps(zoom)
    else:
        major = max(1, int(major))
        minor = next((m for m in (major // 10, major // 5, major // 2, major) if m >= 1 and m * zoom >= 6 and major % m == 0), major)
    x1 = x0 + W / zoom
    y1 = y0 + H / zoom
    dummy = ImageDraw.Draw(img)
    lw = text_wh(dummy, str(int(max(abs(x1), abs(y1), 10))), fnt)[0]
    ml = lw + 14
    nlines = title.count('\n') + 1 if title else 0
    th = (nlines * (text_wh(dummy, 'Ag', tfnt)[1] + 5) + 6) if title else 0
    mt = 22 + th
    canvas = Image.new('RGB', (W + ml + 8, H + mt + 8), bg)
    canvas.paste(img, (ml, mt))
    if grid:
        ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        gx = math.ceil(x0 / major) * major
        while gx <= x1:
            px = int(round((gx - x0) * zoom))
            for yy in range(0, H, 8):
                od.line([(px, yy), (px, min(H - 1, yy + 3))], fill=(255, 255, 255, 110))
                od.line([(px, yy + 4), (px, min(H - 1, yy + 7))], fill=(0, 0, 0, 110))
            gx += major
        gy = math.ceil(y0 / major) * major
        while gy <= y1:
            py = int(round((gy - y0) * zoom))
            for xx in range(0, W, 8):
                od.line([(xx, py), (min(W - 1, xx + 3), py)], fill=(255, 255, 255, 110))
                od.line([(xx + 4, py), (min(W - 1, xx + 7), py)], fill=(0, 0, 0, 110))
            gy += major
        base = canvas.crop((ml, mt, ml + W, mt + H)).convert('RGBA')
        canvas.paste(Image.alpha_composite(base, ov).convert('RGB'), (ml, mt))
    d = ImageDraw.Draw(canvas)
    if title:
        d.multiline_text((6, 4), title, font=tfnt, fill=(235, 235, 235), spacing=5)
    # horizontal ruler
    g = math.ceil(x0 / minor) * minor
    while g <= x1 + 1e-9:
        px = ml + int(round((g - x0) * zoom))
        is_major = (round(g) % major == 0)
        d.line([(px, mt - (9 if is_major else 4)), (px, mt - 1)], fill=(220, 220, 220) if is_major else (150, 150, 150))
        if is_major:
            d.text((px, mt - 10), str(int(round(g))), font=fnt, fill=(255, 230, 120), anchor='mb')
        g += minor
    # vertical ruler
    g = math.ceil(y0 / minor) * minor
    while g <= y1 + 1e-9:
        py = mt + int(round((g - y0) * zoom))
        is_major = (round(g) % major == 0)
        d.line([(ml - (9 if is_major else 4), py), (ml - 1, py)], fill=(220, 220, 220) if is_major else (150, 150, 150))
        if is_major:
            d.text((ml - 11, py), str(int(round(g))), font=fnt, fill=(255, 230, 120), anchor='rm')
        g += minor
    return canvas


def zoom_crop(img, x0, y0, x1, y1, zoom):
    """Crop (reference px, may extend outside: padded) and enlarge with nearest neighbour."""
    x0, y0, x1, y1 = int(math.floor(x0)), int(math.floor(y0)), int(math.ceil(x1)), int(math.ceil(y1))
    c = img.crop((x0, y0, x1, y1))
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    return c.resize((max(1, int(round(w * zoom))), max(1, int(round(h * zoom)))), Image.NEAREST)


def fit_size(w, h, max_w, max_h=None):
    s = max_w / w
    if max_h:
        s = min(s, max_h / h)
    return max(1, int(round(w * s))), max(1, int(round(h * s))), s


def title_panel(img, text, bg=(22, 22, 26), size=15):
    fnt = font(size)
    d0 = ImageDraw.Draw(img)
    th = text_wh(d0, 'Ag', fnt)[1] + 10
    out = Image.new('RGB', (img.width, img.height + th), bg)
    out.paste(img, (0, th))
    ImageDraw.Draw(out).text((6, 4), text, font=fnt, fill=(235, 235, 235))
    return out


def hstack(imgs, gap=8, bg=(22, 22, 26)):
    W = sum(i.width for i in imgs) + gap * (len(imgs) - 1)
    H = max(i.height for i in imgs)
    out = Image.new('RGB', (W, H), bg)
    x = 0
    for i in imgs:
        out.paste(i, (x, 0))
        x += i.width + gap
    return out


def vstack(imgs, gap=8, bg=(22, 22, 26)):
    W = max(i.width for i in imgs)
    H = sum(i.height for i in imgs) + gap * (len(imgs) - 1)
    out = Image.new('RGB', (W, H), bg)
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height + gap
    return out


def colorbar(width, labels, cmap_fn, height=14, title=None, bg=(22, 22, 26)):
    """labels: list of (position 0..1, text)."""
    fnt = font(12)
    th = 18 if title else 0
    out = Image.new('RGB', (width, height + 20 + th), bg)
    grad = cmap_fn(np.linspace(0, 1, width)[None, :].repeat(height, 0))
    out.paste(Image.fromarray(grad), (0, th))
    d = ImageDraw.Draw(out)
    if title:
        d.text((2, 1), title, font=fnt, fill=(230, 230, 230))
    for p, t in labels:
        x = int(round(p * (width - 1)))
        d.line([(x, th + height), (x, th + height + 3)], fill=(230, 230, 230))
        anchor = 'la' if p < 0.02 else ('ra' if p > 0.98 else 'ma')
        d.text((x, th + height + 4), t, font=fnt, fill=(230, 230, 230), anchor=anchor)
    return out


# ----------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------

def load_image(path):
    """Returns (rgb uint8 HxWx3, mask bool HxW or None for fully opaque)."""
    im = Image.open(path)
    try:
        im.seek(0)
    except Exception:
        pass
    mask = None
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = np.asarray(im.convert('RGBA'))
        a = rgba[..., 3]
        if (a < 255).any():
            mask = a > 0
        rgb = rgba[..., :3].copy()
    else:
        rgb = np.asarray(im.convert('RGB')).copy()
    return rgb, mask


# ----------------------------------------------------------------------------
# video helpers (ffmpeg / ffprobe)
# ----------------------------------------------------------------------------

def ffprobe_info(path):
    cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('ffprobe failed: ' + r.stderr.strip())
    j = json.loads(r.stdout)
    v = next((s for s in j.get('streams', []) if s.get('codec_type') == 'video'), None)
    if v is None:
        raise SystemExit('no video stream in ' + path)

    def rate(s):
        try:
            a, b = s.split('/')
            return float(a) / float(b) if float(b) else 0.0
        except Exception:
            return 0.0
    fps = rate(v.get('avg_frame_rate', '0/0')) or rate(v.get('r_frame_rate', '0/0')) or 25.0
    dur = float(v.get('duration') or j.get('format', {}).get('duration') or 0)
    nb = int(v['nb_frames']) if str(v.get('nb_frames', '')).isdigit() else int(round(dur * fps))
    audio = [s.get('codec_name') for s in j.get('streams', []) if s.get('codec_type') == 'audio']
    return {
        'kind': 'video', 'width': int(v['width']), 'height': int(v['height']), 'fps': round(fps, 4),
        'r_frame_rate': v.get('r_frame_rate'), 'avg_frame_rate': v.get('avg_frame_rate'),
        'duration': round(dur, 4), 'frames': nb, 'codec': v.get('codec_name'), 'profile': v.get('profile'),
        'pix_fmt': v.get('pix_fmt'), 'bit_rate': int(j.get('format', {}).get('bit_rate') or 0),
        'variable_frame_rate': v.get('avg_frame_rate') != v.get('r_frame_rate'),
        'audio': audio, 'start_time': float(v.get('start_time') or 0),
    }


def ffmpeg_frames(path, w, h, ss=None, duration=None, vf=None, max_frames=None):
    """Yield decoded frames (uint8 HxWx3) at size w x h."""
    cmd = ['ffmpeg', '-v', 'error', '-nostdin']
    if ss is not None and ss > 0:
        cmd += ['-ss', '%.4f' % ss]
    cmd += ['-i', path]
    if duration is not None:
        cmd += ['-t', '%.4f' % duration]
    if vf:
        cmd += ['-vf', vf]
    cmd += ['-fps_mode', 'passthrough', '-an', '-sn', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=w * h * 3 * 4)
    size = w * h * 3
    n = 0
    try:
        while True:
            buf = p.stdout.read(size)
            if not buf or len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            n += 1
            if max_frames and n >= max_frames:
                break
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def extract_frame(path, t, out_png=None, fps=None, frames=1):
    """Grab full-resolution frame(s) at time t (seconds). Returns list of uint8 arrays."""
    info = ffprobe_info(path)
    w, h = info['width'], info['height']
    ss = max(0.0, t - (0.25 / fps if fps else 0.0))
    res = list(ffmpeg_frames(path, w, h, ss=ss, max_frames=frames))
    if not res:  # past the end: take the last frame
        res = list(ffmpeg_frames(path, w, h, ss=max(0.0, info['duration'] - 1.0)))[-frames:]
    if out_png and res:
        Image.fromarray(res[0]).save(out_png)
    return res


# ----------------------------------------------------------------------------
# pixel grid detection
# ----------------------------------------------------------------------------

def _boundary_energy(Y, axis):
    A = Y if axis == 1 else Y.T
    d = np.abs(np.diff(A, axis=1))
    d = d / (ndi.uniform_filter1d(d, 7, axis=1) + 2.0)  # local contrast normalisation
    return d.sum(0)  # index j <-> boundary between pixel j and j+1 (position j+1)


def _comb(e, s, phase_res=0.25):
    """Best (excess, phase) of a comb of period s over boundary energy e."""
    N = len(e)
    tot = e.sum() + 1e-9
    nph = max(8, int(math.ceil(s / phase_res)))
    ph = (np.arange(nph) + 0.5) / nph * s
    k = np.arange(int(N / s) + 2)
    pos = np.floor(ph[:, None] + k[None, :] * s + 0.5).astype(np.int64) - 1
    valid = (pos >= 0) & (pos < N)
    hit = np.where(valid, e[np.clip(pos, 0, N - 1)], 0).sum(1)
    exc = hit / tot - valid.sum(1) / N
    j = int(exc.argmax())
    return float(exc[j]), float(ph[j])


def _scan(e, s_lo, s_hi, tol_px=0.5):
    N = len(e)
    svals = []
    s = s_lo
    while s <= s_hi:
        svals.append(s)
        s += max(1e-4, tol_px * s / N)
    svals = np.array(svals)
    res = np.array([_comb(e, s) for s in svals])
    return svals, res[:, 0], res[:, 1]


def _conf(exc, s):
    return exc / max(1e-6, 1 - 1 / s)


def _beat(Y, axis):
    """Dominant period of the column sharpness ratio |d2|/|d1| (non-integer grid beat)."""
    A = Y if axis == 1 else Y.T
    d1 = np.abs(np.diff(A, axis=1))
    d2 = np.abs(A[:, 2:] - 2 * A[:, 1:-1] + A[:, :-2])
    r = d2.sum(0) / (d1[:, 1:].sum(0) + 1e-6)
    r = r - r.mean()
    N = len(r)
    M = 1 << int(math.ceil(math.log2(N * 32)))
    P = np.abs(np.fft.rfft(r * np.hanning(N), M)) ** 2
    fr = np.fft.rfftfreq(M)
    sel = (fr >= 4.0 / N) & (fr <= 1 / 12.0)  # at least 4 cycles across the image
    if sel.sum() < 10:
        return None, 0.0
    Ps, frs = P[sel], fr[sel]
    i = int(Ps.argmax())
    return float(1 / frs[i]), float(Ps[i] / (np.median(Ps) + 1e-12))


def _effective_detail(Y):
    """Finest detail scale (px) from the whitened power spectrum (rows and columns)."""
    out = []
    for A in (Y, Y.T):
        X = A - A.mean(1, keepdims=True)
        N = X.shape[1]
        if N < 32:
            continue
        rows = X[:: max(1, X.shape[0] // 400)]
        P = (np.abs(np.fft.rfft(rows * np.hanning(N), axis=1)) ** 2).mean(0)
        f = np.fft.rfftfreq(N)
        w = P * f ** 2
        bins = np.linspace(0.02, 0.5, 49)
        prof = np.array([w[(f >= a) & (f < b)].mean() if ((f >= a) & (f < b)).any() else 0 for a, b in zip(bins[:-1], bins[1:])])
        prof = ndi.uniform_filter1d(prof, 3)
        pk = prof.max()
        above = np.where(prof >= 0.5 * pk)[0]
        fc = bins[above.max() + 1] if len(above) else 0.5
        out.append(0.5 / max(fc, 1e-3))
    return float(np.mean(out)) if out else 1.0


def detect_pixel_grid(rgb):
    """Detect an upscaled pixel-art grid. Returns a dict (scale, phase, native size, kind, confidence...)."""
    H, W = rgb.shape[:2]
    Y = luma8(rgb)
    res = {'width': W, 'height': H}
    e = {'x': _boundary_energy(Y, 1), 'y': _boundary_energy(Y, 0)}
    smax = {ax: min(16.0, len(e[ax]) / 6.0) for ax in e}
    best = {}
    for ax in ('x', 'y'):
        if smax[ax] <= 1.3:
            best[ax] = (1.0, 0.0, 0.0)
            continue
        # rank by raw excess (captured boundary energy minus the comb's density): this prefers
        # the true period over its sub-multiples (denser combs) and multiples (missing boundaries)
        sv, ex, ph = _scan(e[ax], 1.25, smax[ax], tol_px=0.6)
        cands = list(np.argsort(ex)[::-1][:6])
        top = None
        for i in cands:  # refine the top candidates
            lo, hi = sv[i] * 0.995, sv[i] * 1.005
            sv2, ex2, ph2 = _scan(e[ax], lo, hi, tol_px=0.08)
            j = int(ex2.argmax())
            if top is None or ex2[j] > top[1]:
                top = (float(sv2[j]), float(ex2[j]), float(ph2[j]))
        s, x_, p = top
        if 1.5 < s < 2.0:  # s and s/(s-1) are near-aliases: prefer the coarser grid when as good
            s2 = s / (s - 1)
            ex2, ph2 = _comb(e[ax], s2)
            if ex2 >= 0.97 * x_:
                s, x_, p = s2, ex2, ph2
        r = round(s)
        if r >= 2 and abs(s - r) < 0.02 * r:  # snap to integer when as good
            exr, phr = _comb(e[ax], float(r))
            if exr >= 0.97 * x_:
                s, x_, p = float(r), exr, phr
        best[ax] = (s, _conf(x_, s), p)
    res['crisp_candidates'] = {ax: {'scale': round(best[ax][0], 4), 'confidence': round(best[ax][1], 3)} for ax in best}
    # cross-check: evaluate each axis at the other axis' scale (square pixels are the norm)
    sx, cx, px = best['x']
    sy, cy, py = best['y']
    if abs(sx - sy) / max(sx, sy) > 0.01:
        for a, b in (('x', 'y'), ('y', 'x')):
            s_other = best[b][0]
            if s_other < 1.25:
                continue
            ex_, ph_ = _comb(e[a], s_other)
            if _conf(ex_, s_other) > 0.85 * best[a][1]:
                best[a] = (s_other, _conf(ex_, s_other), ph_)
        sx, cx, px = best['x']
        sy, cy, py = best['y']
    s_eff = _effective_detail(Y)
    res['effective_detail_px'] = round(s_eff, 2)
    conf = min(cx, cy)
    if conf >= 0.4 and sx >= 1.25 and sy >= 1.25:
        res.update(kind='crisp', scale_x=sx, scale_y=sy, scale=(sx + sy) / 2 if abs(sx - sy) < 0.01 * sx else None,
                   phase_x=px, phase_y=py, confidence=round(conf, 3))
        res['integer'] = bool(abs(sx - round(sx)) < 1e-6 and abs(sy - round(sy)) < 1e-6)
    else:
        # soft grid route: a sharpness beat reveals a non-integer grid even when edges are blurred
        soft = None
        beats = {}
        for ax, axis in (('x', 1), ('y', 0)):
            P, ratio = _beat(Y, axis)
            beats[ax] = {'period_px': None if P is None else round(P, 2), 'peak_ratio': round(ratio, 1)}
            if P is None or ratio < 15 or P < 12:
                continue
            for n in range(2, 9):
                zs = []
                for s in (n * P / (P - 1), n * P / (P + 1)):
                    if s > len(e[ax]) / 6:
                        continue
                    sv, ex, ph = _scan(e[ax], s * 0.97, s * 1.03, tol_px=0.3)
                    med = np.median(ex)
                    mad = 1.4826 * np.median(np.abs(ex - med)) + 1e-9
                    ex0, ph0 = _comb(e[ax], s)
                    zs.append(((ex0 - med) / mad, s, ph0))
                if not zs:
                    continue
                if n == 2 and len(zs) == 2:
                    # period-2 combs at s and s/(s-1) are exact aliases on an integer lattice:
                    # take the stronger evidence, report the coarser grid (fewer native pixels)
                    z = max(zs[0][0], zs[1][0])
                    cands = [(z, zs[0][1], zs[0][2])]
                else:
                    cands = zs
                for z, s, ph0 in cands:
                    if soft is None or z > soft[0]:
                        soft = (z, s, ph0, ax, P, ratio, n)
        res['grid_beat'] = beats
        if soft is not None and soft[0] >= 4.5:
            z, s, ph, ax, P, ratio, n = soft
            other = 'y' if ax == 'x' else 'x'
            sv, ex, _ = _scan(e[other], s * 0.97, s * 1.03, tol_px=0.3)
            med = np.median(ex)
            mad = 1.4826 * np.median(np.abs(ex - med)) + 1e-9
            exo, pho = _comb(e[other], s)
            zo = (exo - med) / mad
            res.update(kind='soft', scale_x=s, scale_y=s, scale=s,
                       phase_x=ph if ax == 'x' else pho, phase_y=ph if ax == 'y' else pho,
                       confidence=round(min(0.6, 0.05 * z + (0.05 * zo if zo > 3 else 0)), 3),
                       soft_evidence={'axis': ax, 'beat_period_px': round(P, 2), 'beat_peak_ratio': round(ratio, 1),
                                      'base_integer': n, 'comb_z': round(z, 1), 'other_axis_comb_z': round(zo, 1),
                                      'alias_scale': round(n * P / (P + 1) if s > n else n * P / (P - 1), 4)})
            res['integer'] = False
        else:
            res.update(kind='none', scale=None, confidence=round(conf, 3))
    if res['kind'] in ('crisp', 'soft'):
        for ax, n_px in (('x', W), ('y', H)):
            s = res['scale_' + ax]
            o = res['phase_' + ax]
            b = np.floor(o + np.arange(-1, int(n_px / s) + 3) * s + 0.5).astype(int)
            b = np.unique(np.clip(b, 0, n_px))
            cells = [(int(a), int(c)) for a, c in zip(b[:-1], b[1:]) if c - a >= 1]
            target = max(1, int(round(n_px / s)))
            while len(cells) > target:  # drop the narrowest partial edge cell
                if (cells[0][1] - cells[0][0]) <= (cells[-1][1] - cells[-1][0]):
                    cells = cells[1:]
                else:
                    cells = cells[:-1]
            res['cells_' + ax] = cells
        res['native_w'] = len(res['cells_x'])
        res['native_h'] = len(res['cells_y'])
    # verdict text
    if res['kind'] == 'crisp':
        sq = abs(res['scale_x'] - res['scale_y']) < 0.005 * res['scale_x']
        sc = ('%.4g' % ((res['scale_x'] + res['scale_y']) / 2)) if sq else ('%.4g x %.4g' % (res['scale_x'], res['scale_y']))
        res['verdict'] = ('pixel art, crisp grid: scale %s (%s), native %dx%d, phase (%.2f, %.2f), confidence %.2f'
                          % (sc, 'integer' if res.get('integer') else 'non-integer', res['native_w'], res['native_h'],
                             res['phase_x'], res['phase_y'], res['confidence']))
    elif res['kind'] == 'soft':
        ev = res['soft_evidence']
        res['verdict'] = ('pixel-art look on a SOFT grid (no crisp pixel edges: resampled or generated): scale ~%.3f '
                          '(alias %.3f), native ~%dx%d; evidence: %s-axis sharpness beat every %.1f px over base x%d, '
                          'comb z=%.1f (other axis z=%.1f); confidence %s'
                          % (res['scale'], ev['alias_scale'], res['native_w'], res['native_h'], ev['axis'],
                             ev['beat_period_px'], ev['base_integer'], ev['comb_z'], ev['other_axis_comb_z'],
                             'medium' if res['confidence'] >= 0.4 else 'low'))
    else:
        bc = res['crisp_candidates']
        res['verdict'] = ('not pixel art: no pixel grid found (best grid confidence x %.2f at %.2f px, y %.2f at %.2f px; '
                          'no grid beat). Finest detail ~%.1f px%s'
                          % (bc['x']['confidence'], bc['x']['scale'], bc['y']['confidence'], bc['y']['scale'], s_eff,
                             ' (soft: probably upscaled or blurred)' if s_eff >= 1.6 else ''))
    return res


def make_native(rgb, grid, mask=None):
    """Downscale along the detected grid: crisp -> centre pixel, soft -> cell mean."""
    cx, cy = grid['cells_x'], grid['cells_y']
    if grid['kind'] == 'crisp':
        xs = np.array([(a + b - 1) // 2 for a, b in cx])
        ys = np.array([(a + b - 1) // 2 for a, b in cy])
        nat = rgb[ys][:, xs]
        nm = mask[ys][:, xs] if mask is not None else None
        return nat, nm
    ii = np.pad(rgb.astype(np.float64), ((1, 0), (1, 0), (0, 0))).cumsum(0).cumsum(1)
    x0 = np.array([a for a, b in cx])
    x1 = np.array([b for a, b in cx])
    y0 = np.array([a for a, b in cy])
    y1 = np.array([b for a, b in cy])
    S = ii[y1][:, x1] - ii[y0][:, x1] - ii[y1][:, x0] + ii[y0][:, x0]
    area = ((y1 - y0)[:, None] * (x1 - x0)[None, :])[..., None]
    nat = np.clip(np.round(S / area), 0, 255).astype(np.uint8)
    nm = None
    if mask is not None:
        ys = np.array([(a + b - 1) // 2 for a, b in cy])
        xs = np.array([(a + b - 1) // 2 for a, b in cx])
        nm = mask[ys][:, xs]
    return nat, nm


# ----------------------------------------------------------------------------
# palette, ramps, outline, background
# ----------------------------------------------------------------------------

def extract_palette(rgb, mask=None, k=32, exact_max=256, seed=0):
    H, W = rgb.shape[:2]
    flat = rgb.reshape(-1, 3)
    sel = np.ones(H * W, bool) if mask is None else mask.reshape(-1)
    px = flat[sel]
    keys = (px[:, 0].astype(np.int64) << 16) | (px[:, 1].astype(np.int64) << 8) | px[:, 2].astype(np.int64)
    uniq, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    labels = np.full(H * W, -1, np.int32)
    if len(uniq) <= exact_max:
        cols = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], 1).astype(np.uint8)
        labels[sel] = inv
        method = 'exact (%d colours)' % len(uniq)
        cnt = counts
    else:
        lab = rgb_to_lab(px)
        C = kmeans(lab, k, seed=seed)
        lbl, _ = assign_nearest(lab, C)
        cnt = np.bincount(lbl, minlength=len(C))
        keep = cnt > 0
        remap = -np.ones(len(C), np.int32)
        remap[keep] = np.arange(keep.sum())
        lbl = remap[lbl]
        cnt = cnt[keep]
        cols = np.stack([np.bincount(lbl, weights=px[:, d].astype(np.float64), minlength=len(cnt)) / cnt for d in range(3)], 1)
        cols = np.clip(np.round(cols), 0, 255).astype(np.uint8)
        labels[sel] = lbl
        method = 'k-means in CIELAB (k=%d) over %d distinct colours' % (len(cnt), len(uniq))
    shares = cnt / cnt.sum()
    return cols, shares, labels.reshape(H, W), method, int(len(uniq))


def group_ramps(cols, shares, link=12.0, neutral_chroma=7.0):
    """Group palette colours into ramps: average-linkage clustering on hue difference
    (discounted for low-chroma colours, whose hue is unreliable, and for large lightness
    steps, where hue shifting is expected), then sort each ramp dark -> light."""
    lab = rgb_to_lab(cols.astype(np.float32))
    L = lab[:, 0]
    C = np.hypot(lab[:, 1], lab[:, 2])
    h = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    neutral = [int(i) for i in np.where(C < neutral_chroma)[0]]
    chrom = [i for i in range(len(cols)) if i not in neutral]
    n = len(cols)
    D = np.zeros((n, n))
    for i in chrom:
        for j in chrom:
            dh = abs((h[i] - h[j] + 180) % 360 - 180)
            w = min(1.0, min(C[i], C[j]) / 15.0)
            D[i, j] = max(0.0, dh * w - 0.5 * abs(L[i] - L[j]))
    groups = [[i] for i in chrom]
    while len(groups) > 1:
        best = None
        for x in range(len(groups)):
            for y in range(x + 1, len(groups)):
                d = D[np.ix_(groups[x], groups[y])].mean()
                if best is None or d < best[0]:
                    best = (d, x, y)
        if best[0] > link:
            break
        _, x, y = best
        groups[x] = groups[x] + groups[y]
        del groups[y]
    ramps = []
    for g in groups + ([neutral] if neutral else []):
        g = sorted(g, key=lambda i: L[i])
        if not g:
            continue
        sh = float(sum(shares[i] for i in g))
        dark, light = cols[g[0]], cols[g[-1]]
        hd = hsv_of(dark)[0] * 360
        hl = hsv_of(light)[0] * 360
        is_neutral = all(C[i] < neutral_chroma for i in g)
        mean_h = float(np.degrees(np.arctan2(np.sum(np.sin(np.radians(h[g])) * shares[g]),
                                             np.sum(np.cos(np.radians(h[g])) * shares[g]))) % 360)
        weighted = cols[g].astype(np.float64).T @ shares[g] / max(1e-9, shares[g].sum())
        ramps.append({
            'members': [int(i) for i in g], 'share': sh, 'neutral': bool(is_neutral),
            'name': 'neutral' if is_neutral else hue_name(weighted),
            'lab_hue_mean': round(mean_h, 1),
            'dark': hexc(dark), 'light': hexc(light),
            'dark_hue': round(hd, 1), 'light_hue': round(hl, 1),
            'hue_shift_dark_to_light': round(hue_delta(hd, hl), 1) if len(g) > 1 and not is_neutral else 0.0,
            'dark_hue_name': hue_name(dark), 'light_hue_name': hue_name(light),
            'L_range': [round(float(L[g[0]]), 1), round(float(L[g[-1]]), 1)],
        })
    ramps.sort(key=lambda r: -r['share'])
    for i, r in enumerate(ramps):
        r['id'] = i
    return ramps, L, C, h


def adjacency_stats(labels, n, Lcol):
    """Per colour: distinct neighbour colours, share of its pixels touching a lighter colour (dL>=15)."""
    H, W = labels.shape
    A = np.zeros((n, n), np.int64)
    for a, b in ((labels[:, :-1], labels[:, 1:]), (labels[:-1, :], labels[1:, :])):
        a = a.ravel()
        b = b.ravel()
        m = (a != b) & (a >= 0) & (b >= 0)
        idx = a[m].astype(np.int64) * n + b[m]
        A += np.bincount(idx, minlength=n * n).reshape(n, n)
    A = A + A.T
    Limg = np.where(labels >= 0, Lcol[np.maximum(labels, 0)], -1.0)
    nb = Limg.copy()
    pad = np.pad(Limg, 1, mode='constant', constant_values=-1.0)
    nb = np.maximum.reduce([pad[1:-1, :-2], pad[1:-1, 2:], pad[:-2, 1:-1], pad[2:, 1:-1]])
    lighter = (nb - Limg) >= 15
    lab = labels.ravel()
    ok = lab >= 0
    touch = np.bincount(lab[ok], weights=lighter.ravel()[ok], minlength=n) / np.maximum(1, np.bincount(lab[ok], minlength=n))
    diversity = np.array([(A[i] >= max(3, 0.02 * A[i].sum())).sum() for i in range(n)])
    return A, touch, diversity, lighter


def outline_analysis(labels, cols, shares, Lcol, Limg_native):
    n = len(cols)
    A, touch, diversity, lighter = adjacency_stats(labels, n, Lcol)
    Ls = np.array(Lcol)
    order = np.argsort(Ls)
    # candidates: darker third of the palette (by pixel share) with real presence
    cum = np.cumsum(shares[order])
    dark_set = set(order[: max(1, int(np.searchsorted(cum, 0.45)) + 1)].tolist())
    cands = []
    for i in range(n):
        if shares[i] < 0.003 or Ls[i] > 45 or i not in dark_set:
            continue
        score = touch[i] * (1 - Ls[i] / 100.0) ** 2 * min(1.0, diversity[i] / 6.0) * min(1.0, shares[i] * 40)
        cands.append((score, i))
    cands.sort(reverse=True)
    top = [i for s, i in cands[:3] if s > 0]
    out = []
    for i in top:
        out.append({'hex': hexc(cols[i]), 'L': round(float(Ls[i]), 1), 'share': round(float(shares[i]), 4),
                    'touches_lighter': round(float(touch[i]), 3), 'neighbour_colours': int(diversity[i])})
    # outline pixels: in the best candidates and touching something lighter
    sel = [i for s, i in cands[:3] if s >= 0.5 * (cands[0][0] if cands else 0)]
    is_cand = np.isin(labels, sel) if sel else np.zeros(labels.shape, bool)
    outline_px = is_cand & lighter
    valid = labels >= 0
    share = float(outline_px.sum() / max(1, valid.sum()))
    # typical line width: runs of locally-dark pixels bounded on both sides
    L = Limg_native
    med = ndi.median_filter(L, size=7)
    dark = (L < med - 12) & valid
    runs = []
    for arr in (dark, dark.T):
        a = arr.astype(np.int8)
        pad = np.pad(a, ((0, 0), (1, 1)))
        d = np.diff(pad, axis=1)
        for r in range(a.shape[0]):
            st = np.where(d[r] == 1)[0]
            en = np.where(d[r] == -1)[0]
            if len(st) == 0:
                continue
            ln = en - st
            okr = (st > 0) & (en < a.shape[1]) & (ln <= 8)
            runs.extend(ln[okr].tolist())
    runs = np.array(runs) if runs else np.array([0])
    hist = np.bincount(runs, minlength=9)[1:9]
    width = int(np.argmax(hist) + 1) if hist.sum() else 0
    return {'candidates': out, 'outline_share': round(share, 4), 'line_width_px': width,
            'line_width_hist_1to8': hist.tolist(), 'dark_line_share': round(float(dark.sum() / max(1, valid.sum())), 4)}


def background_colour(labels, cols, shares):
    border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    border = border[border >= 0]
    res = {}
    if len(border):
        bc = np.bincount(border, minlength=len(cols))
        i = int(bc.argmax())
        res['border_mode'] = {'hex': hexc(cols[i]), 'border_share': round(float(bc[i] / len(border)), 3),
                              'image_share': round(float(shares[i]), 4)}
    j = int(np.argmax(shares))
    res['most_common'] = {'hex': hexc(cols[j]), 'image_share': round(float(shares[j]), 4)}
    if len(border) and res['border_mode']['border_share'] >= 0.25:
        res['background'] = res['border_mode']['hex']
        res['reason'] = 'dominant border colour'
    else:
        res['background'] = res['most_common']['hex']
        res['reason'] = 'most common colour (border is mixed)'
    return res


def draw_palette(cols, shares, ramps, outline, bg, path, title):
    sw, sh = 78, 44
    fnt = font(12)
    tfnt = font(15)
    maxlen = max([len(r['members']) for r in ramps] + [4])
    left = 240
    W = left + maxlen * (sw + 6) + 10
    rows_h = 34 + len(ramps) * (sh + 36) + 90
    img = Image.new('RGB', (max(W, 760), rows_h), (22, 22, 26))
    d = ImageDraw.Draw(img)
    d.text((10, 8), title, font=tfnt, fill=(240, 240, 240))
    y = 34
    for r in ramps:
        txt = 'R%d %s  %.1f%%' % (r['id'], r['name'], 100 * r['share'])
        d.text((10, y + 4), txt, font=font(13), fill=(240, 240, 240))
        if not r['neutral'] and len(r['members']) > 1:
            d.text((10, y + 22), 'dark %s -> light %s (%+.0f deg)' % (r['dark_hue_name'], r['light_hue_name'], r['hue_shift_dark_to_light']),
                   font=fnt, fill=(170, 170, 170))
        x = left
        for i in r['members']:
            c = tuple(int(v) for v in cols[i])
            d.rectangle([x, y, x + sw, y + sh], fill=c, outline=(70, 70, 70))
            d.text((x + 2, y + sh + 3), hexc(c), font=fnt, fill=(220, 220, 220))
            d.text((x + 2, y + sh + 17), '%.1f%%' % (100 * shares[i]), font=fnt, fill=(150, 150, 150))
            x += sw + 6
        y += sh + 36
    y += 6
    d.text((10, y), 'outline candidates:', font=font(13), fill=(240, 240, 240))
    x = 170
    for o in outline['candidates']:
        c = tuple(int(o['hex'][k:k + 2], 16) for k in (1, 3, 5))
        d.rectangle([x, y - 2, x + 30, y + 18], fill=c, outline=(200, 200, 200))
        d.text((x + 36, y + 2), '%s L*%.0f' % (o['hex'], o['L']), font=fnt, fill=(220, 220, 220))
        x += 150
    y += 30
    d.text((10, y), 'background:', font=font(13), fill=(240, 240, 240))
    c = tuple(int(bg['background'][k:k + 2], 16) for k in (1, 3, 5))
    d.rectangle([170, y - 2, 200, y + 18], fill=c, outline=(200, 200, 200))
    d.text((206, y + 2), '%s (%s)' % (bg['background'], bg['reason']), font=fnt, fill=(220, 220, 220))
    img.save(path)


# ----------------------------------------------------------------------------
# value / light / edge maps
# ----------------------------------------------------------------------------

VALUE_BANDS = [20, 40, 60, 80]
VALUE_GREYS = np.array([18, 70, 125, 180, 238], np.uint8)


def value_analysis(Lst, mask, scale_to_ref, out_dir, display_w=1200, base_rgb=None):
    valid = np.ones(Lst.shape, bool) if mask is None else mask
    v = Lst[valid]
    pct = np.percentile(v, [5, 25, 50, 75, 95]) if v.size else np.zeros(5)
    hist, edges = np.histogram(v, bins=20, range=(0, 100))
    band = np.digitize(Lst, VALUE_BANDS)
    shares = [float(((band == i) & valid).sum() / max(1, valid.sum())) for i in range(5)]
    q = np.percentile(v, [20, 40, 60, 80]) if v.size else np.array(VALUE_BANDS, float)
    q = np.maximum.accumulate(q + np.arange(4) * 1e-3)
    rband = np.digitize(Lst, q)
    H, W = Lst.shape
    dw, dh, _ = fit_size(W, H, display_w // 2)
    panels = []
    for bnd, ttl in ((band, 'absolute: L* bands 0-20-40-60-80-100'),
                     (rband, 'relative: image quintiles at L* %s' % '/'.join('%.0f' % t for t in q))):
        img = np.stack([VALUE_GREYS[bnd]] * 3, -1)
        if mask is not None:
            img[~mask] = (255, 0, 255)
        panels.append(title_panel(Image.fromarray(img).resize((dw, dh), Image.NEAREST), ttl, size=13))
    top = hstack(panels)
    leg = Image.new('RGB', (top.width, 112), (22, 22, 26))
    d = ImageDraw.Draw(leg)
    names = ['0-20', '20-40', '40-60', '60-80', '80-100']
    for i in range(5):
        x = 10 + i * 150
        d.rectangle([x, 10, x + 26, 30], fill=(int(VALUE_GREYS[i]),) * 3, outline=(120, 120, 120))
        d.text((x + 32, 12), 'L* %s: %.0f%%' % (names[i], 100 * shares[i]), font=font(12), fill=(230, 230, 230))
    hmax = math.sqrt(max(1, hist.max()))
    bw = (top.width - 20) / 20
    for i, c in enumerate(hist):
        x = 10 + i * bw
        hh = 60 * math.sqrt(c) / hmax
        g = int(edges[i] * 2.4 + 10)
        d.rectangle([x, 104 - hh, x + bw - 2, 104], fill=(g, g, g), outline=(90, 90, 90))
        if i % 2 == 0:
            d.text((x, 104 - hh - 2), '%d' % edges[i], font=font(10), fill=(150, 150, 150), anchor='lb')
    d.text((top.width - 10, 40), 'L* histogram 0..100 (sqrt scale)', font=font(12), fill=(180, 180, 180), anchor='ra')
    out = vstack([title_panel(top, 'value structure (CIELAB L*), mean %.1f, p5/p50/p95 = %.0f/%.0f/%.0f'
                              % (float(v.mean()) if v.size else 0, pct[0], pct[2], pct[4])), leg], gap=0)
    out.save(os.path.join(out_dir, 'values.png'))
    # light map
    diag = math.hypot(W, H)
    sig = max(2.0, 0.035 * diag)
    Lf = np.where(valid, Lst, np.median(v) if v.size else 0).astype(np.float32)
    Lb = ndi.gaussian_filter(Lf, sig)
    win = max(3, int(0.08 * diag)) | 1
    mx = ndi.maximum_filter(Lb, size=win)
    med = float(np.median(Lb))
    pk = np.argwhere((Lb == mx) & (Lb >= med + 5))
    pools = []
    if base_rgb is not None:
        cb = np.stack([ndi.gaussian_filter(base_rgb[..., c].astype(np.float32), sig) for c in range(3)], -1)
    else:
        cb = None
    lowref = ndi.percentile_filter(Lb[::4, ::4], 10, size=max(3, win // 2))
    accepted = []
    for (yy, xx) in sorted(pk.tolist(), key=lambda p: -Lb[p[0], p[1]]):
        if len(accepted) >= 8:
            break
        if any(math.hypot(yy - ay, xx - ax) < win / 2 for ay, ax in accepted):
            continue  # plateau / neighbour of a stronger pool
        if Lb[yy, xx] - lowref[min(lowref.shape[0] - 1, yy // 4), min(lowref.shape[1] - 1, xx // 4)] < 4:
            continue  # not a pool: no darker surroundings
        accepted.append((yy, xx))
    for (yy, xx) in accepted:
        pools.append({'x': int(round((xx + 0.5) * scale_to_ref[0])), 'y': int(round((yy + 0.5) * scale_to_ref[1])),
                      'L_blur': round(float(Lb[yy, xx]), 1),
                      'colour': hexc(cb[yy, xx]) if cb is not None else None,
                      'hue': hue_name(cb[yy, xx]) if cb is not None else None})
    lo, hi = np.percentile(Lb, 1), np.percentile(Lb, 99.5)
    heat = heat_cmap((Lb - lo) / max(1e-6, hi - lo))
    himg = Image.fromarray(heat).resize((dw, dh), Image.BILINEAR)
    panels = [himg]
    if cb is not None:
        gain = 235.0 / max(1.0, float(np.percentile(cb.max(-1), 99.5)))
        panels.append(Image.fromarray(np.clip(cb * gain, 0, 255).astype(np.uint8)).resize(himg.size, Image.BILINEAR))
    fx = himg.width / W
    fy = himg.height / H
    for p_img in panels:
        dd = ImageDraw.Draw(p_img)
        for i, p in enumerate(pools):
            px_ = p['x'] / scale_to_ref[0] * fx
            py_ = p['y'] / scale_to_ref[1] * fy
            dd.ellipse([px_ - 7, py_ - 7, px_ + 7, py_ + 7], outline=(0, 255, 255), width=2)
            right = px_ > p_img.width - 110
            label(dd, (px_ - 9 if right else px_ + 9, py_ - 8), '#%d (%d,%d)' % (i + 1, p['x'], p['y']), font(12), bg=(0, 0, 0),
                  anchor='ra' if right else 'la')
    lt = hstack(panels)
    lt = title_panel(lt, 'light map: blur sigma %.0f analysis px | left: brightness | right: blurred colour (brightened x%.1f) | circles = light pools'
                     % (sig, gain if cb is not None else 1.0))
    lt.save(os.path.join(out_dir, 'light.png'))
    return {'L_mean': round(float(v.mean()), 2) if v.size else None, 'L_percentiles_5_25_50_75_95': [round(float(p), 1) for p in pct],
            'histogram_L_0_100_20bins': hist.tolist(), 'band_shares_0_20_40_60_80_100': [round(s, 4) for s in shares],
            'key': 'low-key (dark)' if pct[2] < 30 else ('high-key (bright)' if pct[2] > 65 else 'mid-key'),
            'light_pools': pools, 'light_blur_sigma_analysis_px': round(sig, 1)}


def edge_analysis(Lst, mask, out_dir, display_w=1200, scale_to_ref=(1, 1)):
    gx = ndi.sobel(Lst, 1) / 8.0
    gy = ndi.sobel(Lst, 0) / 8.0
    mag = np.hypot(gx, gy)
    edges = mag > 6.0
    if mask is not None:
        edges &= mask
    H, W = Lst.shape
    win = max(5, int(0.04 * math.hypot(W, H)))
    dens = ndi.uniform_filter(edges.astype(np.float32), size=win)
    valid = np.ones(Lst.shape, bool) if mask is None else mask
    overall = float(edges.sum() / max(1, valid.sum()))
    dmax = max(1e-6, float(np.percentile(dens, 99.5)))
    heat = heat_cmap(dens / dmax).astype(np.float32)
    base = np.clip(Lst * 2.55, 0, 255)[..., None].repeat(3, -1) * 0.35
    out = np.clip(base * 0.5 + heat * 0.75, 0, 255).astype(np.uint8)
    edge_layer = np.where(edges[..., None], np.array([255, 255, 255], np.uint8), (base).astype(np.uint8))
    dw, dh, _ = fit_size(W, H, display_w // 2)
    p1 = Image.fromarray(edge_layer).resize((dw, dh), Image.NEAREST)
    p2 = Image.fromarray(out).resize((dw, dh), Image.BILINEAR)
    # densest cells (4x3)
    cells = []
    for r in range(3):
        for c in range(4):
            y0, y1 = r * H // 3, (r + 1) * H // 3
            x0, x1 = c * W // 4, (c + 1) * W // 4
            cells.append({'x0': int(x0 * scale_to_ref[0]), 'y0': int(y0 * scale_to_ref[1]), 'x1': int(x1 * scale_to_ref[0]),
                          'y1': int(y1 * scale_to_ref[1]), 'edge_density': round(float(edges[y0:y1, x0:x1].mean()), 4)})
    img = hstack([p1, p2])
    img = vstack([title_panel(img, 'edges (|grad L*| > 6/px): %.1f%% of pixels | right: edge density (window %d px)' % (100 * overall, win)),
                  colorbar(img.width, [(0, '0'), (0.5, '%.2f' % (dmax / 2)), (1, '%.2f' % dmax)], heat_cmap, title='edge density')], gap=4)
    img.save(os.path.join(out_dir, 'edges.png'))
    return {'edge_share': round(overall, 4), 'density_cells_4x3': cells}


# ----------------------------------------------------------------------------
# tiles + overview
# ----------------------------------------------------------------------------

def make_tiles(img_pil, out_dir, cols=6, rows=4, overlap=0.08, zoom=0):
    W, H = img_pil.size
    tdir = ensure_dir(os.path.join(out_dir, 'tiles'))
    tw, th = W / cols, H / rows
    ox, oy = tw * overlap, th * overlap
    if not zoom:
        zoom = int(max(2, min(6, round(880 / max(tw + 2 * ox, th + 2 * oy)))))
    tiles = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(round(c * tw - ox)))
            x1 = min(W, int(round((c + 1) * tw + ox)))
            y0 = max(0, int(round(r * th - oy)))
            y1 = min(H, int(round((r + 1) * th + oy)))
            z = zoom_crop(img_pil, x0, y0, x1, y1, zoom)
            t = add_ruler(z, x0, y0, zoom, title='tile r%d c%d   x %d-%d   y %d-%d   x%d' % (r, c, x0, x1, y0, y1, zoom))
            p = os.path.join(tdir, 'tile_r%d_c%d.png' % (r, c))
            t.save(p)
            tiles.append({'row': r, 'col': c, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1, 'path': rel(p, out_dir)})
    # overview
    dw, dh, s = fit_size(W, H, min(1600, max(W, 900)))
    ov = img_pil.convert('RGB').resize((dw, dh), Image.LANCZOS if s < 1 else Image.NEAREST)
    d = ImageDraw.Draw(ov)
    fnt = font(16)
    for c in range(1, cols):
        x = c * tw * s
        d.line([(x, 0), (x, dh)], fill=(0, 0, 0), width=3)
        d.line([(x, 0), (x, dh)], fill=(255, 220, 60), width=1)
    for r in range(1, rows):
        y = r * th * s
        d.line([(0, y), (dw, y)], fill=(0, 0, 0), width=3)
        d.line([(0, y), (dw, y)], fill=(255, 220, 60), width=1)
    for r in range(rows):
        for c in range(cols):
            label(d, (c * tw * s + 5, r * th * s + 5), 'r%dc%d' % (r, c), fnt, fg=(255, 230, 90), bg=(0, 0, 0))
            label(d, (c * tw * s + 5, r * th * s + 27), '%d,%d' % (int(c * tw), int(r * th)), font(12), fg=(220, 220, 220), bg=(0, 0, 0))
    ov = add_ruler(ov, 0, 0, s, title='overview %dx%d - tiles %dx%d (cols x rows), overlap %d%%, tile zoom x%d'
                   % (W, H, cols, rows, int(overlap * 100), zoom), grid=False)
    ov.save(os.path.join(out_dir, 'overview_grid.png'))
    return tiles, zoom


# ----------------------------------------------------------------------------
# image analysis
# ----------------------------------------------------------------------------

def analyze_image(path, out_dir, grid_cols=6, grid_rows=4, overlap=0.08, zoom=0, k=32, tiles=True, rgb=None, mask=None,
                  label_name=None):
    t0 = time.time()
    ensure_dir(out_dir)
    if rgb is None:
        rgb, mask = load_image(path)
    H, W = rgb.shape[:2]
    res = {'file': os.path.abspath(path) if path else None, 'width': W, 'height': H,
           'has_alpha': mask is not None}
    grid = detect_pixel_grid(rgb)
    res['pixel_grid'] = {k_: v for k_, v in grid.items() if not k_.startswith('cells_')}
    if grid['kind'] in ('crisp', 'soft'):
        nat, nmask = make_native(rgb, grid, mask)
        Image.fromarray(nat).save(os.path.join(out_dir, 'native.png'))
        res['native_png'] = 'native.png'
        sref = (W / nat.shape[1], H / nat.shape[0])
        ana, amask, units = nat, nmask, 'native px'
    else:
        # analysis copy, at most ~1.2 MP for speed
        f = max(1.0, math.sqrt(W * H / 1.2e6))
        if f > 1.01:
            aw, ah = int(round(W / f)), int(round(H / f))
            ana = np.asarray(Image.fromarray(rgb).resize((aw, ah), Image.BOX))
            amask = None if mask is None else np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((aw, ah), Image.NEAREST)) > 127
        else:
            ana, amask = rgb, mask
        sref = (W / ana.shape[1], H / ana.shape[0])
        units = 'analysis px (x%.2f = reference px)' % sref[0] if f > 1.01 else 'reference px'
    res['analysis_units'] = units
    res['analysis_size'] = [int(ana.shape[1]), int(ana.shape[0])]
    # palette
    cols, shares, labels, method, n_unique = extract_palette(ana, amask, k=k)
    ramps, Lcol, Ccol, hcol = group_ramps(cols, shares)
    ramp_of = {}
    for r in ramps:
        for i in r['members']:
            ramp_of[i] = r['id']
    Lst = rgb_to_Lstar(ana)
    outline = outline_analysis(labels, cols, shares, Lcol, Lst)
    bg = background_colour(labels, cols, shares)
    title = 'palette: %s | %d ramps (hue clusters, sorted dark -> light)' % (method, len(ramps))
    draw_palette(cols, shares, ramps, outline, bg, os.path.join(out_dir, 'palette.png'), title)
    pal = [{'hex': hexc(cols[i]), 'share': round(float(shares[i]), 5), 'ramp': int(ramp_of.get(i, -1)),
            'L': round(float(Lcol[i]), 1), 'C': round(float(Ccol[i]), 1), 'lab_hue': round(float(hcol[i]), 1)}
           for i in np.argsort(-shares)]
    with open(os.path.join(out_dir, 'palette.json'), 'w') as f:
        json.dump(jsonable({'method': method, 'distinct_colours_in_analysis_image': n_unique, 'colours': pal,
                            'ramps': [{**r, 'members': [hexc(cols[i]) for i in r['members']]} for r in ramps],
                            'outline': outline, 'background': bg}), f, indent=1)
    res['palette'] = {'method': method, 'size': len(cols), 'distinct_colours': n_unique, 'ramps': [
        {'id': r['id'], 'name': r['name'], 'share': round(r['share'], 4), 'n': len(r['members']),
         'dark': r['dark'], 'light': r['light'], 'hue_shift_dark_to_light': r['hue_shift_dark_to_light'],
         'dark_hue_name': r['dark_hue_name'], 'light_hue_name': r['light_hue_name'], 'L_range': r['L_range']} for r in ramps],
        'top_colours': pal[:12], 'files': ['palette.png', 'palette.json']}
    res['outline'] = outline
    res['background'] = bg
    # value / light / edges
    res['values'] = value_analysis(Lst, amask, sref, out_dir, base_rgb=ana)
    res['edges'] = edge_analysis(Lst, amask, out_dir, scale_to_ref=sref)
    if tiles:
        tl, z = make_tiles(Image.fromarray(rgb), out_dir, grid_cols, grid_rows, overlap, zoom)
        res['tiles'] = {'cols': grid_cols, 'rows': grid_rows, 'zoom': z, 'overlap': overlap, 'list': tl,
                        'overview': 'overview_grid.png'}
    res['outputs'] = sorted(f for f in os.listdir(out_dir) if f.endswith('.png') or f.endswith('.json'))
    res['seconds'] = round(time.time() - t0, 2)
    return res


def summarize_image(res, name):
    g = res['pixel_grid']
    p = res['palette']
    o = res['outline']
    v = res['values']
    lines = ['IMAGE %s  %dx%d%s' % (name, res['width'], res['height'], '  (has alpha)' if res['has_alpha'] else ''),
             '  pixel grid : ' + g['verdict']]
    if 'native_png' in res:
        lines.append('  native     : %dx%d -> native.png' % (g['native_w'], g['native_h']))
    lines.append('  palette    : %d colours, %s; %d ramps -> palette.png / palette.json' % (p['size'], p['method'], len(p['ramps'])))
    for r in p['ramps'][:8]:
        hs = '' if r['name'] == 'neutral' or r['n'] < 2 else ', hue %s -> %s (%+.0f deg)' % (r['dark_hue_name'], r['light_hue_name'], r['hue_shift_dark_to_light'])
        lines.append('      R%d %-8s %4.1f%%  %d cols  %s..%s  L* %.0f-%.0f%s' % (r['id'], r['name'], 100 * r['share'], r['n'], r['dark'], r['light'], r['L_range'][0], r['L_range'][1], hs))
    lines.append('  background : %s (%s)' % (res['background']['background'], res['background']['reason']))
    oc = ', '.join('%s L*%.0f touch %.0f%%' % (c['hex'], c['L'], 100 * c['touches_lighter']) for c in o['candidates']) or 'none'
    lines.append('  outline    : %s; outline px %.1f%%; dark-line width ~%d %s' % (oc, 100 * o['outline_share'], o['line_width_px'], res['analysis_units']))
    lines.append('  values     : %s, mean L* %.0f, p5/p50/p95 %.0f/%.0f/%.0f, bands %s' % (
        v['key'], v['L_mean'] or 0, v['L_percentiles_5_25_50_75_95'][0], v['L_percentiles_5_25_50_75_95'][2],
        v['L_percentiles_5_25_50_75_95'][4], '/'.join('%.0f' % (100 * s) for s in v['band_shares_0_20_40_60_80_100'])))
    if v['light_pools']:
        lines.append('  light pools: ' + '  '.join('#%d(%d,%d) %s %s' % (i + 1, p_['x'], p_['y'], p_['colour'] or '', p_['hue'] or '') for i, p_ in enumerate(v['light_pools'][:6])))
    lines.append('  edges      : %.1f%% edge pixels -> edges.png' % (100 * res['edges']['edge_share']))
    if 'tiles' in res:
        t = res['tiles']
        lines.append('  tiles      : %d tiles (%d cols x %d rows) at x%d -> tiles/, overview_grid.png' % (len(t['list']), t['cols'], t['rows'], t['zoom']))
    lines.append('  time       : %.1fs' % res['seconds'])
    return '\n'.join(lines)


# ----------------------------------------------------------------------------
# video analysis
# ----------------------------------------------------------------------------

def _block_view(a, B):
    h, w = a.shape[:2]
    bh, bw = h // B, w // B
    return a[:bh * B, :bw * B].reshape(bh, B, bw, B).transpose(0, 2, 1, 3).reshape(bh, bw, B * B)


def _kth_block(d, B, k=4):
    v = _block_view(d, B)
    return np.partition(v, -k, axis=2)[..., -k]


def _noise_threshold(values):
    """Change threshold from per-block robust-max frame differences: find where the codec-noise
    mode has decayed to 1% of its peak (noise ceiling) and keep a 2.5x safety margin so that slow
    light modulation and fades below it do not count as new drawings."""
    v = np.asarray(values).ravel()
    if v.size == 0:
        return 12
    h = np.bincount(np.minimum(v, 255).astype(np.int64), minlength=256).astype(np.float64)
    hs = ndi.uniform_filter1d(h, 3)
    m0 = int(np.argmax(hs[:40]))
    peak = hs[m0]
    j = next((k for k in range(m0 + 1, 64) if hs[k] <= 0.01 * peak), None)
    if j is None:
        j = int(np.percentile(v, 90))
    return int(min(48, max(12, round(2.5 * j))))


def _phase_shift(a, b):
    """Estimated (dx, dy) translation of b relative to a and peak sharpness."""
    A = np.fft.fft2(a - a.mean())
    Bf = np.fft.fft2(b - b.mean())
    R = A.conj() * Bf
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    i = np.unravel_index(np.argmax(r), r.shape)
    dy, dx = i
    if dy > r.shape[0] // 2:
        dy -= r.shape[0]
    if dx > r.shape[1] // 2:
        dx -= r.shape[1]
    return int(dx), int(dy), float(r.max() / (np.abs(r).mean() + 1e-9))


def _weighted_median(v, w):
    v = np.asarray(v, np.float64)
    w = np.asarray(w, np.float64)
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][int(np.searchsorted(c, c[-1] / 2))])


def _find_period(Dl):
    """Period (frames) from a self-difference-vs-lag curve Dl[L-1] (L = 1..): the first clear
    dip below the curve's typical level after the initial rise."""
    if len(Dl) < 6:
        return None
    med = float(np.median(Dl))
    if med <= 1e-6:
        return None
    start = next((k for k in range(len(Dl)) if Dl[k] >= 0.6 * med), None)
    if start is None:
        return None
    for k in range(max(start, 1), len(Dl) - 1):
        if Dl[k] <= Dl[k - 1] and Dl[k] <= Dl[k + 1] and Dl[k] <= 0.6 * med:
            return k + 1
    return None


def _holds_from(idx, excl_cum):
    """Hold lengths between consecutive change frames, skipping spans that cross excluded frames."""
    if len(idx) < 2:
        return np.zeros(0, np.int32)
    a, b = idx[:-1], idx[1:]
    ok = (excl_cum[b] - excl_cum[a]) == 0
    return (b - a)[ok]


def _trimmed_rate(holds, fps, max_hold):
    h = holds[(holds >= 1) & (holds <= max_hold)]
    if len(h) < 3:
        return 0.0
    lo, hi = np.percentile(h, [10, 90])
    hh = h[(h >= lo) & (h <= hi)]
    if len(hh) == 0:
        hh = h
    return float(fps / hh.mean())


def _hold_verdict(holds, fps, max_hold):
    h = holds[(holds >= 1) & (holds <= max_hold)]
    if len(h) < 5:
        return 'not enough animation to judge', {}
    cnt = np.bincount(np.minimum(h, 6), minlength=7)[1:]
    sh = cnt / cnt.sum()
    names = {1: 'ones', 2: 'twos', 3: 'threes', 4: 'fours', 5: 'fives', 6: 'sixes+'}
    order = np.argsort(-sh)
    rate = _trimmed_rate(holds, fps, max_hold)
    a = order[0] + 1
    txt = 'mostly on %s (%.0f%%)' % (names[a], 100 * sh[a - 1])
    if sh[order[1]] >= 0.2:
        b = order[1] + 1
        txt += ' and %s (%.0f%%)' % (names[b], 100 * sh[b - 1])
    txt += ' at %.3g fps -> ~%.1f drawings/s while animating' % (fps, rate)
    return txt, {names[i + 1]: round(float(sh[i]), 3) for i in range(6)}


def _rate_colour(r):
    stops = [(0.5, (60, 60, 200)), (4, (40, 140, 230)), (7, (40, 200, 200)), (9, (60, 200, 90)), (11, (190, 220, 50)),
             (13, (250, 190, 40)), (17, (250, 120, 30)), (25, (235, 50, 40)), (1e9, (230, 60, 200))]
    for lim, c in stops:
        if r < lim:
            return c
    return stops[-1][1]


RATE_LEGEND = [('<4', 0.5), ('4-7', 4), ('7-9', 7), ('9-11', 9), ('11-13', 11), ('13-17', 13), ('17-25', 17),
               ('25+ (every frame: movement, fades, moving light)', 25)]


ANALYSIS_TARGET_W = 800.0  # speed: frames are measured at roughly this width (integer downscale)


def analyze_video(path, out_dir, sheet_fps=4.0, sheet_cols=6, cells=(8, 6), cut_thresh=0.3, regions=None,
                  n_keyframes=3, noise=None, keyframe_image_analysis=True):
    t_start = time.time()
    ensure_dir(out_dir)
    info = ffprobe_info(path)
    W, H, fps = info['width'], info['height'], info['fps']
    fac = max(1, int(round(W / ANALYSIS_TARGET_W)))
    aw, ah = W // fac, H // fac
    aw -= aw % 2
    ah -= ah % 2
    sx, sy = W / aw, H / ah
    B = int(min(24, max(6, round(aw / 60))))
    bh, bw = ah // B, aw // B
    vf = 'scale=%d:%d:flags=area' % (aw, ah) if (aw, ah) != (W, H) else None
    regions = regions or []
    res = {'file': os.path.abspath(path), 'probe': info,
           'analysis': {'width': aw, 'height': ah, 'downscale': round(sx, 4), 'block_px_analysis': B,
                        'block_px_reference': round(B * sx, 2)}}
    # --- noise threshold from a few short samples
    if noise is None:
        samples = []
        dur = max(0.1, info['duration'])
        for frac in (0.2, 0.5, 0.8):
            prev = None
            for fr in ffmpeg_frames(path, aw, ah, ss=dur * frac, vf=vf, max_frames=int(min(40, max(8, fps)))):
                f16 = fr.astype(np.int16)
                if prev is not None:
                    samples.append(_kth_block(np.abs(f16 - prev).max(2).astype(np.uint8), B))
                prev = f16
        T = _noise_threshold(np.array(samples)) if samples else 12
        res['analysis']['noise_threshold'] = T
        res['analysis']['noise_threshold_source'] = 'auto (valley after the codec-noise mode of per-block 4th-largest differences)'
    else:
        T = int(noise)
        res['analysis']['noise_threshold'] = T
        res['analysis']['noise_threshold_source'] = 'user'
    # --- main pass
    n_est = info['frames'] + 5
    bk = np.zeros((n_est, bh, bw), np.uint8)
    frac_changed = np.zeros(n_est, np.float32)
    gdiff = np.zeros(n_est, np.float32)
    hists = np.zeros((n_est, 512), np.float32)
    tw_small = 128
    th_small = max(8, int(round(ah * tw_small / aw)))
    smalls = np.zeros((n_est, th_small, tw_small), np.uint8)
    motion = np.zeros((ah, aw), np.int32)
    motion_frames = 0
    sheet = []
    thumb_w = 288
    thumb_h = int(round(ah * thumb_w / aw))
    reg_a = []
    for (x0, y0, x1, y1) in regions:
        ax0, ay0 = int(max(0, math.floor(x0 / sx))), int(max(0, math.floor(y0 / sy)))
        ax1, ay1 = int(min(aw, math.ceil(x1 / sx))), int(min(ah, math.ceil(y1 / sy)))
        ax1, ay1 = max(ax1, ax0 + 1), max(ay1, ay0 + 1)
        rw, rh = ax1 - ax0, ay1 - ay0
        f = max(1, int(math.ceil(max(rw, rh) / 40)))
        reg_a.append({'box': (ax0, ay0, ax1, ay1), 'flag': np.zeros(n_est, bool), 'mag': np.zeros(n_est, np.float32),
                      'small': [], 'sf': f})
    mid_frame = None
    shifts_at = {}
    buf_n = int(round(4 * fps))
    head_buf = {}
    tail_buf = collections.deque(maxlen=buf_n)
    mid_idx = info['frames'] // 2
    prev = None
    n = 0
    next_sheet_t = 0.0
    for fr in ffmpeg_frames(path, aw, ah, vf=vf):
        if n >= n_est:
            grow = n_est // 2 + 10
            bk = np.concatenate([bk, np.zeros((grow, bh, bw), np.uint8)])
            frac_changed = np.concatenate([frac_changed, np.zeros(grow, np.float32)])
            gdiff = np.concatenate([gdiff, np.zeros(grow, np.float32)])
            hists = np.concatenate([hists, np.zeros((grow, 512), np.float32)])
            smalls = np.concatenate([smalls, np.zeros((grow, th_small, tw_small), np.uint8)])
            for r in reg_a:
                r['flag'] = np.concatenate([r['flag'], np.zeros(grow, bool)])
                r['mag'] = np.concatenate([r['mag'], np.zeros(grow, np.float32)])
            n_est += grow
        f16 = fr.astype(np.int16)
        sub = fr[::4, ::4]
        q = (sub[..., 0] >> 5).astype(np.int32) * 64 + (sub[..., 1] >> 5).astype(np.int32) * 8 + (sub[..., 2] >> 5)
        hh = np.bincount(q.ravel(), minlength=512).astype(np.float32)
        hists[n] = hh / hh.sum()
        g = luma8(fr)
        smalls[n] = np.asarray(Image.fromarray(g.astype(np.uint8)).resize((tw_small, th_small), Image.BOX))
        if prev is not None:
            d = np.abs(f16 - prev).max(2).astype(np.uint8)
            kb = _kth_block(d, B)
            bk[n] = kb
            fc = float((kb > T).mean())
            frac_changed[n] = fc
            gdiff[n] = float(d.mean())
            if fc < 0.3:
                motion += d > T
                motion_frames += 1
            else:
                shifts_at[n] = _phase_shift(luma8(prev), luma8(f16))
            for r in reg_a:
                ax0, ay0, ax1, ay1 = r['box']
                sd = d[ay0:ay1, ax0:ax1]
                c = int((sd > T).sum())
                r['flag'][n] = c >= max(2, 0.002 * sd.size)
                r['mag'][n] = float(sd.mean())
        for r in reg_a:
            ax0, ay0, ax1, ay1 = r['box']
            crop = g[ay0:ay1, ax0:ax1]
            f_ = r['sf']
            hh_, ww_ = crop.shape[0] // f_, crop.shape[1] // f_
            if hh_ >= 1 and ww_ >= 1:
                r['small'].append(crop[:hh_ * f_, :ww_ * f_].reshape(hh_, f_, ww_, f_).mean((1, 3)).astype(np.float32))
            else:
                r['small'].append(crop.astype(np.float32))
        t = n / fps
        if t + 1e-6 >= next_sheet_t:
            sheet.append((n, Image.fromarray(fr).resize((thumb_w, thumb_h), Image.BOX)))
            next_sheet_t += 1.0 / sheet_fps
        if n == mid_idx:
            mid_frame = fr.copy()
        gh = g[:(ah // 2) * 2, :(aw // 2) * 2].reshape(ah // 2, 2, aw // 2, 2).mean((1, 3)).astype(np.uint8)
        if n < buf_n:
            head_buf[n] = gh
        tail_buf.append((n, gh))
        prev = f16
        n += 1
    if n < 2:
        raise SystemExit('could not decode frames from ' + path)
    bk, frac_changed, gdiff, hists, smalls = bk[:n], frac_changed[:n], gdiff[:n], hists[:n], smalls[:n]
    if mid_frame is None:
        mid_frame = fr.copy()
    dur = n / fps
    res['analysis']['decoded_frames'] = n
    res['analysis']['decode_seconds'] = round(time.time() - t_start, 1)
    # --- scene cuts (colour histogram jump that persists; shift-invariant so shakes/pans do not count)
    hd = np.zeros(n, np.float32)
    hd[1:] = 0.5 * np.abs(hists[1:] - hists[:-1]).sum(1)
    cuts = []
    for i in np.where(hd > cut_thresh)[0]:
        j = min(n - 1, i + max(2, int(round(fps * 0.15))))
        persist = 0.5 * np.abs(hists[j] - hists[i - 1]).sum()
        if persist > 0.6 * cut_thresh and (not cuts or (i - cuts[-1]) / fps >= 0.3):
            cuts.append(int(i))
    bounds = [0] + cuts + [n]
    shots = [{'index': k, 'start_frame': bounds[k], 'end_frame': bounds[k + 1] - 1, 'start': round(bounds[k] / fps, 3),
              'end': round(bounds[k + 1] / fps, 3), 'duration': round((bounds[k + 1] - bounds[k]) / fps, 3)} for k in range(len(bounds) - 1)]
    res['cuts'] = [{'frame': c, 'time': round(c / fps, 3), 'timecode': fmt_t(c / fps), 'hist_jump': round(float(hd[c]), 3)} for c in cuts]
    # --- global events (camera shake / pan / flash): most of the frame changes at once
    excl = np.zeros(n, bool)
    excl[0] = True
    for c in cuts:
        excl[c] = True
    glob = (frac_changed > 0.3) & ~excl
    events = []
    i = 1
    while i < n:
        if glob[i]:
            j = i
            while j + 1 < n and (glob[j + 1] or (j + 2 < n and glob[j + 2])):
                j += 1
            shifts = [shifts_at[k] for k in range(i, j + 1) if k in shifts_at]
            moved = [s for s in shifts if (s[0] or s[1]) and s[2] > 8]
            kind = 'camera shake/pan (image shifts)' if len(moved) >= max(1, len(shifts) // 2) else 'global change (flash, fade, transition or large effect)'
            mx = max((math.hypot(s[0], s[1]) for s in moved), default=0) * sx
            events.append({'start': round(i / fps, 3), 'end': round((j + 1) / fps, 3), 'frames': j - i + 1, 'kind': kind,
                           'max_shift_px_approx': round(float(mx), 1), 'timecode': fmt_t(i / fps)})
            excl[max(0, i - 1):min(n, j + 2)] = True
            i = j + 1
        i += 1
    res['global_events'] = events
    valid = ~excl
    excl_cum = np.cumsum(excl.astype(np.int32))
    valid_dur = max(1e-6, valid.sum() / fps)
    max_hold = max(2, int(round(fps * 0.5)))
    # --- overall and per-shot drawing rate
    ch = bk > T
    any_change = ch.reshape(n, -1).any(1)
    res['drawing_rate'] = {
        'frames_with_any_change_per_s': round(float(any_change[valid].sum() / valid_dur), 2),
        'note': 'any-change rate is the union of every independently animated element; per-cell rates below separate them',
        'excluded_frames': int(excl.sum()), 'max_hold_considered_frames': max_hold, 'video_fps': fps}
    # per block
    nb = bh * bw
    chv = ch & valid[:, None, None]
    counts = chv.reshape(n, nb).sum(0)
    block_rate = np.zeros(nb, np.float32)
    block_holds = [None] * nb
    flat = chv.reshape(n, nb)
    for b in np.where(counts >= 6)[0]:
        idx = np.nonzero(flat[:, b])[0]
        hld = _holds_from(idx, excl_cum)
        block_holds[b] = hld
        block_rate[b] = _trimmed_rate(hld, fps, max_hold)
    block_rate = block_rate.reshape(bh, bw)
    animated = (block_rate > 0)
    all_h = np.concatenate([h for h in block_holds if h is not None and len(h)] or [np.zeros(0, np.int32)])
    verdict, hold_shares = _hold_verdict(all_h, fps, max_hold)
    res['drawing_rate']['verdict'] = verdict
    res['drawing_rate']['hold_shares'] = hold_shares
    res['drawing_rate']['typical_rate_while_animating'] = round(_trimmed_rate(all_h, fps, max_hold), 2)
    res['drawing_rate']['animated_area_share'] = round(float(animated.mean()), 4)
    # per shot
    for s in shots:
        a, b = s['start_frame'], s['end_frame'] + 1
        v = valid[a:b]
        vd = max(1e-6, v.sum() / fps)
        s['frames_with_any_change_per_s'] = round(float(any_change[a:b][v].sum() / vd), 2)
        hs = []
        sub = flat[a:b]
        ec = np.concatenate([[0], np.cumsum(excl[a:b].astype(np.int32))])[1:]
        for bb in np.where(sub.sum(0) >= 6)[0]:
            hs.append(_holds_from(np.nonzero(sub[:, bb])[0], ec))
        hs = np.concatenate(hs) if hs else np.zeros(0, np.int32)
        s['typical_rate_while_animating'] = round(_trimmed_rate(hs, fps, max_hold), 2)
        s['verdict'] = _hold_verdict(hs, fps, max_hold)[0]
    res['shots'] = shots
    # per cell
    cx_n, cy_n = cells
    cell_res = []
    win = max(1, int(round(fps)))
    for r in range(cy_n):
        for c in range(cx_n):
            x0, x1 = c * aw / cx_n, (c + 1) * aw / cx_n
            y0, y1 = r * ah / cy_n, (r + 1) * ah / cy_n
            bx = [b for b in range(bw) if x0 <= (b + 0.5) * B < x1]
            by = [b for b in range(bh) if y0 <= (b + 0.5) * B < y1]
            brs = [float(block_rate[yy, xx]) for yy in by for xx in bx if block_rate[yy, xx] > 0]
            bws = [float(counts[yy * bw + xx]) for yy in by for xx in bx if block_rate[yy, xx] > 0]
            rate = _weighted_median(brs, bws) if brs else 0.0
            ones = [block_holds[yy * bw + xx] for yy in by for xx in bx if block_rate[yy, xx] > 0]
            ones = np.concatenate(ones) if ones else np.zeros(0, np.int32)
            ones_share = float((ones == 1).mean()) if len(ones) else 0.0
            union = chv[:, by][:, :, bx].reshape(n, -1).any(1) if bx and by else np.zeros(n, bool)
            nwin = max(1, n // win)
            act = union[:nwin * win].reshape(nwin, win).any(1).mean() if n >= win else float(union.any())
            n_anim = int(sum(1 for yy in by for xx in bx if animated[yy, xx]))
            cell_res.append({'row': r, 'col': c, 'x0': int(x0 * sx), 'y0': int(y0 * sy), 'x1': int(x1 * sx), 'y1': int(y1 * sy),
                             'rate_while_animating': round(rate, 2), 'changes_per_s': round(float(union.sum() / valid_dur), 2),
                             'active_share': round(float(act), 3), 'animated_blocks': n_anim,
                             'block_rate_range': [round(min(brs), 1), round(max(brs), 1)] if brs else None,
                             'hold1_share': round(ones_share, 3),
                             'blocks': len(bx) * len(by)})
    res['cells'] = {'cols': cx_n, 'rows': cy_n, 'list': cell_res}
    # --- rate maps
    base = Image.fromarray(mid_frame).resize((W if W <= 1600 else 1600, int(round(H * (W if W <= 1600 else 1600) / W))), Image.BOX)
    dimg = Image.fromarray((np.asarray(base).astype(np.float32) * 0.45).astype(np.uint8))
    dw_, dh_ = dimg.size
    rm = dimg.copy().convert('RGBA')
    ov = Image.new('RGBA', rm.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for cr in cell_res:
        x0, y0 = cr['x0'] * dw_ / W, cr['y0'] * dh_ / H
        x1, y1 = cr['x1'] * dw_ / W, cr['y1'] * dh_ / H
        if cr['rate_while_animating'] > 0:
            col = _rate_colour(cr['rate_while_animating'])
            od.rectangle([x0, y0, x1, y1], fill=col + (int(40 + 100 * min(1, cr['animated_blocks'] / max(1, cr['blocks']) * 3)),))
        od.rectangle([x0, y0, x1, y1], outline=(255, 255, 255, 90))
    rm = Image.alpha_composite(rm, ov).convert('RGB')
    d = ImageDraw.Draw(rm)
    big = font(max(14, int(dw_ / cx_n / 5)))
    small = font(max(11, int(dw_ / cx_n / 11)))
    for cr in cell_res:
        x0, y0 = cr['x0'] * dw_ / W, cr['y0'] * dh_ / H
        x1, y1 = cr['x1'] * dw_ / W, cr['y1'] * dh_ / H
        cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
        txt = '%.1f' % cr['rate_while_animating'] if cr['rate_while_animating'] > 0 else '0'
        label(d, (cxm, cym - 4), txt, big, fg=(255, 255, 255), bg=(0, 0, 0), anchor='mb')
        if cr['rate_while_animating'] > 0:
            label(d, (cxm, cym + 4), 'act %d%%  %d/%d blk' % (round(100 * cr['active_share']), cr['animated_blocks'], cr['blocks']),
                  small, fg=(220, 220, 220), bg=(0, 0, 0), anchor='mt')
        label(d, (x0 + 3, y0 + 3), 'r%dc%d' % (cr['row'], cr['col']), small, fg=(170, 170, 170), bg=None)
    leg = Image.new('RGB', (dw_, 34), (22, 22, 26))
    ld = ImageDraw.Draw(leg)
    ld.text((8, 10), 'drawings/s:', font=font(12), fill=(230, 230, 230))
    x = 90
    for txt, v in RATE_LEGEND:
        ld.rectangle([x, 8, x + 22, 26], fill=_rate_colour(v + 0.01))
        ld.text((x + 26, 10), txt, font=font(12), fill=(230, 230, 230))
        x += 26 + text_wh(ld, txt, font(12))[0] + 16
    rate_img = vstack([title_panel(rm, 'drawings/s per cell while animating (change-weighted median of its blocks); act = share of seconds with change; '
                                   'blk = animated/all blocks; %.3g fps, threshold %d' % (fps, T)), leg], gap=0)
    rate_img.save(os.path.join(out_dir, 'rate_map.png'))
    # fine block map
    fb = np.asarray(dimg).copy()
    bimg = np.zeros((bh, bw, 3), np.uint8)
    bmask = np.zeros((bh, bw), bool)
    for yy in range(bh):
        for xx in range(bw):
            if block_rate[yy, xx] > 0:
                bimg[yy, xx] = _rate_colour(block_rate[yy, xx])
                bmask[yy, xx] = True
    up = np.asarray(Image.fromarray(bimg).resize((int(round(bw * B * sx * dw_ / W)), int(round(bh * B * sy * dh_ / H))), Image.NEAREST))
    upm = np.asarray(Image.fromarray(bmask.astype(np.uint8) * 255).resize((up.shape[1], up.shape[0]), Image.NEAREST)) > 127
    hh_, ww_ = min(up.shape[0], fb.shape[0]), min(up.shape[1], fb.shape[1])
    region = fb[:hh_, :ww_]
    region[upm[:hh_, :ww_]] = (0.35 * region[upm[:hh_, :ww_]] + 0.65 * up[:hh_, :ww_][upm[:hh_, :ww_]]).astype(np.uint8)
    fbimg = Image.fromarray(fb)
    fbimg = add_ruler(fbimg, 0, 0, dw_ / W, title='drawing rate per block (%d ref px blocks), coloured where animated' % round(B * sx), grid=True)
    vstack([fbimg, leg], gap=0).save(os.path.join(out_dir, 'rate_blocks.png'))
    # --- motion heatmap
    mrate = motion / max(1, motion_frames) * fps
    mtop = float(max(1.0, min(fps, np.percentile(mrate[mrate > 0], 99.5) if (mrate > 0).any() else 1.0)))
    lt = math.log10(1 + mtop)
    mm = np.log10(1 + mrate) / lt
    heat = heat_cmap(0.15 + 0.85 * np.clip(mm, 0, 1)).astype(np.float32)
    basep = np.asarray(Image.fromarray(mid_frame)).astype(np.float32) * 0.4
    mimg = np.where((mrate > 0.05)[..., None], np.clip(basep * 0.2 + heat, 0, 255), basep).astype(np.uint8)
    mimg = Image.fromarray(mimg).resize((dw_, dh_), Image.BOX)
    mimg = add_ruler(mimg, 0, 0, dw_ / W, title='motion heatmap: pixel changes per second (log scale), shakes/cuts excluded', grid=False)
    ticks = [(0, '0')] + [(0.15 + 0.85 * math.log10(1 + v) / lt, '%g' % v) for v in (0.3, 1, 3, 10, 30) if v < mtop * 0.95] + [(1, '%.3g+' % mtop)]
    cb = colorbar(mimg.width, ticks, heat_cmap, title='changes / s (per pixel)')
    vstack([mimg, cb], gap=2).save(os.path.join(out_dir, 'motion.png'))
    # --- boil / jitter check in the most static stretch
    cb_count = ch.reshape(n, -1).sum(1).astype(np.float32)
    blank = smalls.reshape(n, -1).std(1) < 2.0
    lum = smalls.reshape(n, -1).mean(1)
    fading = np.zeros(n, bool)
    fading[1:] = np.abs(np.diff(lum)) > 0.4
    fading = ndi.binary_dilation(fading, iterations=max(1, int(round(fps * 0.25))))
    cb_count[excl | blank | fading] = np.inf
    best = None
    frozen = None
    wl = max(2, int(round(fps)))
    for st in range(1, max(2, n - wl)):
        seg = cb_count[st:st + wl]
        if not np.isfinite(seg).all():
            continue
        m = float(seg.mean())
        if seg.max() <= 0:
            if frozen is None:
                frozen = st
            continue
        if best is None or m < best[0]:
            best = (m, st)
    boil = {'checked': False}
    if frozen is not None:
        boil['fully_static_stretch'] = {'start': round(frozen / fps, 3), 'note': 'a whole second without any change (no boil/flicker at all there)'}
    if best is None and frozen is not None:
        boil.update({'checked': True, 'verdict': 'every animated stretch aside, the video holds still frames: no line boil, flicker or palette cycling'})
    if best is not None:
        st = best[1]
        seg = cb_count[st:st + wl]
        i = st + int(np.argmax(seg))
        boil.update({'checked': True, 'stretch_start': round(st / fps, 3), 'stretch_end': round((st + wl) / fps, 3),
                     'mean_changed_blocks': round(best[0], 2), 'pair_frames': [i - 1, i], 'pair_times': [round((i - 1) / fps, 3), round(i / fps, 3)]})
        frs = extract_frame(path, (i - 1) / fps, fps=fps, frames=2)
        if len(frs) == 2:
            A, Bm = frs[0].astype(np.int16), frs[1].astype(np.int16)
            dd = np.abs(Bm - A).max(2)
            chg = dd > T
            share = float(chg.mean())
            Lfull = luma8(frs[0])
            gm = np.hypot(ndi.sobel(Lfull, 1), ndi.sobel(Lfull, 0)) / 8
            on_edges = float((chg & (gm > 10)).sum() / max(1, chg.sum()))
            gy_, gx_ = 6, 8
            cell_min = max(10, 0.002 * (H // gy_) * (W // gx_))
            spread = float(np.mean([chg[r * H // gy_:(r + 1) * H // gy_, c * W // gx_:(c + 1) * W // gx_].sum() >= cell_min
                                    for r in range(gy_) for c in range(gx_)]))
            lab_, nl = ndi.label(ndi.binary_dilation(chg, iterations=max(2, int(4 * sx))))
            objs = ndi.find_objects(lab_)
            sizes = ndi.sum(chg, lab_, range(1, nl + 1)) if nl else []
            comps = sorted([(float(sizes[k]), objs[k]) for k in range(nl)], key=lambda t: -t[0])[:10]
            mean_amp = float(dd[chg].mean()) if chg.any() else 0.0
            # a per-block gain+offset fit explains fades / light flicker but not redrawn lines
            Bq = 16
            ga = _block_view(luma8(frs[0]), Bq)
            gb = _block_view(luma8(frs[1]), Bq)
            ma, mb = ga.mean(2, keepdims=True), gb.mean(2, keepdims=True)
            va = ((ga - ma) ** 2).mean(2, keepdims=True)
            cv = ((ga - ma) * (gb - mb)).mean(2, keepdims=True)
            g_ = np.clip(np.where(va > 1, cv / np.maximum(va, 1e-6), 1.0), 0.5, 2.0)
            resid = np.abs(gb - (g_ * (ga - ma) + mb))
            raw_b = (np.abs(gb - ga) > T).any(2)
            res_b = (resid > T).any(2)
            explained = float(1 - res_b.sum() / max(1, raw_b.sum()))
            if spread > 0.5 and explained > 0.6:
                kind = 'global light flicker / fade: changes everywhere, mostly explained by brightness gain/offset'
            elif spread > 0.5 and on_edges > 0.6:
                kind = 'line boil likely: changes spread over the frame and sit on edges/lines'
            elif spread > 0.5:
                kind = 'widespread small changes: flicker, dithering noise or codec noise'
            else:
                kind = 'localized loops: %d changed spots (flames, glows, idle loops, palette cycling)' % nl
            boil['explained_by_brightness_share'] = round(explained, 3)
            boil.update({'changed_share': round(share, 5), 'changes_on_edges_share': round(on_edges, 3),
                         'spread_cells_share': round(spread, 3), 'mean_amplitude': round(mean_amp, 1), 'spots': nl,
                         'verdict': kind,
                         'largest_spots': [{'x0': int(o[1].start), 'y0': int(o[0].start), 'x1': int(o[1].stop), 'y1': int(o[0].stop),
                                            'changed_px': int(s_)} for s_, o in comps]})
            dw2, dh2, _ = fit_size(W, H, 760)
            pa = Image.fromarray(frs[0]).resize((dw2, dh2), Image.BOX)
            amp = np.clip(dd * 4, 0, 255).astype(np.uint8)
            heatd = heat_cmap(amp / 255.0)
            pdif = Image.fromarray(heatd).resize((dw2, dh2), Image.BOX)
            red = (np.asarray(Image.fromarray(frs[0])).astype(np.float32) * 0.35).astype(np.uint8)
            red[chg] = (255, 40, 40)
            pred = Image.fromarray(red).resize((dw2, dh2), Image.NEAREST)
            pd = ImageDraw.Draw(pred)
            for s_, o in comps:
                pd.rectangle([o[1].start * dw2 / W, o[0].start * dh2 / H, o[1].stop * dw2 / W, o[0].stop * dh2 / H], outline=(0, 255, 255))
                label(pd, (o[1].start * dw2 / W, o[0].stop * dh2 / H + 1), '%d,%d' % (o[1].start, o[0].start), font(11), bg=(0, 0, 0))
            top = hstack([title_panel(pa, 'frame %d (t=%s)' % (i - 1, fmt_t((i - 1) / fps))),
                          title_panel(pdif, 'abs difference x4 (next drawing, frame %d)' % i)])
            # zoomed before/after of the biggest spots
            zs = []
            for s_, o in comps[:4]:
                y0_, y1_, x0_, x1_ = o[0].start, o[0].stop, o[1].start, o[1].stop
                cxs, cys = (x0_ + x1_) // 2, (y0_ + y1_) // 2
                half = max(16, int(max(x1_ - x0_, y1_ - y0_) * 0.6))
                bx0, by0 = max(0, cxs - half), max(0, cys - half)
                bx1, by1 = min(W, cxs + half), min(H, cys + half)
                zz = max(1, int(150 / max(1, bx1 - bx0, by1 - by0)))
                ca = Image.fromarray(frs[0][by0:by1, bx0:bx1]).resize(((bx1 - bx0) * zz, (by1 - by0) * zz), Image.NEAREST)
                cbm = Image.fromarray(frs[1][by0:by1, bx0:bx1]).resize(((bx1 - bx0) * zz, (by1 - by0) * zz), Image.NEAREST)
                pair = hstack([ca, cbm], gap=4)
                if pair.width < 230:
                    padded = Image.new('RGB', (230, pair.height), (22, 22, 26))
                    padded.paste(pair, (0, 0))
                    pair = padded
                zs.append(title_panel(pair, 'x%d-%d y%d-%d  before | after' % (bx0, bx1, by0, by1), size=12))
            bottom = [title_panel(pred, 'changed pixels (> %d) in red; boxes = spots' % T)]
            if zs:
                bottom.append(vstack(zs, gap=6))
            img = vstack([top, hstack(bottom), title_panel(Image.new('RGB', (top.width, 2), (22, 22, 26)), 'verdict: ' + kind)])
            img.save(os.path.join(out_dir, 'boil.png'))
            boil['image'] = 'boil.png'
    res['boil'] = boil
    # --- loop check: is the last (non-blank, non-faded) frame one normal step away from the first?
    lum_med = float(np.median(lum))
    usable = (~blank) & (lum >= 0.95 * lum_med) & ~fading
    nb_idx = np.where(usable)[0]
    f_first = int(nb_idx[0]) if len(nb_idx) else 0
    f_last = int(nb_idx[-1]) if len(nb_idx) else n - 1
    tail_d = dict(tail_buf)
    typical = float(np.percentile(frac_changed[valid], 90)) if valid.any() else 0.0
    if len(head_buf) > 1:  # the same statistic for consecutive frames at the buffer resolution
        ks = sorted(head_buf)[1:]
        steps = [float((_kth_block(np.abs(head_buf[k_].astype(np.int16) - head_buf[k_ - 1].astype(np.int16)).astype(np.uint8),
                                   max(4, B // 2), k=2) > T).mean()) for k_ in ks if usable[k_] and usable[k_ - 1] and valid[k_]]
        if steps:
            typical = max(typical, float(np.percentile(steps, 90)))

    def _share(a_, b_):
        return float((_kth_block(np.abs(a_.astype(np.int16) - b_.astype(np.int16)).astype(np.uint8), max(4, B // 2), k=2) > T).mean())
    loop = {'compared_frames': [f_first, f_last], 'compared_times': [round(f_first / fps, 3), round(f_last / fps, 3)], 'typical_step_changed_blocks_p90': round(typical, 4),
            'skipped_head_tail_frames': [f_first, n - 1 - f_last]}
    if f_first in head_buf and f_last in tail_d:
        sh = _share(head_buf[f_first], tail_d[f_last])
        cand = [(k_, _share(head_buf[f_first], v_)) for k_, v_ in tail_d.items() if k_ > f_first + 1 and usable[k_] and k_ >= f_last - int(2 * fps)]
        bk_, bs_ = min(cand, key=lambda t: t[1]) if cand else (f_last, sh)
        lim = max(typical, 0.002)
        loop.update({'first_vs_last_changed_blocks': round(sh, 4), 'seamless': bool(sh <= lim),
                     'best_match_to_first_in_last_2s': {'frame': int(bk_), 'time': round(bk_ / fps, 3), 'changed_blocks': round(bs_, 4)}})
        skipped = ' (skipped %d blank/faded frames at the start, %d at the end)' % (f_first, n - 1 - f_last) if (f_first or f_last < n - 1) else ''
        if sh <= lim:
            loop['verdict'] = 'seamless loop: last frame differs from the first like a normal frame step' + skipped
        elif bs_ <= lim:
            loop['verdict'] = 'near loop: frame %d (t=%.2fs) matches the first frame%s' % (bk_, bk_ / fps, skipped)
        else:
            loop['verdict'] = ('not a loop: %.1f%% of blocks differ between first and last frame (a normal step changes <= %.1f%%)%s'
                               % (100 * sh, 100 * typical, skipped))
    else:
        loop['verdict'] = 'not checked: the usable first/last frames lie outside the 4 s buffers (long fades or blank stretches)'
    res['loop'] = loop
    # --- per-region timing
    reg_out = []
    for k, (rg, r) in enumerate(zip(regions, reg_a)):
        fl = r['flag'][:n] & valid
        idx = np.nonzero(fl)[0]
        hld = _holds_from(idx, excl_cum)
        rate_act = _trimmed_rate(hld, fps, max_hold)
        smalls_r = r['small'][:n]
        shp = smalls_r[0].shape
        S = np.stack([s if s.shape == shp else np.zeros(shp, np.float32) for s in smalls_r])
        maxlag = int(min(n // 2, max(4, round(4 * fps))))
        Dl = np.array([np.abs(S[L:] - S[:-L]).mean() for L in range(1, maxlag + 1)])
        period = _find_period(Dl)
        hist = np.bincount(np.minimum(hld, 8), minlength=9)[1:].tolist() if len(hld) else []
        info_r = {'region': list(rg), 'changes': int(len(idx)), 'changes_per_s': round(len(idx) / valid_dur, 2),
                  'rate_while_animating': round(rate_act, 2), 'hold_hist_1to8plus': hist,
                  'verdict': _hold_verdict(hld, fps, max_hold)[0]}
        if period:
            ncyc = [fl[a:a + period].sum() for a in range(0, n - period, period)]
            info_r.update({'period_frames': period, 'period_s': round(period / fps, 3),
                           'drawings_per_cycle': round(float(np.median(ncyc)), 1) if ncyc else None})
        else:
            info_r['period_frames'] = None
        # image: crop + timeline + lag curve
        x0, y0, x1, y1 = rg
        crop = Image.fromarray(mid_frame).crop((int(x0 / sx), int(y0 / sy), int(math.ceil(x1 / sx)), int(math.ceil(y1 / sy))))
        zc = max(1, int(220 / max(crop.width, crop.height)))
        cz = add_ruler(crop.resize((crop.width * zc, crop.height * zc), Image.NEAREST), int(x0 / sx) * sx, int(y0 / sy) * sy, zc / sx,
                       title='region %d (analysis resolution, x%d)' % (k, zc))
        TLW = 1100
        tl = Image.new('RGB', (TLW, 150), (22, 22, 26))
        td = ImageDraw.Draw(tl)
        td.text((6, 4), 'changes over the whole video (%.1fs); tick = new drawing' % dur, font=font(12), fill=(230, 230, 230))
        for f_ in idx:
            xx = 6 + (TLW - 12) * f_ / n
            td.line([(xx, 22), (xx, 52)], fill=(255, 200, 60))
        for e_ in np.where(excl)[0]:
            xx = 6 + (TLW - 12) * e_ / n
            td.line([(xx, 54), (xx, 58)], fill=(200, 60, 60))
        z0 = int(idx[0]) if len(idx) else 0
        zn = int(min(n, z0 + round(3 * fps)))
        td.text((6, 64), 'zoom: %s - %s (each column = 1 frame)' % (fmt_t(z0 / fps), fmt_t(zn / fps)), font=font(12), fill=(230, 230, 230))
        cw = (TLW - 12) / max(1, zn - z0)
        for f_ in range(z0, zn):
            xx = 6 + cw * (f_ - z0)
            colr = (255, 200, 60) if fl[f_] else ((200, 60, 60) if excl[f_] else (60, 60, 70))
            td.rectangle([xx, 82, xx + max(1, cw - 1), 110], fill=colr)
            if (f_ - z0) % max(1, int(round(fps / 2))) == 0:
                td.text((xx, 114), '%.1f' % (f_ / fps), font=font(11), fill=(170, 170, 170))
        lag = Image.new('RGB', (TLW, 130), (22, 22, 26))
        ld2 = ImageDraw.Draw(lag)
        ld2.text((6, 4), 'self-difference vs lag (low = repeats); period: %s' % (
            '%d frames = %.3fs' % (period, period / fps) if period else 'none found'), font=font(12), fill=(230, 230, 230))
        if len(Dl):
            mxD = max(1e-6, Dl.max())
            pts = [(6 + (TLW - 12) * (L - 1) / max(1, len(Dl) - 1), 120 - 90 * Dl[L - 1] / mxD) for L in range(1, len(Dl) + 1)]
            ld2.line(pts, fill=(120, 200, 255), width=2)
            if period:
                xx = 6 + (TLW - 12) * (period - 1) / max(1, len(Dl) - 1)
                ld2.line([(xx, 22), (xx, 122)], fill=(255, 90, 90))
        img = vstack([title_panel(cz, 'region %d  x %d-%d y %d-%d: %s' % (k, x0, x1, y0, y1, info_r['verdict'])), tl, lag])
        pth = os.path.join(out_dir, 'region_%d.png' % k)
        img.save(pth)
        info_r['image'] = rel(pth, out_dir)
        reg_out.append(info_r)
    res['regions'] = reg_out
    # --- contact sheets
    sdir = ensure_dir(os.path.join(out_dir, 'sheets'))
    rows_per = 6
    per = sheet_cols * rows_per
    cutset = set(cuts)
    evset = set(np.where(excl)[0].tolist())
    sheet_paths = []
    for si in range(0, len(sheet), per):
        chunk = sheet[si:si + per]
        rws = int(math.ceil(len(chunk) / sheet_cols))
        SW = sheet_cols * (thumb_w + 6) + 6
        SH = rws * (thumb_h + 6) + 6 + 26
        sh_img = Image.new('RGB', (SW, SH), (22, 22, 26))
        sd = ImageDraw.Draw(sh_img)
        t_a, t_b = chunk[0][0] / fps, chunk[-1][0] / fps
        sd.text((6, 5), 'contact sheet %d: %s - %s at %g fps (red border = first frame after a cut, orange = during shake/global change)'
                % (si // per + 1, fmt_t(t_a), fmt_t(t_b), sheet_fps), font=font(13), fill=(235, 235, 235))
        for j, (fi, th_img) in enumerate(chunk):
            x = 6 + (j % sheet_cols) * (thumb_w + 6)
            y = 32 + (j // sheet_cols) * (thumb_h + 6)
            sh_img.paste(th_img, (x, y))
            new_shot = any(fi - int(round(fps / sheet_fps)) < c <= fi for c in cutset)
            if new_shot:
                sd.rectangle([x - 3, y - 3, x + thumb_w + 2, y + thumb_h + 2], outline=(255, 40, 40), width=3)
            elif fi in evset:
                sd.rectangle([x - 2, y - 2, x + thumb_w + 1, y + thumb_h + 1], outline=(255, 150, 30), width=2)
            label(sd, (x + 3, y + thumb_h - 3), '%s  f%d' % (fmt_t(fi / fps), fi), font(12), bg=(0, 0, 0), anchor='lb')
        p = os.path.join(sdir, 'sheet_%02d.png' % (si // per + 1))
        sh_img.save(p)
        sheet_paths.append(rel(p, out_dir))
    res['contact_sheets'] = {'fps': sheet_fps, 'cols': sheet_cols, 'files': sheet_paths}
    # --- keyframes: one per shot (middle) at full resolution
    kdir = ensure_dir(os.path.join(out_dir, 'keyframes'))
    kfs = []
    for s in shots[:60]:
        mid = (s['start_frame'] + s['end_frame']) // 2
        p = os.path.join(kdir, 'shot_%02d_t%07.2f.png' % (s['index'], mid / fps))
        extract_frame(path, mid / fps, out_png=p, fps=fps)
        s['keyframe'] = rel(p, out_dir)
        kfs.append(p)
    # representative keyframes for image analysis
    if len(shots) >= n_keyframes:
        rep_frames = [(s['start_frame'] + s['end_frame']) // 2 for s in sorted(shots, key=lambda s: -s['duration'])[:n_keyframes]]
    else:
        rep_frames = [int(n * (k + 0.5) / n_keyframes) for k in range(n_keyframes)]
    rep = []
    for k, fi in enumerate(sorted(rep_frames)):
        p = os.path.join(kdir, 'rep_%d_t%07.2f.png' % (k, fi / fps))
        extract_frame(path, fi / fps, out_png=p, fps=fps)
        entry = {'frame': fi, 'time': round(fi / fps, 3), 'file': rel(p, out_dir)}
        if keyframe_image_analysis and os.path.exists(p):
            sub = os.path.join(out_dir, 'keyframe_analysis', 'rep_%d' % k)
            ia = analyze_image(p, sub, tiles=False)
            entry['analysis_dir'] = rel(sub, out_dir)
            entry['pixel_grid'] = ia['pixel_grid']['verdict']
            entry['pixel_scale'] = ia['pixel_grid'].get('scale')
            entry['native'] = [ia['pixel_grid'].get('native_w'), ia['pixel_grid'].get('native_h')]
            entry['palette'] = {'size': ia['palette']['size'], 'method': ia['palette']['method'],
                                'ramps': [(r['name'], r['dark'], r['light'], round(r['share'], 3)) for r in ia['palette']['ramps']]}
            entry['background'] = ia['background']['background']
            entry['outline'] = [c['hex'] for c in ia['outline']['candidates']]
            entry['value_key'] = ia['values']['key']
        rep.append(entry)
    res['representative_keyframes'] = rep
    res['outputs'] = ['rate_map.png', 'rate_blocks.png', 'motion.png'] + (['boil.png'] if boil.get('image') else []) + \
        ['region_%d.png' % k for k in range(len(regions))] + sheet_paths
    res['seconds'] = round(time.time() - t_start, 1)
    return res


def summarize_video(res, name):
    p = res['probe']
    a = res['analysis']
    dr = res['drawing_rate']
    lines = ['VIDEO %s  %dx%d  %.3g fps  %.2fs  %d frames  %s' % (name, p['width'], p['height'], p['fps'], p['duration'], a['decoded_frames'], p['codec']),
             '  analysis   : %dx%d (1/%g), blocks %d ref px, change threshold %d (%s)' % (a['width'], a['height'], a['downscale'], round(a['block_px_reference']), a['noise_threshold'], 'auto' if 'auto' in a['noise_threshold_source'] else 'user'),
             '  cuts       : %d%s' % (len(res['cuts']), (' at ' + ', '.join(c['timecode'] for c in res['cuts'][:20])) if res['cuts'] else ' (one continuous shot)'),
             '  global evts: %d (%s)' % (len(res['global_events']), ', '.join('%s %s' % (e['timecode'], e['kind'].split(' (')[0]) for e in res['global_events'][:8]) + (' ...' if len(res['global_events']) > 8 else '')),
             '  drawing    : %s' % dr['verdict'],
             '               frames with any change: %.1f/s (union of all elements); animated area %.1f%% of blocks' % (dr['frames_with_any_change_per_s'], 100 * dr['animated_area_share'])]
    for s in res['shots'][:12]:
        lines.append('      shot %d %s-%s (%.1fs): %.1f drawings/s while animating; any-change %.1f/s' % (s['index'], fmt_t(s['start']), fmt_t(s['end']), s['duration'], s['typical_rate_while_animating'], s['frames_with_any_change_per_s']))
    cl = res['cells']
    lines.append('  rate map   : (%dx%d cells, drawings/s while animating, 0 = static) -> rate_map.png, rate_blocks.png' % (cl['cols'], cl['rows']))
    for r in range(cl['rows']):
        row = [c for c in cl['list'] if c['row'] == r]
        lines.append('      ' + ' '.join('%5.1f' % c['rate_while_animating'] for c in row))
    b = res['boil']
    if b.get('checked'):
        lines.append('  boil       : stretch %s-%s: %s%s' % (fmt_t(b['stretch_start']), fmt_t(b['stretch_end']), b.get('verdict', ''), ' -> boil.png' if b.get('image') else ''))
    lines.append('  loop       : %s' % res['loop']['verdict'])
    for k, r in enumerate(res['regions']):
        per = ('period %d frames = %.3fs (%s drawings/cycle)' % (r['period_frames'], r['period_s'], r.get('drawings_per_cycle'))) if r.get('period_frames') else 'no period'
        lines.append('  region %d   : %s: %d changes, %.1f/s avg, %.1f drawings/s while animating; %s -> %s' % (k, ','.join(str(v) for v in r['region']), r['changes'], r['changes_per_s'], r['rate_while_animating'], per, r['image']))
    for kf in res['representative_keyframes']:
        if 'pixel_grid' in kf:
            lines.append('  keyframe   : t=%.2fs %s | %s | palette %d (%s) | bg %s' % (kf['time'], kf['file'], kf['pixel_grid'].split(';')[0].split(', confidence')[0], kf['palette']['size'], kf['palette']['method'].split(' (')[0], kf['background']))
    lines.append('  sheets     : %d contact sheets at %g fps -> sheets/; keyframes/ (one per shot + representative)' % (len(res['contact_sheets']['files']), res['contact_sheets']['fps']))
    lines.append('  time       : %.1fs (decode+measure %.1fs)' % (res['seconds'], a['decode_seconds']))
    return '\n'.join(lines)


# ----------------------------------------------------------------------------
# crop / track / probe
# ----------------------------------------------------------------------------

def cmd_crop(a):
    if is_video(a.file):
        info = ffprobe_info(a.file)
        frs = extract_frame(a.file, a.t or 0.0, fps=info['fps'])
        if not frs:
            raise SystemExit('no frame at t=%s' % a.t)
        img = Image.fromarray(frs[0])
        src = '%s @ %s' % (os.path.basename(a.file), fmt_t(a.t or 0))
    else:
        rgb, _ = load_image(a.file)
        img = Image.fromarray(rgb)
        src = os.path.basename(a.file)
    x0, y0, x1, y1 = a.x0, a.y0, a.x1, a.y1
    zoom = a.zoom if a.zoom is not None else (1 if a.clean else 4)
    z = zoom_crop(img, x0, y0, x1, y1, zoom)
    out = z if a.clean else add_ruler(z, x0, y0, zoom, major=a.grid, title='%s  x %d-%d  y %d-%d  x%g' % (src, x0, x1, y0, y1, zoom))
    ensure_dir(os.path.dirname(os.path.abspath(a.out)))
    out.save(a.out)
    d = os.path.dirname(os.path.abspath(a.out))
    merge_study_json(d, 'crops', os.path.basename(a.out), {'file': os.path.abspath(a.file), 'box': [x0, y0, x1, y1], 'zoom': zoom,
                                                           'grid': None if a.clean else a.grid, 'clean': a.clean, 't': a.t, 'size': list(out.size)})
    print('CROP %s  box %d,%d-%d,%d  x%g  %s -> %s (%dx%d)' % (src, x0, y0, x1, y1, zoom, 'clean' if a.clean else 'grid %s' % a.grid,
                                                             a.out, out.width, out.height))


def cmd_track(a):
    t0 = time.time()
    info = ffprobe_info(a.file)
    fps = info['fps']
    x0, y0, x1, y1 = parse_box(a.region)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(info['width'], x1), min(info['height'], y1)
    w, h = x1 - x0, y1 - y0
    w -= w % 2
    h -= h % 2
    if w < 2 or h < 2:
        raise SystemExit('region too small')
    t_from = a.t_from or 0.0
    t_to = a.t_to if a.t_to is not None else info['duration']
    out_dir = ensure_dir(a.out)
    frames = list(ffmpeg_frames(a.file, w, h, ss=t_from, duration=max(0.01, t_to - t_from), vf='crop=%d:%d:%d:%d' % (w, h, x0, y0)))
    if len(frames) < 2:
        raise SystemExit('no frames decoded in that range')
    F = np.stack(frames).astype(np.int16)
    D = np.abs(F[1:] - F[:-1]).max(3)
    T = a.noise if a.noise is not None else _noise_threshold(np.array([_kth_block(dd.astype(np.uint8), max(4, min(12, min(w, h) // 4))) for dd in D]))
    minpx = max(2, int(0.001 * w * h))
    changed = np.concatenate([[True], (D > T).reshape(len(D), -1).sum(1) >= minpx])
    starts = np.nonzero(changed)[0]
    uniq = []
    seq = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(frames)
        img = F[s]
        rep = None
        for u in uniq:
            if ((np.abs(img - u['img']).max(2) > T).sum()) < minpx:
                rep = u['id']
                break
        if rep is None:
            uid = len(uniq)
            uniq.append({'id': uid, 'img': img, 'first_frame': int(s)})
        else:
            uid = rep
        seq.append({'drawing': len(seq), 'id': uid, 'frame_in_range': int(s), 'time': round(t_from + s / fps, 3),
                    'hold_frames': int(e - s), 'repeat_of': rep})
    ids = [s_['id'] for s_ in seq]
    cycle = None
    fr_ = {}
    for p in range(2, len(ids) // 2 + 1):
        n_ = len(ids) - p
        fr_[p] = sum(1 for i in range(n_) if ids[i] == ids[i + p]) / max(1, n_)
    if fr_ and max(fr_.values()) >= 0.6:
        top_ = max(fr_.values())
        cycle = min(p for p, f in fr_.items() if f >= 0.9 * top_)
    cycle_match = round(fr_.get(cycle, 0.0), 3) if cycle else None
    zoom = a.zoom or max(1, int(round(200 / max(w, h))))
    cols = max(1, min(8, int(1500 // (w * zoom + 10))))
    per = cols * 6
    paths = []
    fnt = font(12)
    for si in range(0, len(seq), per):
        chunk = seq[si:si + per]
        rws = int(math.ceil(len(chunk) / cols))
        cw, chh = w * zoom + 10, h * zoom + 40
        img = Image.new('RGB', (cols * cw + 10, rws * chh + 34), (22, 22, 26))
        d = ImageDraw.Draw(img)
        d.text((8, 6), 'track %s region %d,%d-%d,%d  %s-%s  drawings %d-%d of %d (unique %d)%s' % (
            os.path.basename(a.file), x0, y0, x1, y1, fmt_t(t_from), fmt_t(t_to), si, si + len(chunk) - 1, len(seq), len(uniq),
            ('  cycle %d drawings' % cycle) if cycle else ''), font=font(13), fill=(235, 235, 235))
        for j, s_ in enumerate(chunk):
            x = 8 + (j % cols) * cw
            y = 30 + (j // cols) * chh
            fr = Image.fromarray(F[s_['frame_in_range']].astype(np.uint8)).resize((w * zoom, h * zoom), Image.NEAREST)
            img.paste(fr, (x, y))
            d.rectangle([x - 1, y - 1, x + w * zoom, y + h * zoom], outline=(90, 90, 90) if s_['repeat_of'] is None else (90, 160, 255))
            t1 = '#%d  t=%.3fs  f%d' % (s_['drawing'], s_['time'], int(round(s_['time'] * fps)))
            t2 = 'hold %d%s' % (s_['hold_frames'], ('  = id %d' % s_['repeat_of']) if s_['repeat_of'] is not None else '  id %d' % s_['id'])
            d.text((x, y + h * zoom + 3), t1, font=fnt, fill=(235, 235, 235))
            d.text((x, y + h * zoom + 18), t2, font=fnt, fill=(150, 190, 255) if s_['repeat_of'] is not None else (170, 170, 170))
        p = os.path.join(out_dir, 'track_%02d.png' % (si // per + 1))
        img.save(p)
        paths.append(os.path.basename(p))
    holds = np.array([s_['hold_frames'] for s_ in seq[:-1]]) if len(seq) > 1 else np.zeros(0, np.int32)
    res = {'file': os.path.abspath(a.file), 'region': [x0, y0, x1, y1], 'from': t_from, 'to': t_to, 'fps': fps,
           'frames': len(frames), 'noise_threshold': int(T), 'drawings': len(seq), 'unique_drawings': len(uniq),
           'drawings_per_s': round(len(seq) / max(1e-6, len(frames) / fps), 2),
           'rate_while_animating': round(_trimmed_rate(holds, fps, max(2, int(round(fps * 0.5)))), 2),
           'hold_verdict': _hold_verdict(holds, fps, max(2, int(round(fps * 0.5))))[0],
           'cycle_drawings': cycle, 'cycle_match_share': cycle_match, 'cycle_seconds': round(sum(s_['hold_frames'] for s_ in seq[:cycle]) / fps, 3) if cycle else None,
           'sequence': seq, 'sheets': paths, 'seconds': round(time.time() - t0, 2)}
    merge_study_json(out_dir, 'track', '%s@%d,%d,%d,%d' % (os.path.basename(a.file), x0, y0, x1, y1), res)
    print('TRACK %s region %d,%d-%d,%d  %s-%s (%d frames)' % (os.path.basename(a.file), x0, y0, x1, y1, fmt_t(t_from), fmt_t(t_to), len(frames)))
    print('  drawings   : %d (%d unique), %.1f/s; %s' % (len(seq), len(uniq), res['drawings_per_s'], res['hold_verdict']))
    print('  cycle      : %s' % (('%d drawings = %.3fs (%.0f%% of drawings repeat at that lag)' % (cycle, res['cycle_seconds'], 100 * cycle_match))
                                 if cycle else 'no repeating cycle found (drawings do not recur: procedural, or a cycle longer than half the range)'))
    print('  sequence   : ' + ' '.join('%d%s' % (s_['id'], '' if s_['hold_frames'] == 1 else '(%d)' % s_['hold_frames']) for s_ in seq[:60]) + (' ...' if len(seq) > 60 else ''))
    print('  sheets     : %s  (threshold %d, %.1fs)' % (', '.join(paths), T, res['seconds']))


# ----------------------------------------------------------------------------
# level grid: tile size, phase, unique tiles
# ----------------------------------------------------------------------------

PIXEL_TILE_CANDIDATES = [8, 12, 16, 24, 32, 48, 64]
HD_TILE_CANDIDATES = [16, 24, 32, 40, 48, 64, 80, 96, 128, 160, 192, 256]


def _cell_samples(Yb, ox, oy, p, nx, ny, s):
    """Sample an s x s grid of (pre-blurred) values inside every p x p cell."""
    off = (np.arange(s) + 0.5) * p / s
    ys = (oy + np.arange(ny)[:, None] * p + off[None, :]).astype(int)  # ny x s
    xs = (ox + np.arange(nx)[:, None] * p + off[None, :]).astype(int)  # nx x s
    v = Yb[ys[:, None, :, None], xs[None, :, None, :]]  # ny, nx, s, s
    return v.reshape(ny * nx, s * s)


def _znorm(v):
    m = v.mean(1, keepdims=True)
    sd = v.std(1, keepdims=True)
    return (v - m) / np.maximum(sd, 1e-6), sd[:, 0]


def _tiling_cost(Y, Yb4, Ystd, p, ox, oy, flat_std=3.0):
    h, w = Y.shape
    nx, ny = (w - ox) // p, (h - oy) // p
    if nx * ny < 6:
        return None
    sig = _cell_samples(Yb4, ox, oy, p, nx, ny, 4)
    z, _ = _znorm(sig)
    cs = Ystd[(oy + np.arange(ny) * p + p // 2)[:, None], (ox + np.arange(nx) * p + p // 2)[None, :]].ravel()
    flat = cs < flat_std
    q = np.where(z > 0.5, 2, np.where(z < -0.5, 0, 1)).astype(np.uint8)
    keys = q[~flat]
    n_nf = int((~flat).sum())
    if n_nf == 0:
        return {'cost': 9.0, 'groups': 0, 'cells': nx * ny, 'repeat_share': 0.0, 'flat_share': 1.0, 'nx': nx, 'ny': ny}
    _, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    G = len(cnt) + (1 if flat.any() else 0)
    N = nx * ny
    rep = float((cnt[inv.ravel()] >= 2).mean())
    cost = 8.0 * G / N + math.log2(G + 1) / (p * p)
    return {'cost': cost, 'groups': G, 'cells': N, 'repeat_share': rep, 'flat_share': float(flat.mean()), 'nx': nx, 'ny': ny}


def _best_phase(Y, Yb4, Ystd, p):
    step = max(1, p // 8)
    best = None
    for oy in range(0, p, step):
        for ox in range(0, p, step):
            r = _tiling_cost(Y, Yb4, Ystd, p, ox, oy)
            if r and (best is None or r['cost'] < best[0]['cost']):
                best = (r, ox, oy)
    if best is None:
        return None
    if step > 1:
        _, bx, by = best
        for oy in range(by - step + 1, by + step):
            for ox in range(bx - step + 1, bx + step):
                if 0 <= ox < p and 0 <= oy < p:
                    r = _tiling_cost(Y, Yb4, Ystd, p, ox, oy)
                    if r and r['cost'] < best[0]['cost']:
                        best = (r, ox, oy)
    return best


def _group_cells(cells_rgb, flat, corr_min=0.85, dE_max=18.0):
    """Greedy near-duplicate grouping. cells_rgb: (N, p, p, 3) uint8. Returns group id per cell (-1-k for flat colour k)."""
    N, p = cells_rgb.shape[0], cells_rgb.shape[1]
    s = min(p, 8)
    Y = luma8(cells_rgb.astype(np.float32))
    f = p // s
    if p % s == 0:
        sig = Y.reshape(N, s, f, s, f).mean((2, 4)).reshape(N, s * s)
    else:
        idx = ((np.arange(s) + 0.5) * p / s).astype(int)
        sig = Y[:, idx][:, :, idx].reshape(N, s * s)
    z, _ = _znorm(sig)
    z /= math.sqrt(s * s)
    lab = rgb_to_lab(cells_rgb.reshape(N, -1, 3).mean(1))
    exact_keys = (cells_rgb >> 3).reshape(N, -1)
    _, exact_inv = np.unique(exact_keys, axis=0, return_inverse=True)
    exact_inv = exact_inv.ravel()
    gid = np.full(N, -1, np.int64)
    reps = []
    rep_lab = []
    flat_cols = []
    for i in range(N):
        if flat[i]:
            # flat cells: group by mean colour
            c = lab[i]
            k = next((j for j, fc in enumerate(flat_cols) if np.sqrt(((fc - c) ** 2).sum()) < 6), None)
            if k is None:
                flat_cols.append(c)
                k = len(flat_cols) - 1
            gid[i] = -1 - k
            continue
        if reps:
            R = np.array(reps)
            cr = R @ z[i]
            ok = (cr >= corr_min) & (np.sqrt(((np.array(rep_lab)[:, 1:] - lab[i][1:]) ** 2).sum(1)) < dE_max)
            if ok.any():
                gid[i] = int(np.argmax(np.where(ok, cr, -9)))
                continue
        reps.append(z[i])
        rep_lab.append(lab[i])
        gid[i] = len(reps) - 1
    return gid, exact_inv


def rng_sel(n, k, seed=0):
    if n <= k:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, k, replace=False))


def _wall_face_guess(grid_ids, flat_dark, counts):
    """3/4-view heuristic: wall rows are tiles that always sit at the same distance below void
    (empty/dark cells) in their column; floor tiles do not. The band of such rows starting right
    under the void (cap + face) is the wall height in tiles."""
    ny, nx = grid_ids.shape
    dist = np.full((ny, nx), 10 ** 6, np.int64)
    for x in range(nx):
        last = None
        for y in range(ny):
            if flat_dark[y, x]:
                last = y
            elif last is not None:
                dist[y, x] = y - last
    stats = {}
    for g, c in counts.items():
        if g < 0 or c < 3:
            continue
        d = dist[grid_ids == g]
        d = d[d <= 8]
        if len(d) < 3:
            continue
        h = np.bincount(d, minlength=9)
        m = int(np.argmax(h))
        stats[g] = (m, float(h[m] / len(d)), int(len(d)))
    conc = {g: v for g, v in stats.items() if v[1] >= 0.7}
    rows = sorted(set(v[0] for v in conc.values()))
    k = 0
    while k + 1 in rows:
        k += 1
    ev = {'wall_like_groups': [{'group': int(g), 'rows_below_void': v[0], 'consistency': round(v[1], 2), 'n': v[2]}
                               for g, v in sorted(conc.items(), key=lambda t: t[1][0])][:12]}
    if k == 0:
        ev['note'] = ('no tile sits at a consistent distance below empty space (no repeated wall rows)' if stats
                      else 'tiles do not repeat enough to separate wall rows from floor')
        return None, ev
    band = (dist >= 1) & (dist <= k) & (grid_ids >= 0)
    in_conc = np.isin(grid_ids, list(conc.keys())) & band
    band_share = float(in_conc.sum() / max(1, band.sum()))
    ev['band_cells_explained'] = round(band_share, 2)
    if in_conc.sum() < 8 or band_share < 0.25:
        ev['note'] = 'only %d cells (%.0f%% of the rows under empty space) belong to consistent wall tiles' % (int(in_conc.sum()), 100 * band_share)
        return None, ev
    below = grid_ids[dist == k + 1]
    below = below[below >= 0]
    floor_share = float(np.mean([g not in conc for g in below])) if len(below) else 0.0
    ev['floor_share_below_band'] = round(floor_share, 2)
    if floor_share < 0.5:
        ev['note'] = 'band found but what lies below it is not floor-like'
        return None, ev
    return k, ev


def _texture_period(Yh, pmin, pmax):
    """Dominant repeat period along x of a high-passed luma image (incoherent row spectra)."""
    N = Yh.shape[1]
    if N < 2 * pmin + 4:
        return None, 0.0
    M = 1 << int(math.ceil(math.log2(max(N, 64) * 8)))
    P = (np.abs(np.fft.rfft(Yh * np.hanning(N), M, axis=1)) ** 2).mean(0)
    fr = np.fft.rfftfreq(M)
    sel = (fr >= 1.0 / pmax) & (fr <= 1.0 / pmin)
    if sel.sum() < 8:
        return None, 0.0
    lp = np.log(P[sel] + 1e-9)
    base = ndi.median_filter(lp, size=max(9, int(sel.sum() // 6)) | 1, mode='nearest')
    r = lp - base
    i = int(np.argmax(r))
    return float(1.0 / fr[sel][i]), float(np.exp(r[i]))


def _autocorr_peaks(Yh, pmax):
    """Local maxima (lag, prominence) of the normalised autocorrelation along x of a high-passed image."""
    ac = {}
    for q in range(2, int(pmax) + 3):
        if Yh.shape[1] <= q * 2:
            break
        a_, b_ = Yh[:, :-q], Yh[:, q:]
        ac[q] = float((a_ * b_).sum() / math.sqrt((a_ * a_).sum() * (b_ * b_).sum() + 1e-9))
    out = []
    for q in ac:
        if q - 1 in ac and q + 1 in ac and ac[q] > ac[q - 1] and ac[q] >= ac[q + 1]:
            prom = ac[q] - 0.5 * (ac.get(q - 2, ac[q - 1]) + ac.get(q + 2, ac[q + 1]))
            if prom > 0.005 and q >= 3:
                out.append((q, prom))
    return out, ac


def _fundamental(peaks, fmin=3.0, fmax=96.0):
    """Largest period F such that the autocorrelation peaks sit at whole multiples of F."""
    if not peaks:
        return None, 0.0
    best = []
    tot = sum(w_ for _, w_ in peaks)
    for F in np.arange(fmin, fmax, 0.05):
        sc = 0.0
        for q, w_ in peaks:
            m = round(q / F)
            if m >= 1:
                sc += w_ * max(0.0, 1 - 4 * abs(q / F - m))
        best.append((sc / tot, F))
    top = max(b for b, _ in best)
    if top < 0.5:
        return None, top
    F = max(F for b, F in best if b >= 0.95 * top)
    return float(F), float(top)


def _fold_phase(Yh, p):
    """Offset (0..p-1) of the darkest line when the image is folded modulo p along x (grout / seam)."""
    prof = Yh.mean(0)
    n = (len(prof) // p) * p
    if n < p:
        return 0
    f = prof[:n].reshape(-1, p).mean(0)
    return int(np.argmin(f))


def analyze_tiles(rgb, out_dir, region=None, tile=None, max_unique=120, src_name=''):
    t0 = time.time()
    ensure_dir(out_dir)
    H, W = rgb.shape[:2]
    grid = detect_pixel_grid(rgb)
    if grid['kind'] in ('crisp', 'soft'):
        nat, _ = make_native(rgb, grid)
        cx = np.array([a for a, b in grid['cells_x']])
        cy = np.array([a for a, b in grid['cells_y']])
        cx_end = np.array([b for a, b in grid['cells_x']])
        cy_end = np.array([b for a, b in grid['cells_y']])
        units = 'native px (pixel grid scale %.4g)' % grid['scale']
        cands = PIXEL_TILE_CANDIDATES
    else:
        f = max(1, int(math.ceil(max(W, H) / 1600)))
        nat = np.asarray(Image.fromarray(rgb).resize((W // f, H // f), Image.BOX)) if f > 1 else rgb
        cx = np.arange(nat.shape[1]) * f
        cy = np.arange(nat.shape[0]) * f
        cx_end, cy_end = cx + f, cy + f
        units = 'image px' if f == 1 else 'image px / %d' % f
        cands = HD_TILE_CANDIDATES
    nh, nw = nat.shape[:2]
    # region in reference px -> native index range
    if region:
        x0, y0, x1, y1 = region
        nx0 = int(np.searchsorted(cx_end, x0, side='right'))
        ny0 = int(np.searchsorted(cy_end, y0, side='right'))
        nx1 = int(np.searchsorted(cx, x1, side='left'))
        ny1 = int(np.searchsorted(cy, y1, side='left'))
    else:
        nx0, ny0, nx1, ny1 = 0, 0, nw, nh
    nx1, ny1 = max(nx1, nx0 + 1), max(ny1, ny0 + 1)
    sub = nat[ny0:ny1, nx0:nx1]
    h, w = sub.shape[:2]
    Y = luma8(sub)
    Ystd = None
    res = {'source': src_name, 'pixel_grid': grid['verdict'], 'units': units,
           'region_ref': [int(cx[nx0]), int(cy[ny0]), int(cx_end[nx1 - 1]), int(cy_end[ny1 - 1])],
           'region_native': [nx0, ny0, nx1, ny1]}
    # candidate periods: fixed list + autocorrelation peaks (arbitrary periods)
    Yh = Y - ndi.gaussian_filter(Y, 8)
    ac = {}
    for p in range(4, int(min(256, max(w, h) / 3)) + 1):
        vals = []
        for A in (Yh, Yh.T):
            if A.shape[1] > p * 2:
                a_, b_ = A[:, :-p], A[:, p:]
                vals.append(float((a_ * b_).sum() / math.sqrt((a_ * a_).sum() * (b_ * b_).sum() + 1e-9)))
        if vals:
            ac[p] = float(np.mean(vals))
    peaks = [p for p in ac if p - 1 in ac and p + 1 in ac and ac[p] > ac[p - 1] and ac[p] >= ac[p + 1]
             and ac[p] - 0.5 * (ac.get(p - 2, ac[p - 1]) + ac.get(p + 2, ac[p + 1])) > 0.01]
    peaks = sorted(peaks, key=lambda p: -ac[p])[:6]
    if cands is PIXEL_TILE_CANDIDATES:
        cand = [p for p in cands if p <= min(w, h) / 2.5]
    else:  # HD art: the usual sizes plus arbitrary autocorrelation peaks
        cand = sorted(set([p for p in cands if p <= min(w, h) / 2.5] + [p for p in peaks if p >= 8]))
    if tile:
        cand = [int(tile)]
    scored = []
    for p in cand:
        Yb4 = ndi.uniform_filter(Y, size=max(1, p // 4))
        m1 = ndi.uniform_filter(Y, size=p)
        m2 = ndi.uniform_filter(Y * Y, size=p)
        Ystd = np.sqrt(np.maximum(0, m2 - m1 * m1))
        b = _best_phase(Y, Yb4, Ystd, p)
        if b is None:
            continue
        r, ox, oy = b
        scored.append({'tile': p, 'phase': [ox, oy], **{k_: (round(v, 4) if isinstance(v, float) else v) for k_, v in r.items()},
                       'autocorr': round(ac.get(p, float('nan')), 3), 'autocorr_peak': p in peaks})
    if not scored:
        raise SystemExit('region too small for tile analysis (need at least 6 cells of the smallest candidate)')
    # texture periodicity (quasi-periodic floors / bricks in painted or generated art)
    pmax = max(8.0, min(96.0, min(w, h) / 3.0))
    pk_x, _ = _autocorr_peaks(Yh, pmax)
    pk_y, _ = _autocorr_peaks(Yh.T, pmax)
    Ptx, str_x = _fundamental(pk_x, 3.0, pmax / 1.5)
    Pty, str_y = _fundamental(pk_y, 3.0, pmax / 1.5)
    sp_x, _ = _texture_period(Yh, 3.0, pmax)
    sp_y, _ = _texture_period(Yh.T, 3.0, pmax)
    res['texture_period'] = {'x': None if Ptx is None else round(Ptx, 2), 'y': None if Pty is None else round(Pty, 2),
                             'fit_x': round(str_x, 2), 'fit_y': round(str_y, 2),
                             'autocorr_peaks_x': [q for q, _ in sorted(pk_x, key=lambda t: -t[1])[:6]],
                             'autocorr_peaks_y': [q for q, _ in sorted(pk_y, key=lambda t: -t[1])[:6]],
                             'spectral_x': None if sp_x is None else round(sp_x, 2), 'spectral_y': None if sp_y is None else round(sp_y, 2),
                             'note': 'repeat period of the texture (stone / brick / plank size), analysis px: largest period whose '
                                     'multiples explain the autocorrelation peaks'}
    use = [(Ptx, str_x, max([w_ for _, w_ in pk_x] or [0])), (Pty, str_y, max([w_ for _, w_ in pk_y] or [0]))]
    use = [u for u in use if u[0]]
    if len(use) == 2 and abs(use[0][0] - use[1][0]) / max(use[0][0], use[1][0]) > 0.2:
        # the two axes disagree: trust only an axis with a clean, prominent periodicity
        use = [u for u in use if u[1] >= 0.9 and u[2] >= 0.03]
    used = [u[0] for u in use]
    res['texture_period']['used_for_fit'] = [round(u, 2) for u in used]
    for r in scored:
        errs = [abs(r['tile'] / P_ - round(r['tile'] / P_)) for P_ in used if r['tile'] / P_ >= 0.8]
        r['period_fit'] = round(1 - 2 * float(np.mean(errs)), 3) if errs else None
    best_rep = min(scored, key=lambda r: r['cost'])
    fits = [r for r in scored if r['period_fit'] is not None]
    if tile:
        route = 'forced'
        best = scored[0]
    elif best_rep['repeat_share'] >= 0.35:
        route = 'repeats'
        best = best_rep
    elif fits and max(r['period_fit'] for r in fits) >= 0.6:
        route = 'periodicity'
        top = max(r['period_fit'] for r in fits)
        best = min([r for r in fits if r['period_fit'] >= top - 0.1], key=lambda r: r['tile'])
        pp = best['tile']
        best = dict(best)
        best['phase'] = [_fold_phase(Yh, pp), _fold_phase(Yh.T, pp)]
        best['nx'], best['ny'] = (w - best['phase'][0]) // pp, (h - best['phase'][1]) // pp
    else:
        route = 'weak (lowest tiling cost, no clear repeats or periodicity)'
        best = best_rep
    if route == 'repeats':
        # refine the phase: the true grid minimises the number of distinct (quantised) cells
        pp = best['tile']
        bx, by = best['phase']
        r_ = max(1, pp // 4)
        bestu = None
        cands_ph = []
        for dy in range(-r_, r_ + 1):
            for dx in range(-r_, r_ + 1):
                ox_, oy_ = (bx + dx) % pp, (by + dy) % pp
                nx_, ny_ = (w - ox_) // pp, (h - oy_) // pp
                if nx_ * ny_ < 6:
                    continue
                cc = sub[oy_:oy_ + ny_ * pp, ox_:ox_ + nx_ * pp].reshape(ny_, pp, nx_, pp, 3).transpose(0, 2, 1, 3, 4).reshape(nx_ * ny_, -1)
                cc = cc[rng_sel(len(cc), 500)].astype(np.float32)
                sq = (cc ** 2).sum(1)
                D = sq[:, None] + sq[None, :] - 2 * cc @ cc.T
                np.fill_diagonal(D, np.inf)
                u = float(np.mean(np.sqrt(np.maximum(0, D.min(1)) / cc.shape[1])))
                cands_ph.append((u, ox_, oy_, nx_, ny_))
        if cands_ph:
            # among (near-)ties in repetitiveness prefer grid lines that sit on edges (tile seams)
            gxp = np.abs(np.diff(Y, axis=1)).mean(0)
            gyp = np.abs(np.diff(Y, axis=0)).mean(1)
            fx = np.array([gxp[k_ - 1::pp].mean() if k_ >= 1 else gxp[pp - 1::pp].mean() for k_ in range(pp)])
            fy = np.array([gyp[k_ - 1::pp].mean() if k_ >= 1 else gyp[pp - 1::pp].mean() for k_ in range(pp)])
            umin = min(c_[0] for c_ in cands_ph)
            tol = max(1e-6, 0.05 * umin) + 0.02
            near = [c_ for c_ in cands_ph if c_[0] <= umin + tol]
            bestu = max(near, key=lambda c_: fx[c_[1]] / (fx.mean() + 1e-9) + fy[c_[2]] / (fy.mean() + 1e-9))
        if bestu:
            best = dict(best)
            best['phase'] = [bestu[1], bestu[2]]
            best['nx'], best['ny'] = bestu[3], bestu[4]
    res['selection'] = route
    res['tile_confidence'] = {'repeats': 'high', 'periodicity': 'medium', 'forced': 'user'}.get(route, 'low')
    p = best['tile']
    ox, oy = best['phase']
    nxc, nyc = best['nx'], best['ny']
    cells = sub[oy:oy + nyc * p, ox:ox + nxc * p].reshape(nyc, p, nxc, p, 3).transpose(0, 2, 1, 3, 4).reshape(nyc * nxc, p, p, 3)
    cl = luma8(cells.astype(np.float32)).reshape(len(cells), -1)
    flat = cl.std(1) < 3.0
    gid, exact_inv = _group_cells(cells, flat)
    fam, _ = _group_cells(cells, flat, corr_min=0.6, dE_max=30.0)
    fam_ids, fam_counts = np.unique(fam[fam >= 0], return_counts=True)
    fam_sorted = np.sort(fam_counts)[::-1]
    ids, counts_ = np.unique(gid, return_counts=True)
    counts = {int(i): int(c) for i, c in zip(ids, counts_)}
    nonflat = gid >= 0
    groups = sorted([g for g in counts if g >= 0], key=lambda g: -counts[g])
    rank = {g: i for i, g in enumerate(groups)}
    repeated = nonflat & np.array([counts[int(g)] >= 2 for g in gid])
    coverage = float(repeated.sum() / max(1, nonflat.sum()))
    variants = {g: int(len(np.unique(exact_inv[gid == g]))) for g in groups}
    grid_ids = gid.reshape(nyc, nxc)
    mean_L = rgb_to_Lstar(cells.reshape(len(cells), -1, 3).mean(1).astype(np.float32))
    flat_dark = (flat & (mean_L < 15)).reshape(nyc, nxc)
    wall, wall_ev = _wall_face_guess(grid_ids, flat_dark, counts)
    # reference-pixel geometry of the grid lines
    gx_nat = [nx0 + ox + i * p for i in range(nxc + 1)]
    gy_nat = [ny0 + oy + j * p for j in range(nyc + 1)]
    to_ref_x = lambda n: int(cx[n]) if n < len(cx) else int(cx_end[-1])
    to_ref_y = lambda n: int(cy[n]) if n < len(cy) else int(cy_end[-1])
    gx_ref = [to_ref_x(n) for n in gx_nat]
    gy_ref = [to_ref_y(n) for n in gy_nat]
    scale = (W / nw, H / nh)
    res.update({
        'tile': p, 'tile_ref_px': round(p * scale[0], 2),
        'phase': [ox, oy], 'phase_note': 'native px offset of the first full tile from the analysed region origin',
        'phase_ref_px': [gx_ref[0], gy_ref[0]],
        'grid_cells': [nxc, nyc], 'cells': int(len(cells)), 'flat_cells': int(flat.sum()),
        'flat_share': round(float(flat.mean()), 4), 'unique': len(groups), 'unique_exact': int(len(np.unique(exact_inv[nonflat]))) if nonflat.any() else 0,
        'flat_colours': len([g for g in counts if g < 0]), 'coverage': round(coverage, 4),
        'coverage_note': 'share of non-flat cells whose tile (near-duplicate group) occurs at least twice',
        'singletons': int(sum(1 for g in groups if counts[g] == 1)),
        'families': int(len(fam_ids)),
        'families_top10_share': round(float(fam_sorted[:10].sum() / max(1, fam_sorted.sum())), 3),
        'families_note': 'looser clusters (structure correlation >= 0.6): how many distinct designs, ignoring small variations',
        'top_tiles': [{'rank': rank[g], 'count': counts[g], 'variants': variants[g]} for g in groups[:20]],
        'wall_face_tiles': wall, 'wall_face_evidence': wall_ev,
        'candidates': sorted(scored, key=lambda r: r['cost']),
        'grid_lines_ref_x': gx_ref, 'grid_lines_ref_y': gy_ref,
    })
    # ---- tiles_grid.png
    rx0, ry0, rx1, ry1 = res['region_ref']
    crop = Image.fromarray(rgb).crop((rx0, ry0, rx1, ry1))
    rw, rh = crop.size
    zf = 1400 / max(1, rw)
    zf = max(1, int(zf)) if zf >= 1 else zf
    dw, dh = max(1, int(round(rw * zf))), max(1, int(round(rh * zf)))
    disp = crop.resize((dw, dh), Image.NEAREST if zf >= 1 else Image.LANCZOS).convert('RGBA')
    ov = Image.new('RGBA', disp.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    palette_ = [(255, 80, 80), (80, 200, 255), (120, 255, 120), (255, 200, 60), (220, 120, 255), (255, 140, 200),
                (80, 255, 220), (255, 255, 120), (160, 160, 255), (255, 160, 90)]
    for j in range(nyc):
        for i in range(nxc):
            g = int(grid_ids[j, i])
            X0, X1 = (gx_ref[i] - rx0) * zf, (gx_ref[i + 1] - rx0) * zf
            Y0, Y1 = (gy_ref[j] - ry0) * zf, (gy_ref[j + 1] - ry0) * zf
            if g >= 0 and rank[g] < len(palette_) and counts[g] >= 2:
                od.rectangle([X0, Y0, X1, Y1], fill=palette_[rank[g]] + (70,))
            elif g >= 0 and counts[g] == 1 and coverage >= 0.3:
                od.line([(X0 + 2, Y0 + 2), (X1 - 2, Y1 - 2)], fill=(255, 60, 60, 140), width=1)
    for xg in gx_ref:
        od.line([((xg - rx0) * zf, 0), ((xg - rx0) * zf, dh)], fill=(255, 230, 60, 200), width=1)
    for yg in gy_ref:
        od.line([(0, (yg - ry0) * zf), (dw, (yg - ry0) * zf)], fill=(255, 230, 60, 200), width=1)
    disp = Image.alpha_composite(disp, ov).convert('RGB')
    dd = ImageDraw.Draw(disp)
    cell_disp = p * scale[0] * zf
    if cell_disp >= 18:
        fnt = font(max(10, min(16, int(cell_disp / 3))))
        for j in range(nyc):
            for i in range(nxc):
                g = int(grid_ids[j, i])
                if g >= 0 and rank[g] < 20 and counts[g] >= 2:
                    label(dd, ((gx_ref[i] - rx0) * zf + 2, (gy_ref[j] - ry0) * zf + 2), str(rank[g]), fnt, fg=(255, 255, 255), bg=(0, 0, 0), pad=1)
    title = ('tile %d %s (= %.4g ref px), phase %s native / first line at ref (%d,%d); %d unique tiles (%d exact), coverage %.0f%%\n'
             'tint = top-10 repeated tiles (number = rank)%s%s'
             % (p, 'native px' if 'native' in units else units, p * scale[0], best['phase'], gx_ref[0], gy_ref[0], len(groups), res['unique_exact'],
                100 * coverage, ', red slash = singleton' if coverage >= 0.3 else ' (few literal repeats: singletons not marked)',
                ('; wall face ~%d tiles' % wall) if wall else ''))
    disp = add_ruler(disp, rx0, ry0, zf, grid=False, title=title)
    disp.save(os.path.join(out_dir, 'tiles_grid.png'))
    # ---- tiles_unique.png
    show = groups[:max_unique]
    tz = max(1, int(round(72 / p)))
    tw = p * tz
    cols = max(1, min(12, int(1500 // (tw + 14))))
    flat_ids = sorted([g for g in counts if g < 0], key=lambda g: -counts[g])[:cols]
    rows = int(math.ceil(len(show) / cols)) + (1 if flat_ids else 0)
    ch_ = tw + 34
    sheet = Image.new('RGB', (cols * (tw + 14) + 14, rows * ch_ + 40), (22, 22, 26))
    sd = ImageDraw.Draw(sheet)
    sd.text((8, 8), 'unique tiles %d x %d %s, sorted by count (x = occurrences, v = exact variants); %d groups%s' % (
        p, p, 'native px' if 'native' in units else units, len(groups), (' (showing %d)' % len(show)) if len(show) < len(groups) else ''),
        font=font(13), fill=(235, 235, 235))
    for k_, g in enumerate(show):
        members = np.where(gid == g)[0]
        mL = mean_L[members]
        rep_i = members[np.argsort(mL)[len(mL) // 2]]
        x = 10 + (k_ % cols) * (tw + 14)
        y = 34 + (k_ // cols) * ch_
        sheet.paste(Image.fromarray(cells[rep_i]).resize((tw, tw), Image.NEAREST), (x, y))
        sd.rectangle([x - 1, y - 1, x + tw, y + tw], outline=(90, 90, 90))
        sd.text((x, y + tw + 2), '#%d x%d' % (rank[g], counts[g]), font=font(12), fill=(235, 235, 235))
        sd.text((x, y + tw + 16), 'v%d' % variants[g], font=font(11), fill=(150, 150, 150))
    if flat_ids:
        y = 34 + (rows - 1) * ch_
        for k_, g in enumerate(flat_ids):
            members = np.where(gid == g)[0]
            x = 10 + k_ * (tw + 14)
            sheet.paste(Image.fromarray(cells[members[0]]).resize((tw, tw), Image.NEAREST), (x, y))
            sd.rectangle([x - 1, y - 1, x + tw, y + tw], outline=(90, 90, 90))
            sd.text((x, y + tw + 2), 'flat x%d' % counts[g], font=font(12), fill=(200, 200, 200))
    sheet.save(os.path.join(out_dir, 'tiles_unique.png'))
    res['outputs'] = ['tiles_grid.png', 'tiles_unique.png']
    res['seconds'] = round(time.time() - t0, 2)
    return res


def cmd_tiles(a):
    if is_video(a.file):
        info = ffprobe_info(a.file)
        frs = extract_frame(a.file, a.t or 0.0, fps=info['fps'])
        if not frs:
            raise SystemExit('no frame at t=%s' % a.t)
        rgb = frs[0]
        name = '%s@%.3f' % (os.path.basename(a.file), a.t or 0.0)
    else:
        rgb, _ = load_image(a.file)
        name = os.path.basename(a.file)
    region = parse_box(a.region) if a.region else None
    res = analyze_tiles(rgb, a.out, region, a.tile, a.max_unique, name)
    key = name + ('@%s' % a.region.replace(' ', '') if a.region else '')
    merge_study_json(a.out, 'tiles', key, res)
    print('TILES %s  region ref %s  (%s)' % (name, ','.join(str(v) for v in res['region_ref']), res['units']))
    print('  pixel grid : ' + res['pixel_grid'])
    print('  tile       : %d (%.4g ref px), phase %s -> first grid line at ref (%d,%d); %dx%d full cells; chosen by %s'
          % (res['tile'], res['tile_ref_px'], res['phase'], res['phase_ref_px'][0], res['phase_ref_px'][1], res['grid_cells'][0], res['grid_cells'][1], res['selection']))
    tp = res['texture_period']
    print('  texture    : repeat period x %s y %s (autocorr peaks x %s, y %s; spectral %s / %s)' % (
        tp['x'], tp['y'], tp['autocorr_peaks_x'], tp['autocorr_peaks_y'], tp['spectral_x'], tp['spectral_y']))
    print('  candidates : ' + '  '.join('%d:cost %.2f rep %.0f%% fit %s%s' % (c['tile'], c['cost'], 100 * c['repeat_share'], '-' if c['period_fit'] is None else '%.2f' % c['period_fit'],
                                                                            '*' if c['autocorr_peak'] else '') for c in sorted(res['candidates'], key=lambda c: c['tile']))
          + '   (cost: lower = better tiling by literal repeats; fit: tile is a whole multiple of the texture period; * autocorr peak)')
    print('  unique     : %d tiles (%d exact variants), %d singletons, %d flat colours; flat cells %.0f%%'
          % (res['unique'], res['unique_exact'], res['singletons'], res['flat_colours'], 100 * res['flat_share']))
    print('  coverage   : %.0f%% of non-flat cells are repeated tiles; %d looser design families (top 10 cover %.0f%%)'
          % (100 * res['coverage'], res['families'], 100 * res['families_top10_share']))
    print('  top tiles  : ' + ', '.join('#%d x%d (v%d)' % (t['rank'], t['count'], t['variants']) for t in res['top_tiles'][:10]))
    ev = res['wall_face_evidence']
    print('  wall face  : %s' % (('~%d tile(s): cap+face band under empty space (rows %s), floor below %.0f%%'
                                  % (res['wall_face_tiles'], sorted(set(g['rows_below_void'] for g in ev['wall_like_groups'])), 100 * ev['floor_share_below_band']))
                                 if res['wall_face_tiles'] else 'not detectable (%s)' % ev.get('note', '')))
    print('  outputs    : tiles_grid.png, tiles_unique.png (%.1fs)' % res['seconds'])
    print('  json       : %s' % os.path.join(a.out, 'study.json'))


def cmd_probe(a):
    if is_video(a.file):
        info = ffprobe_info(a.file)
        print('VIDEO %s: %dx%d, %.4g fps (%s), %.3fs, %d frames, %s %s %s, %.0f kbit/s%s' % (
            os.path.basename(a.file), info['width'], info['height'], info['fps'], info['r_frame_rate'], info['duration'], info['frames'],
            info['codec'], info['profile'] or '', info['pix_fmt'], info['bit_rate'] / 1000, ', audio: ' + ','.join(info['audio']) if info['audio'] else ', no audio'))
        if info['variable_frame_rate']:
            print('  note: avg_frame_rate != r_frame_rate (possibly variable frame rate)')
    else:
        im = Image.open(a.file)
        rgb, mask = load_image(a.file)
        flat = rgb.reshape(-1, 3) if mask is None else rgb[mask]
        keys = (flat[:, 0].astype(np.int64) << 16) | (flat[:, 1].astype(np.int64) << 8) | flat[:, 2]
        ncol = int(len(np.unique(keys)))
        info = {'kind': 'image', 'width': im.width, 'height': im.height, 'mode': im.mode, 'format': im.format,
                'colours': ncol, 'has_alpha': mask is not None, 'frames': getattr(im, 'n_frames', 1),
                'file_bytes': os.path.getsize(a.file)}
        if mask is not None:
            info['transparent_share'] = round(float(1 - mask.mean()), 4)
        print('IMAGE %s: %dx%d, mode %s (%s), %d distinct colours%s, %d bytes' % (
            os.path.basename(a.file), im.width, im.height, im.mode, im.format, ncol,
            (', alpha: %.1f%% transparent' % (100 * info['transparent_share'])) if mask is not None else '', info['file_bytes']))
    if a.out:
        merge_study_json(a.out, 'probe', os.path.basename(a.file), info)


def parse_box(s):
    v = [int(round(float(x))) for x in s.replace(' ', '').split(',')]
    if len(v) != 4:
        raise SystemExit('region must be x0,y0,x1,y1')
    x0, y0, x1, y1 = v
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def parse_grid(s):
    a, b = s.lower().split('x')
    return int(a), int(b)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Study a 2D art reference (image or video). See the module docstring for examples.')
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('probe', help='basic facts about an image or video')
    p.add_argument('file')
    p.add_argument('--out', help='also record into OUT/study.json')
    p = sp.add_parser('image', help='full still-image study')
    p.add_argument('file')
    p.add_argument('--out', required=True)
    p.add_argument('--grid', default='6x4', help='tiles as COLSxROWS (default 6x4)')
    p.add_argument('--overlap', type=float, default=0.08, help='tile overlap fraction (default 0.08)')
    p.add_argument('--zoom', type=int, default=0, help='tile zoom (default auto 2-6)')
    p.add_argument('--colors', type=int, default=32, help='k-means palette size when >256 colours (default 32)')
    p = sp.add_parser('video', help='full video study')
    p.add_argument('file')
    p.add_argument('--out', required=True)
    p.add_argument('--fps', type=float, default=4.0, help='contact sheet rate (default 4)')
    p.add_argument('--cols', type=int, default=6, help='contact sheet columns (default 6)')
    p.add_argument('--cells', default='8x6', help='rate map cells COLSxROWS (default 8x6)')
    p.add_argument('--cut', type=float, default=0.3, help='scene cut threshold: colour-histogram change 0..1 (default 0.3)')
    p.add_argument('--region', action='append', default=[], help='x0,y0,x1,y1 (reference px); repeatable')
    p.add_argument('--keyframes', type=int, default=3, help='representative keyframes to analyse as images (default 3)')
    p.add_argument('--noise', type=int, default=None, help='per-pixel change threshold 0..255 (default auto)')
    p.add_argument('--no-keyframe-analysis', action='store_true')
    p = sp.add_parser('crop', help='one zoomed crop with a labelled ruler')
    p.add_argument('file')
    p.add_argument('x0', type=int)
    p.add_argument('y0', type=int)
    p.add_argument('x1', type=int)
    p.add_argument('y1', type=int)
    p.add_argument('--zoom', type=float, default=None, help='default 4 (--clean: 1)')
    p.add_argument('--grid', type=int, default=10, help='labelled grid step in reference px (default 10)')
    p.add_argument('--out', required=True)
    p.add_argument('--t', type=float, default=None, help='video time in seconds')
    p.add_argument('--clean', action='store_true', help='no rulers, grid or labels (crops used as generator refs)')
    p = sp.add_parser('track', help='every unique drawing of a video region')
    p.add_argument('file')
    p.add_argument('--region', required=True, help='x0,y0,x1,y1 (reference px)')
    p.add_argument('--out', required=True)
    p.add_argument('--from', dest='t_from', type=float, default=None)
    p.add_argument('--to', dest='t_to', type=float, default=None)
    p.add_argument('--zoom', type=int, default=0, help='display zoom (default auto)')
    p.add_argument('--noise', type=int, default=None, help='per-pixel change threshold (default auto)')
    p = sp.add_parser('tiles', help='level grid: tile size, phase, unique tiles')
    p.add_argument('file')
    p.add_argument('--region', default=None, help='x0,y0,x1,y1 (reference px), e.g. a floor/wall area')
    p.add_argument('--t', type=float, default=None, help='video time in seconds')
    p.add_argument('--out', required=True)
    p.add_argument('--tile', type=int, default=None, help='force a tile size (native px)')
    p.add_argument('--max-unique', type=int, default=120, help='unique tiles shown on the sheet (default 120)')
    a = ap.parse_args(argv)
    if a.cmd == 'probe':
        cmd_probe(a)
    elif a.cmd == 'image':
        if is_video(a.file):
            raise SystemExit('this is a video: use the "video" subcommand')
        cols, rows = parse_grid(a.grid)
        res = analyze_image(a.file, a.out, cols, rows, a.overlap, a.zoom, a.colors)
        merge_study_json(a.out, 'image', os.path.basename(a.file), res)
        print(summarize_image(res, os.path.basename(a.file)))
        print('  json       : %s' % os.path.join(a.out, 'study.json'))
    elif a.cmd == 'video':
        cx, cy = parse_grid(a.cells)
        regions = [parse_box(r) for r in a.region]
        res = analyze_video(a.file, a.out, a.fps, a.cols, (cx, cy), a.cut, regions, a.keyframes, a.noise,
                            not a.no_keyframe_analysis)
        merge_study_json(a.out, 'video', os.path.basename(a.file), res)
        print(summarize_video(res, os.path.basename(a.file)))
        print('  json       : %s' % os.path.join(a.out, 'study.json'))
    elif a.cmd == 'crop':
        cmd_crop(a)
    elif a.cmd == 'track':
        cmd_track(a)
    elif a.cmd == 'tiles':
        cmd_tiles(a)


if __name__ == '__main__':
    main()
