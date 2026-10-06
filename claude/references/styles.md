# Style families: measure → prompt → generate → post → engine

Classify the reference into a family, measure it, and write the style bible (`art.md` §2) from those measurements. Each family below lists what its bible must pin down; fill every item with measured values, in your own wording, then use that one wording verbatim on every call. Attach the reference image to every call. The families are starting points: a reference that sits between families, or one you can't place, is a question for the user. The notes say what each stage of the pipeline must achieve for the family; how to achieve it is decided per project, with the reference in hand.

The bible holds **style only**. Background, isolation and composition never go in it. `gen.py` adds the background line per job from its alpha mode (transparent, key colour, paper), and the job's own prompt carries the composition. Isolation wording in the bible leaks into every job, and sky and band jobs come back "isolated, no scenery".

## 0. Shared measurement and post chain

Measure with scripts on the reference and save the results to `study/study.json`. Never eyeball. `study.py image` already writes palette, value, light and edge analyses there, and `study.py tiles` measures the grid (`study.md`); script the rest.

| Measure | What to record |
|---|---|
| Palette | Clusters in a perceptual space (OKLab) over opaque pixels: how many colours cover nearly all pixels, the hex list, and the hue shift along each ramp (shadow hue vs light hue). |
| Value bands | The L* distribution per depth band (near/mid/far) and its spread (contrast) per band. |
| Edge softness | The transition width of silhouette edges, over many samples, in px at native scale. |
| Line | Is there a dark ring around shapes? Its thickness (distance transform), hue (pure black or a darker local hue), taper, and inner vs outer weight. |
| Texture | High-pass energy inside flat regions; the dominant stroke or grain scale (FFT peak). |
| Pixel grid | Run lengths / autocorrelation peak. Steps that are exact multiples of one size mean pixel art. |
| Light | Key direction from shading gradients; rim light colour; ambient tint. |

The generic post chain (what `gen.py` and `prep.py` do is in `art.md` §8):
1. **Key**: native alpha, or a flat key colour far from the subject's hues, or paper for translucent media.
2. **Decontaminate** edges: `c = (c − (1−a)·key) / a`.
3. **Choke** alpha slightly (`gen.py` chokes 1 px).
4. **Scale-normalise** to a consistent texel density per layer.
5. **Colour**: palette lock (hard) or soft transfer (match mean and std in Lab, Reinhard 2001).
6. **Outline unify**, then the engine settings below.

Generator needs are listed as capabilities to look for when the project picks a model: native transparency, strong reference adherence, multi-reference input, same-canvas edit fidelity, true pixel-grid output, vector/SVG output, palette conditioning, resolution above display size.

## 1. Pixel art (low-res pixel; HD pixel)
**References**: Shovel Knight keeps each sprite to a handful of colours. HD pixel = pixel sprites with modern light: Sea of Stars built a custom dynamic-lighting pipeline; Eastward adds SSAO, CRT and LUT grading.
- **First decide the family, by measuring, not by the word "pixel".** Crop the reference's HUD text and one light falloff at 4×.
  - **True low-res pixel**: the font is a pixel font, light falls off in hard steps or dithers, every edge is on one integer grid. → low-res render target + integer upscale (below).
  - **HD pixel / pixel-look** (most modern references and almost every AI-generated one): pixel-drawn sprites, but smooth anti-aliased UI type, smooth light gradients, soft fog and bloom, often a non-integer grid. → **full-resolution pipeline**: sprites at display size (`SIZES`) from hi-res sources with linear + mipmaps; lights, fog, particles and text at full resolution; outlines and HUD frames crisp but not blocky. **Never pixelate the whole frame or the font** for an HD-pixel reference: it reads as "too pixelated" at once.
  - Unsure? Show the user two stills (both pipelines) in one question.
