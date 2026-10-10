---
name: ref2game
description: "Turn a reference (a screenshot, gameplay video, key art, concept art or mood image) into a live, playable 2D game slice that looks shipped, not like AI slop, and feels alive. Any 2D genre (platformer, top-down, isometric, shmup, puzzle, card/UI, runner…) and any style (pixel, painterly, cel/ink, flat vector, hand-drawn, watercolour, neon…). Art is AI-generated with the session's built-in image generation capability. Effects, rigs, animation, wind, reactive objects, critters, game feel, camera and HUD are code in a tiny WebGL2 engine with a hot-reloading live preview. Independent critic agents check every asset, module, animation, frame and the play feel. Use this skill whenever the user wants to make a game, level, scene, prototype, vertical slice, playable demo, sprites, characters, backgrounds or an asset pack \"like this\", \"in this style\" or \"from this reference\", or wants to bring concept art to life as a game, even if they never say \"game engine\" or \"asset pack\". Not for 3D games."
---

## OpenAI runtime adaptation

Apply these runtime bindings throughout this packaged skill and its references.
They replace edition-specific tool, scheduling and installation requirements;
preserve the production ladder, quality bars, round budgets and measured QA.

- Resolve `<skill>` to the directory containing this SKILL.md. Run bundled scripts
  through the current environment's file and shell capabilities. Never assume a
  Claude installation path or launch a nested Claude/Codex CLI.
- Ask with the current surface's structured question tool when available;
  otherwise ask briefly in chat. Treat `AskUserQuestion` and slash invocations as
  descriptions of intent, not required API names or executable commands.
- Use available research, image viewing, editing and live preview capabilities.
  Generate raster art with the session's built-in image generation capability.
  If required execution, capture or image generation is unavailable, identify
  the blocker, preserve state and continue only work that does not depend on it.
  Never claim a runnable build, successful capture or passed QA without evidence.
- Delegate only when subagents are supported. Otherwise perform the same rubric
  as labelled self-review; do not represent it as independent criticism.
- Keep project state on disk. Goal APIs, `CronCreate` and `/loop` are optional
  lifecycle mechanisms. Use them only when supported and the user explicitly
  requests persistent or scheduled execution. Merely invoking this skill does
  not authorize scheduling. Without that capability, perform a bounded batch
  in this turn, checkpoint state, and report how to resume. Never promise work
  after the turn ends. Skip unavailable Goal calls, including completion calls.
- For scheduled execution, preserve the agreed budget, stop conditions and
  preflight gates. Do not silently replace an unrelated active task or Goal.
- Install only tooling appropriate to the selected engine and available runtime.
  Claude-specific project instruction files or agent templates are reference
  material on other surfaces, not automatically active agents or instructions.
- Respect user authorization and environment policies. Plugin installation alone
  does not authorize publishing, payment, sign-in or changes to external systems.

# ref2game: reference → alive, playable 2D game slice

You turn a reference into a **live, playable slice** in its style. The user watches it in a browser page that reloads itself while you work. You also deliver the assets and a packed build.

There are two sources of truth:
- `art/gen/*.png`: the generated art;
- `live/*.js`: the code (effects, rigs, simulation, scene).

This folder is self-contained: scripts, engine templates, references and Playwright.

## Codex runtime

- `<skill>` is this skill's directory. Run project scripts from the project root; quote paths that contain spaces.
- **Image generation.** All raster generation and creative edits use the session's built-in `imagegen` tool (`image_gen__imagegen` / `image_gen.imagegen`, per its schema). Never ask the user to pick a generator. There are no providers, plugins, API keys, command or manual backends, and no nested Codex CLI or other image skills. `scripts/gen.py` prepares the tool's arguments (`prepare`), imports the image it returned (`import`) and offers offline alpha and pixel tools; it cannot call the tool from Python (`references/generators.md`).
- **Tools.** Ask with `functions.request_user_input_async` when available, otherwise briefly in chat. Open images with `view_image`, run scripts with `exec_command`, edit files with `apply_patch`, and open the live URL with `open_in_codex` when available.
- **Subagents.** Critics and video-study helpers are subagents: start them with `collaboration.spawn_agent`, continue them with `collaboration.send_message` / `collaboration.followup_task`, and stay within the available concurrency slots. If delegation is unavailable, run the same check yourself and label it self-review.
- **Turn model.** Codex cannot send a message after its turn ends. Progress updates may show the live build at once, but critic results are collected and folded in before the turn's final message. Never promise a later message.
- **Python.** Use an interpreter with Pillow, NumPy and SciPy. `setup.sh` takes `REF2GAME_PYTHON=/absolute/path/to/python3` and never installs packages itself; use the same interpreter for the other scripts. If dependencies are missing, prepare a project-local environment instead of modifying system Python.

