# Genre notes for 2D game slices

Background notes per game family: camera, layers, sim, interactions, what makes each family feel alive. Once you know the family (from the picture, or from the user's answer when the picture doesn't settle it), read its block. §14 covers tiles and §15 directional characters. These blocks are a menu of concerns, not recipes: the reference and the play feel decide the values.

- Linked games illustrate how one shipped title solved a problem. Read the source for its numbers; don't copy them as targets.
- Frame counts cited from shipped games are at 60 Hz. The sim runs at 120 Hz (`DT = 1/120`), so convert frame counts to seconds; never count sim ticks.
- **Starting bases** (`setup.sh --genre`):
  - `side`: walk lines, parallax bands, grass, wind, a rig;
  - `top`: an 8-direction mover with dash, circle colliders, y-sorting, fading canopies, cloud shadows, fleeing critters;
  - `blank`: an empty stage with pointer and keyboard input, hover/press springs on hotspots, a scripted attract cursor.

  Keep the engine and the sim/scene contracts (`engine.md`), and rebuild the rest for the family on placeholders.

## 0. Shared spine (every family)

| Concern | Rule |
|---|---|
| Sort key | Sort by whatever encodes depth in the projection. Side view: layer, then z. Top-down / 3/4: layer, then the foot (ground-contact) Y. Isometric: layer, then `gx+gy` and height, or a topological sort for multi-tile boxes. Depth lane: layer, then ground Y. Always break ties on a stable id, or the attract replay flickers. |
| Pivot | The pivot is the ground-contact point, not the sprite centre. Tall props and tiles need a sort origin at their base. |
| Hit-stop | Scale it with the weight of the hit, and always add it on killing blows. Fighting games show the principle: Smash derives hitlag from damage with a cap; SFV steps it by light/medium/heavy. Too short reads as no impact; too long reads as lag. |
| Shake | Trauma model: `trauma∈[0,1]` and `shake = trauma²`. Offset and angle = max × shake × noise(t); trauma decays linearly. Events add trauma in proportion to their weight; the maximum offset and angle stay small enough that the frame remains readable at full trauma. |
| Feedback stack | Gun kickback, hit pause on kills, bigger bullets, muzzle flash, persistent shells and corpses, camera lerp. Stack tween, squash, particles and sound on one event. |
| Camera vocabulary | Camera-window, platform-snap, lerp, physics-smooth, projected focus, dual-forward-focus, cue focus, region anchors, position averaging. |
| Determinism | Camera state, shake noise seed and particle RNG live in the sim state. The attract replay must stay byte-identical. |

Block keys:
- **Cam**: camera and projection.
- **Stack**: a typical layer stack, back to front.
- **Art**: what is usually a big painted layer, a modular piece or a tile.
- **Data**: what the level data has to hold.
- **Views**: which directions are drawn.
- **Get**: ways to produce those views.
- **Sim**: movement, collision and camera model.
- **Alive**: interactions players of this family expect, roughly most-felt first. Pick what the reference's world has.
- **LD**: level design.

