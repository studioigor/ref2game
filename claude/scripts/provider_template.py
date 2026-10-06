"""
<NAME> -- image provider plugin for ref2game gen.py.

Copy to <project>/art/providers/<name>.py, fill it in, and set
"generator": {"provider": "<name>"} in <project>/ref2game.json.

HOW TO FILL THIS IN
  1. Research the API on its OFFICIAL docs (checklist: references/generators.md, section b). Write the
     findings, with URLs, to study/GENERATOR.md. Never guess an endpoint, a field name or a value.
     Mark anything you could not verify as UNVERIFIED in a comment, and keep it overridable through
     opts["params"] so a fix needs no code change.
  2. Fill in API_BASE, ENV and CAPS from the findings.
  3. Pick ONE request pattern below and delete the other two. Replace every <PLACEHOLDER>:
       A  sync JSON         POST JSON -> image in the response (base64 or URL)
       B  multipart upload  POST multipart/form-data with the reference files
       C  async job + poll  POST creates a job -> poll its status -> download the output
  4. Dry-run (prints the exact request, sends nothing, masks keys):
       python3 <skill>/scripts/gen.py one probe art/prompts/probe.txt --provider <name> --dry-run
  5. Make ONE cheap real call only after the user has approved spending.

CONTRACT (gen.py does everything else: prompt assembly, ref labels, size mapping, alpha validation,
chroma key, resize/pad, logs)
  CAPS = {"native_alpha": bool, "max_refs": int, "sizes": "any" | [...], "edit": bool, "env": [...]}
         optional: "default_model", "pixel", "labels", "style_bible", "max_prompt", "size_in_prompt"
  generate(prompt, refs, size, transparent, model, out_raw, opts, dry_run) -> dict
    prompt       the final text: ref labels + style bible + ASSET + background line. Send it verbatim.
    refs         image paths in label order (Image 1 = style ref, ...); already cut to CAPS["max_refs"].
    size         (w, h), already mapped to the nearest entry of CAPS["sizes"].
    transparent  True -> ask the API for real alpha (only if CAPS["native_alpha"]).
    model        --model / generator.model, or None -> use CAPS["default_model"].
    out_raw      suggested raw path (art/raw/<name>.png). save_bytes/save_b64/download fix the extension.
    opts         generator.opts.<name> from ref2game.json, plus quality, seed, _name, _out, _log,
                 _size_requested, _key_hex.
    dry_run      print the request with the helpers (they never send in dry-run) and return
                 {"dry_run": True}.
    returns      {"path": raw_file, "native_alpha": bool, "request_id": str|None, "model": str}
  check() -> (ok, why)   optional extra readiness test for `gen.py check`. Free calls only.
"""
from gen import (GenError, b64_file, data_uri, download, dry_note, env_key, http_json,
                 http_multipart, http_request, poll, save_b64, save_bytes, say)
_UNUSED_OK = (b64_file, http_request)   # also available: raw base64 refs, raw HTTP calls

API_BASE = "<official-base-url>"         # <PLACEHOLDER> official base URL            [source: <url>]
ENV = ["EXAMPLE_API_KEY"]                 # <PLACEHOLDER> env var(s); "A|B" means either  [source: <url>]

CAPS = {
    "native_alpha": False,      # True only if the docs show a real-transparency option   [source]
    "max_refs": 4,              # reference images accepted per call (0 = text only)      [source]
    "sizes": ["1024x1024", "1536x1024", "1024x1536"],   # or "any", or aspects ["16:9","1:1"] [source]
    "edit": True,               # refs condition / edit the output
    "env": ENV,
    "default_model": "<model-id>",                      # [source]
    # "pixel": False,           # true low-res pixel output (nearest scaling, hard alpha ok)
    # "labels": True,           # refs are in-context images, so keep the "Image N = ..." lines
    # "style_bible": True,      # include the style bible text (turn off for short-prompt APIs)
    # "max_prompt": 4000,       # documented prompt limit; gen.py trims the style bible to fit
}
PATTERN = "sync_json"           # "sync_json" | "multipart" | "async_job"   (opts["pattern"] overrides)


def _auth(dry_run):
    # <PLACEHOLDER> the documented auth header, e.g. "Authorization: Bearer <key>" or "x-api-key: <key>"
    return {"Authorization": "Bearer " + env_key(*ENV, dry_run=dry_run)}


def _common(body, prompt, size, transparent, model, opts):
    """Fields most image APIs share. Rename or remove them to match the docs."""
    body.update({
        "model": model,                                  # <PLACEHOLDER>
        "prompt": prompt,                                # <PLACEHOLDER>
        "size": f"{size[0]}x{size[1]}",                  # <PLACEHOLDER> or width/height, or aspect_ratio
        "n": 1,
    })
    if transparent:
        body["background"] = "transparent"               # <PLACEHOLDER> only if documented
    if opts.get("seed") is not None:
        body["seed"] = opts["seed"]                      # <PLACEHOLDER> only if documented
    if opts.get("quality"):
        body["quality"] = opts["quality"]                # <PLACEHOLDER> map to documented values
    body.update(opts.get("params") or {})                # extra or unverified fields from ref2game.json
    return body


def _save_output(item, out_raw, headers=None):
    """Write the first output image. Handles base64, data: URIs and URLs."""
    if isinstance(item, str):
        return download(item, out_raw, headers) if item.startswith(("http", "data:")) else save_b64(item, out_raw)
    for k in ("b64_json", "base64", "image_base64", "b64"):        # <PLACEHOLDER> the documented key
        if item.get(k):
            return save_b64(item[k], out_raw)
    for k in ("url", "image_url", "uri"):
        if item.get(k):
            return download(item[k], out_raw, headers)
    raise GenError(f"no image in response item: {str(item)[:300]}")


