#!/usr/bin/env python3
"""placeholders.py — draw simple stand-in art so the live template runs in minute one (before any generation).

    python3 placeholders.py [--out art/gen] [--force] [--set side|top|blank]

Writes art/gen/<name>.png for every name the template scene uses. Existing files are kept (unless --force), so real
generated art that already replaced a placeholder is never overwritten. Shapes are drawn at 2x and downsampled (AA),
with a dark ink outline on play-plane pieces and none on background bands (stand-ins only: the real art's line
treatment comes from the style bible).
"""
import argparse, math, os
from PIL import Image, ImageDraw, ImageFilter

INK = (40, 26, 14, 255)


def aa(im):                                  # draw at 2x → downsample = antialiased edges
    return im.resize((im.width // 2, im.height // 2), Image.LANCZOS)


def outlined(draw_fn, size, ink=8):
    """draw_fn(d, grow) draws the shape; drawn once grown by `ink` px in INK, then on top in colour."""
    w, h = size[0] * 2, size[1] * 2
    base = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    m = Image.new('L', (w, h), 0); draw_fn(ImageDraw.Draw(m), 0, mask=True)
    edge = m.filter(ImageFilter.MaxFilter(ink * 2 + 1))
    base.paste(Image.new('RGBA', (w, h), INK), (0, 0), edge)
    draw_fn(ImageDraw.Draw(base), 0, mask=False)
    return aa(base)


def sky(W=1920, H=1080):
    im = Image.new('RGBA', (W, H)); px = im.load()
    for y in range(H):
        u = y / H; c = (int(120 + 130 * u), int(170 + 60 * u), int(220 - 40 * u), 255)
        for x in range(W): px[x, y] = c
    d = ImageDraw.Draw(im)
    for i, (cx, cy, r) in enumerate([(300, 220, 120), (420, 200, 90), (1300, 160, 140), (1460, 190, 100), (900, 300, 80)]):
        d.ellipse((cx - r * 1.6, cy - r * 0.6, cx + r * 1.6, cy + r * 0.6), fill=(255, 246, 228, 150))
    return im.filter(ImageFilter.GaussianBlur(6))


def band(W, H, ridge, amp, col, seed, bumps=7):
    im = Image.new('RGBA', (W * 2, H * 2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    pts = [(0, H * 2)]
    for x in range(0, W * 2 + 1, 8):
        u = x / (W * 2)
        y = ridge * 2 + amp * 2 * (0.6 * math.sin(u * math.pi * bumps + seed) + 0.4 * math.sin(u * math.pi * bumps * 2.3 + seed * 3))
        pts.append((x, y))
    pts.append((W * 2, H * 2)); d.polygon(pts, fill=col)
    return aa(im)


def strip(W=1024, H=300):                     # tileable ground strip: grass lip on top, dirt body; walk line ≈ 12% from top
    im = Image.new('RGBA', (W * 2, H * 2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    top = 40
    d.rectangle((0, top, W * 2, H * 2), fill=(120, 82, 50, 255))
    for i in range(0, W * 2, 64):
        d.ellipse((i - 20, top + 60 + (i * 37) % 120, i + 40, top + 100 + (i * 37) % 120), fill=(100, 66, 40, 255))
    d.rectangle((0, top - 8, W * 2, top + 6), fill=INK)
    d.rectangle((0, top + 6, W * 2, top + 46), fill=(120, 190, 70, 255))
    for i in range(0, W * 2, 32): d.polygon([(i, top + 46), (i + 16, top + 70), (i + 32, top + 46)], fill=(120, 190, 70, 255))
    return aa(im)


def ledge(W=700, H=200):
    def f(d, g, mask):
        c = 255 if mask else None
        d.rounded_rectangle((20, 40, W * 2 - 20, H * 2 - 30), 60, fill=c or (128, 88, 54, 255))
        if not mask:
            d.rounded_rectangle((20, 40, W * 2 - 20, 110), 40, fill=(126, 196, 74, 255))
    return outlined(f, (W, H), ink=7)


def tuft(W, H, n, seed, col=(110, 180, 60, 255)):
    def f(d, g, mask):
        for i in range(n):
            u = (i + 0.5) / n; x0 = W * 2 * (0.15 + 0.7 * u); lean = (u - 0.5) * W * 1.2 + 30 * math.sin(i * 2.1 + seed)
            hh = H * 2 * (0.55 + 0.45 * abs(math.sin(i * 1.7 + seed)))
            d.polygon([(x0 - 14, H * 2), (x0 + 14, H * 2), (x0 + lean, H * 2 - hh)], fill=255 if mask else (col[0], col[1] - (i % 3) * 18, col[2], 255))
    return outlined(f, (W, H), ink=4)


def body(W=300, H=340):
    def f(d, g, mask):
        d.ellipse((30, 30, W * 2 - 30, H * 2 - 30), fill=255 if mask else (236, 150, 60, 255))
        if not mask:
            d.ellipse((60, 60, W * 2 - 120, H - 20), fill=(250, 186, 96, 255))
            for ex in (W * 2 * 0.58, W * 2 * 0.78):
                d.ellipse((ex - 34, H * 0.62 - 44, ex + 34, H * 0.62 + 44), fill=(255, 255, 255, 255))
                d.ellipse((ex - 8, H * 0.62 - 24, ex + 24, H * 0.62 + 20), fill=(30, 20, 10, 255))
    return outlined(f, (W, H), ink=7)


def limb(W, H, col):
    def f(d, g, mask):
        d.rounded_rectangle((W * 0.5, 10, W * 1.5, H * 2 - W * 1.1), W * 0.5, fill=255 if mask else col)
        d.ellipse((W * 0.2, H * 2 - W * 1.6, W * 1.9, H * 2 - 10), fill=255 if mask else (200, 40, 40, 255))
    return outlined(f, (W, H), ink=6)


def coin(S=128):
    def f(d, g, mask):
        d.ellipse((16, 16, S * 2 - 16, S * 2 - 16), fill=255 if mask else (255, 196, 40, 255))
        if not mask:
            d.ellipse((60, 60, S * 2 - 60, S * 2 - 60), outline=(200, 130, 20, 255), width=14)
            d.ellipse((70, 50, 110, 90), fill=(255, 240, 180, 255))
    return outlined(f, (S, S), ink=6)


def clump(W=640, H=520):
    im = Image.new('RGBA', (W * 2, H * 2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i in range(14):
        a = i / 14 * math.pi; r = 180 + 60 * math.sin(i * 1.9)
        cx = W + math.cos(a) * W * 0.7; cy = H * 2 - math.sin(a) * H * 1.4
        d.ellipse((cx - r, cy - r * 0.6, cx + r, cy + r * 0.6), fill=(20, 40, 36, 255))
    d.rectangle((0, H * 2 - 160, W * 2, H * 2), fill=(20, 40, 36, 255))
    return aa(im)


ASSETS = {
    'bg_sky': lambda: sky(),
    'bg_far': lambda: band(2400, 700, 330, 60, (150, 170, 196, 255), 1.0, 5),
    'bg_mid': lambda: band(2400, 800, 420, 80, (70, 110, 96, 255), 2.3, 9),
    'ground': lambda: strip(),
    'ledge': lambda: ledge(),
    'tuft_0': lambda: tuft(160, 200, 7, 0.3),
    'tuft_1': lambda: tuft(220, 120, 9, 1.1, (130, 196, 70, 255)),
    'tuft_2': lambda: tuft(180, 180, 6, 2.2, (96, 166, 70, 255)),
    'hero_body': lambda: body(),
    'hero_arm': lambda: limb(60, 200, (236, 150, 60, 255)),
    'hero_leg': lambda: limb(70, 230, (236, 150, 60, 255)),
    'coin': lambda: coin(),
    'fg_clump': lambda: clump(),
}


# ---------------------------------------------------------------- top-down set (templates/live-topdown)
def ground_tex(S=512):                         # tileable grass: low-frequency blotches wrap-safe (drawn 3x3 then cropped)
    im = Image.new('RGBA', (S, S), (96, 150, 70, 255)); d = ImageDraw.Draw(im)
    for i in range(60):
        x, y, r = (i * 97) % S, (i * 57 + i * i * 13) % S, 10 + (i * 7) % 26
        c = (86 + (i % 3) * 10, 140 + (i % 4) * 8, 62, 255)
        for ox in (-S, 0, S):
            for oy in (-S, 0, S): d.ellipse((x + ox - r, y + oy - r * 0.7, x + ox + r, y + oy + r * 0.7), fill=c)
    return im.filter(ImageFilter.GaussianBlur(2))


def path_decal(W=900, H=260):
    im = Image.new('RGBA', (W * 2, H * 2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i in range(40):
        x = W * 2 * i / 40; y = H + 70 * math.sin(i / 6); r = 120 + 20 * math.sin(i * 1.3)
        d.ellipse((x - r, y - r * 0.6, x + r, y + r * 0.6), fill=(196, 168, 120, 255))
    return aa(im).filter(ImageFilter.GaussianBlur(3))


def tree_canopy(S=420):
    def f(d, g, mask):
        for i, (cx, cy, r) in enumerate([(0.5, 0.42, 0.36), (0.3, 0.55, 0.26), (0.7, 0.55, 0.26), (0.5, 0.65, 0.28), (0.38, 0.3, 0.22), (0.64, 0.3, 0.22)]):
            d.ellipse(((cx - r) * S * 2, (cy - r) * S * 2, (cx + r) * S * 2, (cy + r) * S * 2), fill=255 if mask else (60 + i * 8, 130 + i * 6, 64, 255))
        if not mask:
            for (cx, cy, r) in [(0.42, 0.32, 0.12), (0.58, 0.4, 0.1)]:
                d.ellipse(((cx - r) * S * 2, (cy - r) * S * 2, (cx + r) * S * 2, (cy + r) * S * 2), fill=(130, 190, 90, 255))
    return outlined(f, (S, S), ink=7)


def tree_trunk(W=90, H=160):
    def f(d, g, mask):
        d.rounded_rectangle((30, 0, W * 2 - 30, H * 2 - 10), 30, fill=255 if mask else (120, 80, 50, 255))
    return outlined(f, (W, H), ink=6)


def rock(W=180, H=130):
    def f(d, g, mask):
        d.ellipse((20, 40, W * 2 - 20, H * 2 - 10), fill=255 if mask else (140, 140, 150, 255))
        if not mask: d.ellipse((60, 60, W * 1.2, H * 1.0), fill=(175, 175, 185, 255))
    return outlined(f, (W, H), ink=6)


def hero_top(W=150, H=190):
    def f(d, g, mask):
        d.ellipse((30, 80, W * 2 - 30, H * 2 - 20), fill=255 if mask else (236, 150, 60, 255))
        d.ellipse((50, 10, W * 2 - 50, H * 1.2), fill=255 if mask else (250, 186, 96, 255))
        if not mask:
            for ex in (W * 0.75, W * 1.25):
                d.ellipse((ex - 18, H * 0.55 - 22, ex + 18, H * 0.55 + 22), fill=(255, 255, 255, 255))
                d.ellipse((ex - 8, H * 0.55 - 8, ex + 10, H * 0.55 + 14), fill=(30, 20, 10, 255))
    return outlined(f, (W, H), ink=7)


def critter(S=90):
    def f(d, g, mask):
        d.ellipse((20, 40, S * 2 - 20, S * 2 - 20), fill=255 if mask else (240, 236, 220, 255))
        d.ellipse((40, 10, 80, 90), fill=255 if mask else (240, 236, 220, 255)); d.ellipse((S * 2 - 80, 10, S * 2 - 40, 90), fill=255 if mask else (240, 236, 220, 255))
        if not mask:
            d.ellipse((S * 0.7, S * 0.9, S * 0.9, S * 1.1), fill=(30, 20, 10, 255)); d.ellipse((S * 1.1, S * 0.9, S * 1.3, S * 1.1), fill=(30, 20, 10, 255))
    return outlined(f, (S, S), ink=5)


TOP = {
    'ground_tex': lambda: ground_tex(), 'path': lambda: path_decal(), 'tree_canopy': lambda: tree_canopy(), 'tree_trunk': lambda: tree_trunk(),
    'rock': lambda: rock(), 'hero_top': lambda: hero_top(), 'critter': lambda: critter(), 'coin': lambda: coin(),
    'tuft_0': lambda: tuft(160, 200, 7, 0.3), 'tuft_1': lambda: tuft(220, 120, 9, 1.1, (130, 196, 70, 255)), 'tuft_2': lambda: tuft(180, 180, 6, 2.2, (96, 166, 70, 255)),
}

BLANK = {'bg_sky': lambda: sky(), 'coin': lambda: coin()}

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='art/gen'); ap.add_argument('--force', action='store_true'); ap.add_argument('--set', default='side', choices=['side', 'top', 'blank'])
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    for n, fn in {'top': TOP, 'blank': BLANK}.get(a.set, ASSETS).items():
        p = os.path.join(a.out, n + '.png')
        if os.path.exists(p) and not a.force: continue
        fn().save(p); print('placeholder', p)
