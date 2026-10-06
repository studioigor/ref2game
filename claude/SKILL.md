---
name: ref2game
description: Turn a reference (a screenshot, gameplay video, key art, concept art or mood image) into a live, playable 2D game slice that looks shipped, not like AI slop, and feels alive. Any 2D genre (platformer, top-down, isometric, shmup, puzzle, card/UI, runner…) and any style (pixel, painterly, cel/ink, flat vector, hand-drawn, watercolour, neon…). Art is AI-generated with whatever generator the user picks (Codex built-in image_gen, any image API researched and plugged in on the spot, a local tool, or manual drops). Effects, rigs, animation, wind, reactive objects, critters, game feel, camera and HUD are code in a tiny WebGL2 engine with a hot-reloading live preview. Independent critic agents check every asset, module, animation, frame and the play feel. Use this skill whenever the user wants to make a game, level, scene, prototype, vertical slice, playable demo, sprites, characters, backgrounds or an asset pack "like this", "in this style" or "from this reference", or wants to bring concept art to life as a game, even if they never say "game engine" or "asset pack". Not for 3D games.
---

# ref2game: reference → alive, playable 2D game slice

You turn a reference into a **live, playable slice** in its style. The user watches it in a browser page that reloads itself while you work. You also deliver the assets and a packed build.

There are two sources of truth:
- `art/gen/*.png`: the generated art;
- `live/*.js`: the code (effects, rigs, simulation, scene).

This folder is self-contained: scripts, engine templates, references and Playwright.

## Principles

1. **Ask, don't guess.**
   - If something is the user's call and the reference doesn't settle it, ask with `AskUserQuestion`: 2–4 short options, the recommended one first.
   - Typical questions: what game this becomes, who the player is, the scope, a style choice, an ambiguous note.
   - Group questions together. Decide technical matters yourself and state those decisions in your progress message.
2. **Visible progress in minutes.**
   - The page runs on placeholders from minute one.
   - Real art replaces them piece by piece.
   - Never leave the user long without a visible change.
3. **AI paints, code rules.**
   - Generate one piece or depth band per call, always with the reference and the verbatim style bible.
   - Code owns scale, light, haze, outline, alpha, and all motion and effects (`references/art.md`).
4. **Alive means systems, not loops.**
   - Shared forces, springs, things that react, an event bus that drives juice, a camera that travels.
   - Pick what fits this game's world (`references/gamefeel.md`, `references/effects.md`).
5. **Rigs, measured.** The bar is a finished, shipped game.
   - **Every actor gets a cut-out rig with authored poses:** the player, enemies, every NPC and every animal (`references/animation.md`).
   - **NPCs work at their station, facing it; some walk routines. Animals move their neck, ears and tail.**
   - **No action is faked by rotating, scaling or bobbing a whole sprite.**
   - **Every rig reports its joints and passes the measured checks of `qa.mjs` before anyone looks at it:** foot slide, ground, limp, stride, knee, stretch, arm phase, aim at the impact, pops, rigid-only motion, coverage (`animation.md` §14). Frame-by-frame cycle sheets and the motion critic then judge the rest.
6. **Independent critics.**
   - They run in the background on assets, modules, motion, frames and feel.
   - At most 3 rounds each.
   - They gate approval, never what is shown in the live page (`references/critics.md`).
7. **The user is never the first to find a defect a check could find.**
   - `qa.mjs` (automatic) runs after every change to the HUD, a rig, an emitter or the render pipeline, and before anything is shown as done: HUD text inside its panel at worst-case strings, emitted effects drawn where the sim emits them, walk cycles that really move the limbs, time-driven effects that really move and don't sweep when a state changes.
   - Critics are launched by default at the gates, without being asked, **in the background**: they never block the live page, the next step or a hand-back. Speed is the point of this skill; the automatic check is the blocking one because it takes seconds.
   - Every defect the user reports becomes a check: a QA state, an anchor or a cycle that would have caught it (Phase 4).
   - The bar is "a clip of a shipped indie game", not "works": `critics.md` §0 is the polish checklist.
8. **Fidelity to the reference is the default bar.** Unless the user asks for "inspired by", the game must look nearly identical to the reference, not merely "in its style":
   - the same camera angle and scale, the same layout (the reference's composition is the level's first screen), the same palette, value planes and light pools, the same character and prop designs, density of actors, effects and HUD layout;
   - it is measured, not eyeballed: a `match` state in `SCENE.QA()` restages the reference's composition, and the **fidelity critic** (`critics.md` §5a) compares it with `compare.py` at the same scale, region by region;
   - the fidelity critic runs at both gates and after every visual change batch, in the background; fold its top fixes into the next pass;
   - **don't over-polish on your own.** After a pass that visibly closes the gap, show the result (live URL, the `match` frame next to the reference, axis scores, the top remaining gaps) and ask with `AskUserQuestion`: keep polishing (naming the next 2–3 fixes and roughly how long) or stop here. One fidelity pass per gate is the default; further rounds (up to 5) only when the user says to continue.