## 1. Side-scrolling platformer / metroidvania
- **Cam**: orthographic side view. X: camera-window plus dual-forward-focus, shifted ahead of facing with an ease so the player sees where they are going without the view lurching on every turn. Y: platform-snap, i.e. re-centre only on landing, so jumps don't bob the world. Metroidvanias: region anchors per room plus hard edge clamps.
- **Stack**: sky → far → mid → architecture → back wall/cliff → gameplay ground and props → actors → FX → near-foreground occluders (darker, blurred, parallax > 1) → UI. Parallax factors fall with distance; measure them from the reference video or choose them so depth reads without swimming (Tuning Canabalt discusses its choices). Hollow Knight layers 2D sprites in 3D space and fakes lighting with soft transparent shapes.
- **Art**: depth bands read best as big painted layers. Walkable ground can be a frieze along polylines (fill texture, top-edge strip, corner caps), or tiles where the style is grid-based (pixel art). Rocks, vines and roots are modular sprites. Ori shipped thousands of hand-painted pieces so that no stretch repeats visibly.
- **Data**: collision as a tile grid (pixel art) or as polylines/AABBs. Visuals: frieze polylines plus a prop list (id, position, depth layer, scale, flip, sway). A parallax factor per layer, and room rects for the camera.
- **Views**: side only, mirrored for the other side. Optionally a short turn.
- **Get**: a strict-side anchor → part sheet (`animation.md` §1) → rig; `LIB.twoBone` handles two-segment limbs. Reserve frame-by-frame drawing for what a rig can't do: smears, the turn, big one-off moves.
- **Sim**: kinematic AABB against the grid, keeping the sub-pixel remainder so slow motion doesn't stall. What a platformer player feels: acceleration, reduced air control, gravity and a capped fall, variable jump height, coyote time, a jump buffer, apex hang while jump is held, corner correction, wall-jump tolerance, jump stretch and landing squash. Celeste's public player code is one complete tuning; scale anything borrowed by your resolution ratio.
- **Alive**: 1) Grass and foliage bend from walkers and gusts; 2) Landing dust plus squash; 3) Water: splash, ripple ring, floating objects bob; 4) Critter flee FSM (idle → alert → flee → return); 5) Pendulum hanging objects; verlet ropes and bridges that sag under load; 6) Breakables throw debris; hit-stop and shake on hits; 7) Ambient motes.
- **LD**: one core idea per level, structured as kishōtenketsu: introduce → develop → twist → conclude. Forgiveness widens input windows; it does not lower the challenge. Metroidvania: a lock/key graph with loops back to the hub and item-gated shortcuts.

## 2. Top-down action / adventure / RPG (Zelda-like, 3/4 view)
- **Cam**: orthographic 3/4 (oblique) view. Floors are seen from above; walls and characters show their front faces; screen Y carries both depth and height. Either room-locked with slide transitions, or lerp-follow clamped to the room rect.
- **Stack**: ground (splat or autotile) → ground decals (paths, puddles, blob shadows) → **y-sorted band** (actors, props, wall fronts, trunks; key = foot Y) → overhead (canopies, roofs, arch tops) → weather and light → UI. Overhead pieces turn translucent while the player is underneath: enough to see the player, not so much that the canopy vanishes.
- **Art**: terrain is material textures plus autotile or splat (§14). Buildings: a modular wall kit (front face, top cap, corner), or one painted set piece with a separate roof layer. Eastward cuts each pixel asset into parts and hand-paints a bump map per part for real-time lighting.
- **Data**: terrain-ID grid, collision grid (plus a height layer for cliffs), props with a footprint and a sort origin, triggers and doors.
- **Views**: 4-dir = 3 drawn (down, up, side) + mirror. 8-dir = 5 drawn (S, SE, E, NE, N) + 3 mirrored. Few drawings can carry a walk: Stardew's farmer loops a handful, with left and right sharing frames. Don't Starve plays flat 2D animation as billboards under a perspective camera.
- **Get**: the views must be one character. Generate them together (a turnaround) or from one anchor (§15), slice, and rig each view; rigs share part names and timing so every action transfers across views.
- **Sim**: 8-way normalised input with acceleration, quick enough to feel direct. A circle or feet-AABB against the grid; slide along walls. Nudge the player around corners when they almost fit a gap. Knockback impulse along the hit normal, then i-frames with flicker, long enough to escape a crowd but not to ignore it.
- **Alive**: 1) Grass parts around the feet and can be cut (clippings, drops); 2) Bushes rustle on overlap; 3) Footprints and dust, by surface; 4) Push blocks move after a sustained push, so brushing one doesn't shift it; 5) NPCs turn their heads toward the player within a radius; 6) Shallow-water ripples; 7) Birds and butterflies flee; 8) Torch light pools flicker.
- **LD**: dungeons as lock/key graphs with loops; one item per dungeon, reused in its own puzzles (GMTK's Boss Keys method). Give every screen a landmark. Show the goal before the player can reach it.

## 3. Isometric (tactics, city builder, ARPG)
- **Cam**: orthographic 2:1 dimetric (26.565°); pixel lines step 2 across per 1 up. Iso reads as iso only in orthographic projection: Monument Valley's illusions depend on it. Pixel art zooms in integer steps only.
- **Stack**: floor diamonds by `gx+gy` → floor decals → sorted band (walls, props, units) by `(gx+gy, height)` → overhead → UI (tile highlight, ranges). Multi-tile objects sort wrong as one sprite: split them into per-column slices, or topologically sort their bounding boxes.
- **Art**: a floor tile can be a square material texture warped into the 2:1 diamond in code (rotate 45°, then scale Y by 0.5), plus edge masks. Walls are left-face and right-face kits; props are sprites with a footprint. Keep painted backdrops where they cannot contradict the grid (beyond the map edge).
- **Data**: grid cells with terrain, height and blocking; objects have a footprint in cells. Screen position = `((gx−gy)·W/2, (gx+gy)·H/2 − z·Zpx)`. Simulate in grid/world space, never in screen space.
- **Views**: tactics: 4 diagonal facings = 2 drawn (SE, NE) + mirror. ARPG: 8 facings (5 drawn) or 16. Diablo II prerendered many directions from 3D.
- **Get**: the options trade consistency against effort. Few facings: an anchor plus one edit per facing at the same camera elevation, then cut-out rigs. Many facings with many actions: a low-poly 3D proxy rendered per direction as the pose reference for a restyle, or the rotation tool category (§15). Dead Cells rendered 3D skeletal models tiny and unsmoothed to get pixel frames.
- **Sim**: tactics: turn FSM, A* on the grid, telegraphed intents. ARPG: continuous world XY, circle colliders, click-to-move pathing. City builder: agents on a road graph.
- **Alive**: 1) Hovered tile lifts and highlights; 2) Units bob on idle and get a selection outline; 3) Projectile arcs cast ground shadows; 4) Hits flash and push the target (on a grid, by whole tiles); 5) City builder: chimney smoke, traffic agents, day/night tint.
- **LD**: readability caps the threat count. Into the Breach keeps its board small and telegraphs every enemy intent; flooding the board with threats made it unreadable.

