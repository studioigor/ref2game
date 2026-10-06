#!/usr/bin/env python3
"""
gen.py -- generate ONE image per job with any image generator (ref2game skill).
Stdlib + Pillow + numpy only. Run it from the project root (where ref2game.json lives).

USAGE
  python3 gen.py one   NAME art/prompts/NAME.txt [--ref IMG[=label] ...] [--size WxH]
                       [--alpha auto|native|key|lum|none] [--key RRGGBB] [--provider P] [--model M] [--quality Q]
                       [--seed N] [--out-dir art/gen] [--fit auto|cover|contain|stretch|none] [--pixel] [--no-wait]
                       [--no-style-ref] [--dry-run]
  python3 gen.py batch art/prompts/JOBS.json [--jobs 4] [--provider P] [--model M] [--skip-existing] [--no-wait]
                       [--no-style-ref] [--dry-run]
        JOBS.json = [{"name": "..", "prompt": "art/prompts/NAME.txt (or inline text)", "ref": [".."], "size": "WxH",
                      "alpha": "auto", "key": "00ff00", "seed": 7, "model": "..", "pixel": false}, ...]
  python3 gen.py check                                   # which providers are usable here (table)
  python3 gen.py key IN.png OUT.png [--key RRGGBB] [--pixel] [--lum]
                                                         # offline chroma key (--lum: paper key, default ffffff)
  python3 gen.py validate IMG.png                        # native-alpha validator report
  python3 gen.py pixel IN.png OUT.png [--grid auto|N] [--colors 16] [--scale 1]
                                                         # snap "pixel-looking" art to its real grid

CONFIG  ./ref2game.json (CLI flags override it)
  {"generator": {"provider": "codex", "model": null, "size": "1536x1024", "quality": "high",
                 "alpha": "auto", "key": "ff00ff", "jobs": 4,
                 "command": {"template": "python3 tools/my_sd.py --prompt-file {prompt_file} --out {out} --size {size} {refs}",
                             "native_alpha": false, "max_refs": 4, "timeout": 900},
                 "opts": {"<plugin name>": {"any": "plugin-specific options"}}},
   "style_bible": "art/style_bible.txt", "style_ref": ["ref.png"]}

PROMPT  [REFERENCE IMAGES labels] + style bible (if the file exists) + "ASSET:\\n" + prompt file
        + background line. Style refs (default ./ref.png) are always attached first and labelled
        "Image 1 = style reference only: ..."; --ref images follow as Image 2, 3, ...
        A configured style_ref that is missing fails the job (setup.sh --ref puts the reference at ./ref.png);
        --no-style-ref skips style refs on purpose. Real runs refuse while the style bible is still the setup
        placeholder ("replace after the study"); --dry-run works meanwhile.

OUTPUT  <out-dir>/<NAME>.png (final), art/raw/<NAME>.<ext> (provider output untouched),
        art/logs/<NAME>.json (provider, model, sizes, prompt, refs, seconds, request id, alpha method),
        art/old/<NAME>-<time>.png (previous final, copied before it is replaced).

ALPHA   native = ask the provider for real transparency, then VALIDATE (soft partial-alpha edges, no
        baked checkerboard); an opaque result on a flat key-coloured/saturated border is keyed instead.
        key    = prompt asks for a flat #RRGGBB background; removed locally (OKLab soft matte, edge
        un-mix C=(I-(1-a)K)/a, despill, 1px choke, specks < 16 px^2 dropped).
        lum    = strokes on flat paper (watercolour, ink, silhouettes; --key = paper colour, default ffffff,
                 measured from the border when close): alpha = distance to the paper in luminance, raised per
                 channel where needed so colours un-multiply C=(I-(1-a)P)/a without clipping; border grain = floor.
        auto   = none for opaque names (generator "opaque" patterns, default bg_sky*, *_tex); else native if the
                 provider's CAPS say native_alpha, else key.   none = leave as is.

PROVIDERS
  built-in: codex   (Codex CLI built-in image_gen, prompt via stdin; needs `codex` on PATH + login)
            command (shell template from ref2game.json: {prompt_file} {out} {refs} {size} {width}
                     {height} {name} {model} {seed} {quality} {transparent} {key})
            manual  (writes art/requests/NAME.txt, waits for you to drop <out-dir>/NAME.png; --no-wait returns
                     at once, re-run to pick the drop up)
  plugins:  art/providers/<name>.py in the PROJECT, used when generator.provider == "<name>".
            Start from <skill>/scripts/provider_template.py.

PLUGIN CONTRACT (art/providers/<name>.py)
  CAPS = {"native_alpha": bool,        # can return real alpha when asked (transparent=True)
          "max_refs": int,             # how many reference images one call accepts (0 = none)
          "sizes": "any" | ["1024x1024", "1536x1024", "16:9", ...],   # gen.py maps the request to
                                       # the nearest entry, then resizes/pads the result locally
          "edit": bool,                # refs are used as edit/conditioning images
          "env": ["API_KEY_VAR", "ALT_A|ALT_B"],   # required env vars ("A|B" = either)
          # optional: "pixel": bool (true low-res output: nearest scaling, hard alpha ok),
          #           "labels": bool (refs are in-context images -> "Image N = ..." lines; default True),
          #           "style_bible": bool (default True), "max_prompt": int, "size_in_prompt": bool,
          #           "default_model": str
         }
  def generate(prompt: str, refs: list[str], size: tuple[int, int], transparent: bool,
               model: str | None, out_raw: str, opts: dict, dry_run: bool) -> dict:
      # return {"path": <raw file written>, "native_alpha": bool, "request_id": str|None, "model": str}
      # dry_run: print the exact request with the helpers below (they never send when dry_run=True)
      #          and return {"dry_run": True}. Never spend money in dry-run.
      # opts = generator.opts[<name>] from ref2game.json + {"quality", "seed", "_name", "_out",
      #        "_log", "_size_requested"}.
  optional: def check() -> tuple[bool, str]   (extra readiness test for `gen.py check`)
  Helpers (import with `from gen import ...`): http_request, http_json, http_multipart,
  encode_multipart, b64_file, data_uri, poll, download, save_bytes, save_b64, env_key, mask_key,
  dry_note, say, GenError, HTTPFail.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import fnmatch
import glob
import importlib.util
import io
import json
import math
import mimetypes
import os
import random
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from PIL import Image

# `import gen` from a plugin must return THIS module, not a second copy.
sys.modules.setdefault("gen", sys.modules[__name__])
sys.dont_write_bytecode = True   # no __pycache__ in the skill or art/providers

SKILL_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SKILL_SCRIPTS, "provider_template.py")
RAW_DIR, LOG_DIR, REQ_DIR, OLD_DIR, PLUGIN_DIR = "art/raw", "art/logs", "art/requests", "art/old", "art/providers"
CONFIG_FILE = "ref2game.json"
UA = "ref2game-gen/1.0 (+python-urllib)"

CODEX_PREAMBLE = ("Use your built-in image_gen tool (not a CLI, script or API call) to generate ONE image, "
                  "then copy the generated PNG file into this workspace as {path} (create folders if needed). "
                  "Do not write any code or edit other files.")
STYLE_LABEL = ("style reference only: match its art style, rendering, palette and light; "
               "do not copy its composition")
EXTRA_LABEL = "reference for this asset: use it as the ASSET text describes"
# composition (isolated prop, edge-to-edge band…) comes from the ASSET text; these lines only say what fills the rest
KEY_LINE = ("Background: everywhere outside the ASSET, perfectly flat solid #{hex} (key colour); no gradient, no vignette, "
            "no ground or shadow beyond what the ASSET describes")
NATIVE_LINE = ("Background: fully transparent (real alpha channel, PNG) everywhere outside the ASSET, with clean anti-aliased "
               "edges; no ground or cast shadow beyond what the ASSET describes, no frame, no checkerboard pattern")
LUM_LINE = "Background: plain even #{hex} paper and nothing else on it: no texture, no vignette, no frame, no cast shadow"
BIBLE_PLACEHOLDER = "replace after the study"


# ----------------------------------------------------------------------------------------------
# printing / errors
# ----------------------------------------------------------------------------------------------
_PRINT = threading.Lock()


def say(*parts, name=None, err=False):
    msg = " ".join(str(p) for p in parts)
    if name:
        msg = f"[{name}] {msg}"
    with _PRINT:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)


class GenError(Exception):
    """A clear, user-facing failure (missing key, bad config, provider error)."""


class HTTPFail(GenError):
    def __init__(self, status, method, url, body=b"", headers=None):
        self.status, self.method, self.url, self.body, self.headers = status, method, url, body, headers or {}
        text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
        hint = ""
        low = text.lower()
        if status in (401, 403):
            hint = " -> check the API key / account permissions"
        if any(w in low for w in ("moderation", "safety", "policy", "prohibited", "content_filter", "blocked")):
            hint = " -> content filter: rephrase (stylised, non-graphic; 'toy', 'cartoon prop') and retry"
        elif status in (400, 404, 422):
            hint = hint or " -> check endpoint/field names and allowed values against the official docs"
        elif status == 402:
            hint = " -> out of credits / billing"
        super().__init__(f"HTTP {status} on {method} {_mask_url(url)}: {text[:700].strip()}{hint}")


class DryRun(Exception):
    pass


# ----------------------------------------------------------------------------------------------
# helpers shared with plugins
# ----------------------------------------------------------------------------------------------
_SECRET_WORDS = ("authorization", "key", "token", "secret", "cookie", "password")


def mask_key(value):
    """Mask a secret for printing: 'Bearer sk-abc...wxyz' -> 'Bearer ****wxyz'."""
    s = str(value)
    if s.startswith("<"):
        return s
    parts = s.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() in ("bearer", "key", "token", "basic", "apikey", "api-key"):
        return parts[0] + " " + mask_key(parts[1])
    return ("****" + s[-4:]) if len(s) > 10 else "****"


def _mask_headers(h):
    return {k: (mask_key(v) if any(w in k.lower() for w in _SECRET_WORDS) else v) for k, v in (h or {}).items()}


def _mask_url(url):
    return re.sub(r"([?&](?:key|api_key|apikey|token|access_token|secret)=)[^&]+", r"\1****", str(url), flags=re.I)


def _redact(o):
    if isinstance(o, dict):
        return {k: _redact(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_redact(v) for v in o]
    if isinstance(o, str) and len(o) > 300:
        if o.startswith("data:") and "," in o[:200]:
            head = o[: o.index(",") + 1]
            return f"{head}<{len(o) - len(head)} base64 chars>"
        if re.fullmatch(r"[A-Za-z0-9+/=_\-\s]+", o[:400]):
            return f"<base64 {len(o)} chars>"
        return o[:240] + f" ...<{len(o)} chars; full prompt printed above>"
    return o


def dry_note(text):
    """Print an extra line in dry-run output (e.g. 'then polls GET .../status every 2-15 s')."""
    say(f"  [dry-run] {text}")


def _print_request(method, url, headers, body_desc):
    say(f"  [dry-run] {method} {_mask_url(url)}")
    for k, v in _mask_headers(headers).items():
        say(f"    {k}: {v}")
    if body_desc is None:
        return
    if isinstance(body_desc, (dict, list)):
        say("    body: " + json.dumps(_redact(body_desc), indent=2, ensure_ascii=False).replace("\n", "\n    "))
    else:
        say(f"    body: {body_desc}")


class Resp:
    def __init__(self, status, headers, body, url):
        self.status, self.headers, self.body, self.url = status, headers, body, url

    @property
    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except Exception as e:
            raise GenError(f"expected JSON from {_mask_url(self.url)}, got {self.body[:200]!r} ({e})")

    def header(self, name, default=None):
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return default


RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 529}


def _retry_after(headers):
    try:
        v = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
        return min(120.0, float(v)) if v else None
    except (TypeError, ValueError):
        return None


def _backoff(attempt):
    return min(60.0, 2.0 * (2 ** attempt)) * (0.75 + random.random() * 0.5)


def http_request(method, url, headers=None, body=None, timeout=300, retries=4, dry_run=False, show=None):
    """Send one HTTP request with retries on 429/5xx (honours Retry-After). Returns Resp, or None
    in dry-run (after printing the request; `show` overrides what is printed as the body).
    POSTs are NOT retried on timeouts (the job may still be running and billed)."""
    headers = {"User-Agent": UA, **(headers or {})}
    method = method.upper()
    if dry_run:
        _print_request(method, url, headers, show if show is not None else
                       (f"<{len(body)} bytes>" if isinstance(body, (bytes, bytearray)) else body))
        return None
    idempotent = method in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return Resp(r.status, dict(r.headers.items()), r.read(), url)
        except urllib.error.HTTPError as e:
            data = e.read() if hasattr(e, "read") else b""
            if e.code in RETRY_STATUS and attempt < retries:
                wait = _retry_after(e.headers) or _backoff(attempt)
                say(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}; retry {attempt + 1}/{retries} in {wait:.0f}s",
                    err=True)
                time.sleep(wait)
                continue
            raise HTTPFail(e.code, method, url, data, dict(e.headers.items()) if e.headers else {})
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            never_sent = isinstance(reason, (ConnectionRefusedError, socket.gaierror))
            if (idempotent or never_sent) and attempt < retries:
                wait = _backoff(attempt)
                say(f"network error ({reason}); retry {attempt + 1}/{retries} in {wait:.0f}s", err=True)
                time.sleep(wait)
                continue
            raise GenError(f"{method} {_mask_url(url)}: network error: {reason}"
                           + (" (not retried: a POST may still be running server-side)" if not idempotent else ""))
    raise GenError(f"{method} {_mask_url(url)}: gave up after {retries} retries")


def http_json(method, url, payload=None, headers=None, timeout=300, retries=4, dry_run=False):
    """JSON request -> Resp (use .json, .header('x-request-id')). None in dry-run."""
    h = {"Accept": "application/json", **(headers or {})}
    body = None
    if payload is not None:
        h.setdefault("Content-Type", "application/json")
        body = json.dumps(payload).encode("utf-8")
    return http_request(method, url, h, body, timeout, retries, dry_run, show=payload)


def encode_multipart(fields=None, files=None):
    """fields: dict or list of (name, value) (repeat names freely; dict/list values are JSON-encoded).
    files: list of (field, path_or_bytes[, filename[, mime]]). Returns (body_bytes, content_type)."""
    boundary = "----ref2game" + uuid.uuid4().hex
    out = io.BytesIO()
    items = list(fields.items()) if isinstance(fields, dict) else list(fields or [])
    for k, v in items:
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, (dict, list)):
            v = json.dumps(v)
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        out.write(str(v).encode("utf-8") + b"\r\n")
    for f in files or []:
        field, src = f[0], f[1]
        data = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
        fname = f[2] if len(f) > 2 and f[2] else (os.path.basename(src) if isinstance(src, str) else "file.bin")
        mime = f[3] if len(f) > 3 and f[3] else (_sniff_mime(data) or mimetypes.guess_type(fname)[0]
                                                 or "application/octet-stream")
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
                  f"Content-Type: {mime}\r\n\r\n".encode())
        out.write(bytes(data) + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def http_multipart(url, fields=None, files=None, headers=None, method="POST", timeout=300, retries=4, dry_run=False):
    """multipart/form-data request -> Resp. In dry-run prints field names/values and file summaries."""
    if dry_run:
        items = list(fields.items()) if isinstance(fields, dict) else list(fields or [])
        desc = {"multipart fields": {k: _redact(v) for k, v in items if v is not None},
                "multipart files": [f"{f[0]} <- {f[2] if len(f) > 2 and f[2] else (f[1] if isinstance(f[1], str) else 'bytes')}"
                                    f" ({len(f[1]) if isinstance(f[1], (bytes, bytearray)) else os.path.getsize(f[1])} bytes)"
                                    for f in (files or [])]}
        return http_request(method, url, {"Content-Type": "multipart/form-data; boundary=...", **(headers or {})},
                            None, timeout, retries, True, show=desc)
    body, ctype = encode_multipart(fields, files)
    return http_request(method, url, {"Content-Type": ctype, **(headers or {})}, body, timeout, retries, False)


def _sniff_ext(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    head = data[:400].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return ".svg"
    return None


def _sniff_mime(data):
    return {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
            ".svg": "image/svg+xml"}.get(_sniff_ext(bytes(data[:512])) or "")


def _encode_image(path, max_edge=None, fmt=None):
    data = open(path, "rb").read()
    if not max_edge and not fmt:
        return data, _sniff_mime(data) or "image/png"
    im = Image.open(io.BytesIO(data))
    im.load()
    if max_edge and max(im.size) > max_edge:
        s = max_edge / max(im.size)
        im = im.resize((max(1, round(im.size[0] * s)), max(1, round(im.size[1] * s))), Image.LANCZOS)
    fmt = (fmt or "png").lower()
    buf = io.BytesIO()
    if fmt in ("jpg", "jpeg"):
        im.convert("RGB").save(buf, "JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    if fmt == "webp":
        im.save(buf, "WEBP", lossless=True)
        return buf.getvalue(), "image/webp"
    im.save(buf, "PNG")
    return buf.getvalue(), "image/png"


def b64_file(path, max_edge=None, fmt=None):
    """Base64 (no data: prefix) of an image file; optionally downscaled to max_edge / re-encoded."""
    data, _ = _encode_image(path, max_edge, fmt)
    return base64.b64encode(data).decode("ascii")


def data_uri(path, max_edge=None, fmt=None):
    data, mime = _encode_image(path, max_edge, fmt)
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def save_bytes(data, out_raw):
    """Write provider bytes; fixes the extension from the content. Returns the real path."""
    ext = _sniff_ext(bytes(data[:512])) or os.path.splitext(out_raw)[1] or ".png"
    path = os.path.splitext(out_raw)[0] + ext
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def save_b64(b64, out_raw):
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    return save_bytes(base64.b64decode(b64), out_raw)


def download(url, out_raw, headers=None, timeout=300):
    """Fetch an output URL (or data: URI) into out_raw (extension fixed by content)."""
    if url.startswith("data:"):
        return save_b64(url, out_raw)
    r = http_request("GET", url, headers or {}, timeout=timeout)
    return save_bytes(r.body, out_raw)


def poll(fn, timeout=900, interval=2.0, max_interval=15.0, factor=1.5, label="job"):
    """Call fn() until it returns something other than None (raise GenError inside fn to fail).
    Sleeps interval, growing by `factor` up to max_interval."""
    t0, wait = time.time(), interval
    while True:
        r = fn()
        if r is not None:
            return r
        if time.time() - t0 > timeout:
            raise GenError(f"{label}: timed out after {timeout:.0f}s")
        time.sleep(wait)
        wait = min(max_interval, wait * factor)


def env_key(*names, dry_run=False):
    """First set env var among names ('A|B' entries allowed). Missing -> clear GenError naming them."""
    flat = [n for entry in names for n in str(entry).split("|") if n]
    for n in flat:
        v = os.environ.get(n)
        if v:
            return v.strip()
    if dry_run:
        return f"<unset ${flat[0]}>"
    raise GenError(f"missing API key: set {' or '.join('$' + n for n in flat)} "
                   f"(e.g. export {flat[0]}=...) and retry")


# ----------------------------------------------------------------------------------------------
# config / sizes
# ----------------------------------------------------------------------------------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise GenError(f"{CONFIG_FILE} is not valid JSON: {e}")
    return {}


def gcfg(cfg, key, default=None):
    v = (cfg.get("generator") or {}).get(key)
    return default if v is None else v


def parse_size(s):
    if isinstance(s, (list, tuple)):
        return int(s[0]), int(s[1])
    m = re.fullmatch(r"\s*(\d+)\s*[xX*×]\s*(\d+)\s*", str(s))
    if not m:
        raise GenError(f"bad size {s!r}: use WxH, e.g. 1536x1024")
    return int(m.group(1)), int(m.group(2))


def parse_hex(s):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(s).strip())
    if not m:
        raise GenError(f"bad key colour {s!r}: use RRGGBB, e.g. ff00ff")
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def nearest_size(req, sizes):
    """Map a requested (w,h) to the closest allowed size: aspect ratio first, then area.
    sizes: 'any' | list of 'WxH' or 'W:H' (an aspect keeps the requested area, rounded to 16)."""
    if not sizes or sizes == "any":
        return tuple(req)
    w, h = req
    best, best_score = None, None
    for s in sizes:
        s = str(s)
        if ":" in s:
            aw, ah = (float(x) for x in s.split(":"))
            hh = math.sqrt(w * h * ah / aw)
            cand = (max(16, int(round(hh * aw / ah / 16)) * 16), max(16, int(round(hh / 16)) * 16))
        else:
            cand = parse_size(s)
        score = (round(abs(math.log((cand[0] / cand[1]) / (w / h))), 2), abs(math.log(cand[0] * cand[1] / (w * h))))
        if best_score is None or score < best_score:
            best, best_score = cand, score
    return best


def _resize(im, wh, pixel):
    rs = Image.NEAREST if pixel else Image.LANCZOS
    if im.mode == "RGBA":
        return im.convert("RGBa").resize(wh, rs).convert("RGBA")
    return im.resize(wh, rs)


def fit_image(im, size, mode="auto", transparent=False, pixel=False):
    """Bring the provider output to the requested size. auto: same aspect -> resize; otherwise
    transparent -> contain + transparent pad, opaque -> cover + centre crop. Pixel art: integer
    nearest scaling + pad/crop."""
    W, H = size
    if mode == "none" or im.size == (W, H):
        return im, "none"
    sw, sh = im.size
    if mode == "auto":
        same = abs(math.log((sw / sh) / (W / H))) < 0.02
        mode = "stretch" if same else ("contain" if transparent else "cover")
    if pixel:
        k = min(W / sw, H / sh) if mode != "cover" else max(W / sw, H / sh)
        k = max(1, int(math.floor(k + 1e-6))) if k >= 1 else k
        im2 = _resize(im, (max(1, round(sw * k)), max(1, round(sh * k))), True)
        rgba_out = im2.mode == "RGBA" or transparent
        canvas = Image.new("RGBA" if rgba_out else "RGB", (W, H), (0, 0, 0, 0) if rgba_out else (0, 0, 0))
        canvas.paste(im2.convert(canvas.mode), ((W - im2.size[0]) // 2, (H - im2.size[1]) // 2))
        return canvas, f"pixel-x{k:g}"
    if mode == "stretch":
        return _resize(im, (W, H), False), "stretch"
    if mode == "cover":
        s = max(W / sw, H / sh)
        nw, nh = max(W, round(sw * s)), max(H, round(sh * s))
        im2 = _resize(im, (nw, nh), False)
        l, t = (nw - W) // 2, (nh - H) // 2
        return im2.crop((l, t, l + W, t + H)), "cover"
    s = min(W / sw, H / sh)
    nw, nh = max(1, round(sw * s)), max(1, round(sh * s))
    im2 = _resize(im, (nw, nh), False)
    if im2.mode == "RGBA" or transparent:
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.paste(im2.convert("RGBA"), ((W - nw) // 2, (H - nh) // 2))
    else:
        edge = tuple(int(x) for x in np.asarray(im2.convert("RGB")).reshape(-1, 3).mean(0))
        canvas = Image.new("RGB", (W, H), edge)
        canvas.paste(im2, ((W - nw) // 2, (H - nh) // 2))
    return canvas, "contain"


# ----------------------------------------------------------------------------------------------
# alpha pipeline
# ----------------------------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------------------------
# providers: built-ins + plugin loader
# ----------------------------------------------------------------------------------------------
class Provider:
    def __init__(self, name, kind, caps, generate, check=None, path=None):
        self.name, self.kind, self.caps, self.generate, self._check, self.path = name, kind, caps, generate, check, path

    def ready(self):
        missing = [e for e in self.caps.get("env", []) if not any(os.environ.get(n) for n in str(e).split("|"))]
        if missing:
            return False, "set " + ", ".join("$" + m.replace("|", " or $") for m in missing)
        if self._check:
            try:
                ok, why = self._check()
                return bool(ok), str(why)
            except Exception as e:
                return False, f"check() failed: {e}"
        return True, "env ok" if self.caps.get("env") else "no key needed"


def _rel(p):
    try:
        r = os.path.relpath(p)
        return p if r.startswith("..") else r
    except ValueError:
        return p


# --- codex -------------------------------------------------------------------------------------
CODEX_CAPS = {"native_alpha": True, "max_refs": 16, "sizes": "any", "edit": True, "env": [],
              "size_in_prompt": True, "default_model": "codex built-in image_gen"}


def _codex_check():
    exe = shutil.which("codex")
    if not exe:
        return False, "codex CLI not on PATH"
    try:
        out = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=20)
        txt = (out.stdout + out.stderr).strip().splitlines()
        last = txt[-1] if txt else ""
        if out.returncode == 0 and "logged in" in last.lower() and "not" not in last.lower():
            return True, last
        return False, f"not logged in ({last or 'run: codex login'})"
    except Exception as e:
        return True, f"on PATH (login status unknown: {e})"


def codex_generate(prompt, refs, size, transparent, model, out_raw, opts, dry_run):
    target = opts["_out"]
    log = os.path.join(LOG_DIR, f"{opts['_name']}.log")
    full = CODEX_PREAMBLE.format(path=_rel(target)) + "\n\n" + prompt
    exe = shutil.which("codex") or "codex"
    cmd = [exe, "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", os.getcwd(),
           "-c", 'model_reasoning_effort="low"']
    for r in refs:
        cmd += ["-i", r]
    cmd += ["--", "-"]
    if model:
        say(f"note: codex ignores --model ({model}); the built-in image_gen picks its own image model", name=opts["_name"])
    if dry_run:
        say('  [dry-run] printf "%s" "$PROMPT" | ' + shlex.join(cmd) + f" > {log} 2>&1")
        say(f"  [dry-run] then: expect {_rel(target)} (fallback: generated_images path in the log), move it to {out_raw}")
        return {"dry_run": True}
    if not shutil.which("codex"):
        raise GenError("codex CLI not found on PATH: install it (npm i -g @openai/codex) and run `codex login`")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    t0 = time.time()
    timeout = float(opts.get("timeout", 900))
    with open(log, "wb") as lf:
        try:
            p = subprocess.run(cmd, input=full.encode("utf-8"), stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            raise GenError(f"codex timed out after {timeout:.0f}s (see {log}); raise generator.opts.codex.timeout")
    text = open(log, encoding="utf-8", errors="replace").read()
    sid = (re.search(r"session id:\s*([0-9a-f-]{8,})", text) or [None, None])[1]
    src = None
    if os.path.exists(target) and os.path.getmtime(target) >= t0 - 1:
        src = target
    else:
        cands = [c for c in re.findall(r"(/[^\s'\"`]*generated_images/[^\s'\"`]+?\.(?:png|webp|jpg))", text)
                 if os.path.exists(c) and os.path.getmtime(c) >= t0 - 1]
        if not cands and sid:
            home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
            cands = sorted(glob.glob(os.path.join(home, "generated_images", sid, "*")), key=os.path.getmtime)
        if cands:
            src = cands[-1]
            say(f"codex did not copy the file; using {src}", name=opts["_name"])
    if not src:
        tail = "\n".join(text.strip().splitlines()[-12:])
        raise GenError(f"codex finished (exit {rc}) without an image; see {log}\n--- log tail ---\n{tail}")
    data = open(src, "rb").read()
    path = save_bytes(data, out_raw)
    if src == target:
        os.remove(target)
    return {"path": path, "native_alpha": transparent, "request_id": sid, "model": "codex image_gen"}


# --- command -----------------------------------------------------------------------------------
def _command_cfg(cfg):
    c = gcfg(cfg, "command")
    if isinstance(c, str):
        c = {"template": c}
    return c or {}


def make_command_provider(cfg):
    c = _command_cfg(cfg)
    caps = {"native_alpha": bool(c.get("native_alpha", False)), "max_refs": int(c.get("max_refs", 8)),
            "sizes": c.get("sizes", "any"), "edit": bool(c.get("edit", True)), "env": c.get("env", []),
            "pixel": bool(c.get("pixel", False)), "size_in_prompt": bool(c.get("size_in_prompt", False)),
            "labels": bool(c.get("labels", True)), "default_model": c.get("model")}

    def check():
        return (True, "template set") if c.get("template") else (False, 'set generator.command.template in ref2game.json')

    def generate(prompt, refs, size, transparent, model, out_raw, opts, dry_run):
        tpl = c.get("template")
        if not tpl:
            raise GenError('provider "command" needs generator.command.template in ref2game.json, e.g. '
                           '"python3 tools/gen_local.py --prompt-file {prompt_file} --out {out} --size {size} {refs}"')
        name = opts["_name"]
        prompt_file = os.path.join(REQ_DIR, f"{name}.prompt.txt")
        m = {"prompt_file": shlex.quote(prompt_file), "out": shlex.quote(out_raw),
             "refs": " ".join(shlex.quote(r) for r in refs), "size": f"{size[0]}x{size[1]}",
             "width": size[0], "height": size[1], "name": shlex.quote(name), "model": shlex.quote(model or ""),
             "seed": "" if opts.get("seed") is None else opts["seed"], "quality": shlex.quote(str(opts.get("quality") or "")),
             "transparent": "1" if transparent else "0", "key": opts.get("_key_hex", "ff00ff")}
        cmd = re.sub(r"\{(\w+)\}", lambda mm: str(m[mm.group(1)]) if mm.group(1) in m else mm.group(0), tpl)
        log = os.path.join(LOG_DIR, f"{name}.log")
        if dry_run:
            say(f"  [dry-run] writes {prompt_file} ({len(prompt)} chars)")
            say(f"  [dry-run] sh -c {shlex.quote(cmd)} > {log} 2>&1")
            return {"dry_run": True}
        for d_ in (prompt_file, out_raw, log):
            os.makedirs(os.path.dirname(d_), exist_ok=True)
        with open(prompt_file, "w") as f:
            f.write(prompt)
        t0 = time.time()
        with open(log, "wb") as lf:
            try:
                p = subprocess.run(cmd, shell=True, stdout=lf, stderr=subprocess.STDOUT, timeout=float(c.get("timeout", 900)))
            except subprocess.TimeoutExpired:
                raise GenError(f"command timed out (see {log})")
        stem = os.path.splitext(out_raw)[0]
        outs = [p_ for p_ in glob.glob(stem + ".*") if os.path.getmtime(p_) >= t0 - 1]
        if p.returncode != 0 or not outs:
            tail = "\n".join(open(log, errors="replace").read().strip().splitlines()[-10:])
            raise GenError(f"command exit {p.returncode}, output {'missing' if not outs else 'present'}; see {log}\n{tail}")
        return {"path": outs[0], "native_alpha": caps["native_alpha"] and transparent, "request_id": None,
                "model": model or c.get("model") or "command"}

    return Provider("command", "built-in", caps, generate, check)


# --- manual ------------------------------------------------------------------------------------
MANUAL_CAPS = {"native_alpha": True, "max_refs": 99, "sizes": "any", "edit": True, "env": [], "size_in_prompt": True,
               "default_model": "manual"}


def manual_generate(prompt, refs, size, transparent, model, out_raw, opts, dry_run):
    name, target = opts["_name"], opts["_out"]
    req = os.path.join(REQ_DIR, f"{name}.txt")
    stem = os.path.splitext(target)[0]

    def dropped(after):
        for ext in (".png", ".webp", ".jpg", ".jpeg"):
            p = stem + ext
            if os.path.exists(p) and os.path.getmtime(p) > after:
                return p
        return None

    found = dropped(os.path.getmtime(req)) if os.path.exists(req) else None
    if not found:
        lines = [f"# MANUAL IMAGE REQUEST: {name}",
                 "# 1. Generate ONE image with any tool, using the prompt below and the reference images listed (in order).",
                 f"# 2. Size: {size[0]}x{size[1]} px (or the closest the tool allows, same aspect).",
                 "# 3. " + ("Transparent PNG if the tool can; otherwise a perfectly flat #%s background." % opts.get("_key_hex", "FF00FF").upper()
                            if transparent else "Background as the prompt says."),
                 f"# 4. Save it as: {os.path.abspath(target)}   (png/webp/jpg)",
                 "# Reference images:"] + [f"#   Image {i}: {os.path.abspath(r)}" for i, r in enumerate(refs, 1)] + \
                ["", "PROMPT:", prompt, ""]
        if dry_run:
            say(f"  [dry-run] would write {req}:\n" + "\n".join("    " + l for l in lines[:6 + len(refs)]))
            return {"dry_run": True}
        os.makedirs(os.path.dirname(req), exist_ok=True)
        with open(req, "w") as f:
            f.write("\n".join(lines))
        say(f"MANUAL: open {req}, generate the image, save it as {target}", name=name)
        if opts.get("_no_wait"):
            return {"pending": True}
        say("waiting for the file (Ctrl-C to stop; re-run later to pick it up)...", name=name)
        t_req = os.path.getmtime(req)
        found = poll(lambda: dropped(t_req), timeout=float(opts.get("timeout", 86400)), interval=3, max_interval=5,
                     label="manual drop")
        time.sleep(1.0)  # let the writer finish
    elif dry_run:
        say(f"  [dry-run] found dropped file {found}; would process it")
        return {"dry_run": True}
    path = save_bytes(open(found, "rb").read(), out_raw)
    os.replace(req, os.path.join(REQ_DIR, f"{name}.done.txt"))
    if found != target and os.path.exists(found):
        os.remove(found)
    return {"path": path, "native_alpha": transparent, "request_id": None, "model": model or "manual"}


def plugin_dir(cfg):
    return gcfg(cfg, "plugin_dir", PLUGIN_DIR)


def load_plugin(name, cfg):
    path = os.path.join(plugin_dir(cfg), f"{name}.py")
    if not os.path.exists(path):
        raise GenError(f'unknown provider "{name}": no built-in and no plugin at {path}. Built-ins: codex, command, '
                       f"manual. To add an API: research it (references/generators.md), then\n"
                       f"  mkdir -p {plugin_dir(cfg)} && cp {TEMPLATE_PATH} {path}\nand fill it in.")
    if SKILL_SCRIPTS not in sys.path:
        sys.path.insert(0, SKILL_SCRIPTS)
    spec = importlib.util.spec_from_file_location(f"ref2game_provider_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        raise GenError(f"plugin {path} failed to import: {type(e).__name__}: {e}")
    caps = getattr(mod, "CAPS", None)
    if not isinstance(caps, dict) or not callable(getattr(mod, "generate", None)):
        raise GenError(f"plugin {path} must define CAPS (dict) and generate(...) - see {TEMPLATE_PATH}")
    caps = {"native_alpha": False, "max_refs": 0, "sizes": "any", "edit": False, "env": [], **caps}
    return Provider(name, "plugin", caps, mod.generate, getattr(mod, "check", None), path)


def get_provider(name, cfg):
    if name == "codex":
        return Provider("codex", "built-in", dict(CODEX_CAPS), codex_generate, _codex_check)
    if name == "command":
        return make_command_provider(cfg)
    if name == "manual":
        return Provider("manual", "built-in", dict(MANUAL_CAPS), manual_generate, lambda: (True, "always available"))
    return load_plugin(name, cfg)


# ----------------------------------------------------------------------------------------------
# jobs
# ----------------------------------------------------------------------------------------------
def _style_refs(cfg, strict=True):
    """Configured style refs (unset: ./ref.png if present). strict: a missing one is an error, not a silent skip."""
    sr = cfg.get("style_ref")
    if sr is None:
        sr = ["ref.png"] if os.path.exists("ref.png") else []
    if isinstance(sr, str):
        sr = [sr]
    missing = [p for p in sr if not os.path.exists(p)]
    if missing and strict:
        raise GenError(f"no style reference ({', '.join(missing)} missing): copy the reference to ./ref.png "
                       f"or pass --no-style-ref")
    return [p for p in sr if os.path.exists(p)]


def _bible_check(cfg):
    """Refuse real generation while the style bible is still setup.sh's placeholder."""
    sb = cfg.get("style_bible", "art/style_bible.txt")
    if sb and os.path.exists(sb) and BIBLE_PLACEHOLDER in open(sb, encoding="utf-8").read().lower():
        raise GenError(f"{sb} is still the setup placeholder (\"{BIBLE_PLACEHOLDER}\"): write the real style bible "
                       f"from the study first (--dry-run works meanwhile)")