9. **Deterministic and data-first.**
   - Render is a function of time and sim state.
   - The level is data.
   - The attract demo is a scripted replay, checked headless.

The references are background knowledge, not rules: the reference and the user decide.

## Step 0: look, then ask once

Look at the reference first. For a video, run `study.py probe` and make one contact sheet. Then make one `AskUserQuestion` call:
- **Image generator** (always ask):
  - Codex built-in image_gen (the default when `codex` is on PATH);
  - an image API the user names (you research it and plug it in);
  - a local tool via a command template;
  - manual (you write the prompts and the user drops the images in).
- **What game this becomes and who the player is,** when the picture doesn't make it obvious. Each option says what the player does in this picture.
- **Anything else you can't settle yourself.**

All art goes through `gen.py`, which drives Codex too. Don't route generation through other image skills.

After the answer:
1. Run `gen.py check`.
2. For an API, follow `references/generators.md`:
   - research the docs into `study/GENERATOR.md`;
   - write a plugin from `provider_template.py`;
   - `--dry-run` it;
   - **ask once for a budget**;
   - run the capability probe (`generators.md` (c)).
3. Otherwise make one probe generation.

## Phase 1: setup and study

```bash
bash <skill>/scripts/setup.sh <project> --ref <reference> --genre side|top|blank
cd <project> && bash <skill>/scripts/serve.sh      # run in background; prints the LIVE: URL
```

The base is only a starting point:
- `side`: side view;
- `top`: top-down or 3/4;
- `blank`: an empty stage with pointer and keyboard input, for anything else.

Send the live URL right away.

1. **Quick study (about 5 min)** (`references/study.md`):
   - run `study.py probe` and `study.py image`;
   - write `art/style_bible.txt` (`references/styles.md`);
   - start the first batch in the background: the pieces the first frame needs most (e.g. the backdrop, the main depth bands, terrain, the hero anchor).
2. **While it runs, finish the study** (including `study/MATCH.md`: the reference decomposed into a stageable layout, `study.md` §4.7):
   - `study/STYLE.md`;
   - `study/PLAN.md`: layers, assets in generation order, effects, interactions, level data, attract beats.
3. **Shape the base into this game on placeholders:**
   - the mover or interaction model;
   - collision;
   - sort order;
   - camera;
   - level;
   - attract script.

   `references/genres.md` has notes per family. Keep the engine and the sim/scene contracts (`references/engine.md`).

## Phase 2: first real frame

1. **Generate** in parallel batches in PLAN order: `gen.py batch jobs.json [--jobs N]`, run in the background.
   - A job is `{"name", "prompt", "size", "alpha"}`.
   - `prompt` is a file in `art/prompts/` or inline text.
   - Prompt scaffold: `references/art.md`.
2. **As each batch lands:**
   - `slice.py`;
   - `prep.py`;
   - put it in the scene (the page reloads);
   - start the asset critic in the background.
   - A change of texture resolution or display size lands **in the same step** as the scene code that sizes it (`SIZES`): the user is watching the live page, and oversized sprites, even briefly, read as broken.
3. **While images generate,** build the effects this reference and style need (`references/effects.md`, `references/styles.md`).
4. **Hero.** Approve the hero anchor in a real rig pose (feet under the hips, free limbs), then make its part sheet and variants (`variantfix.py`). Do the same for every actor in the animation list (`animation.md` §13), NPCs and animals included.
5. **Gate A.** `qa.mjs` passes (seconds). Launch the asset + frame + fidelity critics in the background (the fidelity critic on `frames/qa/match.png`) and send the live page and a few stills right away; keep working, and fold the critics' top fixes into the next iteration when they land.

## Phase 3: make it alive

1. **Rig every actor in the animation list** (`animation.md` §12–13): walkers plant their feet, attacks aim at the target, NPCs play work loops and routines, animals move their heads and tails. Every rig reports its joints (`L.joint`), and `SCENE.QA()` stages its cycles, loops, attacks all round and transitions. `qa.mjs` rig checks must pass (`animation.md` §14); then the cycle sheets and the motion critic.
2. **Feel.** Player feel, camera, a world that reacts, juice per event (`references/gamefeel.md`). Choose what this world has; skip what it doesn't.
3. **Attract demo.** Tune it headless: `node live/tune.cjs`.
4. **Module critic** per finished module.
5. **Gate B.**
   - `qa.mjs` passes; launch the frame, fidelity, motion and game critics in the background and run the interaction audit meanwhile. Hand back without waiting; the scores follow in the next message.
   - Send the hand-back (`references/delivery.md`): the URL, what to try, what changed, known gaps.