- **Quests (RPG, ARPG)**: a small state machine in the sim per quest (offered → active → goal done → handed in), moved on
  by talking to the giver and by the goal's event (a kill, a pickup), with the reward paid on hand-in through the same
  progression path as kills. Players expect the genre's conventions: a giver marker for "has a quest" and another for "hand in" (`!` and `?` are
  the familiar pair), hidden while that NPC talks; a tracker with the quest name and each objective's progress that
  marks finished steps, draws the eye when a step changes and clears after the reward; a notice on taking the quest and
  one with the reward on hand-in. Place the tracker and notices to fit the reference's HUD layout, never colliding with
  talk bubbles or other transient UI. Stage every step with its worst-case strings as `SCENE.QA()` states, test the whole chain
  headless, and let the attract demo take the quest so its HUD shows.

## 4. Twin-stick / arena shooter
- **Cam**: top-down orthographic; the camera sits between the player and the aim point, biased to the player, clamped to the arena. A digital crosshair with its own position and speed aims more smoothly than the raw stick.
- **Stack**: floor → persistent decals (scorch, shells, corpses accumulated in a decal render target so they cost nothing per frame) → shadows → y-sorted actors → enemy bullets (additive, above actors) → FX → UI.
- **Art**: arena floor material plus autotiled walls; modular cover props. Bullets read by contrast (a bright core and a dark rim); drawing them in code keeps them crisp at any size.
- **Data**: arena grid, spawn points, a wave table (time, enemy type, count, spawner).
- **Views**: body in 4 or 8 directions (or one top view, rotated) plus a separately rotating weapon/arm part. Aim stays continuous while the body uses few facings.
- **Get**: front/side/back body anchors; the weapon is its own part, pivoted at the hand.
- **Sim**: a radial (not per-axis) stick deadzone, a small auto-aim cone, and aim that turns toward the stick at a capped rate, which feels smooth where snapping does not. Circle colliders, pooled bullets, a spatial hash, and i-frames on the dodge.
- **Alive** (follows Art of Screenshake): 1) Player kickback and a camera kick on each shot; 2) A brief muzzle flash; 3) Enemies flash white on hit; 4) Hit pause on kills; 5) Shells and corpses persist; 6) Cover is destructible; 7) Explosions push props.
- **LD**: pillars that break lines of fire. Telegraph spawns early enough to react. Escalate waves by mixing enemy roles, not by raising HP.