def _fullframe(name, cfg):
    """Opaque images (generator "opaque" patterns, default bg_sky*, *_tex): alpha auto -> none.
    Bands with a see-through top (bg_far, bg_mid…) stay transparent."""
    pats = (cfg.get("generator") or {}).get("opaque", ["bg_sky*", "*_tex"])
    return any(fnmatch.fnmatch(os.path.basename(name), p) for p in pats)


def _parse_ref(r):
    if isinstance(r, dict):
        return r["path"], r.get("label")
    r = str(r)
    if "=" in r and not os.path.exists(r):
        p, label = r.split("=", 1)
        return p, label.strip() or None
    return r, None


def _read_prompt(src, strict):
    if os.path.isfile(src):
        return open(src, encoding="utf-8").read(), src
    if strict and re.fullmatch(r"[\w./-]+\.(txt|md|prompt)", src):
        raise GenError(f"prompt file not found: {src}")
    return src, "inline"


def make_job(spec, cfg, base=None, strict=False):
    """spec: dict with name, prompt, ref, size, alpha, key, provider, model, quality, seed, out_dir, fit, pixel."""
    base = base or {}
    g = lambda k, d=None: spec.get(k) if spec.get(k) is not None else (base.get(k) if base.get(k) is not None else gcfg(cfg, k, d))
    name = str(spec["name"]).strip()
    if not name or ".." in name.split("/") or name.startswith("/"):
        raise GenError(f"bad job name {name!r}")
    provider = g("provider") or ("codex" if shutil.which("codex") else "manual")
    refs = spec.get("ref") or []
    if isinstance(refs, (str, dict)):
        refs = [refs]
    text, src = _read_prompt(str(spec["prompt"]), strict)
    out_dir = g("out_dir", "art/gen")
    alpha = g("alpha", "auto")
    key = spec.get("key") or base.get("key") or ("ffffff" if alpha == "lum" else gcfg(cfg, "key", "ff00ff"))   # lum: paper
    return {
        "name": name, "asset": text, "prompt_source": src, "provider": provider, "model": g("model"),
        "quality": g("quality"), "seed": g("seed"), "size": parse_size(g("size", "1024x1024")),
        "alpha": alpha, "key": parse_hex(key), "fit": g("fit", "auto"),
        "pixel": bool(g("pixel", False)), "out_dir": out_dir, "no_wait": bool(g("no_wait", False)),
        "no_style_ref": bool(g("no_style_ref", False)),
        "extra_refs": [_parse_ref(r) for r in refs], "out": os.path.join(out_dir, name + ".png"),
    }


