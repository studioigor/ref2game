# Effects recipes (all in code, all deterministic)

The engine (`templates/live/lib.js`) already has shaders and primitives for most effects below. They are tools you can use, not the only way: write or replace a shader when the reference needs something they don't do. Effects are what make a painting read as a living game, and they must match the reference's **style**. Painterly references get soft, continuous noise; pixel art gets stepped, palette-locked versions (`styles.md`).

Size every effect against the view and the actors (an actor's height, a tile, the screen), never against fixed pixels, and take its colours from the reference. Every effect is a pure function of time, its event and a seed (no `Math.random`, no `Date`), so play, `render.mjs` and `qa.mjs` see the same frame.

## Contents
1. Atmosphere: sky, sun, fog, haze, god rays, motes
2. Water: still water, waterfall, foam, mist, splashes, ripples
3. Wind: one field, many consumers
4. Particles from events
5. Light accents: glows, rim, emissive props, pickups
6. Post: bloom and final grade
7. Ambient life: schedulers, flocks, falling leaves, fish
8. Lessons (what failed and why)

---

## 1. Atmosphere

- **Sky.** A painted band with no alpha and the slowest parallax in the scene. If the camera can travel past its edge, cover the travel (a mirrored copy next to it, or wider art).
- **Sun.** A wide soft glow plus a tighter hot core (`L.glow`), in the reference's sun colour. Failure class: the core bleaches to pure white, while the reference's sun keeps its chroma. Check the sun's colour against the reference crop.
- **Fog bands** (`L.fog(y, h, p, col, seed, t, scatter)`, `p = [scale, speed, threshold, density]`). An fbm field with a vertical profile, drifting sideways; its colour warms toward `L.SUN`. Put fog **between depth bands**, so depth reads as layers of air. Across depth, the trend matters, not the values: far fog is broader, slower, thinner and takes the sky's colour; near fog is finer, faster and takes the colour of the near shade; spray over falls or rough water is dense, fast and near white. Tune each band against the reference's air at that depth.
- **Weather as a world state, not a screen filter.** The sim owns an amount (0..1), smoothed over seconds and tied to a place or a story beat (rain gathers near a boss and passes once it is dead). Thunder comes from the sim on a deterministic schedule. `L.rain(t, amt, cam, phase, { wind })` is ground-view rain in three phases (`engine.md`). Rain needs these layers, however they are built:
  1. **Wet ground** in the ground decal pass (phase `'ground'`): the ground darkens; puddle patches go darker still.
  2. **Splash rings and puddle sheen** after the light pass, on the ground only, masked by the pre-light frame's alpha (phase `'fx'`). Puddles reflect only strong lights (a fire, a lamp, the lightning), as soft broken glints stirred by the drops.
  3. **Streaks** over everything (phase `'sky'`), in several depths with a wind slant. Each streak is lit by the light map where it falls, so drops glow round a fire.
  4. **Heavier fog**, a darker and cooler ambient light, and **lightning**: a stuttering flicker that floods the light map (the whole world lights up cold) plus a faint screen flash.
  Failure classes: puddles lit by the whole light map (ambient included) turn into milky white patches; thresholded value noise makes blocky checker glints; streaks that never get the time hang in the air while every still looks right; anything whose drift rate follows the weather amount (fog speeding up in the rain) races across the screen while the weather comes in, unless its phase is integrated over time. Check rain at full size and at 2×, on lit and dark ground, with a flash; check that it falls and that its arrival sweeps nothing (`qa.mjs` `anim` and `ramps`, at a late world time).
- **Haze per plane** goes through sprite `grade.z` and `haze` (`art.md` §5). The haze colour must equal the fog colour at that depth, or layers look pasted.
- **God rays** (`L.godRays(t, { sun, amt, col })`, then `L.veil(amt, col)`). What the shafts must do:
  - **Come from the picture.** The mask is the bright, warm, sky-ish part of the composed background near the sun, broken up so the shafts have gaps. Because the mask comes from the composed background, the band silhouettes **occlude the rays for free**.
  - **Radiate from the sun** (a radial blur toward it), long enough to read as shafts, not as a halo.
  - **Add light, never paint over:** screened onto the background in the reference's light colour.
  - **Reach the play plane** as a much thinner veil (`L.veil`), so the actors stand in the same air.
  Failure classes: shafts with nothing occluding them read as a filter; a strong veil washes the actors out. Compare with and without (`?fx=0`).
- **Dust motes** (`L.motes(t, { n, amt, col, h })`). Tiny soft dots drifting slowly. Their brightness is multiplied by the ray texture, so they light up only inside the shafts. Without them, shafts look like a filter.

## 2. Water

- **Still water / pool** (`L.water(t, {y, sun, fall, gust})`). A cartoon surface, not a physical one. The concerns it covers, each tuned to the reference:
  - **Depth bands** with soft wavy borders: light near the shore, deep further down.
  - **Reflection** of the background, mirrored at the waterline, displaced by the waves and faded with depth; posterised when the reference is stylised.
  - **Ripple marks** drifting with the current, each living and dying on its own phase.
  - **Sun glints**, concentrated under the sun's x.
  - **Churn** under a waterfall (`fall`).
  - **Shoreline foam** along the top edge.
  - **Gust patch:** a darker, rippled "cat's paw" racing across with each wind gust (`gust`, from the wind field, §3).
- **Waterfall** (`L.waterfall(t, x, y, w, h)` with the FALL shader, `L.foam`).
  - **Flow.** Procedural flow moving down in layers at different speeds, so it never reads as one scrolling texture. Thicker bundles of water vary across its width. The sheet widens toward the bottom.
  - **Colour.** Deep, mid and crest tones from the reference, and a bright lip at the top.
  - **Edges.** Ragged and changing over time, so the sides never look cut.
  - **Base.** Foam, droplets on ballistic arcs with jittered periods, and a dense mist fog band.
  - **Direction.** Failure class: a slanted sample direction makes the fall read as crooked. It flows straight down unless the reference shows otherwise.
- **Splash** (event `splash`, or anything falling in): expanding rings, staggered and flattened to the water's perspective; droplets on ballistic arcs; a small shake; a "sink" state in the sim, then a soft respawn. Size and strength follow what fell in and how fast.
- **Fish or critter jump** (ambient). An arc out of the water with a ring at entry and at exit, in jittered windows with skips (§7). Stay quiet for a moment after the player's own splash.
- **Interactive surface** (optional, when the player plays in water). A row of spring columns that pass energy to their neighbours (the classic 1D spring-wave model). Draw the surface line from the columns. Everything that touches the water calls one `splash(x, strength)` entry point. Tune spacing, tension, damping and spread until waves travel and die like the reference's water; check that the surface settles back to flat and never blows up.

## 3. Wind: one field, many consumers

The wind is one function of time and x, owned by the sim, that every consumer samples. It needs:
- a slow base of a few incommensurate waves travelling across x, so nothing sways in unison;
- **gust fronts** that travel across the scene, with a sharp leading edge and a long tail, arriving in jittered windows (not on a fixed period), each with its own strength;
- one clock shared by the sim and the scene.

The template implements this as `SIM.windAt(t, x)`, `SIM.gustAt(t, x)` and `SIM.gusts(t)` in `sim.js`, so foliage springs and pendulums can use it. The scene samples the same functions with its own `t`, which is the same clock (`wt0`). Retune or replace it to fit the reference's weather.

**Consumers.** When a gust crosses the screen, everything reacts in sequence, in the gust's direction of travel. That shared cause is what turns separate loops into one world. Pick what this scene has:

| Consumer | Response |
|---|---|
| Grass and plant tufts | Spring target leans with the wind, scaled by the tuft's height (sim) |
| Trees, hanging vines, moss | Sway amplitude grows with the gust |
| Banners and flags | Hang leaning with the gust, and sway harder |
| Pendulums (hanging lamps, signs) | The gust adds torque |
| Bridges | Sway grows with the gust |
| Foreground clumps | Rooted lean and stronger sway |
| Flower or plant heads | Lean with the wind |
| Capes and hair | Sway grows with the gust |
| Butterflies and light critters | Pushed along the gust and lifted |
| Water | A cat's paw patch travels with the front (§2) |
| Leaves | A gust strips some leaves from the canopy and carries them across, faster than they fall, tumbling (flip x by cos), fading in |

Scale each response by how much the object catches the wind: light, tall and hung things move most; stiff, rooted things least. Don't fake a gust with a visual only: if the grass leans, the hanging sign must swing too. Verify with a filmstrip across a gust (`render.mjs stills`): the lean travels across the screen as a wave instead of starting everywhere at once.

## 4. Particles from events

Particles are drawn from `ST.ev` with age `a = GT − e.t`. They are pure functions of `(event, a, j)`, with jitter from `rnd(e.t, j)`. So any moment of any effect renders on its own, which is what makes age strips possible.

What each common event must show. Counts, sizes and lifetimes are tuned to the actor's scale, the style and the event's weight:

| Event | Particles |
|---|---|
| step | A small puff of the ground's material behind the feet, on the stride cadence |
| jump | Puffs kicked out to the sides |
| land | Puffs whose spread and size grow with landing speed; a shake only on hard landings |
| bounce pad / spring | A burst (pollen, sparks) rising with the launch; the pad squashes then wobbles (`gamefeel.md` §3) |
| stomp an enemy | An expanding ring, dizzy stars circling the enemy, hit-stop, a shake (`gamefeel.md` §1, §4) |
| head-bump a prop | Sparks fanning upward; the prop's glow flares briefly |
| rustle through foliage | Leaf or blade bits kicked in the move direction, falling and spinning |
| collect | A burst, an expanding ring, a glow; the pickup flies to its HUD counter on a curve; a "+1" rises and fades; the counter bumps when it arrives |
| hurt | Knockback, a spell of invulnerability shown by a flicker, the pose blending to "hurt" |
| critter takes off | A few feathers or leaves drifting down |

Puffs use the PUFF shader (`L.puff`: a noisy soft blob, premultiplied, tinted from the ground colour). Stars and glows are additive (`L.star`, `L.glow`); rings are `L.ring`. Keep each event cheap enough that a burst of events holds the frame rate (`livecheck.mjs` reports fps). Emit from where the action happens (the feet, the contact point, the weapon tip), not from the actor's origin: `qa.mjs` fails emitters drawn more than `tol` px from where the sim emits.

**Ground impacts (slam, stomp, landing of something heavy, an explosion).** The ground itself must break, and the break is
the effect people remember. Never draw it as straight bars, strips, lines or flat rings radiating from a point (they read
as programmer art at once). Build it from layers, each with its own life:
- **fissures**: `L.cracks(x, y, R, age, seed, mode)` (or a shader like it), which has this life built in:
  - jagged main cracks, each with branches, racing out from the impact, tips first;
  - shattered plates round a shallow crater;
  - a pale broken lip along each crack;
  - in the ground decal pass (mode 0), so actors and props stand on it and occlude it;
- **heat or energy in the cracks** (when the style allows it): additive after the light pass (mode 1), cooling from the tips
  inward, embers lingering, masked wherever a sprite covers the ground (sample the pre-light frame's alpha). Unmasked, it
  paints over the trees and actors in front;
- **impact flash** at the contact point, only a few frames long, plus a light-map pulse there;
- **shock front**: a thin bright ring racing out with ease-out, and a dust ring on the ground;
- **sparks** and **debris** on ballistic arcs, with contact shadows. Debris is painted chunks (a rock sprite, tinted to the
  ground), not rectangles. Big chunks fly only toward the camera, so they never paint over the actor;
- **dust**: a wall that rolls out, rises and thins, then a heavier haze settling over the crater;
- **scar**: the dark fissures stay for a few seconds and fade.
It reads as an impact when the first layers are near-instant and each later layer lasts longer than the one before
(flash → front → cracks → debris → dust → scar). The impact point is where the weapon meets the ground (in front of the
actor, by its facing at the strike), not the actor's feet. Check it on an age strip (stills from the first frame to the
scar's fade, dense early and sparse late) on lit and dark ground, with something standing in front of it.

## 5. Light accents

- **Pickups on bright backgrounds.** Draw a soft **dark backing** (`L.shadow`) under the glow, or a gold glow disappears against a cream sky. Check every pickup over the brightest region it can appear on.
- **Emissive props** (lamps, crystals, windows). The glow follows the light source's actual position. On a swinging lamp the light swings too, and a moving light animates the whole image. Flicker comes from a few incommensurate sines (never `Math.random`), subtle enough to read as a flame and not as a fault, plus a flare on bump.
- **Glows near actors.** Keep them weak, or they wash the hero out (§8).
- **Rim light.** The sprite `rim` uniform (strength, direction, width) gives a sun-side edge from the alpha gradient on actors and play-plane pieces. Mirror dir.x for flipped sprites. Colour and side come from the reference's key light. This is what makes separately generated pieces share one light.
- **Contact shadows.** `L.shadow(x, y, rx, ry, amt)` ellipses under actors. They shrink and fade with height above the ground, but never vanish while the actor is over ground. Draw a `L.dropShadow(draw, sp)` pass for platform pieces onto the layers behind.

## 6. Post: bloom and final grade (`L.finish`)

`L.finish(t, { bloom, vignette, warm, roll, dither })` is the last pass before the HUD. What each part is for:
- **Bloom.** A bright pass on the brightest pixels, blurred at two radii and added, so light sources glow without fogging the frame.
- **Grade.**
  - Warm highs and cool lows (`warm`), so the image reads as lit by one light.
  - Hue-keeping highlight roll-off (`roll`): bright pixels compress while keeping their channel ratios, so a hot sun stays orange instead of turning white.
  - Vignette (`vignette`; 1 = none).
  - A tiny dither (`dither`) against banding.
- **Exact-palette styles** (pixel, flat, neon) turn it all off: `{ bloom: [0, 0], warm: 0, roll: 0, dither: 0 }`. Match the grade to the reference with `compare.py`, not by taste.
- **HUD after the grade**, so it stays crisp and unaffected by bloom or vignette.

## 7. Ambient life

- **Scheduler rules.** Use windows with jitter and skips, never exact periods. Use incommensurate periods (primes, the golden ratio). Give each instance its own amplitude and phase. Make **rare events** special, spaced far beyond anything a viewer would read as a cycle. Keep a quiet window after the player's own big events (`gamefeel.md` §5).
- **Distant flock.** A few simple flapping silhouettes crossing a far band now and then, in a jittered window; simple enough to stay in the far layer.
- **Falling leaves.** A few leaves, each on its own period, drifting down with a sideways sway, tumbling via an x-scale of cos. Also small bursts from impacts near trees.
- **Small flyers (insects, sparks of light).** Wander on smooth, non-repeating paths (Lissajous curves work). They **flee** from the hero inside a radius, with a smooth falloff, and return.
- **Every ambient system needs a player hook** (flee, attract, splash or bend). Ambience that ignores the player reads as wallpaper.

## 8. Lessons (what failed and why)

- **Thin light overlays standing for motion** ("wind lines" in screen blend) were invisible over a bright sky and barely visible over mid-tones. The leaves carried the gust; the lines were removed. Test any stylised overlay on the real background's brightest region, and prefer moving real things over drawing symbols of motion.
- **A critter flying off** must leave the screen before its path ends, or it vanishes mid-air. Build flight paths that end well beyond the screen edge.
- **Separate hanging pieces** (vines, ropes) drawn in front of the canopy showed their cut tops floating in the sky. Draw them **behind** the occluding foliage and anchor them inside it.
- **Foreground clumps with parallax > 1** exposed their straight edge at the screen corners when the camera moved. Cover the camera's whole travel (a mirrored twin beyond the edge, or wider art).
- **A glow over the hero** made the hero look washed out. Keep glows away from faces, or keep them weak.
- **NaN hairlines.** `pow(negative, x)` in a deform shader produced a 1 px line across the sky at a quad's padded edge. Clamp before `pow`. Bisect such lines with `?only=`.
