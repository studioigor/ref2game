// qa.mjs — automatic polish checks on the live page (run from the project root). Exit 2 on any failure.
//   node <skill>/scripts/qa.mjs [--out frames/qa] [--only ui,anchors,motion,rig,anim]
// Run it after every scene/sim change that touches the HUD, a rig or an emitter, and always before showing the user a build.
// The scene provides SCENE.QA() → { states: [[name, simState]...], cycles: { name: [simState...] }, box(name, state) → [x,y,w,h] screen px,
//   sprites: { cycleName: [texture names the actor is drawn from] } } (sprites lets the motion check isolate the actor and ignore bob)
//   horiz: { cycleName: 'left' | 'right' } for actors that lie along x (crawlers, snakes, fish): align on that half (the
//   dragging body), and the other half (the reaching end) must change — the top/bottom split means nothing for them
// and records, per rendered frame, window.__UI (HUD texts { k:'text', id, s, x, y, w, h } and containers { k:'box', id, x, y, w, h, pad })
// and window.__ANCHORS ({ name, sim:[x,y], drawn:[x,y], tol, d }: where the sim emits from vs where the holder is drawn).
// lib.js fills both: L.label / L.text record texts, L.uiBox(...) containers, L.anchor(...) emitters; beginBG resets them.
// Checks:
//   ui       every text lies inside a container (with its pad) and on screen; texts don't overlap each other
//   anchors  every emitter is drawn where the sim emits from (d <= tol)
//   motion   every walk cycle really moves its limbs: the actor is isolated (its sprites only vs none), each frame is aligned to
//            frame 0 on the upper body, and the lower body must change (a bobbing / sliding whole sprite fails); also writes a
//            cycle sheet (frames side by side, 2×) for the motion critic. A cycle whose subject reports joints is judged by the rig
//            checks instead (arms that pump change the upper body as much as the legs change the lower)
//   rig      measured rig checks from the joint trace (animation.md §14): rigs call L.joint(id, name, [x, y]) while LIB.TRACE is
//            an object; SCENE.QA() gives subject { name: id }, cycles (walks, really travelling), loops (NPC/animal idle and work),
//            attacks { name: { subject, states } } (impact frames vs targets all round; joints grip, tip, target [+ targetLo/Hi]), transitions { name: [states 1/60 s apart] },
//            cycleT { name: seconds per cycle } (rates per 1/60 s), rest { cycleName: standing state, same view } (segment lengths),
//            actors [type names that must be animated]. Fails: foot slide, ground, lift, limp, stride, knee, stretch (vs rest, drawn neutral), standing stance, arm phase,
//            rigid-only motion, the blade through the target at the impact, a held weapon in the ground, pops, coverage. Numbers go to report.json → rig for the motion critic.
//   anim     time-driven effects and state changes, which stills can't show. Metric: the mean absolute colour change between
//            consecutive frames (0..255, inside box [x,y,w,h] or the whole screen). SCENE.QA() gives
//            anim { name: { on: [states 1/60 s apart, the effect active], off: [the same frames, the effect off], box?, min? } }:
//              fails when the effect adds almost no motion (a frozen effect, e.g. a time uniform the draw never sets);
//            ramps { name: { ramp: [states 1/60 s apart while a state changes, e.g. weather fading in], steady: [the same
//              frames with that state fixed], box? } }: fails when the change makes frames differ much more than at steady
//              state (the picture sweeps or strobes, e.g. a phase computed as rate(state) · t instead of integrated over time).
// Writes <out>/<state>.png, <out>/cycle_<name>.png and <out>/report.json.
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module';
const here = path.dirname(new URL(import.meta.url).pathname);
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT || path.join(here, 'node_modules/playwright'));
const args = process.argv.slice(2), opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const out = opt('out', 'frames/qa'), only = opt('only', 'ui,anchors,motion,rig,anim').split(','); fs.mkdirSync(out, { recursive: true });
const root = process.cwd(), types = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png', '.json': 'application/json' };
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0]));
  fs.stat(f, (e, st) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(r); }); });
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const browser = await chromium.launch({ args: ['--use-angle=' + (process.platform === 'darwin' ? 'metal' : 'default'), '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const errors = []; p.on('pageerror', (e) => errors.push(e.message)); p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
await p.goto(`http://127.0.0.1:${srv.address().port}/live/index.html?render=1`);
await p.waitForFunction(() => window.__ready, null, { timeout: 30000 });
const hasQA = await p.evaluate(() => typeof SCENE.QA === 'function');
const fails = [], warns = [], report = { states: {}, cycles: {} };
if (!hasQA) fails.push('SCENE.QA() missing: the scene must list its HUD states and walk cycles (references/engine.md §7, "QA hooks")');
const save = (f, url) => fs.writeFileSync(f, Buffer.from(url.split(',')[1], 'base64'));

if (hasQA) {
  // ---- HUD states: layout + anchors ----
  const names = await p.evaluate(() => { window.__QA = SCENE.QA(); return window.__QA.states.map((s) => s[0]); });
  for (let i = 0; i < names.length; i++) {
    const r = await p.evaluate((i) => { const [, st] = window.__QA.states[i]; SCENE.state = st;
      try { SCENE.render(st.t + 0.01); } catch (e) { return { err: e.message + ' @ ' + (e.stack || '').split('\n')[1] }; }
      return { url: document.getElementById('c').toDataURL('image/png'), ui: window.__UI || [], an: window.__ANCHORS || [] }; }, i);
    const name = names[i]; if (r.err) { fails.push(`${name}: render threw ${r.err}`); continue; } save(path.join(out, name + '.png'), r.url); report.states[name] = { ui: r.ui.length, anchors: r.an };
    if (only.includes('ui')) {
      const texts = r.ui.filter((u) => u.k === 'text'), boxes = r.ui.filter((u) => u.k === 'box');
      if (!r.ui.length) warns.push(`${name}: no __UI records (HUD text is not checked)`);
      for (const t of texts) {
        if (t.x < 0 || t.y < 0 || t.x + t.w > 1920 || t.y + t.h > 1080) fails.push(`${name}: text "${t.s}" leaves the screen`);
        const cxy = [t.x + t.w / 2, t.y + t.h / 2], inb = boxes.filter((b) => cxy[0] >= b.x && cxy[0] <= b.x + b.w && cxy[1] >= b.y && cxy[1] <= b.y + b.h);
        if (!inb.length) { warns.push(`${name}: text "${t.s}" has no container`); continue; }
        const b = inb.sort((a, c) => a.w * a.h - c.w * c.h)[0], pad = b.pad || 0;
        const over = Math.max(b.x + pad - t.x, t.x + t.w - (b.x + b.w - pad), 0);
        const overY = Math.max(b.y - t.y - t.h * 0.15, t.y + t.h * 0.85 - (b.y + b.h), 0);           // glyph box has some air top/bottom
        if (over > 1 || overY > 1) fails.push(`${name}: text "${t.s}" overflows "${b.id}" by ${Math.round(Math.max(over, overY))} px`);
      }
      for (let a = 0; a < texts.length; a++) for (let b = a + 1; b < texts.length; b++) { const A = texts[a], B = texts[b];
        const ix = Math.min(A.x + A.w, B.x + B.w) - Math.max(A.x, B.x), iy = Math.min(A.y + A.h * 0.85, B.y + B.h * 0.85) - Math.max(A.y + A.h * 0.15, B.y + B.h * 0.15);
        if (ix > 2 && iy > 2) fails.push(`${name}: texts "${A.s}" and "${B.s}" overlap`); }
    }
    if (only.includes('anchors')) for (const a of r.an) if (a.d > a.tol) fails.push(`${name}: ${a.name} drawn ${a.d.toFixed(1)} px from where the sim emits (tol ${a.tol})`);
  }
  // ---- walk cycles: do the limbs move? ----
  if (only.includes('motion')) {
    const cyc = await p.evaluate(() => Object.keys(window.__QA.cycles || {}));
    if (!cyc.length) warns.push('no walk cycles in SCENE.QA().cycles — every actor that walks needs one per view (animation.md §12)');
    for (const name of cyc) {
      const r = await p.evaluate((name) => { try { return (() => { const Q = window.__QA, fr = Q.cycles[name], c = document.getElementById('c'), frames = [], masks = [];
        const box = Q.box(name, fr[0]).map(Math.round), [bx, by, bw, bh] = box, tmp = document.createElement('canvas'); tmp.width = bw; tmp.height = bh;
        const g = tmp.getContext('2d', { willReadFrequently: true }), only = Q.sprites && Q.sprites[name];
        const grab = (st, o) => { LIB.ONLY = o || []; SCENE.state = st; SCENE.render(st.t + 0.01); LIB.ONLY = []; g.clearRect(0, 0, bw, bh); g.drawImage(c, bx, by, bw, bh, 0, 0, bw, bh); return g.getImageData(0, 0, bw, bh).data; };
        let worst = 0;
        for (const st of fr) { const full = grab(st);
          for (const a of window.__ANCHORS || []) worst = Math.max(worst, a.d - a.tol);
          frames.push(Array.from(full));
          // the actor alone: its sprites only vs no sprites at all (ground and full-screen passes are identical in both)
          if (only) { const F = grab(st, only), B = grab(st, ['__none__']), m = new Uint8Array(bw * bh), A = new Uint8ClampedArray(bw * bh * 4);
            for (let i = 0; i < bw * bh; i++) { const d = Math.abs(F[i * 4] - B[i * 4]) + Math.abs(F[i * 4 + 1] - B[i * 4 + 1]) + Math.abs(F[i * 4 + 2] - B[i * 4 + 2]);
              if (d > 24) { m[i] = 1; A[i * 4] = F[i * 4]; A[i * 4 + 1] = F[i * 4 + 1]; A[i * 4 + 2] = F[i * 4 + 2]; A[i * 4 + 3] = 255; } }
            masks.push([m, A]); } }
        const cut = Math.round(bh * 0.6), lo = [], hi = [], hz = Q.horiz && Q.horiz[name], cx = Math.round(bw / 2);
        if (only) {
          // align each frame to frame 0 on the upper body (bob and lean are not limb motion), then count what changed below
          const [m0, A0] = masks[0], px = (A, m, x, y) => (x < 0 || y < 0 || x >= bw || y >= bh || !m[y * bw + x]) ? null : [A[(y * bw + x) * 4], A[(y * bw + x) * 4 + 1], A[(y * bw + x) * 4 + 2]];
          const cmp = (m1, A1, dx, dy, y0, y1, x0 = 0, x1 = bw) => { let n = 0, ch = 0; for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { const a = px(A0, m0, x, y), b = px(A1, m1, x + dx, y + dy);
            if (!a && !b) continue; n++; if (!a || !b || Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]) > 60) ch++; } return n ? ch / n : 0; };
          for (let k = 1; k < masks.length; k++) { const [m1, A1] = masks[k]; let best = [1e9, 0, 0];
            const body = hz ? (hz === 'left' ? [0, bh, 0, cx] : [0, bh, cx, bw]) : [0, cut, 0, bw], limb = hz ? (hz === 'left' ? [0, bh, cx, bw] : [0, bh, 0, cx]) : [cut, bh, 0, bw];
            for (let dy = -8; dy <= 8; dy++) for (let dx = -8; dx <= 8; dx++) { const e = cmp(m1, A1, dx, dy, ...body); if (e < best[0]) best = [e, dx, dy]; }
            hi.push(best[0]); lo.push(cmp(m1, A1, best[1], best[2], ...limb)); }
        } else {
          const diff = (A, B, y0, y1) => { let n = 0, m = 0; for (let y = y0; y < y1; y++) for (let x = 0; x < bw; x++) { const i = (y * bw + x) * 4;
            const d = Math.abs(A[i] - B[i]) + Math.abs(A[i + 1] - B[i + 1]) + Math.abs(A[i + 2] - B[i + 2]); m++; if (d > 60) n++; } return n / m; };
          for (let k = 1; k < frames.length; k++) { lo.push(diff(frames[0], frames[k], cut, bh)); hi.push(diff(frames[0], frames[k], 0, cut)); } }
        // the sheet: frames side by side at 2×
        const sh = document.createElement('canvas'); sh.width = bw * 2 * frames.length; sh.height = bh * 2; const sg = sh.getContext('2d'); sg.imageSmoothingEnabled = false;
        frames.forEach((f, k) => { g.putImageData(new ImageData(new Uint8ClampedArray(f), bw, bh), 0, 0); sg.drawImage(tmp, 0, 0, bw, bh, k * bw * 2, 0, bw * 2, bh * 2); });
        return { lo, hi, sheet: sh.toDataURL('image/png'), worst, masked: !!only }; })(); } catch (e) { return { err: e.message }; } }, name);
      if (r.err) { fails.push(`${name}: render threw ${r.err}`); continue; }
      save(path.join(out, `cycle_${name}.png`), r.sheet);
      const lo = Math.max(...r.lo), hi = Math.max(...r.hi); report.cycles[name] = { legs: +lo.toFixed(3), body: +hi.toFixed(3), masked: r.masked };
      if (!r.masked) warns.push(`${name}: QA().sprites.${name} not given — motion measured on the raw box (a bobbing sliding sprite can pass)`);
      // limbs must change clearly more than the (aligned) upper body does: sub-pixel bob and a wagging tail change ~10–20% too
      const need = r.masked ? Math.max(0.12, 1.5 * hi) : 0.04, traced = only.includes('rig') && await p.evaluate((nm) => typeof LIB.joint === 'function' && !!(window.__QA.subject || {})[nm], name);
      if (lo < need && traced) warns.push(`${name}: pixel limb-motion ratio low (${(lo * 100).toFixed(1)}% vs ${(hi * 100).toFixed(1)}%) — the joint trace measures this cycle (rig checks)`);
      else if (lo < need) fails.push(`${name}: limbs barely move over the walk cycle (lower body ${(lo * 100).toFixed(1)}% changed vs upper ${(hi * 100).toFixed(1)}%${r.masked ? ', aligned on the upper body' : ''}) — a sliding sprite: rig it (references/animation.md)`);
      if (r.worst > 0) fails.push(`${name}: an emitter leaves its holder by ${r.worst.toFixed(1)} px during the cycle`);
    }
  }
  // ---- rig checks from the joint trace (animation.md §14) ----
  if (only.includes('rig')) {
    const meta = await p.evaluate(() => { const Q = window.__QA; return { has: typeof LIB.joint === 'function', subject: Q.subject || {}, cycles: Object.keys(Q.cycles || {}),
      loops: Object.keys(Q.loops || {}), cycleT: Q.cycleT || {}, rest: Object.keys(Q.rest || {}), attacks: Object.keys(Q.attacks || {}), transitions: Object.keys(Q.transitions || {}), actors: Q.actors || [] }; });
    if (!meta.has) warns.push('lib.js has no L.joint: rig checks skipped (animation.md §14)');
    else {
      report.rig = {};
      const trace = (kind, name) => p.evaluate(([kind, name]) => { const Q = window.__QA, A = kind === 'attacks', src = A ? Q.attacks[name].states : Q[kind][name], id = A ? Q.attacks[name].subject : (Q.subject || {})[name];
        const fr = []; for (const st of src) { LIB.TRACE = {}; SCENE.state = st; try { SCENE.render(st.t + 0.01); } catch (e) { LIB.TRACE = null; return { err: e.message }; }
          fr.push({ j: (id && LIB.TRACE[id]) || null, cam: st.cam || [0, 0] }); } LIB.TRACE = null; return { id, fr }; }, [kind, name]);
      const sub = (a, b) => [a[0] - b[0], a[1] - b[1]], len = (v) => Math.hypot(v[0], v[1]), g = (f, k) => f.j && f.j[k] ? [f.j[k][0] + f.cam[0], f.j[k][1] + f.cam[1]] : null;
      const heightOf = (f) => { const j = f.j; if (!j || !j.ground) return null; if (j.top) return j.ground[1] - j.top[1]; if (j.head) return (j.ground[1] - j.head[1]) * 1.15; return null; };
      const corr = (a, b) => { const n = a.length, ma = a.reduce((x, y) => x + y, 0) / n, mb = b.reduce((x, y) => x + y, 0) / n; let s = 0, sa = 0, sb = 0;
        for (let i = 0; i < n; i++) { s += (a[i] - ma) * (b[i] - mb); sa += (a[i] - ma) ** 2; sb += (b[i] - mb) ** 2; } return sa && sb ? s / Math.sqrt(sa * sb) : 0; };
      // similarity fit (rotation + uniform scale + translation) of frame 0's joints onto frame k's: RMS residual
      const simRes = (A, B) => { const n = A.length; if (n < 3) return Infinity; const ca = [0, 0], cb = [0, 0]; A.forEach((p) => { ca[0] += p[0] / n; ca[1] += p[1] / n; }); B.forEach((p) => { cb[0] += p[0] / n; cb[1] += p[1] / n; });
        let a = 0, b = 0, d = 0; for (let i = 0; i < n; i++) { const x = A[i][0] - ca[0], y = A[i][1] - ca[1], u = B[i][0] - cb[0], v = B[i][1] - cb[1]; a += x * u + y * v; b += x * v - y * u; d += x * x + y * y; }
        const c = a / d, s2 = b / d; let r = 0; for (let i = 0; i < n; i++) { const x = A[i][0] - ca[0], y = A[i][1] - ca[1], px = c * x - s2 * y + cb[0], py = s2 * x + c * y + cb[1]; r += (px - B[i][0]) ** 2 + (py - B[i][1]) ** 2; }
        return Math.sqrt(r / n); };
      const rigidCheck = (name, fr, H, R) => { const keys = Object.keys(fr[0].j || {}).filter((k) => !['ground', 'target'].includes(k) && fr.every((f) => f.j && f.j[k]));
        if (keys.length < 3) { warns.push(`${name}: fewer than 3 joints traced, rigid-only check skipped`); return; }
        let res = 0, mov = 0; for (const f of fr) { res = Math.max(res, simRes(keys.map((k) => fr[0].j[k]), keys.map((k) => f.j[k]))); for (const k of keys) mov = Math.max(mov, len(sub(sub(f.j[k], f.j.ground || [0, 0]), sub(fr[0].j[k], fr[0].j.ground || [0, 0])))); }
        R.rigidRes = +(res / H).toFixed(4); R.move = +(mov / H).toFixed(3);
        if (mov < 0.02 * H) fails.push(`${name}: nothing moves (max joint motion ${(mov / H * 100).toFixed(1)} % of H): the actor is not animated`);
        else if (res < 0.004 * H) fails.push(`${name}: all joints move rigidly together (residual ${(res / H * 100).toFixed(2)} % of H): a whole-sprite transform, not animation`); };
      for (const name of [...meta.cycles, ...meta.loops]) {
        const isCyc = meta.cycles.includes(name); if (!meta.subject[name]) { if (!isCyc) warns.push(`${name}: loop without a subject id, not measured`); continue; }
        const r = await trace(isCyc ? 'cycles' : 'loops', name); if (r.err) { fails.push(`${name}: render threw ${r.err}`); continue; }
        const fr = r.fr; if (fr.some((f) => !f.j)) { fails.push(`${name}: subject "${r.id}" reported no joints (L.joint) in some frames`); continue; }
        const H = heightOf(fr[0]); if (!H) { fails.push(`${name}: subject "${r.id}" reports no ground + head/top joints`); continue; }
        const R = (report.rig[name] = { H: Math.round(H) }); rigidCheck(name, fr, H, R);
        if (!isCyc) continue;
        // the rest pose (standing, same view) gives each segment's unforeshortened length
        let rest = null; if (meta.rest.includes(name)) rest = await p.evaluate(([nm, id]) => { const st = window.__QA.rest[nm]; LIB.TRACE = {}; SCENE.state = st; SCENE.render(st.t + 0.01); const j = LIB.TRACE[id] || null; LIB.TRACE = null; return j; }, [name, r.id]);
        // the live standing pose: the rest state drawn as play draws it (rest states may carry neutral: true, the painted layout
        // used for the segment lengths). Feet clearly wider than the hips and the legs in the hips' left-right order — feet
        // straight under narrow painted hips read as a soldier at attention, from behind as crossed legs (animation.md §15.4)
        if (rest) { const lv = await p.evaluate(([nm, id]) => { const st = Object.assign({}, window.__QA.rest[nm], { neutral: false }); LIB.TRACE = {}; SCENE.state = st; SCENE.render(st.t + 0.01); const j = LIB.TRACE[id] || null; LIB.TRACE = null; return j; }, [name, r.id]);
          if (lv && lv.hipL && lv.hipR && lv.ankleL && lv.ankleR) { const hv = sub(lv.hipR, lv.hipL), hl = len(hv) || 1, ax = [hv[0] / hl, hv[1] / hl], al = (v) => v[0] * ax[0] + v[1] * ax[1];
            const wide = len(sub(lv.ankleR, lv.ankleL)) / hl, cross = al(sub(lv.ankleR, lv.ankleL)) <= 0 || (lv.kneeL && lv.kneeR && al(sub(lv.kneeR, lv.kneeL)) <= 0);
            R.stance = +wide.toFixed(2); if (wide < 1.25) fails.push(`${name}: standing, the feet are ${wide.toFixed(2)}× the hip width apart (min 1.25×): a stiff stance at attention`);
            if (cross) fails.push(`${name}: standing, the legs cross (knees or ankles out of the hips' left-right order)`); } }
        const n = fr.length, travels = len(sub(g(fr[n - 1], 'ground'), g(fr[0], 'ground'))) > 1, pairs = travels ? n - 1 : n;   // a travelling cycle does not wrap in world space
        // feet: slide while planted, ground penetration, swing lift
        let slide = 0, pen = -1e9, lift = 0;
        for (const s of ['L', 'R']) for (const pt of ['heel', 'toe', 'ankle']) {
          const k = pt + s; if (!fr.every((f) => f.j[k])) continue;
          const gk = 'ground' + s, hg = fr.map((f) => (f.j[gk] ? f.j[gk][1] : f.j.ground[1]) - f.j[k][1]);       // height above its ground (screen px)
          const lo = Math.min(...hg); if (pt !== 'ankle' && fr.every((f) => f.j[gk])) { pen = Math.max(pen, -Math.min(...hg)); lift = Math.max(lift, Math.max(...hg) - Math.max(0, lo)); }
          if (pt === 'ankle' && (fr[0].j['heel' + s] || fr[0].j['toe' + s])) continue;
          const on = hg.map((h) => h <= lo + 1);
          for (let i = 0; i < pairs; i++) if (on[i] && on[(i + 1) % n]) slide = Math.max(slide, len(sub(g(fr[(i + 1) % n], k), g(fr[i], k))) * (n > 1 ? 1 : 0));
        }
        Object.assign(R, { slide: +slide.toFixed(2), ground: +Math.max(0, pen).toFixed(2), lift: +(lift / H).toFixed(3) });
        if (slide > 1.5) fails.push(`${name}: a planted foot slides ${slide.toFixed(1)} px between frames (tol 1.5)`);
        if (pen > 1.5) fails.push(`${name}: a foot goes ${pen.toFixed(1)} px into the ground (tol 1.5)`);
        if (pen > -1e8 && lift < 0.03 * H) fails.push(`${name}: the swing foot lifts only ${(lift / H * 100).toFixed(1)} % of H (need 3 %)`);
        // limp + bob from the head relative to the ground point
        if (fr[0].j.head) { const hy = fr.map((f) => f.j.head[1] - f.j.ground[1]), k1 = hy.indexOf(Math.max(...hy)); let d2 = -1e9;
          for (let i = 0; i < n; i++) { const dd = Math.min(Math.abs(i - k1), n - Math.abs(i - k1)); if (Math.abs(dd - n / 2) <= n / 8) d2 = Math.max(d2, hy[i]); }
          const limp = Math.abs(hy[k1] - d2), bob = Math.max(...hy) - Math.min(...hy); Object.assign(R, { limp: +(limp / H).toFixed(4), bob: +(bob / H).toFixed(4) });
          if (limp > 0.015 * H) fails.push(`${name}: limp — the two step dips of the head differ by ${limp.toFixed(1)} px (${(limp / H * 100).toFixed(1)} % of H, tol 1.5 %)`);
          if (bob < 0.01 * H || bob > 0.06 * H) fails.push(`${name}: head bob ${(bob / H * 100).toFixed(1)} % of H (want 1–6 %)`); }
        // stride, knees, stretch
        if (fr[0].j.ankleL && fr[0].j.ankleR) { const sp = Math.max(...fr.map((f) => len(sub(f.j.ankleL, f.j.ankleR)))); R.stride = +(sp / H).toFixed(3); if (sp > 0.55 * H) fails.push(`${name}: the feet spread ${(sp / H * 100).toFixed(0)} % of H (max 55 %)`); }
        for (const s of ['L', 'R']) { const hp = 'hip' + s, kn = 'knee' + s, an = 'ankle' + s; if (!fr.every((f) => f.j[hp] && f.j[kn] && f.j[an])) continue;
          const ang = fr.map((f) => { const a = sub(f.j[hp], f.j[kn]), b = sub(f.j[an], f.j[kn]); return Math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]) * 180 / Math.PI; });
          let jump = 0, flip = false; for (let i = 0; i < n; i++) { const a = ang[i], b = ang[(i + 1) % n]; let d = Math.abs(a - b); d = Math.min(d, 360 - d); jump = Math.max(jump, d);
            if (Math.abs(a) < 170 && Math.abs(b) < 170 && Math.sign(a) !== Math.sign(b)) flip = true; }
          // segment length vs its rest length (QA().rest standing pose; else the cycle median): a segment's projection in a 2:1 view
          // is at most ~1.12× its 3D length and the standing projection is ≥ ~0.93× of it, so more than +20 % is rubber; shorter is
          // foreshortening (a knee toward / away from the camera), allowed down to 50 %
          const med = (a) => [...a].sort((x, y) => x - y)[a.length >> 1], th = fr.map((f) => len(sub(f.j[hp], f.j[kn]))), sh = fr.map((f) => len(sub(f.j[kn], f.j[an])));
          const rt = rest && rest[hp] && rest[kn] && rest[an] ? len(sub(rest[hp], rest[kn])) : med(th), rs = rest && rest[hp] && rest[kn] && rest[an] ? len(sub(rest[kn], rest[an])) : med(sh);
          const st = Math.max(Math.max(...th) / rt, Math.max(...sh) / rs) - 1, sq = Math.min(Math.min(...th) / rt, Math.min(...sh) / rs);
          R['knee' + s] = +jump.toFixed(1); R['stretch' + s] = +st.toFixed(3); R['short' + s] = +sq.toFixed(3);
          if (sq < 0.5) fails.push(`${name}: leg ${s} segments shrink to ${(sq * 100).toFixed(0)} % of their rest length (min 50 %)`);
          // 25° per 1/60 s; cycleT { name: seconds per cycle } converts the sampled frames to real time
          const kMax = 25 * (meta.cycleT[name] ? Math.max(1, meta.cycleT[name] / n * 60) : 1); R['kneeMax' + s] = +kMax.toFixed(0);
          if (jump > kMax) fails.push(`${name}: knee ${s} snaps ${jump.toFixed(0)}° between frames (max ${kMax.toFixed(0)}° = 25° per 1/60 s)`);
          if (flip) fails.push(`${name}: knee ${s} bends backwards in part of the cycle`);
          if (st > 0.2) fails.push(`${name}: leg ${s} segments stretch ${(st * 100).toFixed(0)} % over their rest length (max 20 %)`); }
        // a held weapon's tip must stay above the ground the actor stands on
        if (fr.every((f) => f.j.tip)) { const dig = Math.max(...fr.map((f) => f.j.tip[1] - f.j.ground[1])); R.tipDig = +dig.toFixed(1);
          if (dig > 0.02 * H) fails.push(`${name}: the held weapon's tip goes ${dig.toFixed(1)} px below the ground line (max 2 % of H)`); }
        // arms against the legs, along the travel direction
        const t0 = g(fr[0], 'ground'), t1 = g(fr[n - 1], 'ground'), dv = sub(t1, t0), dl = len(dv);
        if (dl > 1) { const dir = [dv[0] / dl, dv[1] / dl], along = (v) => v[0] * dir[0] + v[1] * dir[1];
          for (const s of ['L', 'R']) { const o = s === 'L' ? 'R' : 'L'; if (!fr.every((f) => f.j['hand' + s] && f.j['sh' + s] && f.j['ankle' + s] && f.j['hip' + s])) continue;
            const arm = fr.map((f) => along(sub(f.j['hand' + s], f.j['sh' + s]))), leg = fr.map((f) => along(sub(f.j['ankle' + s], f.j['hip' + s])));
            if (Math.max(...arm) - Math.min(...arm) < 0.02 * H) continue; const c = corr(arm, leg); R['arm' + s] = +c.toFixed(2);
            if (c > 0.3) fails.push(`${name}: arm ${s} swings with its own leg (corr ${c.toFixed(2)}): arms must swing against the legs`); } }
        else warns.push(`${name}: the subject does not travel over the cycle (feet slide is measured against a still ground)`);
      }
      for (const name of meta.attacks) { const r = await trace('attacks', name); if (r.err) { fails.push(`${name}: render threw ${r.err}`); continue; }
        // at the impact the blade (grip → tip) must pass through the target: distance from the target point to the blade segment.
        // (An angle measured from the grip misleads for targets close to the body; the angle is reported for the critic.)
        let worst = 0, miss = 0, bad = 0; const H = heightOf(r.fr.find((f) => f.j) || {}) || 100, per = [];
        const segD = (p, a, b) => { const ab = sub(b, a), t = Math.max(0, Math.min(1, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / Math.max(1e-6, ab[0] ** 2 + ab[1] ** 2))); return len(sub(p, [a[0] + ab[0] * t, a[1] + ab[1] * t])); };
        r.fr.forEach((f) => { const j = f.j; if (!j || !j.grip || !j.tip || !j.target) { bad++; per.push(null); return; } const b = sub(j.tip, j.grip), tg = sub(j.target, j.grip);
          // with targetLo / targetHi (the target's body axis) the blade must cross or touch that segment, else the centre point
          const sx2 = (a, b2, c, d2) => { const cr = (o, p2, q) => (p2[0] - o[0]) * (q[1] - o[1]) - (p2[1] - o[1]) * (q[0] - o[0]);
            if (cr(a, b2, c) * cr(a, b2, d2) < 0 && cr(c, d2, a) * cr(c, d2, b2) < 0) return 0; return Math.min(segD(a, c, d2), segD(b2, c, d2), segD(c, a, b2), segD(d2, a, b2)); };
          let d = Math.abs(Math.atan2(b[1], b[0]) - Math.atan2(tg[1], tg[0])) * 180 / Math.PI; d = Math.min(d, 360 - d);
          const m = (j.targetLo && j.targetHi ? sx2(j.grip, j.tip, j.targetLo, j.targetHi) : segD(j.target, j.grip, j.tip)) / H;
          worst = Math.max(worst, d); miss = Math.max(miss, m); per.push([+(Math.atan2(tg[1], tg[0]) * 180 / Math.PI).toFixed(0), +d.toFixed(0), +m.toFixed(2)]); });
        report.rig[name] = { aimWorst: +worst.toFixed(1), missWorst: +miss.toFixed(3), targets: r.fr.length, per };   // per: [target dir° from the grip, blade angle error°, miss/H]
        if (bad) fails.push(`${name}: ${bad} attack frame(s) without grip/tip/target joints`);
        if (miss > 0.18) { const w = per.filter((q) => q && q[2] > 0.18).map((q) => q[0] + '°'); fails.push(`${name}: at the impact the blade misses the target by up to ${(miss * 100).toFixed(0)} % of H (max 18 %), target directions ${w.join(' ')}`); } }
      for (const name of meta.transitions) { const tsub = await p.evaluate((nm) => { const Q = window.__QA; return (Q.subject || {})[nm]; }, name);
        const r = await p.evaluate(([nm, id]) => { const Q = window.__QA, fr = []; for (const st of Q.transitions[nm]) { LIB.TRACE = {}; SCENE.state = st; SCENE.render(st.t + 0.01); fr.push((id && LIB.TRACE[id]) || null); } LIB.TRACE = null; return fr; }, [name, tsub]);
        if (!tsub || r.some((j) => !j)) { fails.push(`${name}: transition subject reports no joints`); continue; }
        // a pop is a break in the motion, not fast motion: the second difference of each joint (relative to the ground point)
        // between frames 1/60 s apart. A step of s px shows as s; a fast but eased swing stays small.
        const H = heightOf({ j: r[0] }) || 100; let jump = 0, at = ''; const rel = (f, k) => sub(f[k], f.ground);
        for (let i = 2; i < r.length; i++) for (const k of Object.keys(r[i])) { if (!r[i - 1][k] || !r[i - 2][k] || k.startsWith('target')) continue;
          const a1 = sub(rel(r[i], k), rel(r[i - 1], k)), a0 = sub(rel(r[i - 1], k), rel(r[i - 2], k)), d = len(sub(a1, a0)); if (d > jump) { jump = d; at = `${k} @${i}`; } }
        report.rig[name] = { pop: +(jump / H).toFixed(3), at }; if (jump > 0.06 * H) fails.push(`${name}: ${at} pops ${jump.toFixed(1)} px (${(jump / H * 100).toFixed(0)} % of H, max 6 %): the motion breaks across the state change`); }
      for (const a of meta.actors) if (![...meta.cycles, ...meta.loops].some((c) => c === a || c.startsWith(a + '_') || c.startsWith(a))) fails.push(`coverage: actor "${a}" has no cycle or loop in SCENE.QA() — every NPC and animal needs real animation (animation.md §13)`);
      if (!meta.actors.length) warns.push('SCENE.QA().actors is empty: animation coverage of NPCs and animals is not checked');
    }
  }
}
// ---- time-driven effects: frozen effects and sweeps during a state change ----
if (hasQA && only.includes('anim')) {
  const meta = await p.evaluate(() => ({ anim: Object.keys(window.__QA.anim || {}), ramps: Object.keys(window.__QA.ramps || {}) }));
  const motion = (kind, name, key) => p.evaluate(([kind, name, key]) => { const E = window.__QA[kind][name], fr = E[key], c = document.getElementById('c');
    const [bx, by, bw, bh] = E.box || [0, 0, c.width, c.height], cv = document.createElement('canvas'); cv.width = bw; cv.height = bh;
    const g = cv.getContext('2d', { willReadFrequently: true }); let prev = null; const ch = [];
    for (const st of fr) { SCENE.state = st; try { SCENE.render(st.t); } catch (e) { return { err: e.message }; } g.clearRect(0, 0, bw, bh); g.drawImage(c, bx, by, bw, bh, 0, 0, bw, bh);
      const d = g.getImageData(0, 0, bw, bh).data; if (prev) { let m = 0; for (let k = 0; k < d.length; k += 4) m += Math.abs(d[k] - prev[k]) + Math.abs(d[k + 1] - prev[k + 1]) + Math.abs(d[k + 2] - prev[k + 2]); ch.push(m / (bw * bh * 3)); }
      prev = d; }
    return { m: ch.reduce((a, b) => a + b, 0) / Math.max(1, ch.length), n: ch.length }; }, [kind, name, key]);
  report.anim = {};
  for (const name of meta.anim) { const on = await motion('anim', name, 'on'), off = await motion('anim', name, 'off');
    if (on.err || off.err) { fails.push(`${name}: render threw ${on.err || off.err}`); continue; }
    if (!on.n) { warns.push(`${name}: anim.on needs at least 2 frames`); continue; }
    const min = (await p.evaluate((nm) => window.__QA.anim[nm].min, name)) ?? 0.02, add = on.m - off.m;
    report.anim[name] = { on: +on.m.toFixed(3), off: +off.m.toFixed(3) };
    if (add < min) fails.push(`${name}: the effect adds no motion between frames 1/60 s apart (${on.m.toFixed(3)} with it vs ${off.m.toFixed(3)} without, need +${min}): it is frozen — check that the draw passes the time`); }
  for (const name of meta.ramps) { const r = await motion('ramps', name, 'ramp'), s = await motion('ramps', name, 'steady');
    if (r.err || s.err) { fails.push(`${name}: render threw ${r.err || s.err}`); continue; }
    report.anim[name] = { ramp: +r.m.toFixed(3), steady: +s.m.toFixed(3) };
    if (r.m > 1.25 * s.m + 0.02) fails.push(`${name}: while the state changes, frames differ ${(r.m / Math.max(1e-6, s.m)).toFixed(2)}× as much as at steady state (max 1.25×): something sweeps or strobes — a rate that follows the state, multiplied by absolute time, jumps the phase; integrate it over time instead`); }
  if (!meta.anim.length && !meta.ramps.length) warns.push('SCENE.QA() has no anim / ramps: time-driven effects (weather, water, fire, scrolling fog) are not checked for freezing or sweeping');
}
if (errors.length) fails.push(...errors.map((e) => 'page error: ' + e));
report.fails = fails; report.warns = warns; fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 1));
for (const w of warns) console.log('WARN', w); for (const f of fails) console.log('FAIL', f);
console.log(fails.length ? `qa: ${fails.length} failure(s), see ${out}/` : `qa: ok (${Object.keys(report.states).length} states, ${Object.keys(report.cycles).length} cycles) → ${out}/`);
await browser.close(); srv.close(); process.exit(fails.length ? 2 : 0);