## Phase 4: feedback loop

For each note:
1. Fix it in code, or regenerate.
2. Verify with sheets, crops and `livecheck.mjs`.
3. Send a short report with what to try, and ask whether to keep polishing or stop when the remaining gaps are minor.

- **Motion:** look frame by frame before answering.
- **Things stills don't show:** reproduce them with `livecheck.mjs --keys … --shots …`.
- **Unclear note:** ask.
- **Close the class, not just the instance.** After fixing a reported defect, add the check that would have caught it (a `SCENE.QA()` state with the worst-case string, an `L.anchor` for the emitter, a cycle for the gait), run `qa.mjs`, and look for the same defect elsewhere (every panel, every emitter, every walker). Add it to `references/pitfalls.md` when it is new, as a general rule (the class of defect and its fix), never as this project's specifics.

## Phase 5: deliver

`pack.py --name <name> --zip` builds the static playable build, textures, manifest, sources and README. Make a video only when asked.

## Speed

- **Parallelise:**
  - generation;
  - critics;
  - code work while images generate;
  - study subagents for videos.
- **Check with stills, crops and sheets,** not full videos.
- **At most 3 critic rounds;** report what's left.
- **Fix sources, not derived files.**
  - After a sim change, run `tune.cjs`.
  - After a scene or lib change, run `livecheck.mjs`.
- **Pitfalls:** skim `references/pitfalls.md` once per project.

## References

| File | What's in it |
|---|---|
| `generators.md` | Researching and plugging in any generator; alpha strategies; consistency |
| `study.md` | Probing and measuring the reference; STYLE.md, the style bible, PLAN.md |
| `genres.md` | Notes per game family: camera, layers, sim, interactions, tiles, directional characters |
| `styles.md` | Notes per style family: prompt vocabulary, post chain, engine settings, motion and effects |
| `art.md` | What to generate vs code, prompt scaffold, slop fixes, asset classes, slicing, acceptance |
| `engine.md` | Files, live loop, gl.js/lib.js API, sim and scene contracts, asset names, tools |
| `effects.md` | Atmosphere, water, wind, particles, light, post, ambient life |
| `animation.md` | Parts, two-bone limbs, layering, poses, cycles, secondary motion, frame checks |
| `gamefeel.md` | Player feel, camera, reactive world, juice, level design, interaction audit |
| `critics.md` | Critic types (incl. the fidelity critic), briefs, rounds |
| `pitfalls.md` | Bugs that cost hours before |
| `delivery.md` | Hand-back messages and packing |

## Scripts (run from the project root; `<skill>` = this folder)

| Script | Does |
|---|---|
| `setup.sh <dir> --ref <file> [--genre side\|top\|blank]` | Dependencies, project skeleton, base template, placeholder art |
| `serve.sh` | Live preview server |
| `gen.py check / one / batch / key / validate / pixel` | Generation with any provider (style bible and refs on every call, alpha, logs, parallel batches); offline alpha and pixel tools |
| `provider_template.py` | Skeleton for a new API plugin (`art/providers/<name>.py`) |
| `slice.py`, `prep.py`, `variantfix.py` | Cut sheets; turn art/gen into live/assets; make variants differ only where they changed |
| `placeholders.py` | Stand-in art for the base's asset names |
| `sheet.py` | Contact and cycle sheets |
| `rigcut.py`, `partrig.py` | Cut-out rig from the approved drawing / from a part sheet (body, one leg, one arm, weapon) → parts + `live/rigs.js` |
| `jointr.py` | Limb half-widths at elbows and knees → round joint caps (`animation.md` §15.5) |
| `softbones.py` | Weight maps for bending one painted sprite (an animal's neck, head, tail) in the shader (`animation.md` §15.6) |
| `render.mjs stills / video` | Deterministic renders of the live page |
| `livecheck.mjs` | Headless play-test: keys, pointer (click, hold, release, wheel), screenshots, errors, fps, hot reload |
| `qa.mjs` | Automatic polish checks from `SCENE.QA()`: HUD text overflow/overlap, emitter anchors, limb motion of walk cycles (+ cycle sheets), rig checks, frozen effects and sweeps (`anim`), and the measured rig checks from the joint trace (foot slide, ground, lift, limp, stride, knee, stretch, arm phase, rigid-only motion, aim at the impact, pops, coverage) |
| `pack.py` | Static playable build and asset pack |
| `study.py`, `compare.py` | Reference analysis; reference vs render |
