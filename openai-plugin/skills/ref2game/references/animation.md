# Animation: cut-out rigs and procedural motion for generated characters

**The bar is a finished, shipped game.** Players judge animation in the first seconds of a clip. Animate the way
UbiArt/Rayman, Spine and DragonBones games do: **painted parts, a skeleton, authored pose curves and procedural secondary
motion**. A rig reaches the bar when its parts are good (a part sheet, or an anchor drawn in a real rig pose: §1, §12),
its layering is right per view (§3), its poses are authored (§4), and it passes the measured checks of §14. Judge a rig
by those checks and by frame-by-frame sheets (§10), never by a glance at the live page.

- **Every actor animates: the player, enemies, every NPC and every animal** (the animation list, §13).
- **Never animate an action by transforming a whole sprite** (rotate, scale, squash, bob, sway). A worker who "works" by
  tilting, an animal that "grazes" by swaying, or a guard who "stabs" by sliding forward reads as no animation at all.
  Whole-sprite transforms are seasoning on top of a rig (a breath, a brief impact squash, a hit shake); `qa.mjs` fails a
  loop whose joints only move rigidly together.

## Contents
1. Getting parts from the generator
2. The two-bone limb (LIB.twoBone)
3. Layering: near side, far side
4. Poses as tables, blended by state
5. Cycles that stick to the ground
6. Secondary motion
7. Faces and state swaps
8. Critters and creatures (patterns)
9. Directional characters (top-down, iso)
10. Verify frame by frame (mandatory)
11. Lessons (bugs we actually shipped and fixed)
12. Locomotion musts (every character that walks)
13. The animation list: every actor, NPC and animal life
14. Measured checks (`qa.mjs` rig checks: the joint trace contract)
15. Natural 3/4 rigs: legs, arms, stance, held tools, joints, animals

---

## 1. Getting parts from the generator

1. **Anchor.** Generate the full character in a neutral rig pose: a strict view, feet under the hips, limbs clear of the
   body, nothing overlapping the torso. Get it approved in the frame.
2. **Part sheet.** Edit or generate with the anchor as a reference: the SAME character split into separate, complete parts
   on a transparent background with wide gaps. The usual parts:
   - the body and head without limbs;
   - one of each limb type, drawn straight, its root joint (hip, shoulder) at one end;
   - secondary parts the reference has (cape, tail, ears);
   - each complete, including the areas normally hidden.
3. **Slice and assemble.** `slice.py <sheet> name1,name2,...` writes the parts under the names the scene reads;
   `partrig.py` assembles a part sheet into a rig, and `rigcut.py` cuts the approved drawing itself (§12). Then measure the
   joint and attach points on the actual drawings. Check every part at 100%: complete, straight, joints where the anatomy
   puts them, nothing fused.
4. **One drawing per limb type** serves both sides (§3). Generate a second one only if the two sides genuinely differ (a
   weapon hand, a shield arm).
5. **Face variants** (blink, shout, hurt) are edits of the body part, then `variantfix.py` (§7).

## 2. The two-bone limb (LIB.twoBone)

One limb drawing is cut at the joint into two sub-rects (`split` = v of the cut). The upper bone rotates about the root (hip
or shoulder), the lower bone about the joint (knee or elbow). The upper piece is drawn over the lower one with a small
overlap, and a **round joint cap** in the limb's colour hides the seam at any angle.

```js
L.twoBone({ tex, p, a1, a2, face, rot, w, h, split, root: [u, v], joint: [u, v], r, col, u, capDark })
```

- **Measure `root`, `joint` and `split` on the actual drawing**, in uv: where the hip or shoulder centre is, and where the
  knee or elbow is. Guessed values give limbs that start in the wrong place.
- **Angles.** 0 means hanging straight down; positive is clockwise when facing right. The knee's a2 is positive (it bends
  backward); elbows are usually negative (they bend forward).
- `face = ±1` mirrors the whole limb chain via `M.s(face, 1)` at each bone.
- **Ground contact.** Body height comes from leg reach: `reach = Lthigh·cos(a1) + Lshin·cos(a1 + a2)`. Place the hips
  `reach` above the feet; that is what makes a squat lower the body.

