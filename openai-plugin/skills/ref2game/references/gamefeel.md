# Game feel and a living world

**Diagnosis.** A scene reads as a "static picture" for three reasons:
- **(a) The camera never moves,** so parallax layers collapse into one painting.
- **(b) Nothing has a cause:** every motion is an independent loop.
- **(c) The player's actions leave no trace.**

Every section below attacks one of these. The goal the user cares about is: *"I feel the world is alive, and I can really interact with things."*

Springs are written as frequency f (Hz) and damping ζ. Convert with k = (2πf)² and c = 2ζ·2πf, then integrate `v += (k·(target − x) − c·v)·dt; x += v·dt`. Frequency sets how fast a thing answers, damping how much it overshoots: ζ = 1 settles without overshoot, lower values bounce. Pick both per object, by its size, weight and the style.

## Contents
1. Player feel: numbers
2. Camera
3. Reactive world: patterns (sim-side)
4. Juice per event
5. Living ambience without wallpaper
6. Level design for a small slice
7. The interaction audit (run it before saying "done")

---

## 1. Player feel: numbers (platformer; other genres in `genres.md`)

Feel is a handful of numbers, and none of them is universal. Tune them to this game: measure the reference when it is gameplay (jump height in body heights, frames to apex, run speed in screens per second), and otherwise the best-known games of the genre. Design by **jump height and time to apex**, then derive the rest (rise gravity g = 2h/t², jump speed v = 2h/t). Celeste's public source documents the forgiveness mechanics well. Read it for the mechanisms; its values are in its own low-res pixel scale and its own level design, so never copy them across unconverted and unchecked.

| Mechanic | What it does, and the bar |
|---|---|
| Coyote time | Jump still works for a moment after running off a ledge. Long enough that a late press never feels robbed, short enough that nobody sees a jump from thin air |
| Jump buffer | A jump pressed just before landing fires on landing. Long enough that an early press is never eaten |
| Variable jump | Releasing early cuts upward speed; holding extends the jump up to a limit. Both the short hop and the full jump must be useful in the level |
| Apex hang | Lower gravity near the top of the arc while jump is held, so the player has time to aim the landing |
| Fall gravity | Higher than rise gravity, so the jump is snappy, not floaty |
| Max fall | Capped, so long falls stay readable and landings controllable |
| Air control | Weaker than ground control, but enough to correct a jump in flight |
| Enemy bounce | Bouncing off an enemy launches the hero; holding jump gives more |
| Spring or bounce pad | Clearly bigger than a jump, so it opens routes the jump can't reach |

The template's `sim.js` holds these as constants in `K` (`K.COYOTE`, `K.BUFFER`, `K.CUT`, `K.APEX`, gravity, run, jump). They fit its demo level; they are a starting point, not a target.

- **Run.** Snappy but not instant: the hero reaches full speed fast enough to feel responsive and slowly enough to show a start. Top speed follows from how long a screen should take to cross and from the level's gaps.
- **Anticipation.** Never delay the hero's jump. Put anticipation on **world** objects: a pad compresses just before launch, an enemy crouches before it hops. Long enough to be seen, never long enough to be waited for.
- **Hit-stop.** A freeze of a few frames on big impacts, longer for heavier hits. The world keeps moving; only the hero and camera hold.
- **Screen shake** (trauma model, Eiserloh GDC 2016):
  - an event adds trauma (0–1) and trauma decays linearly; offset = max × trauma² × noise(t), so it fades quadratically (same model as `genres.md` §0);
  - the maximum is set per kind of event and ordered by weight (a stomp shakes more than a splash, a splash more than a hard landing), and a single event is over in a fraction of a second;
  - smooth noise or high-frequency sines, never `Math.random()`;
  - budget: rare and meaningful.
- **Squash and stretch** on a soft or round hero: stretch along the motion at take-off, squash on landing scaled by fall speed, recover on an underdamped spring (a visible bounce or two). Keep the volume roughly constant (x and y scale inversely), and only as much as the art style tolerates.
- **Landing feedback stack, in order:** squash → dust (more if hard) → nearby grass flattens → platform dips → leaves drop → shake if hard.