## 5. Shmup (vertical / horizontal)
- **Cam**: fixed playfield, tall for vertical shmups and wide for horizontal ones; constant auto-scroll.
- **Stack**: far bg (slow parallax) → ground targets → air enemies → player → player shots → explosions → **enemy bullets** → UI. Enemy bullets sit above everything except the UI.
- **Art**: backgrounds are long, loopable painted strips per depth band, with a cloud band on top. Ships are single sprites; bullets are drawn in code.
- **Data**: a timeline of spawns (time, enemy type, path, pattern); patterns are data (rings, aimed fans, spirals).
- **Views**: one view plus a few banking poses from hard-left to hard-right, made as edits of one anchor or as a rig tilt.
- **Sim**: the hitbox is tiny, centred and drawn on screen; a focus mode slows the ship for threading. Patterns are aimed, static or random. Bullets use colours the background never uses, with a light core next to a dark border. Chunk the patterns; avoid stray single bullets.
- **Alive**: 1) Bullets cancel into score items when a boss phase ends; 2) Graze sparks; 3) Enemies flash on hit; 4) Explosions chain; 5) Shake only on big kills, because bullets must stay readable.
- **LD**: lanes with spawns alternating sides, and gaps sized by enemy HP, as Boghog describes for Toaplan-style design. Each boss phase gets its own pattern.

## 6. Top-down racing
- **Cam**: north-up or rotating with the car. Look ahead along velocity and zoom out with speed, so the driver sees far enough to brake.
- **Stack**: terrain splat → track ribbon (spline mesh: asphalt fill plus curb friezes) → skid marks (persistent render target) → shadows → cars → overhead (bridges, canopies) → smoke and dust → UI.
- **Art**: the track is a frieze along a centre spline over a few splatted terrain materials. Scatter props by rule: trees off-track, cones at apexes.
- **Data**: a centre spline with width and surface IDs, checkpoints, and an AI racing line.
- **Views**: one top view, rotated freely. Pixel or 3/4 cars can't rotate as one sprite without breaking the grid or the perspective, so they need prerendered angles, often from a 3D proxy.
- **Sim**: per-tyre lateral velocity cancelled by a capped impulse; the car drifts when the cap is exceeded. Add forward drag and angular damping.
- **Alive**: 1) Skid marks and tyre smoke above a slip threshold; 2) Dust and grass flecks off-track; 3) Cones and barrels bounce; 4) Boost flames; 5) Collision sparks plus shake; 6) Engine pitch follows speed.
- **LD**: vary the corners (hairpin, chicane, sweeper); keep the racing line readable; add risk/reward shortcuts; use mild rubber-banding.

## 7. Puzzle (match-3, sokoban, physics)
- **Cam**: fixed; the board fits the safe area with a margin. Portrait on mobile.
- **Stack**: painted bg → board frame (9-slice) → cell backs → pieces → selection and FX → UI.
- **Art**: pieces come from one icon sheet with shared lighting and outline. Tell pieces apart by shape, not only by colour.
- **Data**: a level grid as data. Sokoban levels are ASCII; physics levels are bodies plus joints.
- **Views**: one. Mascots are cut-out rigs.
- **Sim**: rules resolve instantly, then an animation queue replays the result. Never animate inside the rules. Sokoban needs an undo stack; physics puzzles use fixed-step rigid bodies.
- **Alive** (the Juice it or lose it layers): 1) Eased swaps, quick enough never to delay the next move; 2) Pieces fall with gravity and land with squash and a small bounce, staggered by column; 3) Matches pop with a scale-up plus particles; 4) Combo pitch rises with each cascade; 5) A hint shimmers after the player idles a while; 6) Invalid moves bounce back.
- **LD**: find the one "truth" in the mechanic and cut everything else. Grow the scope without adding new mechanics. Each level teaches one idea.

