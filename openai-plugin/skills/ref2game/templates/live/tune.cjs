// node live/tune.cjs [path] — run the attract script headless and print its events (and optionally the path).
// Re-run after EVERY sim change: the demo must still reach its beats. Pass = SIM.demoCheck(S) if the sim defines it,
// else every pickup in S.got collected (no S.got: pass). Tune SCRIPT times here, not by eye.
// SIM.selfCheck() (optional) → [failure strings]: what the level data must satisfy after every placement pass (spawns in open
// space, every enemy able to reach the player, every pickup reachable…); any failure fails the run.
const SIM = require('./sim.js');
const S = SIM.create(); const path = []; const n0 = (v) => (typeof v === 'number' ? v.toFixed(0) : '-');
while (S.t < SIM.L - 1e-6) { SIM.step(S, SIM.scriptInput(S.t, S)); if (S.steps % 6 === 0) path.push([S.t.toFixed(2), n0(S.x), n0(S.y), S.ground || '']); }
for (const e of (S.ev || []).filter((e) => e.k !== 'step' && e.k !== 'rustle')) console.log(e.k.padEnd(8), e.t.toFixed(2), n0(e.x), n0(e.y), e.v ? e.v.toFixed(0) : '');
const ok = SIM.demoCheck ? !!SIM.demoCheck(S) : (!S.got || S.got.every((g) => g >= 0));
const got = S.got ? `collected ${S.got.filter((g) => g >= 0).length}/${S.got.length}` : 'no pickups';
console.log(`${got}${S.hearts !== undefined ? '  hearts ' + S.hearts : ''}  end ${n0(S.x)},${n0(S.y)}${SIM.demoCheck ? '  demoCheck ' + (ok ? 'ok' : 'FAIL') : ''}`);
if (process.argv[2] === 'path') for (const p of path) console.log(p.join(' '));
const self = SIM.selfCheck ? SIM.selfCheck() : []; for (const f of self) console.log('FAIL', f);
if (SIM.selfCheck) console.log(`selfCheck ${self.length ? self.length + ' failure(s)' : 'ok'}`);
process.exitCode = ok && !self.length ? 0 : 1;
