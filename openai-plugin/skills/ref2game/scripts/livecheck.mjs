// livecheck.mjs — play-test the live page like a player would, headless (run from the project root).
//   node <skill>/scripts/livecheck.mjs [--keys "ArrowRight:down@0.2, Space:press@1.0, ArrowRight:up@2, Move:960x360@2.2, Click:960x360@2.5"] [--shots 0.5,1.2,2.5]
//   (Move/Click take view pixels, e.g. 960x360 on a 1920×1080 view; Down:XxY@t moves and holds the left button, Up:_@t releases,
//    Wheel:±1@t scrolls — hold-to-use tools, aim-and-release, hotbar wheels)
//        [--for 4] [--url http://127.0.0.1:PORT/live/index.html] [--out frames/livecheck] [--reload] [--eval "SCENE.state.x"] [--minfps 55]
// Clears the saved session, starts play mode with the first key, runs the timed key script (down/up/press @ seconds),
// takes screenshots at --shots, optionally touches sim.js to prove hot-reload keeps the play state (--reload), and
// prints one JSON line: { errors, fps, dev, evals, shots }. Exit code 2 on page errors or fps < --minfps (default 55).
// Without --url it serves the project itself on a free port.
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module';
const here = path.dirname(new URL(import.meta.url).pathname);
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT || path.join(here, 'node_modules/playwright'));
const args = process.argv.slice(2); const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const root = process.cwd(); let srv = null, url = opt('url');
if (!url) {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png', '.json': 'application/json' };
  srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0]));
    fs.stat(f, (e, st) => { if (e) { r.writeHead(404); r.end(); return; }
      r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream', 'last-modified': st.mtime.toUTCString(), 'content-length': st.size });
      if (q.method === 'HEAD') return r.end(); fs.createReadStream(f).pipe(r); }); });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r)); url = `http://127.0.0.1:${srv.address().port}/live/index.html`;
}
const out = opt('out', 'frames/livecheck'); fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ['--use-angle=' + (process.platform === 'darwin' ? 'metal' : 'default'), '--enable-gpu', '--ignore-gpu-blocklist'] });
const vw = +opt('vw', 1280), p = await browser.newPage({ viewport: { width: vw, height: Math.round(vw * 9 / 16) } });   // --vw 1920: full-size shots
const errors = []; p.on('pageerror', (e) => errors.push(e.message)); p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
await p.goto(url); await p.evaluate(() => sessionStorage.clear()); await p.reload(); await p.waitForTimeout(2500);
const ev = []; for (const s of (opt('keys', 'ArrowRight:down@0, ArrowRight:up@1.5, Space:press@1.8')).split(',').map((x) => x.trim()).filter(Boolean)) {
  const [k, rest] = s.split(':'); const [act, at] = rest.split('@'); ev.push({ k, act, at: +at }); }
const shots = (opt('shots', '1,2.5')).split(',').map(Number).map((at) => ({ at, shot: true }));
const tl = [...ev, ...shots].sort((a, b) => a.at - b.at); const t0 = Date.now(); const files = [];
for (const e of tl) { const wait = e.at * 1000 - (Date.now() - t0); if (wait > 0) await p.waitForTimeout(wait);
  if (e.shot) { const f = path.join(out, `play_${e.at.toFixed(2)}.png`); await p.screenshot({ path: f }); files.push(f); }
  else if (e.k === 'Up') await p.mouse.up();
  else if (e.k === 'Wheel') await p.mouse.wheel(0, +e.act * 100);
  else if (e.k === 'Click' || e.k === 'Move' || e.k === 'Down') { const [vx, vy] = e.act.split('x').map(Number);             // view px → page px
    const [x, y] = await p.evaluate(([vx, vy]) => { const r = document.getElementById('c').getBoundingClientRect(), V = (window.SIM && SIM.VIEW) || { W: 1920, H: 1080 };
      return [r.left + vx / V.W * r.width, r.top + vy / V.H * r.height]; }, [vx, vy]);
    if (e.k === 'Click') await p.mouse.click(x, y); else { await p.mouse.move(x, y, { steps: 8 }); if (e.k === 'Down') await p.mouse.down(); } }
  else if (e.act === 'down') await p.keyboard.down(e.k); else if (e.act === 'up') await p.keyboard.up(e.k); else await p.keyboard.press(e.k); }
const total = +opt('for', 0) * 1000; if (total > Date.now() - t0) await p.waitForTimeout(total - (Date.now() - t0));
let reload = null;
if (args.includes('--reload')) { const before = await p.evaluate(() => !!(window.SCENE && SCENE.state));
  const f = path.join(root, 'live/sim.js'); const now = new Date(); fs.utimesSync(f, now, now); await p.waitForTimeout(3500);
  const after = await p.evaluate(() => !!(window.SCENE && SCENE.state)); reload = { playingBefore: before, playingAfter: after }; }
const evals = []; for (const x of args.filter((a, i) => args[i - 1] === '--eval')) evals.push(await p.evaluate((x) => { try { return JSON.stringify(eval(x)); } catch (e) { return 'ERR ' + e.message; } }, x));
await p.waitForTimeout(1200);
const dev = (await p.textContent('#dev').catch(() => '')) || '';
const fps = Math.round(await p.evaluate(() => new Promise((res) => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 1000) requestAnimationFrame(f); else res(n * 1000 / (performance.now() - t0)); }; requestAnimationFrame(f); })));
console.log(JSON.stringify({ errors, fps, dev, reload, evals, shots: files }));
await browser.close(); if (srv) srv.close(); if (errors.length || fps < +opt('minfps', 55)) process.exit(2);
