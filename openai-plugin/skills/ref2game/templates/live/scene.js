// live/scene.js — the scene: layer plan, play plane, actors, FX and HUD. render(t) is a pure function of t and the
// sim state (attract replay SIM.at(t), or the live play state in SCENE.state). Template: side view with parallax bands.
// Replace placeholder art by generating the same names into art/gen (python3 <skill>/scripts/prep.py picks them up);
// the code keeps working as long as each asset keeps its role (walk line, pivot, proportions).
(function () {
  const S = (window.SCENE = {}), A = window.ASSETS, L = LIB, M = L.M, W = SIM.VIEW.W, H = SIM.VIEW.H;
  S.REPEAT = [];                                           // textures that need GL_REPEAT (scrolling textures for shaders)
  S.programs = () => { L.init(W, H); L.glyphs(); L.SUN = [560, 250]; };
  const TUFT = ['tuft_0', 'tuft_1', 'tuft_2'];
  const DUST = [0.86, 0.84, 0.70], INK = [0.12, 0.08, 0.03];
  const rimL = [0.55, -0.0035, -0.0055, 1];                // warm rim on the sun side (upper left); mirror x for flipped sprites
  // hero poses: [farThigh, farKnee, nearThigh, nearKnee, farArm, farElbow, nearArm, nearElbow, bodyRot, squash] (deg; 0 = down, − = forward)
  const PO = { idle: [-6, 8, 4, 6, -14, -18, 16, 12, 1, 1.0], squat: [-40, 55, -12, 45, -38, -14, 30, 15, 6, 0.86],
    rise: [-6, 12, 10, 16, -104, -10, 88, 25, -4, 1.10], tuck: [-72, 98, -22, 74, -96, -10, 65, 30, 0, 1.0], fall: [-14, 26, 10, 22, -104, -8, 90, 25, 2, 1.03] };
  const runPose = (p) => { const s = Math.sin(p), c = Math.cos(p);                       // legs alternate; arms pump opposite to the legs
    return [-36 * s - 2, 8 + 80 * Math.max(0, c) ** 1.4, 36 * s - 2, 8 + 80 * Math.max(0, -c) ** 1.4, -40 + 48 * s, -22 - 30 * Math.max(0, -s), 12 - 52 * s, -38 - 34 * Math.max(0, s), 8, 1 + 0.035 * Math.cos(2 * p)]; };

  S.render = (t) => {
    const ST = S.state || SIM.at(t), GT = ST.t, SS = L.SS, rnd = L.rnd;
    let shk = 0; for (const e of ST.ev) { const a = GT - e.t; if (a < 0) continue;           // screen shake from events, quadratic decay
      const A0 = e.k === 'land' && (e.v || 0) > 1300 ? 4 : 0; if (A0 && a < 0.28) shk = Math.max(shk, A0 * (1 - a / 0.28) ** 2); }
    const camX = ST.cam + shk * Math.sin(GT * 91), camY = 3 * Math.sin(2 * Math.PI * t / 7.3) + shk * Math.sin(GT * 117 + 1.3);
    const X = (f) => -camX * f, Y = (f) => -camY * f;                                       // parallax offset for depth factor f
    const gw = (x) => SIM.gustAt(t, x), wnd = (x) => SIM.windAt(t, x);

    // ===== background bands → T.bg (one depth band per asset; haze/grade per band; fog between bands) =====
    L.beginBG();
    L.sprite('bg_sky', -40 + X(0.03), -30 + Y(0.03), { w: W + 80, h: H + 60 });
    L.glow(L.SUN[0] + X(0.03), L.SUN[1], 260, [1.0, 0.75, 0.40], 0.30, 3.5); L.glow(L.SUN[0] + X(0.03), L.SUN[1], 60, [1.0, 0.88, 0.6], 0.5, 7);
    L.fog(-40, 420, [0.0016, 0.012, 0.56, 0.22], [1.0, 0.92, 0.80], 1, t, 0.6);
    L.sprite('bg_far', -240 + X(0.12), 300 + Y(0.12), { w: 2400, u: { lod: 0.8, grade: [0.8, 0.95, 0.25, 0.9], haze: [0.86, 0.88, 0.9] } });
    L.fog(420, 300, [0.0022, 0.020, 0.46, 0.35], [0.92, 0.92, 0.88], 2, t, 0.6);
    L.sprite('bg_mid', -240 + X(0.35), 330 + Y(0.35), { w: 2400, pad: 0.01, u: { lod: 1.0, grade: [0.85, 0.95, 0.12, 0.95], haze: [0.75, 0.85, 0.85], sway: [0.0018 * (1 + gw(900)), 9, L.ph(t, 4.5), 1] } });
    L.fog(660, 300, [0.0035, 0.05, 0.40, 0.5], [0.85, 0.93, 0.90], 3, t, 0.3);
    L.godRays(t, { sun: [L.SUN[0] + X(0.03), L.SUN[1]] });

    // ===== composite: background + play plane =====
    L.beginComp();
    const platforms = () => {
      const g = A.ground, walk = g.walk ?? 16;                                              // ground strip repeated along the ground line
      for (let x = -400; x < 2500; x += g.w - 2) L.sprite('ground', x + X(1), 860 - walk + Y(1), { w: g.w, h: g.h });
      for (const s of SIM.SURF) { if (s.id === 'ground') continue;                          // ledges placed on their polylines
        const p0 = s.pts[0], p1 = s.pts[s.pts.length - 1], len = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), ang = Math.atan2(p1[1] - p0[1], p1[0] - p0[0]);
        const ld = A.ledge, k = (len + 40) / ld.w, wl = (ld.walk ?? 20) * k;
        L.sprite('ledge', p0[0] - 20 + X(1), p0[1] - wl + Y(1), { w: len + 40, h: ld.h * k, rot: ang, pivot: [20, wl], u: { rim: [0.3, -0.002, -0.006, 1] } }); }
    };
    L.dropShadow(platforms); platforms();                                                    // soft contact shadow, then the pieces

    // --- grass tufts: tops pushed aside by walkers (sim springs) and leaned by the wind ---
    const drawTufts = (front) => SIM.TUFTS.forEach(([tx, kind, th, fr], i) => { if (fr !== front) return;
      const n = TUFT[kind], w = L.hsz(n, th), fl = rnd(i, 12) > 0.5, lean = Math.max(-0.34, Math.min(0.34, ST.tf[i][0] / w)) * (fl ? -1 : 1);
      L.sprite(n, tx - w / 2 + X(1), SIM.groundBelow(tx, 0) + (front ? 22 : 10) - th + Y(1), { h: th, pad: 0.36, flip: fl,
        u: { lean: [lean, 0], sway: [0.005 + 0.004 * Math.abs(wnd(tx)), 5, t * (2.0 + rnd(i, 13)) + 6.28 * rnd(i, 11), 1], vfade: 0.12, grade: front ? [1, 1, 0, 1.02] : [0.9, 0.88, 0, 1] } }); });
    drawTufts(0);

    // --- pickups: breadcrumbs on the jump arcs; bob, glow, hide when taken (attract: fade back in before the loop ends) ---
    const respawnAt = ST.loop !== undefined ? SIM.L - 0.9 : 1e9;
    SIM.COINS.forEach(([x, y], i) => { const g = ST.got[i]; let sc = 1;
      if (g >= 0 || g === -2) { if (GT < respawnAt) return; sc = SS(respawnAt, respawnAt + 0.35, GT); }
      const a = L.ph(t, 1.7, i * 1.3), xx = x + X(1), yy = y + 7 * Math.sin(a) + Y(1), cw = 54 * sc;
      L.glow(xx, yy, 60 * sc, [1.0, 0.7, 0.2], 0.28, 3.8);
      L.sprite('coin', 0, 0, { m: M.of(M.t(xx, yy), M.s(Math.cos(t * 2.4 + i), 1)), w: cw, h: cw, pivot: [cw / 2, cw / 2] }); });

    // --- hero: cut-out rig posed from the sim state, one ink silhouette around the whole puppet ---
    const heroPose = () => {
      let Q;
      if (ST.ground) { const idle = PO.idle.slice(); idle[9] = 1 + 0.015 * Math.sin(t * 2 * Math.PI / 1.8);
        Q = L.lerpP(idle, runPose(ST.dist / 150 * 2 * Math.PI), Math.min(1, Math.abs(ST.vx) / 240)); }
      else Q = ST.vy < 0 ? L.lerpP(PO.rise, PO.tuck, SS(-650, -60, ST.vy)) : L.lerpP(PO.tuck, PO.fall, SS(60, 650, ST.vy));
      const sl = GT - ST.landT; if (sl >= 0 && sl < 0.3) Q = L.lerpP(Q, PO.squat, Math.exp(-sl / 0.07) * Math.max(0.35, Math.min(1, ST.landV / 1300)));
      const sj = GT - ST.jumpT; if (sj >= 0 && sj < 0.15) { Q = Q.slice(); Q[9] *= 1 + 0.08 * Math.sin(Math.PI * sj / 0.15); }
      return Q; };
    const drawHero = () => { const [fl1, fl2, nl1, nl2, fa1, fa2, na1, na2, rot, sy] = heroPose();
      const k = 0.42, [bw, bh] = L.sz('hero_body', k), [lw, lh] = L.sz('hero_leg', k), [aw, ah] = L.sz('hero_arm', k);
      const LEG = { split: 0.45, root: [0.5, 0.05], joint: [0.5, 0.46], r: 5, col: [0.88, 0.55, 0.22] };
      const ARM = { split: 0.45, root: [0.5, 0.06], joint: [0.5, 0.46], r: 4, col: [0.88, 0.55, 0.22] };
      const Lt = (LEG.joint[1] - LEG.root[1]) * lh, Ls = (0.97 - LEG.joint[1]) * lh;
      const reachOf = (a1, a2) => Lt * Math.cos(a1 * L.D2R) + Ls * Math.cos((a1 + a2) * L.D2R);
      const reach = Math.max(reachOf(fl1, fl2), reachOf(nl1, nl2)) - 4;
      const face = ST.face, hx = ST.x + X(1), hy = ST.y + Y(1), sx = 1 / Math.sqrt(sy);
      if (!L.sp) { const gy = SIM.groundBelow(ST.x, ST.y); if (gy !== null) { const f = Math.max(0.25, 1 - (gy - ST.y) / 320); L.shadow(hx, gy + 3 + Y(1), 34 * f, 7 * f, 0.5 * f); } }
      const Mb = M.of(M.t(hx, hy), M.s(face, 1), M.t(0, -reach), M.r(rot * L.D2R), M.s(sx, sy));
      const at = (nx, ny) => M.ap(Mb, [(nx - 0.5) * bw, (ny - 0.92) * bh]);
      const rim = face > 0 ? rimL : [0.55, 0.0035, -0.0055, 1];
      const limb = (tex, p, a1, a2, c, far, scl) => L.twoBone({ tex, p, a1, a2, face, rot, w: (tex === 'hero_leg' ? lw : aw) * scl, h: (tex === 'hero_leg' ? lh : ah) * scl,
        split: c.split, root: c.root, joint: c.joint, r: c.r * scl, col: c.col, capDark: far ? 0.8 : 1, u: far ? { tint: [0.80, 0.76, 0.74, 1] } : { rim } });
      limb('hero_arm', at(0.66, 0.50), fa1, fa2, ARM, true, 0.85);                         // far limbs: behind the body, darker, smaller
      limb('hero_leg', at(0.60, 0.86), fl1, fl2, LEG, true, 1);
      L.sprite('hero_body', 0, 0, { m: Mb, w: bw, h: bh, pivot: [bw * 0.5, bh * 0.92], u: { rim } });
      limb('hero_leg', at(0.42, 0.88), nl1, nl2, LEG, false, 1);                           // near limbs: in front
      limb('hero_arm', at(0.30, 0.52), na1, na2, ARM, false, 1);
    };
    L.inked(drawHero, { r: 2.4, col: INK });
    drawTufts(1);

    // --- event FX: dust, grass bits, pickup bursts ---
    for (const e of ST.ev) { const a = GT - e.t; if (a < 0) continue; const ex = e.x + X(1), ey = e.y + Y(1);
      if (e.k === 'step' && a < 0.4) for (let j = 0; j < 2; j++) { const q = a / 0.4, s = rnd(e.t, j);
        L.puff(ex - ST.face * (8 + 30 * q * (0.6 + s)), ey - 6 - 14 * q, 7 + 10 * q, DUST, 0.45 * (1 - q), e.t * 10 + j); }
      if ((e.k === 'land' || e.k === 'jump') && a < 0.55) { const n = e.k === 'land' ? 8 : 4, pw = e.k === 'land' ? Math.min(1.3, Math.max(0.6, (e.v || 900) / 1100)) : 0.7;
        for (let j = 0; j < n; j++) { const q = a / 0.55, side = j % 2 ? 1 : -1, s = rnd(e.t, j);
          L.puff(ex + side * (14 + 70 * pw * (1 - (1 - q) ** 2) * (0.5 + s)), ey - 4 - 22 * q * s, (8 + 16 * q) * pw, DUST, 0.55 * (1 - q) ** 1.3, e.t + j); } }
      if (e.k === 'rustle' && a < 0.7) for (let j = 0; j < 4; j++) { const q = a / 0.7, s = rnd(e.t, j + 3);
        L.puff(ex + e.d * (60 + 120 * s) * a + (j - 1.5) * 10, ey - (180 + 160 * s) * a + 520 * a * a, 4, [0.5, 0.8, 0.3], 0.9 * (1 - q), j); }
      if (e.k === 'collect' && a < 0.6) { const q = a / 0.6;
        for (let j = 0; j < 8; j++) { const an = j * Math.PI / 4 + e.t, d = 18 + 60 * (1 - (1 - q) ** 2); L.star(ex + Math.cos(an) * d, ey + Math.sin(an) * d, 11, [1.0, 0.9, 0.45], 1 - q); }
        L.ring(ex, ey, 20 + 40 * q, 20 + 40 * q, [1, 0.95, 0.7], 1 - q); }
    }

    // --- light in front of the play plane, then the dark soft foreground (parallax > 1, mirrored twins cover the corners) ---
    L.veil(0.12); L.motes(t, { n: 110 });
    { const fh = 300, fw = L.hsz('fg_clump', fh), u = { lod: 1.6, tint: [0.10, 0.20, 0.22, 0.65], grade: [0.75, 0.78, 0, 1.05], sway: [0.008 * (1 + gw(100)), 5, L.ph(t, 4), 1], lean: [0.035 * gw(100), 0] };
      const lx = -fw * 0.5 + X(1.3), y = H - fh + 50 + Y(1.3); L.sprite('fg_clump', lx - fw + 8, y, { h: fh, pad: 0.03, flip: true, u }); L.sprite('fg_clump', lx, y, { h: fh, pad: 0.03, u });
      const rx = W - fw * 0.5 + X(1.3); L.sprite('fg_clump', rx, y, { h: fh, pad: 0.03, flip: true, u }); L.sprite('fg_clump', rx + fw - 8, y, { h: fh, pad: 0.03, u }); }
    L.finish(t);

    // ===== HUD (screen space, after the grade): counter + pickups flying into it =====
    const TOK = [W - 250, 80], FLY = 0.55; let arrived = 0, bump = 0;
    ST.got.forEach((g) => { if (g >= 0) { const a = GT - g; if (a >= FLY) { arrived++; bump = Math.max(bump, 1 - SS(0, 0.25, a - FLY)); } } });
    const count = (ST.loop !== undefined ? ST.loop * SIM.COINS.length : (ST.bank || 0)) + arrived;
    L.shadow(W - 190, 82, 175, 66, 0.30);
    const ts = 84 * (1 + 0.22 * bump); L.sprite('coin', TOK[0] - ts / 2, TOK[1] - ts / 2, { w: ts, h: ts }); L.glow(TOK[0], TOK[1], 70, [1.0, 0.75, 0.3], 0.25 + 0.4 * bump, 3.5);
    L.text('×' + String(count).padStart(2, '0'), TOK[0] + 60, TOK[1] + 4, 58 * (1 + 0.18 * bump), 0);
    ST.got.forEach((g, i) => { if (g < 0) return; const a = GT - g; if (a < 0 || a >= FLY) return;
      const q = SS(0, 1, a / FLY), [fx, fy] = SIM.COINS[i], x0 = fx + X(1), y0 = fy + Y(1), cx = (x0 + TOK[0]) / 2, cy = Math.min(y0, TOK[1]) - 160;
      const x = (1 - q) ** 2 * x0 + 2 * (1 - q) * q * cx + q * q * TOK[0], y = (1 - q) ** 2 * y0 + 2 * (1 - q) * q * cy + q * q * TOK[1];
      L.glow(x, y, 40 * (1 - 0.5 * q), [1.0, 0.8, 0.3], 0.7, 3.0); L.sprite('coin', x - 18, y - 18, { w: 36, h: 36 });
      L.text('+1', x0, y0 - 40 - 50 * q, 40, 0.5, 1 - SS(0.6, 1, a / FLY)); });
  };
  // QA hooks for <skill>/scripts/qa.mjs (references/engine.md §7): every HUD screen with worst-case values, and an 8-frame
  // cycle per walking actor and view (+ sprites: the textures it is drawn from, box: its screen box). Grow this with the game.
  S.QA = () => {
    const base = (o = {}) => { const s = SIM.spawn(0); for (let i = 0; i < 120; i++) SIM.step(s, {}); return Object.assign(s, o); };
    return { states: [['start', base()]], cycles: {}, sprites: {}, box: () => [0, 0, W, H] };
  };
})();