def build_prompt(asset, style_text, images, plan, key_hex, size, caps):
    parts = []
    if images and caps.get("labels", True):
        parts.append("\n".join(["REFERENCE IMAGES (attached in this order):"] +
                               [f"Image {i} = {label}" for i, (_, label) in enumerate(images, 1)]))
    if style_text and caps.get("style_bible", True):
        parts.append(style_text.strip())
    parts.append("ASSET:\n" + asset.strip())
    if caps.get("size_in_prompt"):
        w, h = size
        g = math.gcd(w, h)
        orient = "landscape" if w > h else "portrait" if h > w else "square"
        parts.append(f"Canvas: {w}x{h} px ({w // g}:{h // g} {orient}); if that exact size is unavailable, "
                     f"use the closest size with the same aspect ratio.")
    if plan == "native":
        parts.append(NATIVE_LINE)
    elif plan == "key":
        parts.append(KEY_LINE.format(hex=key_hex.upper()))
    elif plan == "lum":
        parts.append(LUM_LINE.format(hex=key_hex.upper()))
    return "\n\n".join(parts)


def _backup(path, name):
    if os.path.exists(path):
        os.makedirs(OLD_DIR, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, os.path.join(OLD_DIR, f"{name.replace('/', '_')}-{stamp}.png"))


