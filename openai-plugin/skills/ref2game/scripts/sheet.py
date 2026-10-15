#!/usr/bin/env python3
"""sheet.py — contact sheets for looking at many images at once (the lead looks at sheets and crops, not full frames).

    python3 sheet.py OUT.png IMG [IMG ...] [--cols 4] [--w 480] [--crop x0,y0,x1,y1] [--bg gray|checker|black|white] [--label]

  * assets on a neutral background:   sheet.py out.png art/gen/tuft_*.png --bg gray --label
  * a cycle frame by frame (crop):     sheet.py run.png frames/t*.png --crop 600,300,1000,700 --cols 6 --w 240 --label
  * before/after or 4 key beats:       sheet.py beats.png frames/t1.00.png frames/t2.50.png --cols 2 --w 960
Images are sorted by the number in their file name (t0.25 < t1.50 < t10.0), so time series come out in order.
"""
import argparse, re
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument('out'); ap.add_argument('imgs', nargs='+'); ap.add_argument('--cols', type=int, default=4); ap.add_argument('--w', type=int, default=480)
ap.add_argument('--crop'); ap.add_argument('--bg', default='gray'); ap.add_argument('--label', action='store_true')
a = ap.parse_args()
key = lambda p: [float(x) for x in re.findall(r'\d+(?:\.\d+)?', p.split('/')[-1])] or [0]
files = sorted(a.imgs, key=key)
ims = []
for f in files:
    im = Image.open(f).convert('RGBA')
    if a.crop: im = im.crop(tuple(int(v) for v in a.crop.split(',')))
    im.thumbnail((a.w, a.w * 4)); ims.append((f, im))
cw = a.w; ch = max(im.height for _, im in ims) + (18 if a.label else 0)
rows = (len(ims) + a.cols - 1) // a.cols
S = Image.new('RGBA', (cw * min(a.cols, len(ims)), ch * rows), (0, 0, 0, 255))
for k, (f, im) in enumerate(ims):
    x, y = (k % a.cols) * cw, (k // a.cols) * ch
    if a.bg == 'checker':
        t = Image.new('RGBA', (cw, ch)); d = ImageDraw.Draw(t)
        for i in range(0, cw, 16):
            for j in range(0, ch, 16): d.rectangle((i, j, i + 15, j + 15), fill=(200, 200, 200, 255) if (i + j) // 16 % 2 else (150, 150, 150, 255))
    else:
        t = Image.new('RGBA', (cw, ch), {'gray': (110, 110, 110, 255), 'black': (0, 0, 0, 255), 'white': (255, 255, 255, 255)}.get(a.bg, (110, 110, 110, 255)))
    t.alpha_composite(im, ((cw - im.width) // 2, 0)); S.paste(t, (x, y))
    if a.label: ImageDraw.Draw(S).text((x + 4, y + ch - 15), f.split('/')[-1], fill=(255, 255, 255, 255))
S.convert('RGB').save(a.out); print(a.out, S.size)