## 3. Layering: near side, far side

Draw from far to near. Side view facing right:
1. **Far arm** first, behind the body, a little smaller and darker (its cap darker too): it is further away and in the
   body's shadow. Its shoulder sits behind the torso centre. Mostly hidden; the hand peeks out past the silhouette.
2. **Far leg**, behind the body, darker, its hip offset toward the front.
3. **Body** (+ head).
4. **Near leg**, its hip offset toward the back, so both legs read separately at rest.
5. **Near arm** last, in front of the body. Shoulder at the front-mid side of the torso (not at the face). Narrow enough not
   to hide the body.
6. **Cape, tail, hair** where the reference has them, usually behind the body, attached at the neck or back.

If the style has an outline, ink the **whole** puppet once (`L.inked`): the line goes around the silhouette, not around
every part, which is what shipped cut-out games look like.

## 4. Poses as tables, blended by state

A pose is a table of joint angles plus body rotation and squash.
- Keep named poses: `idle`, `squat` (anticipation/land), `rise`, `tuck` (apex), `fall`, `hurt`, plus the genre's own
  (attack windup/contact/recover, climb, swim).
- Blend with `L.lerpP(a, b, w)`, with the weights driven by the sim state (speed, vertical velocity, time since an event):
  - **ground:** idle (+ breath) toward the locomotion cycle as speed rises;
  - **air:** rise → tuck around the apex → fall, by vertical velocity;
  - **landing:** a squat impulse scaled by landing speed that decays quickly back into the current pose;
  - **takeoff:** a brief stretch;
  - **hurt:** a pose that fades out over the hurt state.
- **Squash and stretch keep the mass constant:** the actor widens as it shortens and thins as it stretches. Scale the
  amount with the event (a hard landing squashes more than a soft one).
- **Idle is never still:** a slow, subtle breath and a slight sway. Arms hang DOWN at idle; don't reuse a jump pose.

## 5. Cycles that stick to the ground

- **Phase from distance, not time.** `phase = dist / stride · 2π`, with `dist` accumulated in the sim from speed. The
  stride must match what the legs can cover, or the feet slide at every speed.
- **A run cycle shows:** thighs in antiphase; knees folding in the swing, nearly straight in stance; arms pumping against
  the same-side leg, elbows bending more on the forward swing; the body leaning into speed; one bob per step.
- **Multi-leg walkers** (insects, spiders, quadrupeds):
  - **Stance and swing.** In **stance** the foot sweeps BACKWARD relative to the body at ground speed; in **swing** it
    lifts and moves forward. If the feet sweep forward while the body moves forward, the creature "moonwalks". Check the
    direction against the body velocity.
  - **Hexapods** use a tripod gait: front and back legs on one side share a phase with the middle leg on the other.
  - **Quadrupeds** trot in diagonal pairs.
  - The body bobs once per step. Phase also comes from distance.

## 6. Secondary motion

- **Capes, scarves, ears, tails.** A damped spring in the sim toward a target angle driven by velocity and state (drag
  while running, lift while falling). Tune it to lag and settle, not to ring forever or snap. Add a travelling wave (sprite
  sway mode 3) whose amplitude grows with the spring's speed, the actor's speed and wind gusts.
  - **No discontinuities.** Never switch the target abruptly at a state change; the spring must carry the change. A cape
    that jerks at jump start is exactly this bug.
- **Hair, antennae, small attachments on the head:** the same spring, smaller.
- **Body follow-through:** a small rotation lag on start and stop (a spring on body rotation).
- **Wobble after impact.** Something squashed returns with a damped oscillation, `1 − A·e^(−kt)·cos(ωt)`, that settles
  within a few swings.

## 7. Faces and state swaps

- **Blinks.** Swap the body texture for the blink variant briefly, at irregular intervals, with a per-character phase.
  Shut the eyes during squashes, hurts and cowering.
- **The variant must be pixel-aligned and colour-matched to the base** (`variantfix.py`), or the swap flashes. The defect
  looks like "it changes colour when it blinks".