## Principles

1. **Ask, don't guess.**
   - If something is the user's call and the reference doesn't settle it, ask with `functions.request_user_input_async` when available (2–3 short options, the recommended one first), otherwise briefly in chat. Keep working on what doesn't depend on the answer.
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
   - Critics are launched by default at the gates, without being asked, **in the background**: they never block the live page, the next step or a progress update; their results are folded in before the turn's final message (the turn model above). Speed is the point of this skill; the automatic check is the blocking one because it takes seconds.
   - Every defect the user reports becomes a check: a QA state, an anchor or a cycle that would have caught it (Phase 4).
   - The bar is "a clip of a shipped indie game", not "works": `critics.md` §0 is the polish checklist.
8. **Fidelity to the reference is the default bar.** Unless the user asks for "inspired by", the game must look nearly identical to the reference, not merely "in its style":
   - the same camera angle and scale, the same layout (the reference's composition is the level's first screen), the same palette, value planes and light pools, the same character and prop designs, density of actors, effects and HUD layout;
   - it is measured, not eyeballed: a `match` state in `SCENE.QA()` restages the reference's composition, and the **fidelity critic** (`critics.md` §5a) compares it with `compare.py` at the same scale, region by region;
   - the fidelity critic runs at both gates and after every visual change batch, in the background; fold its top fixes into the next pass;
   - **don't over-polish on your own.** After a pass that visibly closes the gap, show the result (live URL, the `match` frame next to the reference, axis scores, the top remaining gaps) and ask (principle 1): keep polishing (naming the next 2–3 fixes and roughly how long) or stop here. One fidelity pass per gate is the default; further rounds (up to 5) only when the user says to continue.
9. **Deterministic and data-first.**
   - Render is a function of time and sim state.
   - The level is data.
   - The attract demo is a scripted replay, checked headless.

The references are background knowledge, not rules: the reference and the user decide.

## Step 0: look, then ask once

Look at the reference first (`view_image` for a still). For a video, run `study.py probe` and make one contact sheet. Then ask once (principle 1), grouping everything:
- **What game this becomes and who the player is,** when the picture doesn't make it obvious. Each option says what the player does in this picture.
- **Anything else you can't settle yourself.**

**Never ask about the image generator:** built-in imagegen is fixed (`generators.md` (a)). All art goes through it, with arguments from `gen.py prepare` and back through `gen.py import`. Don't route generation through other image skills or tools.

After the answer:
1. Once the project exists (Phase 1), run `gen.py check`. It checks local inputs only (the style bible and style refs), not the tool.
2. The first production asset doubles as the capability probe (`generators.md` (c)): no throwaway probe and no budget question, since there is no per-image cost.
3. If imagegen is unavailable, report the blocker and keep building on placeholders; don't offer other generators.

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
   - start generating the pieces the first frame needs most (e.g. the backdrop, the main depth bands, terrain, the hero anchor): `gen.py prepare` → imagegen → `gen.py import`, one call per asset, overlapping calls only when the tool supports it. The first one is the capability probe (`generators.md` (c)).
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

