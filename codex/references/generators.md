# Built-in imagegen: prepare, call, inspect, import

In Codex, all raster generation and creative edits go through the session's built-in `imagegen` tool
(`image_gen__imagegen` / `image_gen.imagegen`, per its current schema). `scripts/gen.py` handles everything
that is the same for every asset, but it cannot call the tool from Python and never generates:
- prompt assembly: the verbatim style bible, role-labelled refs, background line, canvas hint (`prepare`);
- import of the returned file: raw copy, alpha validation, logs, backups (`import`);
- offline alpha and pixel tools (`validate`, `key`, `pixel`).

```
python3 <skill>/scripts/gen.py check                                  # local inputs only, not the tool
python3 <skill>/scripts/gen.py prepare NAME art/prompts/NAME.txt [--ref IMG=role] [--size WxH] \
        [--alpha auto|native|none] [--pixel]
python3 <skill>/scripts/gen.py import NAME /actual/returned/image.png [--replace]
python3 <skill>/scripts/gen.py validate IMG [--pixel]
python3 <skill>/scripts/gen.py key IN OUT [--key RRGGBB] [--lum] [--pixel] [--choke 1] [--speck 16]
python3 <skill>/scripts/gen.py pixel IN OUT [--grid auto|N] [--colors 16] [--scale 1]
```

Outputs:
- `art/requests/NAME.json`: the prepared tool arguments; update it to the arguments actually sent if they changed;
- `art/gen/NAME.png`: the imported image, not resized;
- `art/raw/NAME.*`: the untouched tool output;
- `art/logs/NAME.json`: source path and hash, actual size, alpha report and the request snapshot;
- `art/old/NAME/<timestamp>/`: the earlier raw, final and log, kept before a `--replace`.

## (a) The generator is fixed

- **Built-in imagegen, always.** Never ask the user to choose a generator. No providers, plugins, API keys,
  command or manual backends, nested Codex CLI, or delegation to other image skills.
- The built-in `imagegen` skill may supply prompt guidance; its CLI/API fallback does not apply here.
- Creative changes and background removal use the same tool. Slicing, trimming, packing, alignment and texture
  preparation stay deterministic local steps.
- No model choice, no seed, no exact size: the tool picks its own model and the returned size. Consistency comes
  from refs, anchors and edits (e).
- `gen.py check` validates local inputs only (the style bible and style refs). Only the session can tell whether
  the tool is available.
- **If the tool is unavailable,** report the blocker, keep building the engine on placeholders, keep useful
  work, and don't offer another generator or describe the build as finished.

## (b) Project configuration

`ref2game.json` in the project root:
```json
{"generator": {"tool": "imagegen", "size": "1536x1024", "alpha": "auto", "opaque": ["bg_sky*", "*_tex"]},
 "style_bible": "art/style_bible.txt", "style_ref": ["ref.png"]}
```

- `size` is a canvas/aspect hint written into the prompt, not a tool parameter. Imported images keep the
  dimensions actually returned; size them in `SIZES` and `prep.py` from those.
- `alpha: auto` means native transparency except for names matching `opaque`; background bands keep their
  transparent top. `--alpha native|none` overrides it per asset.
- `gen.py` rejects a legacy `provider` field. For a project made with an older version, replace its `generator`
  object with the one above and drop provider, command-template, model and API settings.

## (c) The first asset is the capability probe

There is no throwaway probe and no budget question (there is no per-image cost). The first production asset,
the one the first frame needs most, doubles as the probe. Each risk is tested by the first production asset
that carries it: the first sprite (alpha), the first part sheet (sheet discipline and gutters), the first wide
band (the returned aspect and the crop). Judge each when it lands and write the verdict into `study/GENERATOR.md`:
- **Alpha quality.** It passed `gen.py import`; view it over a dark and a light background at display size: soft
  edges, no halo, no checkerboard, nothing missing.
- **Style adherence.** Compare to the reference crop side by side at the same scale. An independent critic
  (`critics.md` §2) is better than self-review.
- **Consistency.** When the next asset of the same class lands, compare identity, palette, line and light.
- **Edit fidelity.** On the first edit-based variant (`--ref art/gen/NAME.png="edit target: change only X; keep
  everything else identical"`), check that only X changed (`variantfix.py` reports the changed region).

From the results, pick:
- the alpha strategy per asset class (native, or paper/key for styles that need it, (f));
- the canvas hints per asset class;
- sheets vs single assets.