- **Expression swaps** (open mouth on jump, wince on hurt) use the same technique.
- **Procedural add-ons drawn in code** (an extra body part, a speech bubble) must match the art's rendering exactly. If they
  don't, cut them: a mismatched add-on reads worse than its absence.

## 8. Critters and creatures (patterns)

| Creature | Motion |
|---|---|
| Hopper (small hopping animal) | Discrete hops, each with an anticipation crouch, an arc sized to the body and a squash at takeoff and landing. Notice → anticipation → hop. Cower when cornered (squash, shiver, eyes shut). |
| Walker (insect, quadruped) | A rig with a gait (§5); an alert pose (rearing, trembling) when the hero is near |
| Flyer (bird, bat) | Body + wings rotating about the shoulder, flap rate fitting the size (small fliers flap fast). Fake foreshortening by scaling the wing across its stroke. The far wing is darker and phase-offset. Glide = slow or held flap; take-off arcs leave the screen. |
| Butterfly | Two wings, a fast flap, a wandering, non-repeating path; flees the hero |
| Blob, slime, round creature | Squash on its own pivot + bulge (sprite shader) + blink; stomped = a big squash with a dizzy reaction |
| Swinging prop | Not a creature, but the same spirit: a pendulum in the sim, bump impulses |

Critter behaviour (notice, flee, return) lives in the sim FSMs (`gamefeel.md` §3). The scene only poses them.

## 9. Directional characters (top-down, iso)

- **Views.** Generate front, side and back anchors (one turnaround sheet in one call keeps them consistent), then part
  sheets per view. Mirror the side view for the other side.
- **8 directions.** Generate the unique views and mirror the rest. Blend the rig between views only for slow turns; snap
  otherwise.
- **Walk.** The same two-bone legs, seen from the front: legs swing in depth, which reads as small vertical foot offsets
  plus alternating scale.
- **Frame-by-frame** is still right for small pixel-art sprites, where a rig's sub-pixel rotation looks mushy. See
  `genres.md` and `styles.md` for when to switch.

## 10. Verify frame by frame (mandatory)

Never judge animation from a single still or from memory. For every changed motion:
1. Render a **cycle sheet**: evenly spaced stills over one cycle, enough to show every contact and passing pose, cropped
   and zoomed so each joint is clear (`render.mjs stills` + `sheet.py --crop`; `qa.mjs` also writes `cycle_<name>.png`).
2. Check every frame for:
   - limbs attached at the right anatomical point (no arm out of the face);
   - near and far limbs on the correct sides and layers;
   - joints continuous with no gaps;
   - feet planted during stance, no sliding;
   - arcs smooth;
   - no pose popping between states;
   - secondary parts lagging rather than leading.
3. Check transitions (idle → run → jump → apex → land → run) slowed down (`[`) and single-stepping (`.`).
4. Give it to the **motion critic** (`critics.md`) with the sheets and the reference.

## 11. Lessons (bugs we actually shipped and fixed)

- **An arm came out of the face.** The shoulder anchor was guessed in body uv. Measure anchors on the drawing; verify with
  a zoom.
- **Both arms on the same side of the body.** The far arm sits behind the torso (drawn before the body), smaller and
  darker, its hand barely peeking out. The near arm attaches at the front-mid side.
- **No knees.** A one-piece leg rotating at the hip looks like a stilt. Use two bones per leg, with a visible knee bend in
  every pose.
- **Legs crossing wrong.** Give the near and far hips distinct offsets, so the legs read separately at rest.
- **An idle arm pointed sideways** (a jump pose reused). Idle arms hang down; the right "down" pose often already exists
  inside the run cycle.
- **A multi-legged walker's feet swept forward while it walked forward.** Stance sweeps backward (§5).
- **A cape jerked at jump start.** Its spring target switched discontinuously; blend it.
- **A blink flashed colour.** The variant was unaligned and not colour-matched; fixed with `variantfix`. Later `prep.py`
  overwrote the fix because it had been written to `live/assets` instead of `art/gen`. Fix in sources.