def generate(prompt, refs, size, transparent, model, out_raw, opts, dry_run):
    model = model or CAPS["default_model"]
    fn = {"sync_json": _sync_json, "multipart": _multipart, "async_job": _async_job}[opts.get("pattern", PATTERN)]
    return fn(prompt, refs, size, transparent, model, out_raw, opts, dry_run)


# ---- A. sync JSON ----------------------------------------------------------------------------
def _sync_json(prompt, refs, size, transparent, model, out_raw, opts, dry_run):
    body = _common({}, prompt, size, transparent, model, opts)
    if refs:
        # <PLACEHOLDER> how the docs pass refs: a list of data URIs, raw base64, or URLs (see _ref_url).
        # Check the documented inline-size limit; downscale big refs with max_edge.
        body["images"] = [data_uri(r, max_edge=2048) for r in refs]
    r = http_json("POST", f"{API_BASE}/images/generations", body, _auth(dry_run),   # <PLACEHOLDER> path
                  timeout=float(opts.get("timeout", 300)), dry_run=dry_run)
    if dry_run:
        return {"dry_run": True}
    data = r.json
    item = (data.get("data") or data.get("images") or [None])[0]                   # <PLACEHOLDER> path
    if item is None:
        raise GenError(f"no image in response: {str(data)[:400]}")
    return {"path": _save_output(item, out_raw), "native_alpha": transparent and CAPS["native_alpha"],
            "request_id": r.header("x-request-id") or data.get("id"), "model": model}


# ---- B. multipart upload ---------------------------------------------------------------------
def _multipart(prompt, refs, size, transparent, model, out_raw, opts, dry_run):
    fields = _common({}, prompt, size, transparent, model, opts)
    # <PLACEHOLDER> the documented file field name. Some APIs repeat "image[]"; some use image, image_2, ...
    files = [("image[]", r) for r in refs]
    url = f"{API_BASE}/images/edits" if refs else f"{API_BASE}/images/generations"   # <PLACEHOLDER>
    r = http_multipart(url, fields, files, _auth(dry_run), timeout=float(opts.get("timeout", 300)), dry_run=dry_run)
    if dry_run:
        return {"dry_run": True}
    if (r.header("content-type") or "").startswith("image/"):      # APIs that answer with raw image bytes
        return {"path": save_bytes(r.body, out_raw), "native_alpha": transparent and CAPS["native_alpha"],
                "request_id": r.header("x-request-id"), "model": model}
    data = r.json
    item = (data.get("data") or data.get("images") or [None])[0]                   # <PLACEHOLDER>
    if item is None:
        raise GenError(f"no image in response: {str(data)[:400]}")
    return {"path": _save_output(item, out_raw), "native_alpha": transparent and CAPS["native_alpha"],
            "request_id": r.header("x-request-id") or data.get("id"), "model": model}


# ---- C. async job + poll ---------------------------------------------------------------------
def _ref_url(path, dry_run):
    """For APIs that want URLs, not inline bytes: upload to the provider's file store first.
    (Or use data_uri(path) when the docs allow it and the file is under their inline limit.)"""
    if dry_run:
        return f"<url of uploaded {path}>"
    r = http_multipart(f"{API_BASE}/files", None, [("file", path)], _auth(False))   # <PLACEHOLDER>
    return r.json["url"]                                                            # <PLACEHOLDER>


def _async_job(prompt, refs, size, transparent, model, out_raw, opts, dry_run):
    body = _common({}, prompt, size, transparent, model, opts)
    if refs:
        if dry_run:
            dry_note(f"uploads {len(refs)} ref(s) first: POST {API_BASE}/files (multipart 'file')")
        body["image_urls"] = [_ref_url(r, dry_run) for r in refs]                 # <PLACEHOLDER>
    r = http_json("POST", f"{API_BASE}/jobs", body, _auth(dry_run), dry_run=dry_run)   # <PLACEHOLDER>
    if dry_run:
        dry_note(f"then polls GET {API_BASE}/jobs/<id> every 2-15 s until done, then downloads the output")
        return {"dry_run": True}
    job = r.json
    job_id = job.get("id") or job.get("request_id") or job.get("task_id")         # <PLACEHOLDER>
    status_url = job.get("status_url") or f"{API_BASE}/jobs/{job_id}"             # prefer URLs the API returns
    say(f"job {job_id} submitted", name=opts.get("_name"))

    def check():
        s = http_json("GET", status_url, None, _auth(False)).json
        st = str(s.get("status", "")).lower()                                     # <PLACEHOLDER> status values
        if st in ("succeeded", "completed", "complete", "done", "success"):
            return s
        if st in ("failed", "error", "canceled", "cancelled", "aborted"):
            raise GenError(f"job {job_id} {st}: {str(s.get('error') or s)[:400]}")
        return None

    s = poll(check, timeout=float(opts.get("timeout", 900)), label=f"job {job_id}")
    if s.get("response_url"):                         # some queues return the result on a separate URL
        s = http_json("GET", s["response_url"], None, _auth(False)).json
    out = s.get("output") or s.get("images") or s.get("result")                  # <PLACEHOLDER>
    item = out[0] if isinstance(out, list) else out
    if item is None:
        raise GenError(f"job {job_id}: no output in {str(s)[:400]}")
    return {"path": _save_output(item, out_raw), "native_alpha": transparent and CAPS["native_alpha"],
            "request_id": job_id, "model": model}


# ---- optional readiness test (free endpoints only, e.g. account/balance) ---------------------
# def check():
#     try:
#         http_json("GET", f"{API_BASE}/me", None, _auth(False), retries=0, timeout=15)
#         return True, "key accepted"
#     except GenError as e:
#         return False, str(e)[:80]