## (d) One asset, several assets

**One asset:**
1. Inspect `ref.png` and any anchor or edit target with `view_image`. Finish the style bible and write
   `art/prompts/NAME.txt`.
2. Prepare the call from the project root:
   ```bash
   python3 <skill>/scripts/gen.py prepare NAME art/prompts/NAME.txt \
     --ref art/gen/hero_anchor.png="same character; keep design and proportions" --alpha native
   ```
   Omit the extra `--ref` before an anchor exists. `art/requests/NAME.json` holds an `arguments` object with the
   verbatim style bible, the role-labelled prompt, absolute reference paths and the transparency flag. Missing
   references or an unfinished style bible fail preparation.
3. Call `image_gen__imagegen` / `image_gen.imagegen` directly with those arguments, per its current schema:
   ```json
   {"prompt": "<the assembled prompt>",
    "referenced_image_paths": ["/abs/project/ref.png", "/abs/project/art/gen/hero_anchor.png"],
    "transparent_background": true}
   ```
   Never send the wrapper metadata (`name`, `tool`, `requested_size`) as arguments. Don't invent model, seed,
   quality, exact-size or destination-path fields. The reference order must match the Image 1 / Image 2 labels.
4. If a required image exists only in the conversation, use `num_last_images_to_include` instead of
   `referenced_image_paths`, with the smallest count that includes every target (at most 5). Never use both. If
   neither mechanism includes every target, ask the user to reattach it. Save the arguments actually sent in the
   request before import; never claim an unattached reference was used.
5. Show the image through the tool's native result mechanism, inspect it, and use the local path it actually
   returned. Never guess which generated file is newest. If only inline data comes back, use its supported
   local-save mechanism; don't switch generators.
6. Import it and wire it in:
   ```bash
   python3 <skill>/scripts/gen.py import NAME /actual/returned/image.png
   python3 <skill>/scripts/prep.py --only NAME
   ```
   Use `--replace` for an intended replacement, including a template placeholder; the previous raw output, final
   and log are backed up. Otherwise use a versioned name. Import keeps the pixels and alpha as returned,
   validates required transparency, and records the actual size and prompt inputs. Wire the display size in the
   scene in the same step.

**Several assets:**
- One distinct call per asset or coherent part sheet, in PLAN order. Inspect anchors before making the
  variants that depend on them.
- Make independent calls in parallel only when the active tool supports it; otherwise call them back to back.
  Keep coding while a call runs.
- In functions code mode, follow the image tool's execution instructions and show the result with
  `generatedImage(result)`; never print base64 data. Keep progress visible while calls run.
- Every call attaches the style reference and any approved class or character anchor.

## (e) Prompting and consistency

- **Label refs by role.** `gen.py prepare` labels each style ref "style reference: match style, palette,
  rendering and light; do not copy composition". Give extra refs an explicit role: `--ref img.png="edit target"`,
  `="same character: keep face, outfit, proportions"`, `="pose only"`.
- **Verbatim style bible on every call** (`art/style_bible.txt`): light direction, palette, line and edge
  treatment, rendering, detail density, what to avoid. Never paraphrase it per asset. Put the asset specifics in
  the prompt file.
- **Golden-set anchor.** Once the user approves the first assets, append them to `style_ref` in
  `ref2game.json`. Every later call then sees the approved look, not just the original reference.
- **Edit-based variants.** For states, colours, damage or expressions, pass the approved asset as a ref with the
  line "change only X; keep everything else identical". This holds identity better than a fresh prompt. Drift
  accumulates along an edit chain; when it shows, edit from the approved base again.
- **One asset per call** gives the most resolution and the cleanest alpha. **Kit-mates on one sheet**, with
  gutters wide enough to slice cleanly, share lighting, scale and palette. Slice them afterwards. Sheets suit
  sets that must match: tile variants, part rigs, icon sets. Weigh the two per set.
- **No seeds.** Re-rolls are not reproducible; refs, anchors and edits carry consistency.
- **Reject budget.** Don't keep re-rolling. When a re-roll or two hasn't fixed it, change the prompt or the
  approach (an edit from the nearest good asset, a sheet, a different ref or crop, a different part layout or
  integration), not the dice. Note rejects and their reasons in `study/GENERATOR.md`. Judge replacements in the
  assembled same-scale frame, not alone.