- **Effects left from the actor's feet.** Shots, beams and thrown things used the actor's ground point. The sim owns one
  origin function built from the rig's real geometry (shoulder, arm, grip), the arm points at the aim so the grip lands
  there, and `L.anchor` + `qa.mjs` check it in every pose.
- **The arm holding a forward-pointed item was drawn over the chest.** In side view a held, pointed item is in the **far**
  hand: that arm is drawn before the torso, darker, and only its forearm and the item show in front. The near arm swings
  free, on top.
- **Generated limb parts didn't match the approved character** (shorter, thicker, their tops pasted over the body). When
  the approved whole drawing separates cleanly, **cut the approved drawing itself** into parts (§12) instead of using a
  generated part sheet.
- **A walker limped and its boots dug into the ground.** The anchor's "rig pose" had the feet spread wide and the gait
  added its stride on top, so the head dipped unevenly on alternate steps. The boot was part of the shin, so it rotated
  with it and sank. Draw walkers with the feet under the hips, cut a separate foot that stays level and rolls heel → toe,
  and check the head height over a full cycle (equal dips on both steps).
- **Attacks broke for some target directions.** An end-angle wrap and clamp worked for targets to the side but sent the
  blade at the sky for targets straight below. Stage every attack against targets all round, densely enough that no
  direction band is skipped, and measure the blade against the target at the impact frame (§14).
- **Only the player was animated.** NPCs "worked" by tilting the whole sprite, a worker turned his back to his station to
  face the player, animals only swayed, and nobody walked. Every actor in the animation list (§13) gets a rig with real
  joints, and workers keep facing their station (§13).
- **Rounds of rig fixes kept missing defects a viewer saw at once** (a limp, boots in the ground, a blade pointing away at
  the hit, popping deaths). The checks were a glance and one limb-motion number. Measure every rig with the §14 checks on
  every change, and fix until they pass; the motion critic then judges what numbers can't.

## 12. Locomotion musts (every character that walks)

The user reads a sprite that glides, or bobs, as "the legs don't move". Every walker gets articulated legs:
- **Plant feet with explicit foot paths, not swinging thighs.** Drive the gait phase from distance, matched to the sim's
  step events (one stride = two steps). A periodic thigh angle still skates: its sweep matches body speed at one instant
  only. Give each foot a path: in stance it slides back at exactly body speed; in swing it eases forward with a lift arc
  and a toe tip. Solve the knee by two-bone IK from hip to ankle, and split the leg into thigh / shin / foot so the foot
  stays flat.
- **The hip rides the stance leg.** Hip height follows from the stance leg's geometry (highest over the straight stance
  leg, lowest at double support in a walk), not from a separate sine bob.
- **Knees fold in the swing**, with only a slight bend in stance.
- **Arms swing against the legs**, with less amplitude than the legs, and less again when aiming.
- **Front/back views:** the legs lift in turn (raise and shorten the swing leg), the body drops at contact.
- **Quadrupeds:** trot in diagonal pairs (near-front with far-back), far legs drawn first and darker; secondary parts react
  to speed and state.