## 8. Card / board / UI-heavy
- **Cam**: fixed. A per-card fake 3D tilt toward the cursor makes cards feel physical; Balatro-style shaders warp the perspective in the fragment stage.
- **Stack**: painted table → zone panels (9-slice) → cards in hand order (the hovered card goes on top) → drag ghost → FX → tooltips.
- **Art**: the card frame and art window are composed in code. Each illustration is generated separately with the same framing prompt. Icons go on one sheet; numbers use a bitmap font.
- **Data**: card definitions as data; a game state machine plus an action queue.
- **Views**: none; portraits only.
- **Sim**: the rules engine is separate from the tween layer. Every state change emits an event that the presentation consumes.
- **Alive**: 1) A skeuomorphic, physical board that reacts to clicks; 2) Hovered cards scale up slightly and tilt; 3) Cards sway idly in the hand and snap with overshoot; 4) Scoring is layered: shake, particles, counting numbers and rising pitch.
- **LD**: preview the outcome before the player commits. Keep few enough changing numbers on screen that the player can track them.

## 9. Visual novel / point-and-click
- **Cam**: fixed screens, or rooms wider than the screen with a horizontal pan and parallax.
- **Stack**: depth layers (far, room) → actors scaled by Y → foreground occluders → dialogue/UI.
- **Art**: rooms are painted big layers, one per depth band; hotspots are polygons. VN sprites are layered images: base + eyes + brows + mouth + blush.
- **Data**: a room with layers, walkboxes, hotspots and exits; a dialogue graph.
- **Views**: VN: one 3/4 front bust plus expressions. Point-and-click: front, back and side (mirrored) walks, plus talk and reach.
- **Get**: a base anchor, then expression variants made by editing only the face. Align each variant back onto the base canvas and paste it through a diff mask, so nothing outside the face drifts.
- **Sim**: walkboxes are convex polygons, so no pathfinding is needed inside one; path along a graph between boxes. Each walkbox sets an actor scale for depth.
- **Alive**: 1) Blink at random intervals; 2) Breathing idle; 3) Lip flap synced to text; 4) Ambient loops: steam, birds, flickering signs; 5) Hover highlight plus verb cursor.
- **LD**: puzzle dependency charts expose linearity versus parallelism.

## 10. Fighting / beat-'em-up (side view with depth lane)
- **Cam**: side orthographic. Fighting: frame both fighters and zoom with their distance. Beat-'em-up: scroll-lock into arenas until each wave clears.
- **Stack**: bg bands → perspective floor strip → blob shadows at ground position → actors sorted by ground Y → hit sparks → foreground occluders.
- **Art**: the stage is painted depth bands plus a floor strip; props are breakable.
- **Data**: beat-'em-up arenas (scroll range, waves); moves as frame data: startup, active, recovery, hitboxes, hurtboxes.
- **Views**: side plus mirror. Fighting-game quality is frame-heavy: Skullgirls averaged over a thousand frames per fighter. With AI art, cut-out rigs carry the bulk: author the key poses as part edits and add smear sprites as FX.
- **Sim**: position = (x, groundY) plus jump height z; draw at (x, groundY − z). A hit lands only if the depth difference is within a lane tolerance scaled to the actors' size (ChronoCrash discusses the rule of thumb). Streets of Rage 4 shrinks the player's hitbox depth while moving vertically, so dodges work.
- **Alive**: 1) Hit-stop by strength (§0); 2) Hit sparks; 3) Knockback slide with dust; 4) Wall bounce and juggles; 5) Shake on heavy hits only; 6) Background characters react; 7) Breakables drop pickups.
- **LD**: mix enemy roles in each wave (rusher, ranged, grabber, shield). Shape arenas so that lanes matter.

