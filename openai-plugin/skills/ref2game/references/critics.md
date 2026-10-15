# Critics: independent agents check every stage, fast

An author judging their own work misses what the user sees at once. Weak parts then surface in the assembled frame, or worse, the user finds them first. So every piece gets an **independent critic subagent** before it is used. Critics run **in parallel with production** and never block the live preview.

**Codex runtime.** Critics are subagents started with `collaboration.spawn_agent`, within the available concurrency slots; continue them with `collaboration.send_message` (running) or `collaboration.followup_task` (idle). If delegation is unavailable, the lead runs the same checks itself and labels the report self-review. Codex can't send a message after its turn ends: progress updates may show the live build at once, but critic results are collected and folded in before the turn's final message; never promise a later message.

## Contents
0. Automatic checks first, critics always, and the polish checklist
1. Rules for every critic
2. Asset critic (each generated asset or sheet)
3. Module critic (a finished system: hero rig, backdrop, water, critters…)
4. Motion critic (animation cycles and transitions)
5. Frame critic (the assembled look vs the reference)
5a. Fidelity critic (near-identical to the reference, measured)
6. Game critic (does it play and feel alive?)
7. Measurements critics use
8. Brief template
9. Keeping it fast

---

## 0. Automatic checks first, critics always, and the polish checklist