- **Cut from the approved drawing** when the part sheet doesn't match it (`rigcut.py`): one sub-rect per part of the
  *same* texture, each placed as part of the whole (pivot in the whole's uv). Hide the hip joints under the body piece and
  put each pivot near its cut, so a swinging leg shows no kink or hole. At rest the pieces must reassemble the approved
  drawing pixel for pixel; check that before anything else.
- **Held items and their arm draw behind the near leg** when they hang at the side: far leg → far arm + item → near leg →
  body → near arm.
- **Blend pose switches** (aim in/out, draw/release, tool on/off) over a few frames from the state's toggle time: a
  one-frame snap reads as a glitch, a slow blend as lag. The frame where a shot leaves must still show the aiming pose.
- **Swaps between different drawings** (stand ↔ sit, normal ↔ shout) need a transition: a short squash, or a
  pixel-aligned variant of the same drawing (`variantfix.py`); never cut instantly between unaligned art.
- **Cuts through overlapping parts follow the overlap** (stair-stepped rects), so no part carries a sliver of its
  neighbour.
- **Layer by depth in 3/4 view:** limbs whose feet sit lower on screen than the body centre are drawn after the body, the
  far ones before (and darker).
- **Rest pose = approved sprite.** Whatever the rig, the idle frame must match the approved drawing in proportions and
  design; a rig that changes the character's look at rest is wrong.
- **Check:** `SCENE.QA().cycles` per walker and view (with the tool aimed too), then `qa.mjs` (limb-motion, anchor and rig
  checks, cycle sheets), then the motion critic on those sheets.

## 13. The animation list: every actor, NPC and animal life

Write the list into `study/PLAN.md` before rigging, one row per actor type and view, and give every row a rig:

| actor | motions |
|---|---|
| **player** | idle; walk or run; every attack or skill (ready → anticipation → peak → strike → **impact** → follow-through → recover); hit; death (the whole rig falls and stays); every other verb (cast, dodge, jump, pick up) |
| **enemies** | idle or patrol; walk; attack; hit; death |
| **NPCs** | a work or idle loop that fits the role (a worker at a station, a vendor handling goods, a guard shifting weight and scanning, a child playing), with the arms, head and torso moving at their joints; a walk for every NPC with a routine; a talk gesture |
| **animals, critters** | an idle loop that fits the species (feeding, looking around, resting), with neck/head, ears and tail as parts; a walk if it moves; a startle |
| **props alive in shipped games** | flags, doors, chests opening, fire, wheels and mechanisms: parts or a shader, never a static sprite |

- **Rig pose for every actor that moves**, NPCs and animals included: generate their anchors (or part sheets) with free
  limbs (§1). A drawing whose arms are painted over the body can't be rigged; regenerate it instead of faking motion.
- **Workers face their workstation and keep working.** Only idle or talking NPCs turn toward the player. A worker's drawing
  faces the station (put the station in the anchor prompt so the pose fits it).
- **Routines.** Some NPCs walk between a few points that make sense for their role, pause there to play their loop, and
  avoid obstacles and the player. A settlement where nobody walks reads as a diorama.
- **Loops get per-instance phase offsets and rates**, so two NPCs never move in sync. A loop's events (a tool's impact)
  come from its pose clock, so sparks and sounds land on the impact pose.

## 14. Measured checks (`qa.mjs` rig checks: the joint trace contract)

A viewer spots a limp, a sliding foot or a blade pointing away in one second; a glance at a still does not. So every rig
reports its joints and `qa.mjs` measures them on every run.

**Contract.** While `LIB.TRACE` is an object, rig code reports screen-space points each draw:
`L.joint(id, name, [x, y])`, with `id` naming the actor instance. Names (report what the actor has):
- `ground` (the ground point; per foot `groundL/R` where the ground differs), `head` (centre) or `top`, `hip` (pelvis
  centre). `ground` with `head` or `top` gives the actor's height H;
