# Studying the reference (time-boxed; parallel agents for video)

The study turns the reference into decisions and numbers: what game this is, how it is layered, what every asset is, what moves and what reacts. The look comes from measurements, never from defaults. Keep it short and actionable; the live page is where quality is won.

## Contents
1. Probe and sample
2. Classify: genre, camera, style
3. Measure the style → STYLE.md + style bible
4. Decompose → PLAN.md (layers, assets, effects, interactions, level data)
5. Video references
6. Templates

---

## 1. Probe and sample

```bash
python3 <skill>/scripts/study.py probe ref.png                  # size, colours, alpha; for video: duration, fps, frames
python3 <skill>/scripts/study.py image ref.png --out study/      # palette + ramps, value map, light map, edges, overview grid, tiles
python3 <skill>/scripts/study.py crop ref.png x0 y0 x1 y1 --out study/crops/hero.png --zoom 3 --grid 20
python3 <skill>/scripts/study.py tiles ref.png --region x0,y0,x1,y1 --out study/   # tile size and phase, repeat period, unique tiles, 3/4 wall height guess
```

Make 1:1 crops (`study.py crop --clean` for crops that go to the generator as refs) of every distinct subject into `study/crops/`: each character, enemy, prop, platform or terrain material, background depth band, effect (water, fall, fog, light), and HUD element. Critics compare against these crops later.

## 2. Classify: genre, camera, style

Decide and write down:
- **Game family:** side-scroller, top-down, isometric, shmup, puzzle, card/UI, etc. (`genres.md`). That family dictates the layer stack, the sim template and which interactions matter.
- **Camera and projection:** strict side, 3/4 top-down, isometric 2:1. Also the view size (1920×1080 by default; pixel art uses its native resolution plus an integer scale).
- **Style family:** pixel, painterly, cel/ink, flat vector, hand-drawn, watercolour, silhouette, neon… (`styles.md`). That family dictates the prompt vocabulary, the post chain and the engine flags (filtering, outline pass, bloom, effect stylisation).
- **If the reference is not a game** (concept art, illustration, photo), the game type comes from the user's Step 0 answer. If the study shows that answer doesn't fit the picture, ask again.

## 3. Measure the style → `study/STYLE.md` and `art/style_bible.txt`

- **Rendering family, from zoomed crops** (record it in STYLE.md, it decides the pipeline): is the UI font a pixel font or smooth? Do lights fall off in steps or smoothly? Are sprite edges on one integer grid? A pixel-drawn sprite style with smooth type and light is "HD pixel" and renders at full resolution (`styles.md` §1).
Measure, with crop references:

| Axis | What to write |
|---|---|
| Value planes | L* ranges of the foreground, play plane, near, mid and far planes; the squint picture |
| Palette | Ramps per material (`study.py image` → palette.json), the light colour, the shadow colour (temperature split) |
| Light | Key direction (clock position), fill colour, rim presence, how light is painted (shafts, glows, haze) |
| Line | Weight in px at the view size, colour, where it appears (actors only? props? none in BG?) |
| Shading | Tones per form, terminator softness, gradients, texture or brushwork |
| Shapes | Rounded/angular, chunky/thin, proportions (head:body for characters) |
| Detail hierarchy | Where detail concentrates; where the rest areas are |
| Atmosphere | Fog and haze colour per depth; particles present |
| Motion (video) | fps per element class (on twos/threes?), holds, squash amount, loop lengths |
| UI | Placement, frames, font feel |

Then write the **style bible** (`art.md` §2): short, measured from the table above, sent verbatim on every generation call (`gen.py` prepends it), and stating the light and the projection the same way every time.

## 4. Decompose → `study/PLAN.md`

This is the production plan. Everything later is checked against it.

1. **Layer plan** (depth order, parallax factor, grade/haze/lod per layer). The bands and their count come from the reference; parallax falls with distance, the play plane is 1.0 and foreground framing is above 1. Measure factors from a video reference; for a still, choose them so depth reads without swimming. A side-view plan might look like:

   ```
   sky → far band → fog → mid band → fog → near band → [water] → play plane (1.0) → fg framing (>1) → HUD
   ```

   Top-down stacks differ (ground materials, decals, y-sorted props and actors, overhangs, weather; `genres.md`).
2. **Asset inventory**: one row per asset, in generation order: whatever another asset uses as a reference comes before it (backgrounds and terrain set the look, the hero anchor precedes its parts):

   | name | class (`art.md` §6) | view | canvas/alpha | refs (style + anchor) | sheet? | used by (code) | status |
   |---|---|---|---|---|---|---|---|

3. **Effects list.** What should move or glow, and which recipe covers it (`effects.md`): water, falls, fog bands, rays, particles, wind consumers.
4. **Interaction inventory.** Every object the player can touch or come near, and how it answers (`gamefeel.md` §3): plants part, hanging things swing, platforms sag, critters flee, lamps sway, pads bounce, enemies can be stomped. Pick what this world has. If you're unsure which reactions the user wants, offer them as options.
5. **Level as data.** Walk lines, a tile grid, a board or hotspots; goals and pickups where the play leads; an attract route. Never paint a level as one image and reverse-engineer it.
6. **Beats for the attract demo.** A short looping route that shows the best interactions and returns to the start (checked headless by `live/tune.cjs`).
7. **Match layout → `study/MATCH.md`** (fidelity is the default bar, `SKILL.md` principle 8). Decompose the reference into a stageable layout, in reference px with a box per element: the camera (view centre, scale: px per character height), every set piece, prop, light (centre, radius, colour), actor (type, facing, pose, state), decal cluster, effect in flight (explosion, beam, tracers, flying bodies) and HUD element (box, font feel, colour, value shown). Build the level so that this composition **is** its first screen (world = camera origin + ref px × view/ref scale), and add a `['match', state]` entry to `SCENE.QA().states` that stages the moment (HUD values, actors, effects at the right age). `qa.mjs` then renders `frames/qa/match.png` for the fidelity critic (`critics.md` §5a).

## 5. Video references

```bash
python3 <skill>/scripts/study.py video ref.mp4 --out study/     # contact sheets, keyframes, motion/rate maps, loops, boil
python3 <skill>/scripts/study.py track ref.mp4 --region x0,y0,x1,y1 --out study/track_hero/   # every unique drawing of a region
```

- Split viewing across parallel subagents: each summarises a time range or a subject, with timings and measured numbers. The lead keeps decisions, not images.
- Write `study/BREAKDOWN.md`: beats with times; who does what; camera moves; interactions seen; effects and their timing; fps per element.

## 6. Templates

**`study/STYLE.md`**
```
# Style passport — <name>
View: <WxH>, <projection>; pixel size <n or smooth>
Game family: <...>      Style family: <...>
Value planes (L*): fg <..>, play <..>, near <..>, mid <..>, far <..>
Light: key <clock, colour>, fill <colour>, rim <yes/no>, painted light <shafts/glows/haze>
Palette: <ramps per material with hex>, light temp <warm/cool>, shadow temp <..>
Line: <px> <colour> on <actors/props/none>
Shading: <tones>, terminator <soft/hard>, texture <..>
Shapes & proportions: <..>
Detail: focal <..>, rest areas <..>
Atmosphere: fog colours per depth <..>, particles <..>
Motion: <fps, holds, squash> (video only)
UI: <..>
Crops: study/crops/<list>
```

**`study/PLAN.md`**: sections 4.1–4.6 above as tables and lists.

**`study/GENERATOR.md`**: the chosen generator, its researched capabilities and the probe results (`generators.md`).