Put feel-only options behind a play-mode flag (`S.vj`) so the tuned attract demo stays valid. Verify with `livecheck.mjs --keys` scripts: press jump just after leaving a ledge and just before landing, tap and hold jump, and read the results with `--eval`; then let the game critic play it (`critics.md`).

## 2. Camera

Patterns from Itay Keren's "Scroll Back":
- **Forward focus.** Lead the hero in the facing direction, so the player sees where they are going, via a critically damped follow (a spring with ζ = 1: no overshoot). Lead distance and follow speed are tuned to the hero's speed and the view.
- **Make the world wider than the screen**, so the camera must travel and parallax shows. A locked camera turns every layer into one painting.
- **Asymmetric clamps** where framing art must stay on screen (a big tree on one edge), and art wide enough to cover the travel. Mirrored twins handle parallax > 1.
- **Platform snapping.** Change the camera's y only on landing (if vertical travel exists).
- **Idle breathing.** A small, slow drift, on a period that matches no other loop: felt, not seen.
- **Shake.** Added on top, never fed into the follow.

Verify with `livecheck.mjs --shots` across a run: the hero sits ahead of centre while moving, the layers separate, and no edge of framing art shows at the clamp limits.

## 3. Reactive world: patterns (all in the sim, deterministic)

Size every radius and amplitude by the object and the actors (a plant's height, the hero's width), not by fixed pixels.