- per leg `hipL/R`, `kneeL/R`, `ankleL/R`, `heelL/R`, `toeL/R`;
- per arm `shL/R`, `elbowL/R`, `handL/R`;
- a held weapon or tool: `grip`, `tip`;
- in attack states, the aimed-at point: `target` (plus `targetLo` / `targetHi` for the target's body axis).

`SCENE.QA()` adds:
- `subject: { cycleOrLoopName: id }`: which actor each cycle, loop or transition measures;
- `cycles`: walk cycles, frames over exactly one cycle, the actor really travelling (x/y advance with `dist`, the camera
  following);
- `cycleT: { name: seconds per cycle }`: converts sampled frames to real time for rate checks;
- `loops`: idle and work loops of NPCs and animals, frames over one loop;
- `attacks: { name: { subject, states } }`: the impact frame of the attack against targets all round;
- `transitions: { name: [stateA, stateB, …] }`: consecutive frames 1/60 s apart across a state change (walk → stop, an
  interrupted windup, the first frames of a death);
- `actors`: every animated actor type (each one needs a cycle or a loop);
- `rest: { cycleName: state }`: the actor standing in the same view. Mark it `neutral: true` and have the rig draw the
  painted layout for it (no idle stance): it is the reference for unforeshortened segment lengths. `qa.mjs` also draws it
  without `neutral` to check the live standing pose (§15.4).

**Checks** (`--only rig`). Loops get the motion checks (nothing moves, rigid); walk cycles get all of them. Distances are
in fractions of H; the thresholds live in `qa.mjs`, and the measured values go to `report.json` → `rig` for the critic.

| check | what it detects |
|---|---|
| foot slide | a planted heel or toe (at its lowest) moving in world space between consecutive planted frames |
| ground | a heel or toe below its ground line |
| lift | a swing foot that never clearly leaves the ground |
| limp | the head's two step dips (half a cycle apart) differing; a head bob too small or too large |
| stride | the ankles spreading too wide for H |
| knee | the knee angle changing faster per 1/60 s than allowed (scaled by `cycleT`), or bending backwards |
| stretch | a thigh or shin longer than in `rest` (or the cycle median) beyond what projection explains, or shrinking past plausible foreshortening |
| stance | standing (`rest` drawn live, without `neutral`): ankles not clearly wider than the hips, or knees or ankles out of the hips' left-right order (crossed legs) |
| arms | an arm's swing along the travel direction correlating with its own leg's |
| rigid | joints that barely move, or that all fit one rotation + uniform scale + translation: a whole-sprite transform |
| weapon in ground | a held weapon's `tip` below the ground line during a cycle |
| aim | at the impact frame, the blade (`grip → tip`) not passing through or near `target` (or the `targetLo`–`targetHi` segment); the angle error is only reported |
| pop | a break in a joint's motion (its second difference between frames 1/60 s apart), not merely fast motion |
| coverage | an entry of `actors` with no cycle or loop |

Fix until they pass, then render the frame sheets (§10) and run the motion critic. The critic judges what the numbers
can't (appeal, weight, timing, silhouette), with the bar of a shipped game in this genre.

## 15. Natural 3/4 rigs: legs, arms, stance, held tools, joints, animals

What turned "unnatural, legs out of proportion, arms bent, holds the tool sideways" into motion a viewer accepts, in a 2:1
iso / 3/4 view with painted cut-out parts. Each point is a rule; most have a check in §14.

**15.1 Legs: a painted gait in the picture plane, not a 3D leg projected.** Projecting a 3D leg makes every step a crouch
(the foot stepping toward the camera reads as "leg too short" and pulls the hips down) and makes the trailing thigh stubby.
- Each foot target is its rest ankle plus the travel direction as seen on screen (in 2:1 iso, the y component halves)
  times the gait sweep, lifted in the swing (§12 foot paths). Solve the knee by two-bone IK from the painted hip.
- In a 3/4 view part of a knee's bend points toward the camera. Show only part of the IK fold as a sideways bend and the
  rest as a foreshortened shin. The knee never kinks far sideways.
- Let a leg stretch a little (within what the stretch check accepts, plus the extra a leg leaning toward the camera really
  shows on screen) before the hips have to drop, so a stride never turns into a crouch. Check the drop now and half a cycle
  later (no limp).
- Bob: a walk is highest over the stance leg; a run is lowest at mid-stance and highest in the flight. A runner lands under
  the hips and pushes off far behind (shift the stance sweep backward).
- Proportions are the painted ones: never scale a limb to reach. A leg that has to look clearly longer than painted means
  the stride or the drop is wrong.

**15.2 Arms: 3D swing, projected.** A 2D rotation of an arm in a 3/4 view moves the hand sideways out of the body (an
idle arm "bent", a far arm sticking out). Turn arms in 3D about the shoulder and project them with the view's projection
(in 2:1 iso, `screen y = −Y + Z/2`):
- build the arm as a hierarchy so the elbow hinge turns with the upper arm: the bend in the upper arm's own frame, then the
  humeral twist (what makes a bent forearm swing from the front to the side), abduction about the facing axis (away from
  the body), and the forward swing about the lateral axis;
- a forward-swung arm in a front view comes toward the camera (the hand moves along the facing direction, sideways AND
  down); in a back view it goes up and shortens;
- walking arms hang nearly straight and swing against the legs; running arms bend and pump; the arm holding a weapon swings
  less;
- idle arms hang: a small elbow bend and a little abduction, never a bent pose held at the side.

**15.3 Held weapons and tools.**
- The weapon's direction is the forearm's 3D direction plus its own grip angle, projected. A weapon held upright on its
  own (a grounded spear, a drawn bow) keeps its own tilt, and the hand slides along the shaft instead of the arm bending.
- **Facing away, the weapon goes behind the body:** draw it before the body (and its arm), whatever side it is on.
- **Strikes on a fixed target** (a tool on a workpiece): solve the shoulder swing and elbow bend so the tool head lands on
  the target at the impact. The lift raises the elbow out and up with the forearm up, and the elbow leads both the lift
  and the strike. A tool seen edge-on (from its narrow side) reads as held wrong: keep its broad side to the camera.
- Keep the tool in the hand the drawing and the user expect (usually the right one); after a mirror, pick the hand by view.
  Don't swap hands when the actor turns: the item visibly jumps from hand to hand.
- An upright item held at the side in the far hand (a spear, a staff, a banner) drawn with the far arm sits behind the body
  and only its ends show, as if it were lost. Draw it over the body in the layer order, after the body and before the near
  arm, and keep the far arm itself behind.

**15.4 Standing: a relaxed stance, not the painted layout.** Feet straight under narrow painted hips read as a soldier at
attention, and from behind as crossed legs.
- Place the feet in 3D a little wider than the hips along the body's lateral axis, so in a 3/4 view the far foot sits
  higher on screen.
- Contrapposto: the weight on one leg (the pelvis over that foot), the free foot out and a little forward, its heel
  slightly up, both knees soft.
- Shift the weight to the other leg now and then (eased, per-instance phase). Blend the stance in as the gait amount falls,
  so a stop settles into it foot by foot.
- Checked by the `qa.mjs` stance check. The `rest` reference is drawn `neutral` (the painted layout), so the soft knees
  don't count as segment shortening.

**15.5 Joints stay round.** Two straight cut pieces meeting at a bent elbow or knee show a corner or a gap. Draw a round
cap:
- a disc of the upper segment's own texture, with radius = the limb's half-width there, measured from the part's alpha
  (`jointr.py`);
- laid over the joint and turned with the upper segment;
- fading in with the bend (`disc` uniform of the sprite shader).

**15.6 Animals from one painted sprite: soft bones.** When an animal is a single painting, bend it in the shader instead
of cutting it: a weight map per bone (R/G/B, `softbones.py`), every pixel turned about the bone's root by angle × weight,
drawn by inverse mapping (`bone0..2`, `wtex`, `wsz` uniforms of the sprite shader).
- Bend at the base: ramp the weight over the base of a neck only, then let it turn rigidly. A ramp over the whole neck
  curls it into a camel's arc.
- Fade the weight to 0 along the seam where the bone leaves the body (shoulder, chest): the body stretches there instead of
  tearing a notch.
- A child bone for the head (it flexes where the head meets the neck, then rides on the neck): a raised head tucks its nose
  down, a lowered one hangs. Without it a lifted head points its nose at the sky.
- The inverse map has several exact sources for one pixel (the background under the raised head maps to itself too): pick
  the opaque one, then the one that moved more. Sample weights and colour with an explicit LOD (warped lookups have no
  usable derivatives).
- The region leaves out legs, reins and anything that must stay; it may include the background around it.
- Know the limit: one painting reads only up to a moderate change of pose. Past that, generate a second pose of the same
  animal or a part sheet (neck + head as a part over a body with a complete chest).
- Report the warped head, tail and ground joints (the forward map of the bone tips). Give each animal its idle behaviour as
  a loop in `SCENE.QA().loops`, so `qa.mjs` measures it.

**15.7 Sizes.** Calibrate each character's on-screen height on the figure (head to sole), never on the drawing's box: a
spear or staff held above the head shrinks the person who holds it.