1. **Generate** in PLAN order, one imagegen call per distinct asset or part sheet (`references/generators.md` (d)):
   - write the asset prompt in `art/prompts/NAME.txt`; `gen.py prepare NAME art/prompts/NAME.txt [--ref IMG=role] [--size WxH] [--alpha auto|native|none] [--pixel]` writes the call's arguments to `art/requests/NAME.json`;
   - call imagegen with the prepared `prompt`, `referenced_image_paths` and `transparent_background`, and nothing else;
   - inspect the result, then `gen.py import NAME /returned/path [--replace]` (raw copy, alpha validation, log);
   - make independent calls in parallel only when the tool supports it, otherwise back to back; keep coding meanwhile.
   - Prompt scaffold: `references/art.md`.
2. **As each asset lands:**
   - `slice.py`;
   - `prep.py`;
   - put it in the scene (the page reloads);
   - start the asset critic in the background.
   - A change of texture resolution or display size lands **in the same step** as the scene code that sizes it (`SIZES`): the user is watching the live page, and oversized sprites, even briefly, read as broken.
3. **While images generate,** build the effects this reference and style need (`references/effects.md`, `references/styles.md`).
4. **Hero.** Approve the hero anchor in a real rig pose (feet under the hips, free limbs), then make its part sheet and variants (`variantfix.py`). Do the same for every actor in the animation list (`animation.md` §13), NPCs and animals included.
5. **Gate A.** `qa.mjs` passes (seconds). Launch the asset + frame + fidelity critics in the background (the fidelity critic on `frames/qa/match.png`) and send the live page and a few stills right away in a progress update; keep working, and fold the critics' top fixes into the next iteration when they land.

## Phase 3: make it alive

1. **Rig every actor in the animation list** (`animation.md` §12–13): walkers plant their feet, attacks aim at the target, NPCs play work loops and routines, animals move their heads and tails. Every rig reports its joints (`L.joint`), and `SCENE.QA()` stages its cycles, loops, attacks all round and transitions. `qa.mjs` rig checks must pass (`animation.md` §14); then the cycle sheets and the motion critic.
2. **Feel.** Player feel, camera, a world that reacts, juice per event (`references/gamefeel.md`). Choose what this world has; skip what it doesn't.
3. **Attract demo.** Tune it headless: `node live/tune.cjs`.
4. **Module critic** per finished module.
5. **Gate B.**
   - `qa.mjs` passes; launch the frame, fidelity, motion and game critics in the background and run the interaction audit meanwhile. Show the live build in a progress update at once; collect the critic results and fold them in before the turn's final message (Codex cannot message after its turn ends; never promise a later message).
   - Send the hand-back (`references/delivery.md`): the URL, what to try, what changed, known gaps.

## Phase 4: feedback loop

For each note:
1. Fix it in code, or regenerate.
2. Verify with sheets, crops and `livecheck.mjs`.
3. Send a short report with what to try, and ask whether to keep polishing or stop when the remaining gaps are minor.

- **Motion:** look frame by frame before answering.
- **Things stills don't show:** reproduce them with `livecheck.mjs --keys … --shots …`.
- **Unclear note:** ask.
- **Close the class, not just the instance.** After fixing a reported defect, add the check that would have caught it (a `SCENE.QA()` state with the worst-case string, an `L.anchor` for the emitter, a cycle for the gait), run `qa.mjs`, and look for the same defect elsewhere (every panel, every emitter, every walker). Add it to `references/pitfalls.md` when it is new, as a general rule (the class of defect and its fix), never as this project's specifics. If the sandbox can't write to the skill folder, record the general rule in the project's `study/PITFALLS.md` and mention it in the hand-back.

## Phase 5: deliver

`pack.py --name <name> --zip` builds the static playable build, textures, manifest, sources and README. Make a video only when asked.

## Speed

- **Parallelise:**
  - generation (parallel imagegen calls when the tool supports them, otherwise back to back with no idle gaps);
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
| `generators.md` | The built-in imagegen workflow (prepare → call → inspect → import); the first asset as the probe; prompting and consistency; transparency; pixel art |
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
| `gen.py check / prepare / import / validate / key / pixel` | Prepare built-in imagegen arguments (style bible and role-labelled refs on every call), import the returned image (raw copy, alpha validation, logs); offline alpha and pixel tools. It never generates |
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