- **`qa.mjs` before any critic and before any hand-back** (cheap, objective; `engine.md` §7 QA hooks). A failing qa is fixed first; critics never spend a round on what a script can find.
- **Critics are not on request, and never in the way.** Gate A: asset, frame and fidelity critics. Rigs: motion critic. Gate B and final: frame, fidelity, motion and game critics. Launch them in the background as soon as the thing exists and keep working; don't wait for them to show the user progress (§9). Their fixes go into the next iteration; their scores go into the hand-back, collected before the turn's final message. One critic per gate and subject, a batch per call, max 3 rounds (the fidelity critic's rounds follow §5a).
- **The polish checklist** (the "shipped game, not AI slop" bar). Every frame and game critic goes through all of it and reports each item as pass/fail with a crop:
  1. **One rendering family.** The pipeline matches the reference's (true low-res vs HD pixel vs painterly…, `styles.md`): type, light falloff and sprite edges measured on same-scale crops. Nothing blockier or blurrier than the reference.
  2. **One texel density.** Every sprite shows art pixels (or brush/line weights) at the same size on screen; no sprite scaled by a different factor than its neighbours (mixels).
  3. **One outline weight and one light direction** across sprites, props, rigs and code-drawn pieces (code-drawn limbs, wires and particles get the same ink treatment as the art).
  4. **HUD like a shipped game:** consistent margins and a grid, panels sized to their content, text never touching or leaving its panel at worst-case strings, one type family in a small consistent set of sizes, legible at the smallest window the game supports, and text contrast on its backing that meets accessibility guidance (WCAG).
  5. **Every emitted effect starts at what emits it** (the held item's tip, the hand, the contact point) in every pose and facing and across each facing's range of aim angles. Every layer of it (haze, light-map contribution, glow, the item itself) is hidden by whatever stands between it and the camera, and the emitter is not lit by its own light.
  6. **Characters articulate:** legs plant and alternate, arms swing, far limbs behind and darker, no sliding or bobbing-only sprites, rest pose = approved drawing.
  7. **Grounding and sorting:** contact shadows under everything standing, correct depth sort and occlusion at every overlap, nothing floating.
  8. **No generator artifacts:** garbled glyphs or logos, smudged details, inconsistent designs between views or states, halos, cut edges, repeated tiles visible at play zoom.
  9. **No placeholder tells:** debug overlays, default fonts, unstyled rectangles, programmer-coloured shapes, untranslated strings, mixed languages.
  10. **States read at a glance:** every tool, hazard and resource has a visible state and a reaction (`gamefeel.md` §7).
  11. **No primitive-shape effects:** cracks, slashes, beams, shockwaves, debris and magic made of straight bars, plain rectangles, uniform lines or flat rings read as programmer art. Effects are shaped, layered, and change over their life. Judge each one on an age strip (frames sampled across its life), magnified.

---

## 1. Rules for every critic

- **Independence.** A fresh subagent (`collaboration.spawn_agent`), never the author and never the lead's own eye; only when delegation is unavailable does the lead run it, labelled self-review. It does not edit project code. It writes `study/critique/<subject>_rN.md` and replies with a short summary.
- **Same scale.** It builds its own side-by-sides: the reference crop scaled to our render scale next to our crop, both magnified. It judges those, never downscaled wholes (`compare.py side|grid|report`, `sheet.py`).
- **It measures, doesn't guess.** Colours sampled at matching points, value and chroma percentiles per region, line widths, proportions, timing in frames (§7).
- **Blunt brief.** "What makes this read as cheap, generated or a static picture instead of the reference/a shipped game, and exactly how do we close the gap in code or in the prompt?"
- **Output, in this order:**
  1. scores 1–10 per axis, each with a one-line reason;
  2. the **top fixes ranked by impact** (a short list, not a laundry list), each with WHAT (crop coordinates, file and function), WHY (a measured number vs the reference) and the concrete CHANGE (the code change, or a regenerate/edit prompt);
  3. the rules broken (`art.md`, `animation.md`, `gamefeel.md`);
  4. minor issues.
- **Applying fixes.** The author applies them (continue the same author agent with `collaboration.send_message` or `collaboration.followup_task` so it keeps context; when the lead is the author, the lead applies them). Re-render the same crops; the critic runs round N+1 on the new renders.
- **Bounded rounds.** At most 3 per subject. Stop early when nothing is above "minor". Leftovers become "known differences" in the hand-back.

## 2. Asset critic (each generated asset or sheet, while it is already in the live page)

**Inputs:**
- the asset on mid-grey **and** composited on its real background;
- a 100% crop;
- the reference crop for that class;
- the style bible;
- `art.md` §9 (the checklist).

**Judges:**
- style match (medium, line, palette, shading);
- the light side;
- alpha quality (fringe, specks);
- view and scale;
- part completeness (for rigs);
- hallucinated detail;
- silhouette at play size.

**Verdict:** ACCEPT / FIX IN POST (what) / REGENERATE (the prompt change).

It's fast: one critic can review a batch of assets on one contact sheet (`sheet.py --bg gray --label`) and zoom only into the doubtful ones.

## 3. Module critic (one finished system at a time)

A module is anything with its own code and art: the backdrop stack, the terrain/platform kit, the hero rig, each enemy, critters, water/falls, props, HUD, foreground. Run it as soon as the module works in the live page, in parallel with other modules still being built. It gates approval, not display: the module stays in the live page while the critic runs.

| Module | Judge |
|---|---|
| Backdrop | Value band per layer vs the reference; haze order; shape language per depth; light direction and haze colour; seams at wraps; edges exposed at camera extremes |
| Terrain / platforms | Silhouette; the lit walk lip clearly separated in value from the underside; repetition at play zoom; seams; caps; contact shadows; walk line = drawn top |
| Characters | Proportions vs the reference; line weight; tones and terminator; palette at matching points; face appeal; layering of limbs (§4) |
| Props / FX | Silhouette; glow look (halo shape, hot core keeps chroma); state readability; grounding |
| Water / falls / fog | Matches the reference's stylisation (not a "shader demo" pasted on a painting); flow direction; edges; base foam; values vs the reference |
| Foreground / HUD | Framing vs the reference, darkness and defocus, corners covered at all camera positions, HUD legibility over busy art |

## 4. Motion critic (animation)

**Inputs:**
- the `qa.mjs` rig-check report (`frames/qa/report.json` → `rig`): measured foot slide, ground, lift, limp, stride, knee, stretch, stance, arm phase, aim, pops, coverage (`animation.md` §14);
- cycle sheets (the ones `qa.mjs` writes, or `sheet.py`), magnified, for **every** actor in the animation list: the player, enemies, every NPC loop and routine walk, every animal loop;
- transition sheets (idle → run → jump → land, walk → stop, interrupted attacks, deaths);
- attack sheets against targets all round;
- slowed-down video or stills;
- `animation.md`.

**The bar is a shipped game in this genre.** Score against clips of released games, not against "it moves". Fail on sight:
- any actor animated only by whole-sprite transforms;
- a worker facing away from their station;
- a village or crowd where nobody walks;
- an animal that only sways.

**Judges, frame by frame:**
- limb attachment points;
- near/far sides and layering;
- joint continuity;
- foot planting (no sliding);
- arcs;
- spacing (ease in/out);
- holds;
- squash amounts;
- secondary lag (cape, hair) vs leading;
- loop seams;
- pops between states;
- whether gaits sweep the right way (stance backward).

It must cite frame indices, re-measure anything the numbers disagree with, and name a new automatic check for every defect the numbers missed (it goes into `qa.mjs` / `animation.md` §14).

## 5. Frame critic (the assembled look)

Run after the module critics pass, on the assembled live frame at the key beats.

**Inputs:**
- `compare.py report ref.png ours.png --out study/critique/frame_rN/`;
- the same-scale whole-frame and region side-by-sides;
- `study/STYLE.md`.

**It judges only what modules can't show alone:**
- the three value planes and the squint test;
- one light everywhere (direction and temperature);
- relative scale between actors, props and platforms;
- depth and haze ordering;
- focal hierarchy and composition;
- covers between layers (glows over occluders);
- HUD integration.

Its fixes name the module and the change.

## 5a. Fidelity critic (near-identical to the reference, measured)

The default bar (`SKILL.md` principle 8): a viewer who glances from the reference to our `match` frame should see the same picture. The frame critic asks "does it read like a shipped game"; this one asks "where, exactly, does it differ from THE reference", and measures every answer.

**Inputs:**
- `frames/qa/match.png` (the `match` state of `SCENE.QA()`: the reference's composition restaged from `study/MATCH.md`, same camera, scale and HUD values) and, when the reference is a video, matching beats;
- `compare.py report ref.png frames/qa/match.png --out study/critique/fidelity_rN/` (whole-frame side, lowfreq brightness map, palette coverage, ranked mismatch regions);
- `compare.py side` crops, magnified, for **every subject class** the reference shows: the hero, each enemy type, each prop family, ground materials, set pieces, light pools, lights and effects the player emits, pickups, decals, every HUD element, world text;
- `study/MATCH.md`, `study/STYLE.md`, the style bible.

**It measures, per subject and for the whole frame (each with the reference's number next to ours):**

| Axis | Measurement | Bar |
|---|---|---|
| Camera and scale | Character height, prop sizes, tile/line spacing in px at the same scale | no scale difference a glance catches |
| Layout | Position of every MATCH.md element (centre, in % of frame) | every element where the reference has it |
| Values | `lowfreq` brightness ratio per cell; value percentiles of the frame and of each light pool vs its surroundings | same value structure, cell by cell |
| Palette | Share of our pixels near the reference palette; hue/chroma of named colours (shadows, light colour, skin, signature materials, HUD) | the reference's palette, named colours indistinguishable side by side |
| Light | Pool count, radius, falloff, colour; beam shape and length; what is lit vs in shadow | same structure and sizes |
| Line and rendering | Outline width and colour, shading tones, texture/grime density on same-scale crops | same widths and tone count |
| Designs | Each character/prop vs its reference crop: silhouette, proportions, costume, colours, facing | "same character" at a glance |
| Density and life | Number of actors, decals, litter, effects in the frame | same density |
| HUD | Element positions, sizes, fonts (family feel, weight), colours, bar styles, text | same positions and structure |
| Text and FX | World text style (extrusion, colour, angle), explosion/flash shapes and colours | same look |

The critic states the tolerance it judged each axis against and reports every gap as a measured number, ours vs the reference.

**Output:** scores 1–10 per axis (10 = indistinguishable at a glance), then the **top fixes ranked by visible gap**, each with the measured gap (ours vs reference), WHERE (file/function or asset), and the concrete change (the code change, or a regenerate/edit prompt with the reference crop attached). Also list what cannot be matched with the current approach and what would close it (new asset, new effect).

**Rounds:** one per gate by default. After applying a round's fixes, show the user the result (match frame beside the reference, scores, remaining gaps as numbers) and ask whether to keep polishing or stop; further rounds (up to 5, an exception to §1's 3) only on the user's go-ahead. Stop early when no axis has a gap a viewer would notice at a glance. Run it in the background; never block the live page on it.

**Pitfalls it exists to catch:** a "same style" frame with a different camera height or zoom; a lit-up scene where the reference is low-key (or the reverse); light pools of a different size or colour; generic generated designs instead of the reference's characters; a HUD rebuilt from memory instead of measured; layout drift (an element on the wrong side of the frame).

## 6. Game critic (does it play and feel alive?)

The critic that answers the user's real question.

**Inputs:**
- `livecheck.mjs` runs with key scripts it designs: walk into every object, jump on everything, idle long enough to see loops repeat, wait for the world's shared causes (a gust…);
- `livecheck.mjs` screenshots and `render.mjs stills` of the attract loop;
- `gamefeel.md`.

**Scores (1–10):**
- **Readability:** play plane vs background, walk lines, roles.
- **Game-feel:** verbs, juice layers, responsiveness.
- **Aliveness:** reactions, shared causes, no visible loops.
- **Depth:** camera travel, parallax, planes.
- **Lighting:** consistency, moving lights.
- **Style consistency.**
- **Motion.**
- **Overall:** "does it pass as a screenshot or clip of a real game?"

It runs the interaction audit (`gamefeel.md` §7) and lists every object that does nothing when touched.

## 7. Measurements critics use

What to measure; the critic picks the method and states it in the report.

- **Value and chroma percentiles per region** (dark, mid and bright ends), ours vs ref: value and chroma bands per plane.
- **Squint:** grayscale, blurred until detail drops out, quantized into a few value bands. Do actors and walk lines separate from what's behind them?
- **Detail maps.** Fine detail (high frequency) and texture clumps (mid frequency), e.g. from differences of blurs. Detail should peak on actors and focal props, not on the background.
- **Walk-line contrast:** the lip's value vs the area just above it and vs the underside.
- **Lit-side check per sprite:** mean value of the rim band facing the light vs the opposite rim.
- **Alpha fringe:** count of edge pixels whose colour deviates from both their neighbours inside and the background (halo).
- **Motion energy:** a frame-difference map over a loop. Where does the screen move? Dead zones are "postcard" areas.
- **Timing:** event times from `tune.cjs`; frame counts of holds and anticipation.
- **Tools:**
  - `compare.py report|side|grid|lowfreq|tones|palette`;
  - `study.py crop`;
  - `sheet.py`;
  - small numpy snippets: critics may write measurement scripts in `study/critique/measure/`.

## 8. Brief template (spawn with `collaboration.spawn_agent`, run in background)

```
You are an independent <asset|module|motion|frame|fidelity|game> critic for a 2D game made from a reference.
Do NOT edit project code. Write study/critique/<subject>_r<N>.md and reply with a short summary.
Inputs: reference <ref.png + crops>, our renders <paths>, style bible <path>, rules <skill>/references/<files>.
Build same-scale, magnified side-by-sides (compare.py side/grid), measure (value/chroma percentiles, line width,
proportions, timings), and answer bluntly: what makes this read as <cheap/generated/a static picture> instead of
<the reference / a shipped game>, and how exactly do we close the gap?
Output: scores per axis (1–10 + one-line reason); the top fixes ranked by impact, each WHAT (coords/file:function),
WHY (measured number vs reference), CHANGE (the code change, or the regenerate/edit prompt); rules broken; minor issues.
Round <N> of max <3, or the fidelity limit in critics.md §5a>. Previous report: <path or none>.
```

## 9. Keeping it fast

- **Critics run in the background while production continues.** The lead keeps generating and wiring the next module; fixes land between iterations.
- **Batch assets** into one sheet per critic call. Use one module critic per module, not per file.
- **Don't wait for a critic to show the user progress.** The live page always shows the current state. Critics gate *assembly* and *hand-back*, not iteration.
- **3 rounds maximum** (fidelity: §5a). Report leftovers instead of looping.
- **Self-check first** (cheap): sheets, crops, `livecheck`. Then the critic (expensive).
- **Big gates go to the user:** the first frame, the "alive" pass, final. Critic scores are included in the hand-back: progress updates show the live build without waiting, and the critic results are folded in before the turn's final message (Codex can't message after its turn ends).
