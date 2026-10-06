// live/scene.js — BLANK base scene: backdrop, hotspots with hover/press springs, a soft cursor, event FX, HUD counter.
// Pure function of t and the sim state (same contract as the other bases). Replace with the game's board, cards, room…
(function () {
  const S = (window.SCENE = {}), L = LIB, M = L.M, W = SIM.VIEW.W, H = SIM.VIEW.H;
  S.programs = () => { L.init(W, H); L.glyphs(); };
  S.render = (t) => {
    const ST = S.state || SIM.at(t), GT = ST.t;
    L.beginBG([0.1, 0.1, 0.12, 1]); L.sprite('bg_sky', 0, 0, { w: W, h: H }); L.beginComp();
    SIM.ITEMS.forEach(([x, y], i) => { const g = ST.got[i], a = g >= 0 ? GT - g : -1; if (a > 0.3) return;
      const h = ST.hov[i][0], pop = a >= 0 ? 1 + 1.2 * a : 1, s = (1 + 0.16 * h) * pop, cw = 130, b = 6 * Math.sin(t * 2.2 + i * 1.7);
      L.shadow(x, y + 74, 54 * (1 - 0.1 * h), 13, 0.3); L.glow(x, y + b, 110, [1, 0.8, 0.4], 0.12 + 0.3 * h, 3.5);
      L.sprite('coin', 0, 0, { m: M.of(M.t(x, y + b - 10 * h), M.s(s, s)), w: cw, h: cw, pivot: [cw / 2, cw / 2], u: { alpha: a >= 0 ? 1 - a / 0.3 : 1 } }); });
    for (const e of ST.ev) { const a = GT - e.t; if (a < 0) continue;
      if (e.k === 'collect' && a < 0.6) { const q = a / 0.6;
        for (let j = 0; j < 8; j++) { const an = j * Math.PI / 4 + e.t, d = 20 + 70 * (1 - (1 - q) ** 2); L.star(e.x + Math.cos(an) * d, e.y + Math.sin(an) * d, 13, [1, 0.9, 0.45], 1 - q); }
        L.ring(e.x, e.y, 30 + 60 * q, 30 + 60 * q, [1, 0.95, 0.7], 1 - q); }
      if (e.k === 'tap' && a < 0.35) { const q = a / 0.35; L.ring(e.x, e.y, 14 + 30 * q, 14 + 30 * q, [1, 1, 1], 0.6 * (1 - q)); } }
    L.glow(ST.x, ST.y, 46, [1, 0.95, 0.85], 0.35 + 0.3 * ST.press, 3);                                  // cursor
    L.ring(ST.x, ST.y, 20 - 5 * ST.press, 20 - 5 * ST.press, [1, 1, 1], 0.85, 0.16);
    L.finish(t, { bloom: [0.18, 0.16], vignette: 0.9 });
    const n = ST.got.filter((g) => g >= 0 && GT - g >= 0.3).length;
    L.sprite('coin', W - 292, 38, { w: 84, h: 84 }); L.text('×' + String(n).padStart(2, '0'), W - 190, 84, 58, 0);
  };
  // QA hooks for <skill>/scripts/qa.mjs (references/engine.md §7): every HUD screen with worst-case values, and an 8-frame
  // cycle per walking actor and view (+ sprites: the textures it is drawn from, box: its screen box). Grow this with the game.
  S.QA = () => {
    const base = (o = {}) => { const s = SIM.spawn(0); for (let i = 0; i < 120; i++) SIM.step(s, {}); return Object.assign(s, o); };
    return { states: [['start', base()]], cycles: {}, sprites: {}, box: () => [0, 0, W, H] };
  };
})();