| Object | Model | Hooks |
|---|---|---|
| Grass, plants, tufts | A spring per instance on a lean. Target = wind lean + a push away from each walker within a radius (sign = which side, smooth falloff, scaled to the plant's height) + velocity drag | Landing nearby: impulse ∝ landing speed. Fast pass: `rustle` event (bits fly). Drawn with the sprite `lean` uniform (rooted, quadratic). prime31 grass |
| Hanging vines, ropes, banners | Pendulum per strand (ω'' = −(g/L)·sin θ − c·ω + wind) or a short Verlet chain for long ones | Body passes through: impulse ∝ vx at the contact point, plus a `vine` event (leaves). Draw rotated about the anchor plus a hung lean ∝ −ω for the whip lag |
| Bridges, planks, branches | Analytic sag: an overall arch plus a local dip at the load (what the sprite `bend` uniform draws), its amplitude on a spring that deepens while loaded | Landing: impulse ∝ landing speed. Walk line includes the sag. Moss and branches jiggle (hung sway amplitude) from step, land and jump events nearby |
| Hanging lamps, signs, swings | 1-DOF pendulum, low damping, so a knock keeps it swinging for several seconds; its frequency follows its length | Head bump: angular impulse from the hit's speed (plus its upward component); wind torque; **the light follows the tip** |
| Bounce pad (flower, mushroom, spring) | A short contact phase (the rider sinks with the pad), then launch; a wobble that settles | Burst (pollen, sparks), small shake, leaves shaken loose |
| Enemies you can stomp | Top contact → bounce + hit-stop + squash + stars; side contact → hurt + knockback + i-frames | Enemy turns to face you, rears when alert |
| Water | Splash event, rings, droplets, sink → soft respawn (no death) | Critters can splash too |
| Pickups | A collect radius generous enough that touching the art always counts; a breadcrumb arc doubles as tutorial | Burst + fly-to-HUD + counter bump; respawn rules on death |

**Critter FSMs** (the world notices you):

```
idle ─(hero inside the notice radius; a short notice beat: crouch / turn to look)→ flee (hop / fly away from the hero)
flee ─(cornered: no room in the flee direction)→ cower (squash, shiver, eyes shut) ─(hero passed)→ flee the other way
flee ─(hero beyond a larger safe radius for a while)→ return (hop / fly back along the path) → idle
loud events (bounce, stomp, hard land) within a wider radius → instant flee for skittish critters (birds)
```

- **Hysteresis.** The safe radius is larger than the notice radius, and the return waits, so a critter never flickers between states at the edge.
- **Idle critters watch the hero:** they face toward them from further away than they flee.
- **Flying exits must leave the screen** (overshoot the edge); returns come back in along the path, facing the travel direction.
- **Attract loop.** Reactions triggered in the demo must complete before the loop resets, or they pop (check the timeline with `tune.cjs`).

## 4. Juice per event

The rule from the GDC talk "Juice it or lose it": every player action produces **several layered responses at different time scales**. A platformer example; build the same table for each verb of any genre:

| Event | Instant (within a few frames) | Short (under a second) | Long (seconds) |
|---|---|---|---|
| Step | — | Dust puffs | Grass push |
| Jump | Stretch | Dust | Platform rebound, moss jiggle |
| Land | Squash, shake if hard | Dust by speed | Grass flatten + wobble, platform dip + spring, leaves drop |
| Bounce pad | Pad squash, rider sinks | Launch, pollen burst | Pad wobble, nearby birds flee |
| Stomp | Hit-stop, shake | Enemy squash, ring, stars | Enemy wobble back |
| Bump a prop | Sparks, glow flare | Prop swings | Swing decays slowly |
| Collect | Burst, ring | Flight to the HUD, "+1" | Counter bump |
| Hurt | Knockback, flash | Hurt pose | i-frames flicker, heart icon empties |

Verify each event on an age strip (`render.mjs stills` from the event's first frame onward): all three time scales are present, and the instant layer lands on the frame of the action, not after it.

## 5. Living ambience without wallpaper

- **One shared wind field with gust fronts** that cross the scene (`effects.md` §3). A shared cause turns dozens of loops into one world.
- **Anti-wallpaper rules:**
  1. Use incommensurate periods (primes, the golden ratio); never reuse a period.
  2. Give each instance its own amplitude and a random phase (`rnd(i, k)`).
  3. Time events in jittered windows with skips, not fixed intervals.
  4. **Every ambient system has a player hook:** flee, bend, splash or light up.
  5. Add rare events, spaced far beyond anything a viewer would read as a cycle: something unusual.
  6. Keep a quiet window after the player's own big events.
- **Persistent traces.** Grass stays flattened for a moment. Pickups you took stay gone across respawns (banked). Optionally, collected items change the world (a light source grows brighter per pickup).

## 6. Level design for a small slice

- **Four steps** (Hayashida's kishōtenketsu, via GMTK): introduce a verb safely → develop it with danger → twist it → conclude with a payoff. Use the rule of three, then a reward.
- **Breadcrumbs.** Put pickups **on the intended arcs**. Compute the arcs in node from the sim and place pickups on them, so the attract demo collects them all and players read the path.
- **Signposted secrets, not hidden ones**: breakables at screen edges, an "unnecessary-looking" platform implying a route, a distinct light on a suspicious spot, critters drifting in and out of a passage.
- **Light grammar.** One consistent code within the reference's palette: one kind of light marks the critical path (pickups, lamps), another marks secrets, a light shaft or the strongest light marks the goal. Warm for the path and cool for secrets is a common choice.
- **Edges imply more world.** Paths, ropes and branches run off-screen; something moves in the far layers.
- **Soft fail.** Falling in water or a pit costs time, not progress; respawn keeps banked pickups.
- **Every placed object should do something**, or it is decoration and must look like decoration (hazed, behind the play plane).

## 7. The interaction audit (Gate B)

Play it with `livecheck.mjs` scripts, then let the game critic play it (`critics.md`). Tick what this game has (the PLAN's interaction inventory), and skip what it doesn't:
- [ ] Something travels or changes during normal play: camera, parallax, board state.
- [ ] Each verb has layered juice (§4).
- [ ] The things the player touches answer physically.
- [ ] If the world has living things, they notice the player, react, and settle back.
- [ ] If the world has a shared force (wind, current, a beat), it moves everything consistently.
- [ ] Nothing loops on an exact, visible period.
- [ ] Goals read: targets or pickups trace the route, the HUD reacts, and failure keeps progress.
- [ ] The attract demo shows the best interactions within its loop and passes `tune.cjs`.
- [ ] The hand-back says what to try.