- **Measure**: native pixel size; character height and tile size in native pixels; colours per sprite and in total; outline type (black, coloured, selective); anti-aliasing and dithering present or not.
- **Bible must pin down**: native resolution (subject height, grid); every pixel a hard square of one flat colour; the palette (count and hex list); outline type and colour, including any selective outline on the lit side; tone ramps per material and their hue shift; the light direction; the exclusions (blur, gradients, noise); a strong readable silhouette.
- **Avoid in prompts**: resolution and rendering words (HD, 4K, realistic, render, 3D), soft-light and lens words (gradient, glow, volumetric, depth of field), detail boosters. Each pulls the model away from hard flat pixels.
- **Generator fit**: either a model that outputs true low-res pixel grids with palette conditioning, or any strong model at high resolution followed by downscale-to-grid and palette quantize. General models produce fake pixels on fractional grids.
- **Post**:
  1. Detect the cell size (runs or FFT) and sample the **dominant** colour per cell, not the mean (the mean invents in-between colours).
  2. Quantize to the locked palette in OKLab, with no dither unless the reference dithers.
  3. Binarise alpha.
  4. Remove orphan pixels and doubled-line jaggies; enforce one outline width.
  5. Share one palette across the whole pack (curated palettes: Lospec).
  - Tools: `gen.py pixel IN OUT [--grid auto|N] [--colors 16] [--scale 1]` snaps pixel-looking art to its real grid; `--pixel` on a job gives nearest scaling and hard alpha.
- **Engine**:
  - Nearest filtering, mipmaps off (`SCENE.NEAREST`).
  - True low-res: render to a low-res target, then integer-upscale with letterbox (`L.init(W, H, extra, { pixel: k })`, `engine.md`; Unity Pixel Perfect).
  - Integer scale only. Where a non-integer scale is forced, known approaches: nearest to the closest integer then bilinear, or an fwidth "fat pixel" sampler.
  - Snap the camera and sprite draw positions to whole native pixels; keep sub-pixel positions in the sim.
  - Outline width = one *texel*. Bloom off for true low-res; HD pixel may bloom true highlights only.
  - Grade with a palette LUT; do palette swaps with an index→palette texture.
  - Dither only where the reference dithers.
