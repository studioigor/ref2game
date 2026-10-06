// live/scene.js — TOP-DOWN (3/4 view) scene. Pure function of t and the sim state, same contract as the side template.
// Layers: tiled ground (REPEAT texture in world space) → path/decals → drifting cloud shadows → ground shadows →
// Y-SORTED objects (trunks, rocks, grass, pickups, critters, hero) → canopies (fade when the hero is underneath) → FX → HUD.
(function () {
  const S = (window.SCENE = {}), A = window.ASSETS, L = LIB, M = L.M, W = SIM.VIEW.W, H = SIM.VIEW.H;
  S.REPEAT = ['ground_tex'];
  S.programs = () => { L.init(W, H); L.glyphs(); L.SUN = [W * 0.2, -400]; };
  const TUFT = ['tuft_0', 'tuft_1', 'tuft_2'], DUST = [0.80, 0.74, 0.58], INK = [0.12, 0.08, 0.03];
  const SHADOW_DIR = [26, 14];                                  // light from the upper left: shadows fall right-down

  S.render = (t) => {
    const ST = S.state || SIM.at(t), GT = ST.t, SS = L.SS, rnd = L.rnd;
    let shk = 0; for (const e of ST.ev) { const a = GT - e.t; if (e.k === 'dash' && a >= 0 && a < 0.2) shk = Math.max(shk, 2.5 * (1 - a / 0.2) ** 2); }
    const cx = ST.cam[0] + shk * Math.sin(GT * 91), cy = ST.cam[1] + shk * Math.sin(GT * 117);
    const sx = (x) => x - cx, sy = (y) => y - cy;                              // world → screen
    const gw = (x) => SIM.gustAt(t, x), wnd = (x) => SIM.windAt(t, x);

    // ===== ground =====
    L.beginBG([0.2, 0.3, 0.15, 1]);
    { const T = 512; L.sprite('ground_tex', 0, 0, { w: W, h: H, src: [cx / T, cy / T, (cx + W) / T, (cy + H) / T] }); }
    L.sprite('path', sx(560), sy(560), { w: 1500, u: { alpha: 0.9 } }); L.sprite('path', sx(1360), sy(880), { w: 900, rot: 0.25, u: { alpha: 0.9 } });
    // drifting cloud shadows (fbm, dark, moving with the wind) — the cheapest "alive" signal in a top-down scene
    L.fog(-200, H + 400, [0.0011, 0.03 + 0.02 * gw(900), 0.52, 0.32], [0.05, 0.10, 0.08], 7, t, 0);
    L.beginComp();

    // ground shadows of everything (one soft ellipse each), then the Y-sorted objects
    for (const [x, y, s] of SIM.TREES) L.shadow(sx(x) + SHADOW_DIR[0] * 3 * s, sy(y) - 30 * s + SHADOW_DIR[1] * 3, 150 * s, 90 * s, 0.35);
    for (const [x, y, s] of SIM.ROCKS) L.shadow(sx(x) + SHADOW_DIR[0] * s, sy(y) + SHADOW_DIR[1] * 0.5, 90 * s, 34 * s, 0.4);
    const Y = [];                                                              // [ground y, draw]
    SIM.TREES.forEach(([x, y, s]) => Y.push([y, () => { const h = 150 * s; L.sprite('tree_trunk', sx(x) - L.hsz('tree_trunk', h) / 2, sy(y) - h, { h, u: { rim: [0.3, -0.004, -0.004, 1] } }); }]));
    SIM.ROCKS.forEach(([x, y, s]) => Y.push([y, () => { const h = 120 * s; L.sprite('rock', sx(x) - L.hsz('rock', h) / 2, sy(y) - h, { h, u: { rim: [0.35, -0.004, -0.004, 1] } }); }]));
    SIM.TUFTS.forEach(([x, y, kind, th], i) => Y.push([y, () => { const n = TUFT[kind], f = ST.tf[i], w = L.hsz(n, th), fl = rnd(i, 12) > 0.5;
      const lean = Math.max(-0.34, Math.min(0.34, f[0] / w)) * (fl ? -1 : 1), hh = th * (1 - 0.45 * f[3]);       // flattened underfoot
      L.sprite(n, sx(x) - w / 2, sy(y) - hh, { w, h: hh, pad: 0.36, flip: fl, u: { lean: [lean, 0], sway: [0.005 + 0.004 * Math.abs(wnd(x)), 5, t * (2 + rnd(i, 13)) + 6.28 * rnd(i, 11), 1], vfade: 0.15 } }); }]));
    SIM.COINS.forEach(([x, y], i) => { const g = ST.got[i]; if (g >= 0 || g === -2) return;
      Y.push([y + 30, () => { const b = 8 * Math.sin(t * 3 + i), cw = 46; L.shadow(sx(x), sy(y) + 30, 18, 6, 0.3); L.glow(sx(x), sy(y) - b, 50, [1, 0.7, 0.2], 0.25, 3.8);
        L.sprite('coin', 0, 0, { m: M.of(M.t(sx(x), sy(y) - b), M.s(Math.cos(t * 2.4 + i), 1)), w: cw, h: cw, pivot: [cw / 2, cw / 2] }); }]); });
    ST.cr.forEach((c, i) => { let x = c.x, y = c.y, z = 0, q = 1;
      if (c.hop) { const u = Math.min(1, (GT - c.hop.t0) / c.hop.dur); x = c.hop.x0 + (c.hop.x1 - c.hop.x0) * u; y = c.hop.y0 + (c.hop.y1 - c.hop.y0) * u; z = c.hop.ht * 4 * u * (1 - u); q = 1 + 0.15 * Math.sin(Math.PI * u); }
      else if (c.n >= 0) q = 0.88;                                             // noticed: crouch
      Y.push([y, () => { const h = 54, w = L.hsz('critter', h); L.shadow(sx(x), sy(y), 22 * (1 - z / 90), 7, 0.4);
        L.sprite('critter', 0, 0, { m: M.of(M.t(sx(x), sy(y) - z), M.s(c.face / Math.sqrt(q), q)), w, h, pivot: [w / 2, h * 0.95], u: { rim: [0.4, -0.004, -0.005, 1] } }); }]); });
    // hero: body bob + lean into motion + two feet stepping (top-down rigs: body + feet + optional arms)
    Y.push([ST.y, () => {
      const sp = Math.hypot(ST.vx, ST.vy), run = Math.min(1, sp / 200), ph = ST.dist / 70 * Math.PI, dash = GT - ST.dashT < 0.16;
      const bob = run * 7 * Math.abs(Math.sin(ph)), q = 1 + 0.04 * run * Math.cos(2 * ph) + (dash ? -0.1 : 0), lean = ST.vx * 0.0005;
      const hx = sx(ST.x), hy = sy(ST.y);
      L.shadow(hx, hy, 34, 10, 0.45);
      const draw = () => {
        for (const side of [-1, 1]) { const st = Math.sin(ph + (side > 0 ? 0 : Math.PI)) * run; L.shadow(hx + side * 13 + st * 8 * ST.faceX, hy - 4 - Math.max(0, st) * 6, 11, 7, L.sp ? 0 : 0.9); }
        const h = 110, w = L.hsz('hero_top', h);
        L.sprite('hero_top', 0, 0, { m: M.of(M.t(hx, hy - 8 - bob), M.r(lean), M.s(ST.faceX / Math.sqrt(q), q)), w, h, pivot: [w / 2, h], u: { rim: ST.faceX > 0 ? [0.5, -0.0035, -0.005, 1] : [0.5, 0.0035, -0.005, 1] } }); };
      L.inked(draw, { r: 2.2, col: INK }); }]);
    Y.sort((a, b) => a[0] - b[0]).forEach(([, d]) => d());

    // canopies above everything; fade when the hero walks under one (keeps the player readable)
    SIM.TREES.forEach(([x, y, s], i) => { const h = 380 * s, w = L.hsz('tree_canopy', h), top = y - 150 * s - h * 0.78;
      const under = Math.abs(ST.x - x) < w * 0.42 && ST.y < y + 20 && ST.y > top + h * 0.2;
      const ox = 6 * wnd(x) + 10 * gw(x);
      L.sprite('tree_canopy', sx(x) - w / 2 + ox, sy(top), { w, h, pad: 0.04, u: { alpha: under ? 0.45 : 1, sway: [0.006 * (1 + gw(x)), 4, L.ph(t, 3.7, i), 1], rim: [0.4, -0.004, -0.005, 1] } }); });

    // ===== event FX =====
    for (const e of ST.ev) { const a = GT - e.t; if (a < 0) continue; const ex = sx(e.x), ey = sy(e.y);
      if (e.k === 'step' && a < 0.4) { const q = a / 0.4; L.puff(ex - ST.vx * 0.05, ey - 4 - 10 * q, 6 + 9 * q, DUST, 0.4 * (1 - q), e.t * 10); }
      if (e.k === 'dash' && a < 0.5) for (let j = 0; j < 6; j++) { const q = a / 0.5, s = rnd(e.t, j);
        L.puff(ex - e.dx * (20 + 90 * q * s), ey - e.dy * (20 + 90 * q * s) - 6, 8 + 14 * q, DUST, 0.5 * (1 - q), e.t + j); }
      if (e.k === 'rustle' && a < 0.6) for (let j = 0; j < 4; j++) { const q = a / 0.6, s = rnd(e.t, j + 3);
        L.puff(ex + e.d * (50 + 90 * s) * a + (j - 1.5) * 9, ey - (150 + 120 * s) * a + 420 * a * a, 4, [0.45, 0.75, 0.3], 0.9 * (1 - q), j); }
      if ((e.k === 'flee' || e.k === 'hopland') && a < 0.35) { const q = a / 0.35; for (let j = 0; j < 3; j++) L.puff(ex + (j - 1) * 14 * (0.5 + q), ey - 3, 5 + 6 * q, DUST, 0.35 * (1 - q), e.t + j); }
      if (e.k === 'collect' && a < 0.6) { const q = a / 0.6;
        for (let j = 0; j < 8; j++) { const an = j * Math.PI / 4 + e.t, d = 16 + 56 * (1 - (1 - q) ** 2); L.star(ex + Math.cos(an) * d, ey + Math.sin(an) * d, 11, [1.0, 0.9, 0.45], 1 - q); }
        L.ring(ex, ey, 20 + 40 * q, 20 + 40 * q, [1, 0.95, 0.7], 1 - q); }
    }
    L.finish(t, { bloom: [0.18, 0.16], vignette: 0.9 });

    // ===== HUD =====
    const TOK = [W - 250, 80]; let n = (ST.loop !== undefined ? ST.loop * SIM.COINS.length : ST.bank) + ST.got.filter((g) => g >= 0 && GT - g >= 0.4).length;
    L.shadow(W - 190, 82, 175, 66, 0.30); L.sprite('coin', TOK[0] - 42, TOK[1] - 42, { w: 84, h: 84 });
    L.text('×' + String(n).padStart(2, '0'), TOK[0] + 60, TOK[1] + 4, 58, 0);
  };
  // QA hooks for <skill>/scripts/qa.mjs (references/engine.md §7): every HUD screen with worst-case values, and an 8-frame
  // cycle per walking actor and view (+ sprites: the textures it is drawn from, box: its screen box). Grow this with the game.
  S.QA = () => {
    const base = (o = {}) => { const s = SIM.spawn(0); for (let i = 0; i < 120; i++) SIM.step(s, {}); return Object.assign(s, o); };
    return { states: [['start', base()]], cycles: {}, sprites: {}, box: () => [0, 0, W, H] };
  };
})();