def finalize(job, raw_path, plan, key_prompt_used, pixel):
    """Raw provider output -> validated / keyed / fitted final PNG. Returns (image, alpha_record, warnings)."""
    im = Image.open(raw_path)
    im.load()
    warns, rec = [], {"requested": job["alpha"], "plan": plan}
    key = job["key"]
    transparent_out = plan in ("native", "key", "lum")
    if plan == "none":
        out = im.convert("RGBA") if ("A" in im.getbands() or "transparency" in im.info) else im.convert("RGB")
        rec["method"] = "none"
    elif plan == "lum":
        arr, kinfo = lum_key(np.asarray(im.convert("RGB")), key, pixel=pixel)
        out = Image.fromarray(arr)
        rec["method"], rec["key"] = "lum", kinfo
        if kinfo.get("warning"):
            warns.append(kinfo["warning"])
    else:
        ok, kind, vinfo = validate_alpha(im, allow_hard=pixel)
        rec["validation"] = {"ok": ok, "kind": kind, **vinfo}
        if ok:
            out = Image.fromarray(clean_native(np.asarray(im.convert("RGBA")), pixel))
            rec["method"] = "native" if plan == "native" else "native-unrequested"
        elif kind in ("opaque",):
            rgb = np.asarray(im.convert("RGB"))
            flat = flat_border_color(rgb, near_key=key)
            if plan == "key" or key_prompt_used or flat is not None:
                use = key if plan == "key" or flat is None else tuple(int(round(x)) for x in flat)
                arr, kinfo = chroma_key(rgb, use, pixel=pixel)
                out = Image.fromarray(arr)
                rec["method"] = "key" if plan == "key" else "key-fallback"
                rec["key"] = kinfo
                if kinfo.get("warning"):
                    warns.append(kinfo["warning"])
                if plan == "native":
                    warns.append(f"native alpha missing (opaque output); keyed the flat border colour {kinfo['key_used']}")
            else:
                out = im.convert("RGB")
                rec["method"] = "native-invalid"
                warns.append("asked for transparency but got an opaque image with no flat key border; kept as is. "
                             "Re-run with --alpha key, or remove the background with a bg-removal model")
        else:
            out = im.convert("RGBA")
            rec["method"] = f"native-invalid:{kind}"
            msg = {"checkerboard": "the image has a BAKED checkerboard instead of real alpha; re-run with --alpha key",
                   "empty": "the image is (almost) fully transparent",
                   "hard-edges": "alpha has hard binary edges (no anti-aliasing): looks like a thresholded cut-out; "
                                 "OK for pixel art (use --pixel), otherwise re-run with --alpha key"}[kind]
            warns.append(msg)
            if kind == "hard-edges":
                out = Image.fromarray(clean_native(np.asarray(im.convert("RGBA")), pixel))
    fitted, how = fit_image(out, job["size"], job["fit"], transparent_out, pixel)
    rec["fit"] = how
    return fitted, rec, warns


