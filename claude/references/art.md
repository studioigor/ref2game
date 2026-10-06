# Art direction for AI-generated game art

**The goal.** Generated pieces should assemble into a frame that reads like a shipped game, not "AI slop".

**The core rule.** The image model makes the **raw paint**. Code enforces every **system rule**:
- scale;
- light direction;
- per-plane value and haze;
- palette;
- outline;
- alpha;
- all effects and all motion.

Studios that ship with AI treat the output as a starting point, with a mandatory finishing pass.

## Contents
1. What to generate vs what to do in code
2. The style bible and prompt scaffold
3. Slop signals and their fixes
4. Consistency across separate generations
5. Readability: planes, values, roles
6. Asset classes: how to ask for each
7. Sheets, slicing, parts, variants
8. Post chain (every sprite, automated)
9. Asset acceptance checklist (the asset critic's list; the asset is already in the page)

---

## 1. What to generate vs what to do in code

| Generate (image model) | Do in code (lib.js shaders, sim, scene) |
|---|---|
| Painted depth bands: sky, far, mid, near, framing foreground | Parallax, haze, fog, blur per plane, god rays, bloom, grade, vignette |
| Platform, terrain and prop pieces (strips, caps, modules) | Tiling and placement from level data, contact shadows, wind sway, bending, sag |
| Characters as **part sheets** (body, limbs, cape, face swaps) | Rigs, poses, walk and run cycles, squash, follow-through, blink timing |
| Critters, collectibles, HUD frames and icons | Bobbing, glows, pickup bursts, fly-to-HUD, counters (glyph atlas) |
| Material textures for procedural effects (rarely needed) | Water, waterfalls, foam, fog, particles, rings, sparks, light shafts |

**Never bake** these into an image:
- glow, bloom or light rays;
- cast shadows;
- motion blur;
- text;
- particles;
- water motion.

Each one doubles an engine effect, breaks alpha, or freezes something that must move. If the reference shows a glowing lamp, generate the lamp **unlit-neutral** and add the glow in code.

**Effects and animation are code.** The look of "alive" comes from systems: wind, springs, FSMs, particles. Generated frames cannot provide it. See `effects.md`, `animation.md` and `gamefeel.md`.

## 2. The style bible and prompt scaffold

Write `art/style_bible.txt` after the study, from measurements of the reference (`styles.md` lists what each style family's bible must pin down). **Prepend it verbatim to every call** (`gen.py` does this). Never paraphrase it per asset: one wording for the whole pack is what keeps separate calls consistent. Keep it short: it rides on every call, and `gen.py` truncates it when a provider's prompt limit is hit. It covers:
- style family and shape language;
- shading model (how many tones, how soft the terminator, gradients or flat);
- palette temperature: what colour the lights are, what colour the shadows are;
- line: weight, colour, and **where** it is used (actors vs props vs background);
- texture or brushwork;
- detail hierarchy: big quiet shapes, detail only at focal points;
- **one fixed light sentence**: key direction, key and fill colours, no cast shadow. The same words on every call;
- the projection (strict side view, top-down 3/4, isometric 2:1…);
- the exclusions that follow from §1: no text, logos, watermark, glow, light rays or cast shadows.

The bible holds **style only**; background and composition belong to each job (`styles.md`).

**The per-asset prompt.** `gen.py` assembles each call: the labelled reference images, the bible, `ASSET:` plus the prompt file, then a background line from the job's alpha mode. The prompt file supplies the rest, inputs before the subject and constraints last. It needs:
- **Use case**: the asset class (§6) and the genre.
- **The role of each attached image.** The style reference is matched for style, rendering, palette and light, never for composition (`gen.py` labels it that way as Image 1). An anchor passed with `--ref` (Image 2, 3…) is matched for design and proportions; say so.
- **Subject**: what it is, in plain words, with the view stated explicitly.
- **Composition**: one asset centred, with padding, a fill ratio and a ground line; or N separate pieces with wide empty gaps; or a single horizontal band with its ridgeline height.
- **Constraints**: one subject only, the exclusions, where detail is allowed.
- **For edits**: what changes, and that everything else (proportions, palette, design) stays identical.

**Wording that works** is literal: name the medium and the view, state isolation, the flat background and the absence of shadows. For painterly styles, ask for matte paint and say it is not a 3D render.

**Never write** generic quality boosters ("high detail", "intricate", "8k", "masterpiece"), mood-lighting words ("cinematic", "epic" or "dramatic lighting"), "trending", or artist names. They pull toward the model's default look and fight the reference.

**Scale cues.** Fix the canvas and fill ratio per asset class, and name size relations in words ("the enemy is as tall as the hero's shoulder"). Code still normalises the final size (§3).

## 3. Slop signals and their fixes

| Signal | Why it reads as slop | Fix |
|---|---|---|
| Micro-detail everywhere, no hierarchy | Every pixel equally important, no rest areas | Ask for big quiet shapes. Generate above display size and downscale. Blur and haze background planes in the engine. |
| Light direction differs between pieces | The No. 1 tell | The fixed light sentence on every call. The lit-side check (§9). Add the sun-side rim in the **engine** (`rim` uniform) so flipped sprites stay correctly lit. |
| Glossy "3D render" plastic look | Default model aesthetic | Name the medium in the prompt and say it is not a 3D render. **Reject** the image; post can't fix it. |
| Oversaturation / neon | The model pushes chroma | Clamp chroma per plane in the grade (`grade.x`, saturation). Keep high chroma for actors and interactables. |
| Line weight varies | Each call picks its own line | One engine ink pass for actor silhouettes (`LIB.inked`); interior lines stay as generated. |
| Scale and texel density vary | Each image is framed differently | Fix canvas and fill per class. Normalise in code to the class's display size (`SIZES`, `engine.md`). Compare outline widths across assets at display size. |
| Halo or fringe around sprites | Key colour or dark matte mixed into the edges | Un-mix the edges, choke, bleed RGB outward (`gen.py`, `prep.py`, §8). Premultiplied textures (gl.js). |
| Gibberish detail (pseudo-runes, extra toes, melted leaves) | Hallucinated "detail" | Exclude text, runes and symbols in the prompt. Review at 100%, then regenerate or edit. |
| Tangents and mushy silhouettes | No designed silhouette | Generate objects separately and compose overlaps deliberately in the scene. Run the silhouette test (§5). |
| Same texture visibly repeating | One strip tiled | Several variants in random order, flips of unlit detail, scattered decals. |
| Everything equally sharp: play plane = background | Shipped games separate planes | Per-plane haze, blur (`lod`) and chroma in the engine (§5). |
| A frozen "postcard" | Nothing reacts | That is a systems problem, not an art problem (`gamefeel.md`). |

**Budgets.**
- **Rejects.** The reject budget is in `generators.md` §e. Past it, change the approach (the prompt, the anchor, a sheet, an edit from the nearest good asset), not the dice. Re-running an unchanged prompt does often clear a one-off hallucination.
- **Edits.** Drift accumulates with every iterative edit of the same image. Keep edit chains short and restate the invariants each time ("change only X; keep everything else unchanged"). When drift shows, edit from the approved base again.
- **Approval.** Approve assets only **in the assembled frame** at display size. "Looks great alone" is not approval.

## 4. Consistency across separate generations

- **One call makes one image** (`gen.py` runs one job per image). Distinct assets need distinct calls or one deliberate sheet; asking one prompt for "n variants" gives near-duplicates, not a kit.
- Attach the **style reference to every call**, labelled by role. `gen.py` does this from `ref2game.json → style_ref`.
- After the first approvals, add a **golden-set anchor** per class as a second reference:
  - the approved hero for all characters;
  - the approved terrain piece for all terrain;
  - the approved band for all background bands.
- Generate **kit-mates on one sheet**: the props of one biome, or the caps and middles of one platform type. Pieces made in one image share light, palette and line. Ask for a row or grid with **wide empty gutters** and slice by connected components (§7). Characters are the exception: they need full resolution and a stable identity, so anchor each one alone, then derive parts from it.
- Use **edit-based variants** for states (closed eyes, open mouth, damaged, lit). Edit the approved image, then run `variantfix.py` so only the changed region differs (§7).
- **Colour drift.** After keying, a partial (not full) LAB mean/std transfer toward the reference material is usually enough; a full transfer flattens the asset's own contrasts. Use a hard palette lock only for small-palette styles (pixel art, limited palette; `styles.md`).

## 5. Readability: planes, values, roles

Shipped 2D games (Hollow Knight, Ori, Rayman Legends) separate three planes. The **play plane** gets the strongest contrast, the outlines and the brightest actors. Everything behind it is compressed and hazed; everything in front is dark and soft.

| Plane | Value range | Chroma | Haze | Blur (`lod`) | Outline |
|---|---|---|---|---|---|
| Foreground framing (parallax > 1) | darkest, narrow | low | — | strong | none |
| **Play plane** (actors, platforms, props, pickups) | full range, highest contrast | accents allowed | none | none | yes (actors heaviest) |
| Near background | compressed | reduced | light | slight | none |
| Mid background | more compressed, lighter | lower | more | more | none |
| Far background / sky | narrowest, high key, toward the fog colour | lowest | most | most | none |

The rule is the ordering: contrast, chroma and sharpness fall with distance from the play plane, and haze rises. The actual ranges come from the reference's own depth bands (`study.json`, `styles.md` §0), not from a fixed table.

**Light the walkable surfaces.** Every platform has a lit lip over a darker underside, with a value step at the walk line big enough to survive the squint test. Players read "solid" from that lip.

**Colour-code roles** from the reference's palette:
- hazards and enemies in alarming hues;
- interactables in an inviting accent, often glowing;
- secrets in their own distinct accent;
- the background never uses the role hues at high chroma.

**Tests**, run on the assembled frame (the critic does them, `critics.md`):
- **Silhouette test.** Fill each actor's alpha with black and shrink it below play size; the actor and its pose must still read.
- **Squint test.** Grayscale, blur and posterise the frame into a few value bands (`critics.md` §7). Hero, enemies and walk lines must still separate from what is behind them.
- **No false ledges.** No background layer may contain a platform-like horizontal ledge in the play band. Players will try to stand on it.
- **HUD readability.** The HUD needs a soft dark backing over busy art (`LIB.shadow` behind it).

## 6. Asset classes: how to ask for each

| Class | Canvas / layout | What the prompt must pin down | Then in code |
|---|---|---|---|
| Sky | full frame or wider, no alpha | sky only, no landforms; where the sun is | Mirror copy if the camera pans past an edge; sun glow and rays in code |
| Background band (far / mid / near) | wide, key colour or alpha above the ridgeline | a single horizontal band; the ridgeline height; left and right edges at the same height and density so it tiles; flat key above; even light, lightly hazed | Per-plane grade/haze/lod, fog strips between bands, parallax factor |
| Framing foreground | clump, alpha | a dark silhouette clump for a screen corner | Tint dark, blur, sway; extend it past the screen edge (a mirrored twin works) so corners never expose at any camera position |
| Platform / terrain strip | wide, alpha | exactly side-on; ends complete inside the frame; a level walking surface at a stated height; lit walk-top, dark underside | Cut caps and middles, tile middles, `walk` line measured by `prep.py`, colliders from data |
| Tiles / top-down ground | see `genres.md` (materials + autotile composition in code) | — | — |
| Props (static, interactive) | one sheet per biome/kit, alpha, wide gutters | N separate props, wide empty gaps, one shared ground line | Slice; pivots at the base; sway, pendulum, spring in the sim |
| Character anchor | portrait canvas, alpha | full body in the game's view and facing; a neutral rig pose with the limbs clear of the torso | The approved anchor becomes the `--ref` (Image 2) for its parts |
| Character part sheet | wide, alpha, wide gutters | the SAME character split into separate parts: body and head without limbs; one of each limb, straight; extras (cape, tail, ears); each complete, including the parts normally hidden | Two-bone limbs, layering, poses (`animation.md`) |
| Face / state variants | same canvas as the base | same image; change ONLY the named region; everything else identical | `variantfix.py`, then swap by time |
| Critter / enemy | as character; small ones can be one sprite + parts | scale in words relative to the hero | Rig or procedural deform (squash, bend, wing flap) |
| Collectible / icon | square, alpha | a single centred icon, bold silhouette, readable at the smallest size it is shown | Bob, glow, burst, fly-to-HUD |
| HUD frames | alpha | an empty plaque or frame, no text | Text from the glyph atlas (`LIB.glyphs`) |
| Texture for a shader | square | a seamless tileable material, flat lighting | Offset by half a tile to expose the seam and repair it, `REPEAT` wrap |

## 7. Sheets, slicing, parts, variants

**Slicing.** `python3 <skill>/scripts/slice.py art/gen/<sheet>.png` lists the components (index, box, area). `slice.py <sheet> a,b,c` keeps the N largest components, orders them (`--order reading|x|y|size`, default reading) and writes `art/gen/a.png` and so on (`--out DIR` to change the folder). Each piece keeps only its own pixels.
- `--dilate` (default 6) merges a piece's detached bits into it: raise it if a piece splits, lower it if neighbours merge. `--alpha` and `--min` set the opacity threshold and the smallest component kept.
- Wide empty gutters in the prompt are what make slicing reliable.
- Name sheets `*_sheet` so `prep.py` skips them.

**Parts for rigs.**
- **Limbs.** Ask for each limb **straight**, with the joint clearly readable. The rig cuts it at the joint with sub-rects (`LIB.twoBone`).
- **Overlap.** Joint pieces must overlap enough that no gap opens at any bend. Hide the seam with round joint caps in the limb colour.
- **Far side.** One drawing of each limb can serve both sides: the far copy sits behind the body, pushed back by a darker value and a smaller scale.

**Variants.**
- Generate a variant by editing the approved base.
- Run `python3 <skill>/scripts/variantfix.py art/gen/base.png art/gen/base_blink.png [--out OUT.png]`. It aligns scale and offset, colour-matches, and pastes only the changed blobs (`--regions`, `--thresh`, `--min`, `--feather`) into a copy of the base, so output alpha equals base alpha. It prints the changed region in base uv, for a shader-side effect at the same spot.
- Swapping the textures then never pops colour or position.
- **Write the result back to `art/gen/`.** `prep.py` is a pure function of `art/gen`; anything fixed only in `live/assets` is silently overwritten on the next prep.

## 8. Post chain (every sprite, automated)

Run in this order (`gen.py` keys, `prep.py` does the rest):
1. **Alpha.** `--alpha native` asks the provider for transparency and validates it (soft partial-alpha edges, no baked checkerboard). `key` asks for a flat colour and removes it locally; choose the key **per asset**, far from the asset's hues (default `ff00ff`; pick another when the subject is near it). `lum` keys strokes against paper (watercolour, ink, silhouettes; `styles.md`). `auto` leaves full-frame names opaque, else uses native when the provider supports it, else key.
2. **Decontaminate edges.** Un-mix the key: `C = (I − (1−α)·K) / α`, despill, choke 1 px, drop specks (`gen.py key --choke`, `--speck`).
3. **Clean.** `prep.py` crushes near-0 and near-1 alpha noise.
4. **Bleed.** Spread edge RGB outward into transparent pixels. This prevents dark or coloured halos under mipmaps and blur.
5. **Trim.** Crop to the alpha box + 4 px, except names in `notrim` (default `bg_*`, `*_tex`). Cap at `max` (default 2048 px).
6. **Measure.** Record size, the crop box (used for pivots), and the `walk`/`bottom` lines for names matched by the `walk` config (platform pieces).
7. **Upload premultiplied** (gl.js): linear with mipmaps, or nearest without mips (`SCENE.NEAREST`) for true low-res pixel art.

Final per-plane **grade, haze, blur, rim and outline are engine uniforms**, not baked. That way one rule change re-grades everything, and flipped sprites stay correctly lit.

## 9. Asset acceptance checklist (the asset critic's list; the asset is already in the page)

Run per asset or per sheet, as the asset critic's checklist (`critics.md` §2):
- [ ] **Style.** It matches the reference next to a same-scale crop of it: medium, line, palette, shading model.
- [ ] **Light.** The lit side matches the bible's light sentence; no baked glow, rays or cast shadow.
- [ ] **Alpha.** No fringe on mid-grey **and** on the real background; no specks; no holes.
- [ ] **View and scale.** The projection is right (strict side / top-down / iso); the fill ratio is right; the scale words are respected.
- [ ] **Parts.** Complete including normally hidden areas, straight, with a readable joint, nothing fused.
- [ ] **Variants.** `variantfix` is applied; alpha is identical to the base.
- [ ] **No hallucinated detail.** No text, runes, extra digits or melted forms at 100%.
- [ ] **Silhouette.** It reads at play size (silhouette test, §5).
