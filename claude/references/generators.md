# Image generators: choose, research, plug in, probe

All art goes through `scripts/gen.py`, one image per job. gen.py handles everything that is the same
for every generator:
- prompt assembly: ref labels, style bible, background line;
- size mapping and local resize/pad;
- alpha validation and chroma key;
- retries with backoff;
- logs and the raw copy.

A generator is either a **built-in** (`codex`, `command`, `manual`) or a **plugin**
(`art/providers/<name>.py` in the project), which you write after researching the API the user names.
Never hard-code facts about an API from memory. Model ids, sizes and flags change every few months.

```
python3 <skill>/scripts/gen.py check                               # what is usable here
python3 <skill>/scripts/gen.py one NAME art/prompts/NAME.txt [--ref IMG[=label]] [--size WxH] \
        [--alpha auto|native|key|none] [--key 00ff00] [--seed N] [--pixel] [--dry-run]
python3 <skill>/scripts/gen.py batch jobs.json --jobs 4 [--skip-existing] [--dry-run]
python3 <skill>/scripts/gen.py key|validate|pixel ...              # offline tools
```

`ref2game.json` in the project root holds the configuration, for example:
```json
{"generator": {"provider": "codex", "model": null, "size": "1536x1024", "quality": "high",
               "alpha": "auto", "key": "ff00ff", "jobs": 4, "opts": {"<plugin>": {}}},
 "style_bible": "art/style_bible.txt", "style_ref": ["ref.png"]}
```

Outputs:
- `art/gen/NAME.png`: the final image;
- `art/raw/NAME.*`: the untouched provider output;
- `art/logs/NAME.json`: prompt, refs, sizes, seconds, request id, alpha method and warnings;
- `art/old/`: earlier finals, kept before each overwrite.

## (a) The start-of-project question

Run `gen.py check` first. It prints one row per provider: ready (CLI on PATH and logged in, env key
set, template configured), alpha support, max refs and sizes. It also shows the style bible and
style refs it found. Then ask the user, recommending the first option that is ready. The pros and cons below are what to weigh; re-check them against the current state of each option:

| Option | Pros | Cons |
|---|---|---|
| **Codex built-in** (`codex`) | The built-in default when `codex` is on PATH. No API key, uses the user's Codex plan. Accepts reference images, can return real alpha, any aspect ratio | Slow per image. Counts against Codex usage limits. No seed and no exact size control. The prompt is read by an agent, not sent raw |
| **An API the user names** (plugin) | Exact parameters (size, seed, quality, native alpha, edits/masks), fast and parallel, scriptable | Costs money per image. Needs research and a plugin first. Content filters and rate limits vary |
| **Local tool** (`command`) | Free and private: e.g. ComfyUI scripts, a local diffusion model, a custom pipeline | Quality depends on the user's setup. Configure the template: `{prompt_file} {out} {refs} {size} {width} {height} {seed} {model} {quality} {transparent} {key} {name}` |
| **Manual** (`manual`) | Works with anything: web UIs, artists, other apps | A human in the loop for every image. gen.py writes `art/requests/NAME.txt` and waits for the drop (`--no-wait` returns at once; re-run later to process) |

Record the choice in `ref2game.json` under `generator.provider`.

## (b) Research checklist for a named API

Use WebSearch and WebFetch on the **official** docs only (API reference, guides, pricing, changelog
or deprecations). Third-party blogs are leads, not sources. Write `study/GENERATOR.md` with one line
per item, each with its URL and **verified** or **unverified**:

1. **Auth.** Header name and scheme, env var name, where the key is issued.
2. **Endpoints.** Base URL, generate vs edit paths, **sync or async** (job id, status URL, status values, result URL), streaming.
3. **Model ids.** The current recommended id, deprecation dates, and the cheap draft model vs the quality model.
4. **Reference images.** How they are passed: multipart field name (repeated?), base64, data URI, URL or an upload step first. Max count, max bytes, accepted formats. Whether the docs say how to refer to "image 1/2".
5. **Sizes.** The allowed list or the rules: multiples, min/max pixels, max ratio, aspect-ratio enums, resolution tiers. What happens to an unsupported size.
6. **Native transparency.** The exact parameter and the models that support it, plus the required output format. If there is none, plan on key colour.
7. **Edit and inpaint.** Mask format (alpha or greyscale, same size?), and whether the first image is the edit target.
8. **Seeds and determinism.** The seed field, and whether it is "best effort".
9. **Output.** Base64 or URL, URL expiry, default format (avoid JPEG for keying), and the request-id header or field.
10. **Rate limits.** Requests/images per minute, concurrent jobs, the 429 body and Retry-After.
11. **Pricing.** Per image or per token at your size and quality, and the cost of a probe and of the full asset list.
12. **Content policy.** Moderation levels or params, and how a block looks: HTTP code, `finish_reason`, a blurred image. Note weapons, violence, blood and "realistic person" rules that matter for game art.