def run_job(job, cfg, dry_run=False):
    name = job["name"]
    t0 = time.time()
    rec = {"name": name, "provider": job["provider"], "status": "error", "started": _dt.datetime.now().isoformat(timespec="seconds")}
    try:
        prov = get_provider(job["provider"], cfg)
        caps = prov.caps
        model = job["model"] or caps.get("default_model")
        pixel = job["pixel"] or bool(caps.get("pixel"))
        images = [] if job["no_style_ref"] else [(p, STYLE_LABEL) for p in _style_refs(cfg)]
        for p, label in job["extra_refs"]:
            if not os.path.exists(p):
                raise GenError(f"--ref image not found: {p}")
            images.append((p, label or EXTRA_LABEL))
        maxr = int(caps.get("max_refs", 0))
        if len(images) > maxr:
            dropped = [p for p, _ in images[maxr:]]
            say(f"warning: provider {prov.name} takes {maxr} reference image(s); dropped {dropped}", name=name, err=True)
            images = images[:maxr]
        alpha = job["alpha"]
        if alpha not in ("auto", "native", "key", "lum", "none"):
            raise GenError(f"bad --alpha {alpha!r}")
        native_ok = bool(caps.get("native_alpha"))
        plan = {"auto": "native" if native_ok else "key", "native": "native", "key": "key", "lum": "lum", "none": "none"}[alpha]
        if alpha == "auto" and _fullframe(name, cfg):
            plan = "none"                                    # backgrounds / tiles are opaque: no transparency text
        if plan == "native" and not native_ok:
            say(f"warning: {prov.name} has no native alpha; using key colour", name=name, err=True)
            plan = "key"
        key_hex = "%02x%02x%02x" % job["key"]
        size_sent = nearest_size(job["size"], caps.get("sizes", "any"))
        style_path = cfg.get("style_bible", "art/style_bible.txt")
        style_text = open(style_path, encoding="utf-8").read() if style_path and os.path.exists(style_path) else ""
        prompt = build_prompt(job["asset"], style_text, images, plan, key_hex, size_sent, caps)
        maxp = caps.get("max_prompt")
        if maxp and len(prompt) > maxp and style_text:
            cut = len(prompt) - maxp + 20
            short = style_text[: max(0, len(style_text) - cut)].rsplit("\n", 1)[0]
            say(f"warning: prompt {len(prompt)} > {maxp} chars; style bible truncated", name=name, err=True)
            prompt = build_prompt(job["asset"], short, images, plan, key_hex, size_sent, caps)
        if maxp and len(prompt) > maxp:
            raise GenError(f"prompt is {len(prompt)} chars; {prov.name} accepts {maxp}. Shorten the ASSET text.")
        opts = dict((gcfg(cfg, "opts", {}) or {}).get(prov.name, {}))
        opts.update({"quality": job["quality"], "seed": job["seed"], "_name": name, "_out": job["out"],
                     "_log": os.path.join(LOG_DIR, name + ".json"), "_size_requested": job["size"],
                     "_key_hex": key_hex, "_no_wait": job["no_wait"]})
        out_raw = os.path.join(RAW_DIR, name + ".png")
        rec.update({"model": model, "size_requested": "%dx%d" % job["size"], "size_sent": "%dx%d" % size_sent,
                    "quality": job["quality"], "seed": job["seed"], "prompt_source": job["prompt_source"],
                    "refs": [{"path": p, "label": l} for p, l in images], "prompt": prompt})
        if dry_run:
            say(f"=== DRY RUN {name}: provider={prov.name} ({prov.kind}) model={model} "
                f"size {rec['size_requested']} -> sent {rec['size_sent']} alpha {alpha} -> {plan}"
                f"{' key #' + key_hex.upper() if plan == 'key' else ' paper #' + key_hex.upper() if plan == 'lum' else ''}"
                f"{' (opaque name)' if alpha == 'auto' and plan == 'none' else ''} pixel={pixel}")
            say("  refs: " + (", ".join(f"Image {i}={p}" for i, (p, _) in enumerate(images, 1)) or "none"))
            say("  prompt:\n    " + prompt.replace("\n", "\n    "))
            ok, why = prov.ready()
            if not ok:
                say(f"  [dry-run] note: provider not ready here ({why})")
        if not dry_run and prov.name != "manual":
            _backup(job["out"], name)
        res = prov.generate(prompt, [p for p, _ in images], tuple(size_sent), plan == "native", job["model"], out_raw,
                            opts, dry_run) or {}
        if dry_run or res.get("dry_run"):
            return {"name": name, "status": "dry-run", "provider": prov.name}
        if res.get("pending"):
            return {"name": name, "status": "pending", "provider": prov.name}
        raw = res.get("path")
        if not raw or not os.path.exists(raw):
            raise GenError(f"provider {prov.name} returned no file ({res})")
        if _sniff_ext(open(raw, "rb").read(512)) == ".svg":
            png = os.path.splitext(raw)[0] + ".svg.png"
            conv = shutil.which("rsvg-convert")
            if not conv:
                raise GenError(f"provider returned SVG ({raw}); install rsvg-convert or use a raster model")
            subprocess.run([conv, "-w", str(job["size"][0]), "-o", png, raw], check=True)
            raw = png
        key_prompt_used = plan == "key"
        final, arec, warns = finalize(job, raw, plan, key_prompt_used, pixel)
        os.makedirs(os.path.dirname(job["out"]) or ".", exist_ok=True)
        final.save(job["out"], "PNG")
        rec.update({"status": "ok" if not warns else "warn", "raw": raw, "out": job["out"], "model": res.get("model") or model,
                    "request_id": res.get("request_id"), "native_alpha_returned": res.get("native_alpha"),
                    "size_raw": "%dx%d" % Image.open(raw).size, "size_final": "%dx%d" % final.size,
                    "alpha": arec, "warnings": warns})
        for w_ in warns:
            say("warning: " + w_, name=name, err=True)
    except DryRun:
        return {"name": name, "status": "dry-run", "provider": job["provider"]}
    except Exception as e:  # one bad job must never kill a batch
        rec["error"] = str(e) if isinstance(e, (GenError, OSError, subprocess.SubprocessError)) \
            else f"{type(e).__name__}: {e} (bug? see traceback with python3 -X dev)"
        if dry_run:
            say(f"ERROR: {e}", name=name, err=True)
            return {"name": name, "status": "error", "provider": job["provider"], "error": str(e)}
    rec["seconds"] = round(time.time() - t0, 1)
    if not dry_run:
        logp = os.path.join(LOG_DIR, name + ".json")
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        with open(logp, "w") as f:
            json.dump(rec, f, indent=2)
    if rec["status"] == "error":
        say(f"ERROR: {rec.get('error')}", name=name, err=True)
    else:
        say(f"{rec['status']}: {rec['out']} ({rec['alpha'].get('method')}, {rec['size_final']}, {rec['seconds']}s)", name=name)
    return rec


