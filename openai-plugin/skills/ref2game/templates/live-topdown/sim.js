// live/sim.js — deterministic TOP-DOWN (3/4 view) simulation, fixed 120 Hz. Same contract as the side-view template:
// create / step / at / spawn / respawn / outOfPlay / scriptInput, events in S.ev, every reaction lives here.
// Mover: 8-direction run with accel/decel + dash (act). Collision: circles (trunks, rocks) + world bounds.
// Reactions: grass tufts lean away and flatten underfoot, critters notice → flee (hops) → return, wind gusts.
(function (root) {
  const DT = 1 / 120, L = 10.0;
  const K = { RUN: 330, ACC: 2400, DEC: 2800, DASH: 900, DASH_T: 0.16, DASH_CD: 0.5, R: 26 };
  const VIEW = { W: 1920, H: 1080 }, WORLD = { x0: 0, y0: 0, x1: 2600, y1: 1500 };

  // ---------------- the level, as data (y = ground contact point; draw order = y) ----------------
  const TREES = [[420, 520, 1.0], [980, 360, 1.15], [1500, 760, 1.0], [2050, 420, 1.2], [700, 1150, 1.05], [1900, 1180, 0.95]];
  const ROCKS = [[1240, 980, 1.0], [560, 820, 0.8], [2250, 900, 1.1]];
  const SOLIDS = [...TREES.map(([x, y, s]) => ({ x, y: y - 6, r: 30 * s })), ...ROCKS.map(([x, y, s]) => ({ x, y: y - 10, r: 56 * s }))];
  const TUFTS = []; for (let i = 0; i < 46; i++) { const h = (n) => { const v = Math.sin(n * 127.1 + i * 311.7) * 43758.5453; return v - Math.floor(v); };
    TUFTS.push([220 + h(1) * 2200, 240 + h(2) * 1100, Math.floor(h(3) * 3), 54 + 40 * h(4)]); }
  const COINS = [[640, 700], [705, 640], [880, 600], [1180, 560], [1320, 620], [1640, 980], [1780, 975], [1920, 1000]];
  const CRITTERS = [[1100, 820], [1700, 600], [600, 1000]];          // homes
  // attract route: [time, targetX, targetY] — the scripted input steers toward the current waypoint
  const ROUTE = [[0, 640, 700], [1.2, 880, 600], [2.2, 1180, 560], [3.0, 1320, 620], [3.8, 1150, 870], [5.0, 1640, 980], [6.2, 1920, 1000], [8.0, 1500, 1060], [9.0, 1000, 900]];

  const h1 = (n) => { const v = Math.sin(n * 127.1 + 311.7) * 43758.5453; return v - Math.floor(v); };
  const GUST = 14, GUST_V = 360;
  const gusts = (t) => { const k = Math.floor(t / GUST), out = [];
    for (const kk of [k - 1, k]) { const t0 = kk * GUST + 2 + 6 * h1(kk); if (t < t0) continue;
      const front = -500 + GUST_V * (t - t0); if (front < WORLD.x1 + 1000) out.push({ k: kk, t0, front, amp: 0.8 + 0.7 * h1(kk + 0.5) }); }
    return out; };
  const gustAt = (t, x) => { let g = 0; for (const q of gusts(t)) { const d = x - q.front; g += q.amp * Math.exp(-((d / (d > 0 ? 140 : 420)) ** 2)); } return g; };
  const windAt = (t, x) => 0.25 * Math.sin(0.6 * t + 0.013 * x) + 0.12 * Math.sin(1.7 * t + 0.031 * x + 1.3) + gustAt(t, x);
  const ss = (e0, e1, x) => { const q = Math.max(0, Math.min(1, (x - e0) / (e1 - e0))); return q * q * (3 - 2 * q); };

  function create() {
    return { t: 0, steps: 0, wt0: 0, x: 520, y: 760, vx: 0, vy: 0, faceX: 1, faceY: 1, dist: 0, dashT: -9, dashCD: 0, prevAct: 0,
      landT: -9, hurtT: -9, hearts: 3, bank: 0, freeze: 0, ev: [], cam: [0, 0], camV: [0, 0],
      got: COINS.map(() => -1), tf: TUFTS.map(() => [0, 0, -9, 0]),        // lean px, lean vel, last rustle, flatten 0..1
      cr: CRITTERS.map(([x, y]) => ({ x, y, m: 'idle', t0: -9, hx: x, hy: y, n: -1, hop: null, face: 1 })) };
  }
  const spawn = (worldT) => Object.assign(create(), { wt0: worldT });
  const respawn = (S, worldT) => { const bank = S.bank + S.got.filter((g) => g >= 0).length, all = !S.got.includes(-1);
    return Object.assign(spawn(worldT), { bank, got: all ? S.got.map(() => -1) : S.got.map((g) => (g === -1 ? -1 : -2)) }); };
  const outOfPlay = () => false;

  function step(S, inp) {
    const t = S.t + DT, wt = S.wt0 + t;
    // ---- grass: lean away from the hero (x only: tufts are drawn upright in 3/4 view) + flatten underfoot ----
    TUFTS.forEach(([tx, ty, , th], i) => { const f = S.tf[i]; let tg = 10 * windAt(wt, tx) * th / 100, flat = 0;
      const dx = tx - S.x, dy = (ty - S.y) * 1.6, d = Math.hypot(dx, dy);
      if (d < 90) { const w = ss(90, 14, d); tg += Math.sign(dx || 1) * 0.32 * th * w + S.vx * 0.012 * w; flat = ss(40, 8, d);
        if (w > 0.6 && Math.hypot(S.vx, S.vy) > 120 && t - f[2] > 0.5) { f[2] = t; S.ev.push({ k: 'rustle', t, x: tx, y: ty - th * 0.5, i, d: Math.sign(S.vx || 1) }); } }
      f[1] += (355 * (tg - f[0]) - 11 * f[1]) * DT; f[0] += f[1] * DT; f[3] += (flat - f[3]) * Math.min(1, (flat > f[3] ? 14 : 2.5) * DT); });
    // ---- critters: idle (small hops near home) → notice (0.15 s crouch) → flee hops → return home when the hero is far ----
    S.cr.forEach((c, i) => { const d = Math.hypot(c.x - S.x, c.y - S.y);
      if (c.hop) { const u = (t - c.hop.t0) / c.hop.dur; if (u >= 1) { c.x = c.hop.x1; c.y = c.hop.y1; c.hop = null; S.ev.push({ k: 'hopland', t, x: c.x, y: c.y }); } return; }
      const hop = (x1, y1, dur, ht) => { x1 = Math.max(WORLD.x0 + 40, Math.min(WORLD.x1 - 40, x1)); y1 = Math.max(WORLD.y0 + 80, Math.min(WORLD.y1 - 40, y1));
        c.hop = { t0: t, x0: c.x, y0: c.y, x1, y1, dur, ht }; c.face = Math.sign(x1 - c.x) || c.face; };
      if (d < 170) { if (c.n < 0) c.n = t; if (t - c.n > 0.15) { const ax = (c.x - S.x) / (d || 1), ay = (c.y - S.y) / (d || 1); c.m = 'flee'; c.t0 = t;
          hop(c.x + ax * 110 + 30 * (h1(t * 7 + i) - 0.5), c.y + ay * 110, 0.3, 34); S.ev.push({ k: 'flee', t, x: c.x, y: c.y }); } }
      else { c.n = -1;
        if (c.m === 'flee' && d > 360 && t - c.t0 > 1.5) c.m = 'return';
        if (c.m === 'return') { const hx = c.hx - c.x, hy = c.hy - c.y, hd = Math.hypot(hx, hy); if (hd < 8) c.m = 'idle'; else hop(c.x + hx / hd * Math.min(90, hd), c.y + hy / hd * Math.min(90, hd), 0.32, 26); }
        else if (c.m === 'idle' && h1(Math.floor(t * 0.7) + i * 13) > 0.8 && Math.abs((t * 0.7) % 1) < DT * 0.7) hop(c.hx + 40 * (h1(t + i) - 0.5), c.hy + 30 * (h1(t + i + 3) - 0.5), 0.26, 18); } });
    if (S.freeze > 0) { S.freeze -= DT; S.t = t; S.steps++; return S; }
    // ---- input: 8-direction run with accel / decel, dash on action ----
    const ix = (inp.right ? 1 : 0) - (inp.left ? 1 : 0), iy = (inp.down ? 1 : 0) - (inp.up ? 1 : 0), il = Math.hypot(ix, iy) || 1;
    const tx = ix / il * K.RUN, ty = iy / il * K.RUN;
    const app = (v, tgt) => { const a = (Math.abs(tgt) > Math.abs(v) ? K.ACC : K.DEC) * DT; return v < tgt ? Math.min(tgt, v + a) : Math.max(tgt, v - a); };
    S.vx = app(S.vx, tx); S.vy = app(S.vy, ty);
    if (ix) S.faceX = ix; if (ix || iy) S.faceY = iy || S.faceY;
    const actEdge = (inp.act || inp.jump) && !S.prevAct; S.prevAct = inp.act || inp.jump; S.dashCD = Math.max(0, S.dashCD - DT);
    if (actEdge && S.dashCD <= 0 && (ix || iy)) { S.dashT = t; S.dashCD = K.DASH_CD; S.ev.push({ k: 'dash', t, x: S.x, y: S.y, dx: ix / il, dy: iy / il }); }
    const dashing = t - S.dashT < K.DASH_T, sp = Math.hypot(S.vx, S.vy) || 1;
    const mvx = dashing ? S.vx / sp * K.DASH : S.vx, mvy = dashing ? S.vy / sp * K.DASH : S.vy;
    S.x += mvx * DT; S.y += mvy * DT;
    for (const o of SOLIDS) { const dx = S.x - o.x, dy = (S.y - o.y) * 1.4, d = Math.hypot(dx, dy), r = o.r + K.R;     // ellipse-ish ground footprint
      if (d < r && d > 0) { S.x = o.x + dx / d * r; S.y = o.y + dy / d * r / 1.4; } }
    S.x = Math.max(WORLD.x0 + 40, Math.min(WORLD.x1 - 40, S.x)); S.y = Math.max(WORLD.y0 + 120, Math.min(WORLD.y1 - 30, S.y));
    const moved = Math.hypot(mvx, mvy) * DT;
    if (moved > 0.05) { const b = Math.floor(S.dist / 70); S.dist += moved; if (Math.floor(S.dist / 70) !== b) S.ev.push({ k: 'step', t, x: S.x, y: S.y }); }
    S.got.forEach((g, i) => { if (g !== -1) return; const [cx, cy] = COINS[i]; if (Math.hypot(cx - S.x, cy - (S.y - 30)) < 56) { S.got[i] = t; S.ev.push({ k: 'collect', t, x: cx, y: cy, i }); } });
    // ---- camera: follow with look-ahead in the move direction, clamped to the world ----
    const tgx = Math.max(WORLD.x0, Math.min(WORLD.x1 - VIEW.W, S.x - VIEW.W / 2 + S.vx * 0.35));
    const tgy = Math.max(WORLD.y0, Math.min(WORLD.y1 - VIEW.H, S.y - VIEW.H / 2 + S.vy * 0.3));
    S.camV[0] += (30 * (tgx - S.cam[0]) - 11 * S.camV[0]) * DT; S.cam[0] += S.camV[0] * DT;
    S.camV[1] += (30 * (tgy - S.cam[1]) - 11 * S.camV[1]) * DT; S.cam[1] += S.camV[1] * DT;
    if (S.ev.length > 64) S.ev.splice(0, S.ev.length - 64);
    S.t = t; S.steps++; return S;
  }

  // attract input: steer toward the waypoint of the current time window (depends on the state → deterministic replay)
  const scriptInput = (t, S) => { let w = ROUTE[0]; for (const r of ROUTE) if (r[0] <= t + 1e-9) w = r;
    const dx = w[1] - S.x, dy = w[2] - S.y, inp = { left: 0, right: 0, up: 0, down: 0, jump: 0, act: 0 };
    if (Math.hypot(dx, dy) > 24) { if (Math.abs(dx) > 14) inp[dx > 0 ? 'right' : 'left'] = 1; if (Math.abs(dy) > 14) inp[dy > 0 ? 'down' : 'up'] = 1; }
    return inp; };
  let cache = null;
  function at(t) {
    const loop = Math.floor(t / L), q = t - loop * L, n = Math.round(q / DT);
    if (!cache || cache.loop !== loop || cache.S.steps > n) { const S0 = Object.assign(create(), { wt0: loop * L }); S0.cam = [Math.max(0, S0.x - VIEW.W / 2), Math.max(0, S0.y - VIEW.H / 2)]; cache = { loop, S: S0 }; }
    const S = cache.S; while (S.steps < n) step(S, scriptInput(S.t, S));
    return Object.assign({}, S, { loop, q });
  }
  root.SIM = { DT, L, K, VIEW, WORLD, TREES, ROCKS, SOLIDS, TUFTS, COINS, CRITTERS, gusts, gustAt, windAt, create, spawn, respawn, outOfPlay, step, at, scriptInput };
  if (typeof module !== 'undefined') module.exports = root.SIM;
})(typeof window !== 'undefined' ? window : globalThis);