## 11. Endless runner
- **Cam**: side view. Hold the player toward the trailing edge so most of the screen shows what's coming; zoom out with speed.
- **Stack**: parallax bands → gameplay chunk → actors → FX → foreground.
- **Art**: chunks are built from modular pieces with frieze edges. Background bands loop; test the wrap seam at x=0 and x=W.
- **Data**: chunk templates plus generator rules keyed on speed.
- **Views**: side only: run, jump, fall, land/roll, stumble, crash.
- **Sim**: speed is the difficulty dial. Canabalt's tuning notes show one coherent rule set: acceleration tapers as speed rises; a tap jumps shorter than a hold; the widest gap derives from current speed, so every gap stays clearable; the hitbox is smaller than the sprite; obstacles cost speed instead of ending the run.
- **Alive**: 1) Birds flush as the runner passes; 2) Speed lines; 3) Dust trail; 4) Stumble animation; 5) Debris and crash shake.
- **LD**: difficulty comes from speed, not density, and telegraph distance grows with speed. Set pieces punctuate the run at intervals (Canabalt's notes, above).

## 12. Tower defense
- **Cam**: fixed or limited pan; 3/4 top-down or iso.
- **Stack**: painted map → path decals → build sockets → y-sorted towers and enemies → projectiles → FX → range overlays and UI.
- **Art**: the whole map is painted as big layers with fixed build sockets. Each tower tier is one sprite plus a rotating turret part. Enemies are small.
- **Data**: path polylines parameterised by arc length, build spots, a wave table.
- **Views**: enemies walk in every direction. Use 4-dir (3 drawn), or side plus mirror if the paths run mostly horizontal. Turrets rotate as a part; pixel-art turrets need drawn angles, because rotating a pixel sprite breaks its grid.
- **Sim**: enemies advance by distance along the path. Targeting: first, strongest or closest. Projectiles lead or home.
- **Alive**: 1) Build and upgrade squash; 2) Muzzle flashes; 3) Hit flash plus a death puff; 4) Coins pop up as numbers; 5) Soldiers rally; 6) Early-call button.
- **LD**: Kingdom Rush as one example: build spots are limited and sit near the road; paths split and converge late; each level introduces one new enemy; calling a wave early pays gold.

## 13. Farming / life sim
- **Cam**: top-down 3/4, following the player with room clamps; pixel-perfect.
- **Stack**: ground autotiles (grass, dirt, tilled, watered) → y-sorted crops and objects → canopies (fade when the player is behind them) → day/night and weather overlay → UI.
- **Art**: tile terrain; buildings are big modular sprites; each crop has growth stages that read apart at a glance; tools are part sprites.
- **Data**: grid layers (terrain, tilled, watered, crop, object), NPC schedules, a day clock.
- **Views**: 4-dir walks plus a tool swing per direction; few drawings carry it (Stardew).
- **Sim**: tile actions change grid state. A day clock paces the session: long enough to do a loop of chores, short enough to end in one sitting (Stardew documents its pacing). Growth ticks at day change.
- **Alive**: 1) Grass sways and rustles underfoot; 2) Trees shake and burst leaves on an axe hit; 3) Crops bounce on harvest; 4) Items pop out in arcs and magnet to the player; 5) Footsteps differ by surface; 6) Rain puddles; 7) Critters wander; 8) Lights warm at dusk.
- **LD**: nested loops (day, week, season); short walks between core stations; the same map changes visibly each season.

## 14. Tile-based worlds with AI art

**Why image models fail at tilesets.** An image model draws *a picture of* a tileset:
- edges do not match pixel for pixel;
- scale, perspective and baked light drift from tile to tile;
- adjacency semantics (which corner is grass) are ignored;
- pixel grids wander.

Real seamlessness needs explicit boundary constraints; research does it with boundary inpainting. So the principle: **generate materials, compose tiles in code.** The steps below are the concerns; choose the technique per style.

