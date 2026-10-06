// render.mjs — deterministic offline renders of the live page (run from the project root).
//   node <skill>/scripts/render.mjs stills 0,1.5,3 [--out frames/check] [--q "fx=0&only=coin"] [--page live/index.html]
//   node <skill>/scripts/render.mjs video [--from 0] [--to 12] [--fps 30] [--jobs 4] [--out frames/film.mp4]
// Serves the project over http itself (file:// images cannot be uploaded to WebGL), opens <page>?render=1 and calls
// window.__renderAt(t) — the scene must be a pure function of t. Exit code 2 if the page logged errors.
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { execFileSync } from 'node:child_process'; import { createRequire } from 'node:module';
const here = path.dirname(new URL(import.meta.url).pathname);
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT || path.join(here, 'node_modules/playwright'));
const root = process.cwd();
const [mode, a2, ...rest] = process.argv.slice(2); const args = mode === 'stills' ? rest : [a2, ...rest].filter(Boolean);
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
if (!['stills', 'video'].includes(mode)) { console.log('usage: render.mjs stills T1,T2 [--out dir] | video [--to s --fps n --out file.mp4]'); process.exit(1); }
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.png': 'image/png', '.jpg': 'image/jpeg', '.json': 'application/json', '.css': 'text/css' };
const srv = http.createServer((q, r) => { const f = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' }); r.end(d); }); });
await new Promise((r) => srv.listen(0, '127.0.0.1', r)); const port = srv.address().port;
const browser = await chromium.launch({ args: ['--use-angle=' + (process.platform === 'darwin' ? 'metal' : 'default'), '--enable-gpu', '--ignore-gpu-blocklist'] });
let errors = 0;
const open = async () => { const tab = await browser.newPage({ viewport: { width: 960, height: 540 } });
  tab.on('pageerror', (e) => { errors++; console.error('PAGE ERROR:', e.message); }); tab.on('console', (m) => { if (m.type() === 'error') { errors++; console.error('console:', m.text()); } });
  await tab.goto(`http://127.0.0.1:${port}/${opt('page', 'live/index.html')}?render=1&${opt('q', '')}`);
  await tab.waitForFunction(() => window.__ready === true, null, { timeout: 120000 }); return tab; };
const grab = async (tab, t, f) => { const d = await tab.evaluate((t) => window.__renderAt(t), t); fs.writeFileSync(f, Buffer.from(d.split(',')[1], 'base64')); };
if (mode === 'stills') {
  const out = opt('out', 'frames/check'); fs.mkdirSync(out, { recursive: true }); const tab = await open(); const t0 = Date.now(); const ts = a2.split(',').map(Number);
  for (const t of ts) { const f = path.join(out, `t${t.toFixed(2)}.png`); await grab(tab, t, f); console.log(f); }
  console.log('ms/frame', Math.round((Date.now() - t0) / ts.length));
} else {
  const from = +opt('from', 0), to = +opt('to', 12), fps = +opt('fps', 30), out = opt('out', 'frames/film.mp4'), jobs = +opt('jobs', 4);
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  const dir = fs.mkdtempSync(path.join(path.dirname(path.resolve(out)), '.frames-')); const n = Math.round((to - from) * fps);
  const tabs = await Promise.all(Array.from({ length: jobs }, open)); let next = 0, done = 0; const t0 = Date.now();
  await Promise.all(tabs.map(async (tab) => { while (next < n) { const i = next++; await grab(tab, from + i / fps, path.join(dir, String(i).padStart(5, '0') + '.png'));
    if (++done % 60 === 0) console.log(done + '/' + n, ((Date.now() - t0) / 1000).toFixed(0) + 's'); } }));
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-framerate', String(fps), '-i', path.join(dir, '%05d.png'), '-c:v', 'libx264', '-crf', '17', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]);
  fs.rmSync(dir, { recursive: true, force: true }); console.log('wrote', out);
}
await browser.close(); srv.close(); if (errors) process.exit(2);
