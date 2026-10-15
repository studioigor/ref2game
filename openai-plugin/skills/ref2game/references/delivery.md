# Delivery

The main deliverable is the **live, playable slice** that the user has been watching. Packaging makes it portable and reusable.

## Pack

```bash
python3 <skill>/scripts/pack.py --name <game-name> --zip
```

This writes `dist/<name>/` (and `dist/<name>.zip` with `--zip`; `--out` changes `dist`; it never edits the project):

| Path | Contents |
|---|---|
| `game/` | Static playable build: no hot-reload polling, no dev overlay; textures limited to the manifest (plus any packed atlas the page loads) |
| `assets/textures/` | Engine-ready PNGs |
| `assets/manifest.json` | Sizes, crops, walk lines |
| `assets/source/` | Full-resolution generated sources |
| `README.md` | Contents, controls (`SIM.HINT`), view size (`SIM.VIEW`), how to run |
| `STYLE.md`, `PLAN.md`, `style_bible.txt` | Copied, so the set can be extended in the same style later |

**Verify the build:**
1. Serve `dist/<name>/game/` statically.
2. Run `livecheck.mjs --url http://127.0.0.1:<port>/index.html`. Expect 0 errors and a running play state.

## Optional outputs (only when asked)

- **Video.**
  ```bash
  node <skill>/scripts/render.mjs video --to <seconds> --fps <fps> --jobs <n> --out frames/<name>.mp4
  ```
  (Defaults: `--from 0 --to 12 --fps 30 --jobs 4`.) Cover the attract loop in full, so the clip shows the key interactions; add a play-mode capture if needed.
- **Rig data for another engine.** Export from scene.js constants to `assets/rigs.json`: the part names, pivot uv (root, joint, split), layer order, pose tables and cycle formulas. Spine or DragonBones import is a separate task; say so instead of improvising.
- **Engine ports** (Godot, Unity, Phaser, etc.). The art and manifest are engine-agnostic. The effects (`effects.md`) and the sim patterns (`gamefeel.md`) carry over as principles; port them as a follow-up task, module by module, with the live page as the visual reference.

## Hand-back message (short; critic scores only at Gate B and final delivery)

1. The live URL. It is already open, and it reloads by itself.
2. **What to try:** keys, where to go, and what should react ("run through the tall grass left of the ledge: it parts and springs back; jump on the pad: …").
3. What changed in this iteration, in a few bullets.
4. The `qa.mjs` result, the latest critic scores (asset, frame and fidelity at Gate A; frame, fidelity, motion and game at Gate B and final), and the known differences. Never hand back a build whose qa fails without saying so.
5. Next steps you would take, ranked.