## (c) Capability probe (before production)

**Ask the user once for a budget**: price per image × planned assets, plus a margin for rejects. Work within it; ask again before going over. Run cheap probe jobs
(a low quality setting or the draft model), each with the style ref attached, one per risk:
1. **A style-matched prop** on native alpha, or on a key colour if the API has no native alpha. Check it with `gen.py validate art/gen/probe_prop.png`, then view it over a dark and a light background.
2. **A character part sheet.** Body parts as separate pieces on one canvas with wide gutters. This tests sheet discipline and keying between parts.
3. **A wide background band** at the widest ratio allowed. This tests the size limits and the cover-crop.

Judge and write the verdict into `study/GENERATOR.md`:
- **Alpha quality.** Soft edges, no halo, no checkerboard, nothing missing.
- **Style adherence.** Compare to the ref side by side. An independent critic agent is better than self-review.
- **Consistency.** Re-run the prop with the same refs, and the same seed if the API has one, and compare the two.
- **Edit fidelity.** `--ref art/gen/probe_prop.png="edit target: change only the colour of X, keep everything else identical"`.

From the results, pick:
- the alpha strategy;
- default sizes per asset class;
- sheets vs single assets;
- the draft vs final quality settings.

## (d) Writing the plugin

```
mkdir -p art/providers && cp <skill>/scripts/provider_template.py art/providers/<name>.py
```

1. Fill in `API_BASE`, `ENV` and `CAPS` (`native_alpha`, `max_refs`, `sizes`, `edit`, `env`, plus the optional `default_model`, `pixel`, `max_prompt`, `style_bible`, `labels`) from `study/GENERATOR.md`.
2. Keep ONE request pattern: A sync JSON, B multipart upload, or C async job + poll. Replace every `<PLACEHOLDER>`.
3. Use the helpers imported from gen.py: `http_json`, `http_multipart`, `b64_file`, `data_uri`, `poll`, `download`, `save_b64`, `env_key`, `mask_key`, `dry_note`. They retry 429 and 5xx with backoff and honour Retry-After. They never retry a POST timeout, because that could double-bill.
4. Put unverified or optional fields in `ref2game.json` → `generator.opts.<name>.params`, not in code.

Then:
- `gen.py check` should show the plugin row, and `ready = no (set $VAR)` until the key exists.
- `gen.py one probe art/prompts/probe.txt --provider <name> --dry-run` prints the exact URL, headers with masked keys, and the JSON or multipart fields. Compare them field by field with the docs.
- Only then, with the user's OK, make one real call, then run the probe.

## (e) Prompting and consistency (any model)

- **Label refs by role.** gen.py writes "Image 1 = style reference only: match its art style, rendering, palette and light; do not copy its composition". Give extra refs an explicit role: `--ref img.png="edit target"`, `="same character: keep face, outfit, proportions"`, `="pose only"`.
- **Verbatim style bible on every call** (`art/style_bible.txt`): light direction, palette, line and edge treatment, rendering, detail density, what to avoid. Never paraphrase it per asset. Put the asset specifics in the ASSET text.
- **Golden-set anchor.** Once the user approves the first assets, append them to `style_ref` in `ref2game.json`. Every later call then sees the approved look, not just the original reference.
- **Edit-based variants.** For states, colours, damage or expressions, pass the approved asset as a ref with the line "change only X; keep everything else identical". This holds identity better than a fresh prompt.
- **One asset per call** gives the most resolution and the cleanest alpha. **Kit-mates on one sheet**, with gutters wide enough to slice cleanly on one flat background, share lighting, scale and palette. Slice them afterwards. Sheets suit sets that must match: tile variants, part rigs, icon sets. Weigh the two per set.
- **Seeds** (where they exist): fix one seed per asset family for re-rolls. They help but do not guarantee consistency.
- **Reject budget.** Don't keep re-rolling. When a re-roll or two hasn't fixed it, change the prompt or the approach (an edit from the nearest good asset, a sheet, a different ref), not the dice. Log rejects and their reasons in the job log.
- Ask for **no cast shadow, no floor, no glow, no frame, centred with margin**. Add shadows, glows and outlines in the engine, where they stay consistent and animatable.

## (f) Alpha strategies