- Ask for **no cast shadow, no floor, no glow, no frame, centred with margin**. Add shadows, glows and outlines in
  the engine, where they stay consistent and animatable.

## (f) Transparency

1. **Native, then validate.** `transparent_background: true` (`--alpha native`, or `auto` for names outside
   `generator.opaque`) for sprites, part sheets and transparent bands. `gen.py import` rejects:
   - opaque results;
   - empty results;
   - baked checkerboards;
   - hard binary edges, which are allowed when the asset was prepared with `--pixel`.

   On a rejection, correct the image with imagegen (restate the transparency requirement) and import again. Keep
   transparency in edits unless changing it is the point.
2. **Paper and keyed art, offline.** Paper styles (watercolour, ink, silhouettes; `styles.md`) are generated
   opaque on the paper colour (`--alpha none`, the paper named in the asset prompt), imported, then keyed from the
   untouched output: `gen.py key art/raw/NAME.png art/gen/NAME.png --lum --key <paper>` (alpha from luminance
   against the paper, colour un-multiplied; the paper defaults to `ffffff`). Art that already sits on a flat key
   colour uses `gen.py key IN OUT --key RRGGBB` (default `ff00ff`). Choose the key **per asset, far from the
   asset's palette**, never white or black and never a colour in the outlines.

   `gen.py key` builds a soft OKLab matte with thresholds set from the border noise, refines edge alpha against
   the nearby solid colour, and un-mixes `C = (I - (1-a)K)/a`. It then despills (only spill beyond the subject's
   own colour), contracts the edge (`--choke`, default 1 px; thin parts are kept), drops specks (`--speck`,
   default 16 px²), and bleeds colour into clear pixels so filtering never shows dark fringes.
3. **Background removal** is a creative edit: ask imagegen to remove the background and keep the subject
   identical, with real transparency, then re-check with `gen.py validate`.
4. `--alpha none` is for backgrounds and full-frame layers.

Inspect edges over light and dark backgrounds at display size. `prep.py` crushes alpha noise, bleeds edge colour
and trims, while `art/raw` keeps the original.

## (g) Pixel art

- imagegen's pixel art is "pixel-looking" hi-res output: an uneven grid and stray colours. Snap it with
  `gen.py pixel IN OUT --grid auto --colors K` (default 16; set K from the style's palette; `--scale N` enlarges
  with nearest-neighbour), which:
  1. detects cell size and phase;
  2. quantises the palette (median cut + k-means);
  3. takes the **mode** colour per cell;
  4. binarises alpha.

  Then fix outlines and jaggies. If the grid is non-integer, regenerate or change the approach.
- `gen.py prepare --pixel` marks the asset so `gen.py import` accepts hard binary alpha; `validate --pixel` and
  `key --pixel` (a hard key, no un-mix, despill or choke) are the offline equivalents.
- Lock a palette early. Pass the approved palette image as a ref, and quantise every asset to it.

## (h) Files, provenance and gotchas

- **Where the image lands.** The tool may save under `$CODEX_HOME/generated_images/`; it takes no project
  destination. Use the returned path; `gen.py import` copies it into the project.
- **Provenance.** `art/requests/NAME.json` is what was intended (update it if the arguments sent differed),
  `art/raw` what came back, `art/logs` what was imported. A request without a log is not done
  (`pitfalls.md`).
- **"Transparent background" written into a prompt** instead of requested with the transparency flag gives a
  painted checkerboard. Use `transparent_background`; `gen.py import` and `validate` detect a checkerboard.
- **Native alpha may not be fully opaque inside,** or carry faint noise outside. `prep.py` crushes near-0 and
  near-1 alpha.
- **The returned size and aspect may differ from the hint.** Very wide bands may come back narrower than asked:
  tile or extend them in the engine. The log has `actual_size`.
- **Subjects touching the canvas edge** get cut and confuse key-border detection. Ask for the subject centred with
  a clear margin.
- **Content filters.** Phrase game violence as stylised and non-graphic ("cartoon toy sword", "no blood",
  "knocked out, not hurt"). Never retry a block unchanged.
- **Prompt rewriting.** The tool may rewrite or expand prompts. Keep must-have constraints short and explicit,
  and judge the image against them, not against the prompt.
- **Keying needs a lossless source.** Key from the PNG in `art/raw`, never from a recompressed copy.