# ----------------------------------------------------------------------------------------------
# pixel snapping
# ----------------------------------------------------------------------------------------------
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
# ----------------------------------------------------------------------------------------------
def cmd_check(cfg):
    rows = []
    names = ["codex", "command", "manual"]
    pdir = plugin_dir(cfg)
    names += sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(pdir, "*.py"))
                    if not os.path.basename(p).startswith("_"))
    for n in names:
        try:
            p = get_provider(n, cfg)
            ok, why = p.ready()
            c = p.caps
            rows.append((n, p.kind, "yes" if ok else "no", why, "yes" if c.get("native_alpha") else "key",
                         str(c.get("max_refs")), str(c.get("sizes") if c.get("sizes") == "any" else f"{len(c['sizes'])} sizes"),
                         ",".join(c.get("env") or []) or "-"))
        except GenError as e:
            rows.append((n, "plugin", "no", str(e).splitlines()[0][:60], "?", "?", "?", "?"))
    hdr = ("provider", "kind", "ready", "detail", "alpha", "refs", "sizes", "env")
    wd = [max(len(str(r[i])) for r in rows + [hdr]) for i in range(len(hdr))]
    wd[3] = min(wd[3], 48)
    for r in [hdr] + rows:
        say("  ".join(str(v)[:wd[i]].ljust(wd[i]) for i, v in enumerate(r)))
    conf = gcfg(cfg, "provider")
    say("")
    say(f"configured provider: {conf or '(none; default codex if on PATH, else manual)'}"
        f"   config: {'./' + CONFIG_FILE if os.path.exists(CONFIG_FILE) else 'missing (defaults)'}"
        f"   plugins dir: {pdir}")
    sb = cfg.get("style_bible", "art/style_bible.txt")
    bib = "missing" if not (sb and os.path.exists(sb)) else ("PLACEHOLDER (write it after the study)"
                                                             if BIBLE_PLACEHOLDER in open(sb, encoding="utf-8").read().lower() else "found")
    sr = cfg.get("style_ref")
    miss = [p for p in ([sr] if isinstance(sr, str) else sr or []) if not os.path.exists(p)]
    say(f"style bible: {sb} ({bib})   style refs: {_style_refs(cfg, strict=False) or 'none'}"
        f"{'   MISSING: ' + ', '.join(miss) + ' (setup.sh --ref, or copy the reference there)' if miss else ''}")
    say(f"new API? research it (references/generators.md), then: cp {TEMPLATE_PATH} {pdir}/<name>.py")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gen.py", description="ref2game: one image per job, any provider.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--provider")
        p.add_argument("--model")
        p.add_argument("--quality")
        p.add_argument("--no-wait", action="store_true", help="manual provider: don't wait for the file")
        p.add_argument("--no-style-ref", action="store_true", help="attach no style reference (deliberately)")
        p.add_argument("--dry-run", action="store_true")

    p1 = sub.add_parser("one", help="generate one image")
    p1.add_argument("name")
    p1.add_argument("prompt_file")
    p1.add_argument("--ref", action="append", default=[], help="extra reference image (IMG or IMG=label)")
    p1.add_argument("--size")
    p1.add_argument("--alpha", choices=["auto", "native", "key", "lum", "none"])
    p1.add_argument("--key", help="key colour RRGGBB (default ff00ff; --alpha lum: paper colour, default ffffff)")
    p1.add_argument("--seed", type=int)
    p1.add_argument("--out-dir")
    p1.add_argument("--fit", choices=["auto", "cover", "contain", "stretch", "none"])
    p1.add_argument("--pixel", action="store_true", help="pixel art: nearest scaling, hard alpha")
    common(p1)

    p2 = sub.add_parser("batch", help="run a JOBS.json list in parallel")
    p2.add_argument("jobs_file")
    p2.add_argument("--jobs", type=int)
    p2.add_argument("--skip-existing", action="store_true")
    common(p2)

    sub.add_parser("check", help="list providers usable here")

    p4 = sub.add_parser("key", help="chroma-key an existing image offline")
    p4.add_argument("inp")
    p4.add_argument("out")
    p4.add_argument("--key", help="key colour (default ff00ff; --lum: paper colour, default ffffff)")
    p4.add_argument("--lum", action="store_true", help="luminance key against paper (watercolour, ink, silhouettes)")
    p4.add_argument("--pixel", action="store_true")
    p4.add_argument("--choke", type=int, default=1)
    p4.add_argument("--speck", type=int, default=16)

    p5 = sub.add_parser("validate", help="validate native alpha of an image")
    p5.add_argument("img")

    p6 = sub.add_parser("pixel", help="snap pixel-looking art to its grid")
    p6.add_argument("inp")
    p6.add_argument("out")
    p6.add_argument("--grid", default="auto")
    p6.add_argument("--colors", type=int, default=16)
    p6.add_argument("--scale", type=int, default=1)

    a = ap.parse_args(argv)
    try:
        cfg = load_config()
        if a.cmd == "check":
            return cmd_check(cfg)
        if a.cmd == "key":
            rgb = np.asarray(Image.open(a.inp).convert("RGB"))
            arr, info = (lum_key(rgb, parse_hex(a.key or "ffffff"), a.pixel, a.speck) if a.lum
                         else chroma_key(rgb, parse_hex(a.key or "ff00ff"), a.pixel, a.choke, a.speck))
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            Image.fromarray(arr).save(a.out)
            say(json.dumps(info))
            return 0
        if a.cmd == "validate":
            ok, kind, info = validate_alpha(Image.open(a.img))
            say(json.dumps({"ok": ok, "kind": kind, **info}))
            return 0 if ok else 1
        if a.cmd == "pixel":
            im, k = pixel_snap(Image.open(a.inp), a.grid, a.colors, a.scale)
            im.save(a.out)
            say(f"grid {k}px -> {im.size[0]}x{im.size[1]} ({a.colors} colours max) -> {a.out}")
            return 0
        base = {k: getattr(a, k, None) for k in ("provider", "model", "quality")}
        base.update({"no_wait": a.no_wait or None, "no_style_ref": a.no_style_ref or None})
        if not a.dry_run:
            _bible_check(cfg)                                    # before any job reaches a provider
        if a.cmd == "one":
            base.update({"size": a.size, "alpha": a.alpha, "key": a.key, "seed": a.seed, "out_dir": a.out_dir,
                         "fit": a.fit, "pixel": a.pixel or None})
            job = make_job({"name": a.name, "prompt": a.prompt_file, "ref": a.ref}, cfg, base, strict=True)
            r = run_job(job, cfg, a.dry_run)
            return 0 if r.get("status") in ("ok", "warn", "dry-run", "pending") else 1
        with open(a.jobs_file) as f:
            specs = json.load(f)
        if isinstance(specs, dict):
            specs = specs.get("jobs", [])
        jobs, bad = [], 0
        for s in specs:
            try:
                j = make_job(s, cfg, base)
                if a.skip_existing and os.path.exists(j["out"]):
                    say("skip (exists)", name=j["name"])
                    continue
                jobs.append(j)
            except (GenError, KeyError) as e:
                say(f"bad job {s.get('name', '?') if isinstance(s, dict) else s}: {e}", err=True)
                bad += 1
        n = max(1, min(int(a.jobs or gcfg(cfg, "jobs", 4)), len(jobs) or 1))
        say(f"batch: {len(jobs)} job(s), {n} in parallel{' (dry-run)' if a.dry_run else ''}")
        results = []
        with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
            futs = {ex.submit(run_job, j, cfg, a.dry_run): j for j in jobs}
            for fu in as_completed(futs):
                results.append(fu.result())
        say("\nsummary:")
        for r in sorted(results, key=lambda r: r["name"]):
            say(f"  {r['name']:<28} {r.get('status'):<8} {r.get('provider', ''):<10} "
                f"{(r.get('alpha') or {}).get('method', '') if isinstance(r.get('alpha'), dict) else ''} "
                f"{r.get('seconds', '')} {r.get('error', '')[:80] if r.get('error') else ''}")
        failed = bad + sum(1 for r in results if r.get("status") == "error")
        return 1 if failed else 0
    except GenError as e:
        say(f"ERROR: {e}", err=True)
        return 2
    except KeyboardInterrupt:
        say("interrupted", err=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