1. **Material**: one per terrain, asked for as a seamless top-down texture: orthographic, flat even lighting, no objects, no vignette, no horizon, with the style bible. Make it larger than a tile so it can be sampled without visible repeats.
2. **Wrap**: offset by half its size with wrap to expose the cross seam. If it shows, feather-blend it or inpaint it with the same prompt.
3. **Flatten low frequencies**: divide out the large-scale brightness variation (a high-pass in linear space, then restore the mean). Otherwise tiling shows periodic blotches.
4. **Edge masks**, one set per transition. Procedural (a cell SDF displaced by noise, with the lip or shadow ring as a darkened band) or painted (an edge strip such as grass overhang, foam or a cliff lip, on key colour).
5. **Compose**, for example with:
   - **Blob-47** from 5 quarter-tile cases (interior, horizontal edge, vertical edge, outer corner, inner corner). Each quadrant picks its case from its two edge neighbours plus the diagonal; RPG Maker builds all 47 tiles from 5 this way. A corner bit counts only when both adjacent edges are set.
   - **Dual grid, 16 Wang-corner tiles**: offset the render grid by half a tile. Index = `TL | TR<<1 | BL<<2 | BR<<3` gives 16 tiles, 6 unique under rotation (Excalibur, from Stålberg's "Beyond Townscapers"). Gameplay stays on the main grid; the dual grid is for field-like terrain.
   - **Pixel art**: compose at native resolution, then palette-lock the whole atlas once.
6. **Shader splatting** suits painterly or vector art: a terrain-ID texture sampled per fragment, with neighbouring cells' materials blended by height (texture luminance plus noise) so boundaries follow the material's shapes rather than the grid. Sample materials in world space with a random offset and rotation per cell to hide repetition.
7. **Edge-transition strips**: marching squares on the grid → boundary polylines → the strip texture drawn along them, u running with arc length and the overhang pointing outward.
8. **9-slice** for panels, framed platforms, windows and signs: corners fixed, edges tiled, centre filled.
9. **Friezes**: a polyline plus a fill texture, edge strips chosen by segment angle (top/side/bottom), and corner pieces. UbiArt built Rayman's levels from friezes; SpriteShape exposes the same angle-range and corner model.
10. **Break repetition**. The eye finds any period; concerns:
    - variants per tile, picked deterministically by a hash of the cell, with the plain variant dominant;
    - flip or rotate only isotropic, unlit materials (a flipped light direction shows);
    - scatter decals (pebbles, cracks, flowers) with Poisson-disk spacing so they neither clump nor grid;
    - multiply in a macro variation mask at a scale much larger than a tile;
    - for stochastic materials, hex tiling with histogram-preserving blending.

**Checks** (script them; set the tolerance by what the reference itself shows at the view size):
- **Seam**: tile 3×3; on both axes, compare the difference across a tile boundary with the typical difference between neighbouring columns inside the tile. A seam is a boundary that stands out.
- **Repetition**: tile 4×4 and blur by a fraction of a tile; structure that survives the blur, relative to the source's variation, is visible periodicity.
- **Coverage**: render a random map that exercises all 256 neighbour masks (8 neighbours); it must show no seam.
- **Pixel art**: edge pixels match their neighbour's palette index exactly.
- **Baked light**: no visible luminance gradient across one tile.

**Specialist tileset generators (category).** Some tools emit corner Wang sets (16 tiles), transition sets, path sets and building kits, with terrain chaining and engine export. When researching one, check:
- the output's exact bit order and layout;
- native pixel size and grid alignment;
- a style-reference input;
- that chained transitions (grass→dirt→water) stay consistent;
- transparent overhang for side view.

Run the checks above on its output anyway. If it fails, treat the output as material and re-compose it in code.

## 15. Directional characters with AI

| Need | Drawn | Mirrored | Typical families |
|---|---|---|---|
| Side | 1 | 1 | platformer, fighting, runner |
| 4-dir | 3 (S, N, E) | W | Zelda-like, farming, point-and-click, TD |
| 4 diagonal | 2 (SE, NE) | SW, NW | iso tactics |
| 8-dir | 5 | 3 | ARPG, twin-stick body |
| 16-dir | 9 | 7 | ARPG, racing (3D proxy) |

**Consistency techniques.** The goal is one character in every view (proportions, palette, height, ground line, details). Options:
1. **Turnaround in one call**: all views in one image, so the model keeps one identity. Ask for orthographic views (front, side, back) on one ground line at one height, a pose with the limbs clear of the body (so parts can be cut), a flat key-colour background and no labels. Slice by connected components, then normalise each view's ground line (lowest opaque row), height and centre (hip x).
2. **Anchor + edit**: when a view fails, regenerate it from the best anchor ("same character, rotate to <view>") with the anchor attached. Accept the result only if its palette and height match the anchor; measure both (e.g. a palette distance in OKLab and the opaque height) rather than eyeballing.
3. **Mirror** for the opposite side. Mirroring swaps handedness, scars, hair parting and emblem text. Design those features symmetric, or make them separate rig parts that do not flip.
4. **Diagonals**: attach both front and side as references in one call, or use a 3D proxy render as the pose reference.
5. **Part sheets** per view, with identical part names across views. Make face variants by editing only the face, then align them to the base.

**Rotation tools (category).** Pixel-art tools exist that take one view and return 8 directions in one call. They often offer a camera elevation choice (side, low or high top-down) and skeleton-pose animation; frame sizes are often capped small. When researching one, check:
- max frame size versus your sprite size;
- elevation options that match your camera;
- palette lock across all directions and animations;
- the export layout.

| Method | Use when | Avoid when |
|---|---|---|
| Cut-out rig | Rigid or semi-rigid parts (armour, cartoon, paper, mascots); many actions over few views; runtime aim, sway or blending. Don't Starve-style symbol swaps per part. | Small pixel-art sprites, because rotated parts break the grid. Silhouettes that change shape. Many directions, which means one rig per view. |
| Frame by frame | Pixel art; smears, turns, transformations; fighting-game key moves | Long cycles × many directions done by hand |
| Image-to-video extraction | Organic motion (creatures, cloth, fire, flags), painterly breathing idles; needs a model with first-frame conditioning and a locked camera | Exact contact timing; seamless loops (needs last frame = first frame); pixel art without re-gridding every frame |
| 3D proxy → 2D | Many directions (ARPG, racing). Dead Cells and Diablo II worked this way; Ori baked 3D rigs to sprites, including motion blur. | Painterly characters with a lot of hand-made detail |

**Video extraction: what matters**:
1. A flat key-colour background, and enough empty border that no limb or effect leaves the frame.
2. Prompt anticipation → action → recovery with a locked camera and no travel across the frame.
3. Extract all frames, then pick the start frame, the end frame and the key beats.
4. Despill, then place frames into fixed cells **without per-frame recentring** (recentring makes the body jitter).
5. Downsample to the frame count the style needs. For pixel art, re-grid every frame with one shared palette.

**Rates and frame counts in shipped work** (illustrations, not targets):
- Animation rate is independent of the game rate: Cuphead animates at 24 fps on ones while gameplay runs at 60.
- Very few drawings can carry a cycle: Stardew's walk and Shovel Knight's idles are tiny loops.
- Pace carries character: in Richard Williams' timings, fewer frames per step read as brisk and more as a stroll; runs are faster still.

| Action | What it must read as |
|---|---|
| Idle | Alive without drawing the eye: a rig breath or a short loop of few drawings, slow and subtle |
| Walk | Contact and passing poses read; planted feet never slide; the pace matches the character |
| Run | Faster than the walk, with a lean and a moment with both feet off the ground |
| Jump | Rise, apex, fall and land are distinct; the landing squash is brief |
| Attack | Anticipation → contact → recovery; the contact is fast and lands with hit-stop; the recovery is long enough to read the commitment |
| Hurt | A readable flinch plus a brief flash |
| Death | Reads at a glance; hold the last pose |

Holds and timing matter more than frame count. Rigs sample poses at the sim rate for smooth styles; for a hand-drawn feel, step pose updates as on twos or threes.