1. **Native, then validate** (`--alpha native`, or `auto` when CAPS say native). gen.py rejects:
   - opaque results;
   - baked checkerboards;
   - hard binary edges, which are allowed with `--pixel`.

   An opaque result with a flat, saturated border is keyed automatically. The log records `method: key-fallback`.
2. **Key colour** (`--alpha key --key RRGGBB`). Choose it **per asset, far from the asset's palette**:
   - magenta `ff00ff` is gen.py's default, and suits subjects with little magenta in them;
   - for magenta-heavy subjects (pink, purple, magic, neon) pick a key on the other side of the colour wheel, e.g. green `00ff00` or blue `0000ff`;
   - never key on white or black, or on a colour in the outlines. The exception is paper styles (watercolour, ink, silhouettes): generate on the paper colour and use `--alpha lum --key <paper>`, alpha from luminance against the paper.

   gen.py builds a soft OKLab matte with thresholds set from the border noise, refines edge alpha against the nearby solid colour, and un-mixes `C = (I - (1-a)K)/a`. It then despills (only spill beyond the subject's own colour), contracts the edge by 1px (thin parts are kept), drops specks under 16px², and bleeds colour into clear pixels so filtering never shows dark fringes.
3. **Background-removal model** when keying fails: hair, smoke, glass, or a key colour that bled into the subject.
   - Run a local rembg-style tool on `art/raw/NAME.*`. Check the model's licence: some default weights are non-commercial.
   - Or use the chosen API's own remove-background endpoint, as a second plugin or a `command` step.
   - Re-check with `gen.py validate`.
4. `--alpha none` is for backgrounds and full-frame layers.

## (g) Pixel art

- **True low-res generators**, which output the native grid with hard alpha, avoid grid repair. Set `"pixel": true` in their CAPS or pass `--pixel`. Request the native size and scale in the engine with nearest-neighbour. gen.py scales by integer factors only, keys hard (no matte, no choke) and accepts binary alpha.
- **"Pixel-looking" hi-res output** from general models has an uneven grid and stray colours. Snap it with `gen.py pixel IN OUT --grid auto --colors K` (default 16; set K from the style's palette), which:
  1. detects cell size and phase;
  2. quantises the palette (median cut + k-means);
  3. takes the **mode** colour per cell;
  4. binarises alpha.

  Then fix outlines and jaggies by hand or with a dedicated tool. If the grid is non-integer, regenerate or use a specialist snapper.
- Lock a palette early. Pass the approved palette image as a ref, and quantise every asset to it.

## (h) Gotchas

- **Model ids and parameters churn.** Re-verify the docs at the start of every project and date the notes in `study/GENERATOR.md`.
- **"Transparent background" in a prompt to an RGB-only model** gives a painted checkerboard. Use a key colour instead. gen.py detects the checkerboard and warns.
- **Native alpha may not be fully opaque inside.** Interiors slightly below 255 have been seen. gen.py snaps values of 248 and above to 255 and values of 3 and below to 0.
- **Sizes get mapped.** A requested size is mapped to the nearest allowed one, then resized, padded (transparent assets) or cover-cropped (opaque). Very wide bands lose height to the crop, so generate the band at the widest allowed ratio and tile or extend it in the engine. The log has `size_sent`, `size_raw` and `size_final`.
- **Content filters.** Phrase game violence as stylised and non-graphic ("cartoon toy sword", "no blood", "knocked out, not hurt"). Never auto-retry a moderation block unchanged. Use a documented moderation setting only if the user agrees.
- **Rate limits and concurrency.** Keep `--jobs` at or below the account's concurrent limit. 429s are retried with backoff. A POST that times out is *not* retried, so check the provider dashboard before re-running.
- **Output URLs expire**, often within hours. Plugins should download at once (`download()`).
- **Inline images have size caps.** Downscale refs with `b64_file(path, max_edge=N)` or `data_uri(...)` to the documented limit, or use the API's upload step.
- **JPEG outputs ruin keying.** Request PNG or WebP where the API allows it.
- **SVG outputs** from vector models are rasterised with `rsvg-convert` if it is installed.
- **Codex specifics:**
  - The image lands in `$CODEX_HOME/generated_images/<session>/`. gen.py recovers it from there if the agent did not copy it.
  - The full transcript is in `art/logs/NAME.log`.
  - Batches run in parallel (`--jobs`) within the account's usage limits.
  - `--model` is ignored, because the built-in tool picks its own image model.
- **Subjects touching the canvas edge** confuse key-border detection. Ask for the subject centred with a clear margin.
- **Prompt rewriting.** Some APIs rewrite prompts or have "thinking" models. Log any revised prompt the API returns, and keep must-have constraints short and explicit.
