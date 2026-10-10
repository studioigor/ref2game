// live/sim.js — BLANK base: an empty stage with pointer + keyboard input wired, for games without a closer base
// (puzzle, cards, board, point-and-click, VN, tactics…). Same contract as the other bases: deterministic 120 Hz steps,
// create/step/at/spawn/scriptInput, events in S.ev. Replace ITEMS and the click rule with the actual game.
// Input fields: px, py (pointer in view px), press (button held), click (true for one step); left/right/up/down/jump/act keys.
(function (root) {
  const DT = 1 / 120, L = 8.0, VIEW = { W: 1920, H: 1080 };
  const ITEMS = [[560, 420], [960, 360], [1360, 420], [560, 720], [960, 780], [1360, 720]], R = 80;   // hotspots and their hit radius
  const ROUTE = ITEMS.map((p, i) => [0.8 + i * 1.05, p]);                                          // attract: [click time, target]

  const create = () => ({ t: 0, steps: 0, wt0: 0, x: VIEW.W / 2, y: VIEW.H / 2, press: 0, ev: [],
    got: ITEMS.map(() => -1),                               // -1 available, ≥0 time taken
    hov: ITEMS.map(() => [0, 0]) });                        // hover spring per item: [value, velocity]
  const spawn = (worldT) => Object.assign(create(), { wt0: worldT });

  function step(S, inp) {
    const t = S.t + DT;
    if (inp.px !== undefined) { S.x = inp.px; S.y = inp.py; }
    S.press = inp.press ? 1 : 0;
    ITEMS.forEach(([x, y], i) => { const on = S.got[i] === -1 && Math.hypot(S.x - x, S.y - y) < R, h = S.hov[i];
      h[1] += (300 * ((on ? (S.press ? 0.4 : 1) : 0) - h[0]) - 16 * h[1]) * DT; h[0] += h[1] * DT;      // underdamped: overshoot reads as "alive"
      if (on && inp.click) { S.got[i] = t; S.ev.push({ k: 'collect', t, x, y }); } });
    if (inp.click && !S.ev.some((e) => e.t === t)) S.ev.push({ k: 'tap', t, x: S.x, y: S.y });
    S.t = t; S.steps++; return S;
  }

  // attract: the cursor glides to each item and clicks it (smoothstep between targets)
  const scriptInput = (t) => { let from = [VIEW.W / 2, VIEW.H / 2], t0 = 0;
    for (const [tc, p] of ROUTE) { if (t < tc) { const u = Math.max(0, Math.min(1, (t - t0 - 0.2) / (tc - t0 - 0.35))), e = u * u * (3 - 2 * u);
        return { px: from[0] + (p[0] - from[0]) * e, py: from[1] + (p[1] - from[1]) * e, press: tc - t < 0.08 }; }
      if (t < tc + DT) return { px: p[0], py: p[1], press: 1, click: 1 };
      from = p; t0 = tc; }
    return { px: from[0], py: from[1], press: 0 }; };
  let cache = null;
  function at(t) {
    const loop = Math.floor(t / L), q = t - loop * L, n = Math.round(q / DT);
    if (!cache || cache.loop !== loop || cache.S.steps > n) cache = { loop, S: Object.assign(create(), { wt0: loop * L }) };
    const S = cache.S; while (S.steps < n) step(S, scriptInput(S.t, S));
    return Object.assign({}, S, { loop, q });
  }
  root.SIM = { DT, L, VIEW, ITEMS, R, create, spawn, step, at, scriptInput };
  if (typeof module !== 'undefined') module.exports = root.SIM;
})(typeof window !== 'undefined' ? window : globalThis);