- **Motion**: few drawings, held. Count the drawings and holds on the reference (`study.py track`). Never free-rotate or non-integer-scale a sprite: mixed pixel sizes read as amateur. Rigs are allowed only if every frame is re-rasterised at native res and re-quantized (Dead Cells' 3D→pixel pipeline).
- **Effects**:
  - Water and fire through colour cycling.
  - Particles are whole-pixel squares.
  - Light is drawn shapes with stepped falloff. HD pixel can use additive lights plus hand-painted normal or bump maps per part, as Eastward does.
- **Slop**: fractional or mixed grids, fuzzy anti-aliased edges, far more colours than the palette, gradient or pillow shading, speckle noise, outlines of varying thickness, light from several directions. **Fix**: grid-snap + palette lock + cleanup script; regenerate smaller.

## 2. Painterly / hand-painted (Ori, Hollow Knight backgrounds, Rayman Legends)
**References**: Ori layered thousands of hand-painted pieces with heavy parallax. Hollow Knight lights scenes with soft transparent shapes. UbiArt deforms painted parts with 2D patches and bones.
- **Measure**: brush-stroke scale relative to object size; lost-vs-found edge ratio; L* range per depth band (far bands are usually lighter, lower-contrast, cooler); saturation of the focal point vs the background; rim colour.
- **Bible must pin down**: the brushwork (opacity, visible strokes, stroke scale relative to the object); the edge policy (soft lost edges inside forms, crisp only on the silhouette); the palette sampled from the reference; key, bounce and rim colours and the key direction; matte surfaces; the value range for the layer; no ground shadow.
- **Avoid in prompts**: photoreal and 3D-engine words, detail boosters, gloss and lens words (specular, bokeh, flare, HDR, sharp focus).
- **Generator fit**: strong reference adherence plus multi-reference input (reference + previous approved asset); native transparency or a clean key; resolution above display size; edit fidelity for variants.
- **Post**:
  - Key, decontaminate, choke.
  - **Generate each asset at a size proportional to its in-game size**, so brush scale stays uniform; otherwise strokes disagree after scaling.
  - Soft Lab transfer per depth band toward the reference band statistics.
- **Engine**:
  - Linear filtering, mipmaps on for anything scaled below 1:1.
  - The grade pass does per-band haze: lerp toward the fog colour by depth and lower contrast.
  - Rim light from the key direction; fbm fog bands; occluded god rays; subtle bloom on highlights only.
  - Blur and darken near-foreground occluders.
  - Ink outline pass only if the reference has lines.
- **Motion**: smooth 60 fps cut-out rigs with mesh/patch deformation; shader sway, lean and bend for foliage; spring secondary motion on cloth, hair and antennae.
- **Effects**: painterly water (flow-mapped colour bands plus soft highlights), soft-edged particle sprites (pollen, leaves), light as additive soft shapes, layered fog.
- **Slop**: uniform detail everywhere with no focal hierarchy; identical fake-brush texture at different scales; light directions that differ between assets; plastic highlights; halo fringe; over-saturation. **Fix**: size-proportional generation; texel-density check; a shared grade and rim pass; regenerate offenders with the approved asset attached.

## 3. Cel / anime / cartoon with ink lines (Cuphead rubber hose, Rayman)
**References**: Cuphead animates at 24 fps "on ones" over 60 fps gameplay. Its characters are hand-drawn and inked, then coloured digitally, over watercolour backgrounds. Its grade layers film grain and chromatic aberration.
- **Measure**: outer line width in px at the reference scale; inner/outer ratio; line colour (black, or coloured per material); taper; fill tones per material (shadow tones, highlight or not); shadow hue shift; hand style (finger count, gloves).
- **Bible must pin down**: the outline (width relative to the canvas, colour, taper) and the inner-line weight relative to it; flat fills with the measured number of hard-edged shadow tones and highlights per material; the shadow hue shift; the shape language and hand style; the exclusions (gradients, texture, soft shading).
- **Avoid in prompts**: soft-rendering words (soft shading, airbrush, gradient), painterly or sketchy words, realism and 3D, gloss, texture.
- **Generator fit**: clean line adherence and same-canvas edit fidelity (expression and pose variants must keep line weight); native transparency, or a key colour far from the line colour (never a dark key).
- **Post**:
  - Posterize fills per region to the measured tone count (k-means per connected fill region).
  - Remove gradients.
  - Unify silhouette lines in the engine, not in the bitmap.
- **Engine**:
  - Linear filtering plus mipmaps.
  - Ink outline pass (`LIB.inked`) at a constant screen width matched to the reference's line at display size, in the measured line colour.
  - Bloom off.
  - Grade: grain, vignette or slight chromatic aberration only if the reference has them.
  - Hold poses: step rig updates at the reference's drawing rate for the drawn feel.
- **Motion**: rubber hose means no elbows; bend limbs as splines. Squash and stretch with volume preserved, as strong as the reference shows. Strong anticipation, smear frames, overshoot. UbiArt/Rayman puts a skeleton on imported drawings and animates the pieces.
- **Effects**: flat-band cartoon water with foam lines; dust and impacts as flat shapes with a line; light as flat shadow shapes, no soft gradients.
- **Slop**: wobbling or doubled line weight between assets; lines broken at joints; soft gradients in a cel style; realistic hands where the style is stylised; off-model faces between variants. **Fix**: re-ink pass, posterize, explicit hand spec, face-only edits aligned to the base.

## 4. Flat vector / geometric (Alto, Monument Valley, mobile casual)
**References**: Alto's lighting blends predefined colour schemes (directional, ambient, fog) with a rotating sky plane, in real time. Monument Valley's illusions need orthographic iso; each level is whiteboxed before the art pass.
- **Measure**: flat tones per object (base, shade, highlight); total hue count; corner radii; outline presence (usually none); gradients (sky only?); facet lighting direction.
- **Bible must pin down**: primitive-based shapes with one consistent corner radius; the flat tones per object (base, shade facet, highlight facet); outlines or none; the palette (count and hex list); light shown only as a lighter flat facet, and its direction; silhouettes readable at small size; generous negative space; crisp edges; the exclusions (texture, noise, gradients except where the reference has them).
- **Avoid in prompts**: texture, grunge, brush and sketch words, realism, 3D render, gloss, noise, grain.
- **Generator fit**: vector/SVG-capable output; or a strong raster model followed by colour raster→SVG tracing (stacked-shape tracers give fewer shapes than outline tracers); or a raster concept rebuilt in code as SVG paths.
- **Post**:
  1. Vectorise.
  2. Simplify paths (Douglas-Peucker), with a tolerance that removes jitter but keeps the designed shape.
  3. Snap colours to the palette.
  4. Normalise corner radii.
  5. Rasterise at device resolution, or draw as meshes.
- **Engine**:
  - Linear filtering; MSAA or analytic edge AA.
  - No outline pass, no grain.
  - Lighting = palette-scheme interpolation per time of day and weather, plus depth fog as a lerp to the fog colour per band.
  - Gradient sky.
- **Motion**: smooth 60 fps tweens with ease-out and springs; little squash; no line boil.
- **Effects**: geometric particles (circles, triangles); light shafts as translucent polygons; snow and rain as simple strokes.
- **Slop**: hidden noise textures, inconsistent corner radii, gradients on every object, melted organic curves, stray tiny details. **Fix**: vectorise, simplify, palette snap, rebuild in code.

## 5. Hand-drawn ink / sketch / paper cut-out (Don't Starve, Paper Mario-like, Tearaway-like)
**References**: Don't Starve's art pipeline runs through Flash with cut-out parts and plays flat animation as billboards in 3D.
- **Measure**: line width range and wobble; hatching angle and density; fill saturation; paper grain scale; cut-out border width and colour; drop-shadow offset.
- **Bible must pin down**: the line character (width range, wobble, colour); hatching for shadow (one angle for the whole pack) instead of soft shading; the fills (saturation, any misregistration against the line); the proportions and asymmetry; a paper cut-out border if the reference has one.
- **Avoid in prompts**: clean-vector and perfect-line words, smooth gradients, gloss, 3D, photoreal, neon, bloom.
- **Generator fit**: strong reference adherence on line texture; same-canvas edit fidelity for symbol-swap parts (hands, mouths) so the line character matches.
- **Post**: keep the line texture (no posterize on lines). Paper look: dilate alpha and fill the ring with the paper colour, then an offset drop shadow, both measured from the reference. Make the border in post, not in the prompt, so its width is uniform.
- **Engine**:
  - Linear filtering.
  - Multiply a paper-grain overlay anchored in world space (not screen space, or it swims).
  - Line boil: re-sample with small UV noise across a few seeds, cycled at a low rate matched to the reference (classic boil traces a few drawings in a loop).
  - Paper flip turn: scale X through zero to the mirrored side, fast.
  - No bloom.
- **Motion**: cut-out rigs with symbol swaps (hand shapes, mouths, eyes); poses stepped at the reference's drawing rate; snappy holds.
- **Effects**: scribbled smoke and dust; hatched shadows; ink splats; night as darkness with a desaturated vignette.
- **Slop**: too-clean uniform strokes, hatching directions that disagree between assets, smooth digital gradients, cut-out borders of varying width. **Fix**: unify the hatch angle in the bible; make the border in post, not in the prompt.

## 6. Watercolour / gouache / storybook (Gris, Child of Light)
**References**: Gris tried scanned paper textures, scanned watercolour stains and pencil strokes, and relied on shaders to look hand-made; it restores colour progressively as a mechanic. Real-time watercolour: edge darkening via difference of Gaussians, granulation, colour bleeding, paper distortion.
- **Measure**: wet-edge darkening width; granulation scale; paper texture scale; how much paper white is left; value range (often high-key); palette per scene; presence of an underdrawing.
- **Bible must pin down**: transparent layered washes with pigment pooling at wet edges, blooms and granulation; paper white left for highlights; the palette and value range; an underdrawing if the reference has one; the shape language; where gouache (opaque) accents are allowed; no frame or border.
- **Avoid in prompts**: airbrush and vector words, black outlines, gloss, neon, 3D, photoreal, high contrast, sharp.
- **Generator fit**: strong reference adherence; generate on the paper colour (`--alpha lum`, `--key` = paper, default `ffffff`), not on a key colour. Watercolour is translucent, so keying destroys its edges.
- **Post**:
  - Treat the asset as pigment: alpha from the distance to the paper, colour un-multiplied (`gen.py` `lum` mode does this); or draw with multiply blending over the paper.
  - Soft Lab transfer per scene.
- **Engine**:
  - Linear filtering plus mips.
  - One world-anchored paper texture multiplied over everything.
  - Edge darkening from an alpha DoG; granulation from paper height × pigment density; slight UV distortion by the paper normal.
  - Light as unpainted paper glow; bloom only soft, wide and low.
- **Motion**: graceful and floaty; long eases; cloth and hair secondary motion carries the emotion.
- **Effects**: fog and water as layered washes; rain as dry-brush streaks; a colour-reveal mechanic (desaturate the world, restore hues per region).
- **Slop**: airbrush gradients posing as watercolour, a uniform fake texture overlay, harsh black outlines, over-saturation, a texture that swims with the camera. **Fix**: pigment alpha, world-space paper, DoG edges, palette limit.

## 7. Dark gothic / high-contrast silhouette (Limbo, Inside-like 2D)
**References**: Limbo is black silhouettes in grey fog, with film grain, a vignette and depth blur. Its scenes split into foreground (out of focus), midground (in focus) and background.
- **Measure**: number of value bands; black level of the gameplay plane; fog colour and its gradient with depth; grain strength; vignette radius; any accent (eyes, a single rim colour).
- **Bible must pin down**: the subject as a single near-black value with no interior detail beyond the reference's accents (eyes, a thin rim); crisp anti-aliased edges; a distinctive readable outline and the reference's proportions; rim light colour and edge if present; the view. A background variant: the same shape language at a flat band value, no texture.
- **Avoid in prompts**: colour and saturation words, texture and internal shading, cartoon or cute, gloss, gradients.
- **Generator fit**: almost any model; silhouettes forgive identity drift. The deciding capability is clean shape design. Generate dark on white (`--alpha lum --key ffffff`).
- **Post**: alpha from a luminance threshold with a thin soft edge; fill with the band's value in the engine (one sprite reused at any depth).
- **Engine**:
  - Each layer is tinted toward the fog colour by depth.
  - Gaussian blur on the foreground and far layers.
  - Animated film grain, subtle; vignette.
  - Light shafts and flicker; bloom only on rare light sources.
- **Motion**: weighty, realistic, smooth 60 fps; physics-driven ropes, boxes and ragdolls; long holds, slow idles.
- **Effects**: fog layers, dust motes in shafts, water as a black mirror with a thin highlight line, brief high-contrast flashes.
- **Slop**: interior detail inside silhouettes, several light colours, noisy edges, mismatched blur between layers. **Fix**: threshold, one grade, depth-driven blur.

## 8. Retro CRT / vaporwave neon
**References**: CRT shaders model scanlines, an aperture or shadow mask, curvature and bloom. crt-lottes is a well-known reference implementation with documented parameters.
- **Measure**: neon hues (usually few); line width; glow radius relative to line width; dark base value; scanline period; chromatic offset in px; curvature.
- **Bible must pin down**: flat dark base shapes; thin neon strokes of one measured width in the measured hues; clean continuous lines that trace edges and key details; the reference's motifs; the palette limit; a readable silhouette against black; no glow, blur, bloom or reflections drawn into the image.
  - **Emissive pass**: a second call with edit fidelity that returns the same image with only the neon strokes, white on black, aligned to the colour pass.
- **Avoid in prompts**: glow, bloom, lens flare, blur, haze, photographic, realistic, chrome reflections (unless the reference has them).
- **Generator fit**: same-canvas edit fidelity, so the emissive mask aligns with the colour pass; transparency is not needed on a black base (use additive blending).
- **Post**: derive or clean the emissive mask; threshold it; keep the base and emissive textures pixel-aligned.
- **Engine**:
  - Render the game at low res if the reference does.
  - Bloom **on**: multi-scale, emissive mask only.
  - Then the CRT pass, with the components the reference shows: scanlines, mask, curvature, vignette, chromatic offset, a rolling noise line.
  - Pixel-art sources keep nearest filtering before the CRT pass.
- **Motion**: snappy and fast; time distortion (slow-mo, rewind glitch) as a feel tool.
- **Effects**: scrolling perspective grids, banded sun, glitch slices, VHS tracking.
- **Slop**: glow baked into sprites (double bloom), the generic sunset-grid cliché when the reference lacks it, illegible bloom wash. **Fix**: separate emissive, bloom threshold, a readability check below play size.

## 9. Low-colour 1-bit / limited palette
**References**: Return of the Obra Dinn's stable 1-bit dithering kept its patterns from crawling when the camera moved.
- **Measure**: colour count; dither type (Bayer, blue noise, hand-placed); line weight; pattern scale versus native pixel size.
- **Bible** (generate a clean **value study**, then dither in code) **must pin down**: bold simplified shapes readable at the target native height; a few flat, well-separated value bands, the darkest reserved for outline and cast shadow; no texture, noise or gradients inside bands; a crisp silhouette with chunky features and no detail thinner than survives at native resolution; the light direction.
- **Avoid in prompts**: dithered, halftone, pixel art, detailed, texture, noise. The model fakes these badly; the code does them.
- **Generator fit**: any model with good shape design; the look comes entirely from post.
- **Post**: levels → map bands → ordered (Bayer) or blue-noise threshold at native res → palette map; an outline from the alpha edge.
- **Engine**:
  - Nearest filtering, integer scale.
  - Anchor the dither pattern in world/object space and snap the camera to whole pixels, so dots don't crawl.
  - Palette swap at the end through a LUT; no bloom.
- **Motion**: low frame rates, strong poses, screen flashes as palette inversion.
- **Effects**: inversion flashes, dither-faded fog, hatched light cones.
- **Slop**: grey anti-alias pixels, dither swimming in screen space, moiré from non-integer scaling. **Fix**: binarise, world-anchored dither, integer scale.

## 10. Decision table

| Reference cues | Family | Generator capability | Post chain | Engine settings |
|---|---|---|---|---|
| Hard square pixels, few colours, steps at one size | Pixel art | True pixel-grid output with palette input, or high-res + post | Grid detect → dominant-per-cell → palette lock → alpha binarise → outline fix | Nearest, no mips, low-res RT + integer scale, pixel snap, 1-texel outline, bloom off |
| Pixel sprites + soft light, bloom, fog | HD pixel | As above, plus normal/bump per part | As above + painted normal maps | Sprites at display size; lights, bloom, fog and text at full res |
| Visible brush, soft inner edges, atmospheric depth | Painterly | Reference adherence, multi-reference, transparency, high res | Key → decontaminate → size-proportional gen → Lab transfer per band | Linear + mips, per-band haze, rim, fbm fog, god rays, soft bloom, ink pass only if lined |
| Uniform dark lines, flat fills, hard shadow tones | Cel / cartoon | Line adherence, edit fidelity, light key | Posterize fills, kill gradients | Linear, constant-width outline pass, bloom off, grain only if the reference has it; poses stepped at the reference's drawing rate |
| Flat tones, primitives, no lines | Flat vector | Vector/SVG output, or vectorise | Vectorise → simplify → palette snap | Linear + MSAA, scheme-blend lighting, depth fog |
| Scratchy line, hatching, paper | Ink / paper | Reference adherence on line texture | Keep line; paper border in post; drop shadow | World-anchored paper multiply, line boil at the reference's rate, paper flip |
| Translucent washes, wet edges, paper white | Watercolour | Reference adherence; generate on paper | Pigment alpha / multiply | Paper overlay, DoG edge darkening, granulation |
| Black shapes, grey fog, grain | Silhouette | Shape design only | Threshold → value per band | Depth tint + blur, grain, vignette |
| Neon strokes on dark, glow, scanlines | CRT / neon | Edit fidelity for emissive pass | Emissive mask clean-up | Bloom on emissive, CRT pass |
| A few colours, dither patterns | 1-bit | Shape design; value study | Bands → Bayer/blue-noise → palette map | Nearest, world-anchored dither, LUT swap |

If two rows match, the sprites follow the gameplay-layer row and the backgrounds may follow the other. Example: pixel-art characters over painterly backgrounds; flag that mix to the user as a deliberate choice.
