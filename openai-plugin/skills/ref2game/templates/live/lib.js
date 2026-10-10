// live/lib.js — the shared engine layer on top of gl.js. Everything a scene draws goes through here:
//   shader library (sprite with grade/haze/tint/rim/sway/lean/bend/bulge/fades, glow, shadow, fbm fog, waterfall, foam,
//   cartoon water with reflection, puffs, stars, rings, rig joint caps, god rays, bloom, final grade, lit dust motes),
//   sprite(), drop-shadow and ink-outline passes, 2D affine helpers, a two-bone cut-out limb, a HUD glyph atlas, and
//   the frame pipeline: beginBG → (layers) → godRays → beginComp → (water, play plane, FX) → veil/motes → finish → HUD.
// Pure function of its inputs: no Math.random, no Date. Query flags: ?fx=0 (no fog/rays), ?only=a,b (draw only those sprites).
(function () {
  const L = (window.LIB = {});
  const Q = new URLSearchParams(location.search);
  L.NOFX = Q.get('fx') === '0';
  L.ONLY = (Q.get('only') || '').split(',').filter(Boolean);

  // ---------------- shaders (GLSL ES 3.00 bodies; gl.js prepends COMMON: hash, vnoise, fbm, scr) ----------------
  const SPRITE = `
uniform sampler2D u_tex; uniform float u_alpha, u_lod;
uniform vec4 u_src;            // uv sub-rect x0,y0,x1,y1
uniform vec4 u_grade;          // saturation, brightness, haze amount, contrast
uniform vec3 u_haze;
uniform vec4 u_sway;           // amp (uv), spatial freq, phase, mode (1 rooted at bottom, 2 hung from top)
uniform vec2 u_pad;            // quad padding (uv) so swayed pixels are not clipped
uniform vec4 u_rim; uniform vec3 u_rimCol;   // strength, dir.xy (uv), width
uniform vec4 u_tint;           // rgb, amount
uniform vec2 u_fade;           // soft left / right edge (uv) to hide strip cuts
uniform float u_vfade;         // ragged bottom fade (uv of the drawn rect)
uniform float u_tfade;         // soft top fade
uniform vec4 u_bulge;          // centre uv, radius (uv), amount — local inflate (breathing, swelling)
uniform vec4 u_bend;           // amp (uv of height), load u, load width (uv), on — sag field: catenary dip + local dip
uniform float u_disc;          // > 0: only a round disc of the drawn rect is kept (soft edge width, uv) — joint caps
uniform vec2 u_lean;           // shift (uv of width) at the free end, y = 0 rooted at the bottom / 1 hung from the top — pushed aside, leaned by wind
// soft bones in one painted sprite (an animal's neck and head, a tail): weight map u_wtex (R, G, B = bones 0..2,
// tools/softbones.py), u_bone0..2 = root (uv), angle (rad), on; u_wsz = texture px. Every pixel turns about its bone's root by
// angle × weight, so the bone bends with no cut. Bone 2 is a child of bone 0 (the head turns at the poll, then rides on the
// neck). Drawn by inverse mapping: a few guesses refined by fixed-point steps; of those that map back exactly, the opaque one
// wins (the background under a raised head maps to itself too), then the one that moved more (the bone is in front); a spot
// nothing maps to any more (where the head was) is left empty.
uniform sampler2D u_wtex; uniform vec4 u_bone0, u_bone1, u_bone2; uniform vec2 u_wsz;
vec2 rotP(vec2 p, vec2 c, float a){ vec2 d = (p - c) * u_wsz; float cs = cos(a), sn = sin(a); return c + vec2(d.x * cs - d.y * sn, d.x * sn + d.y * cs) / u_wsz; }
vec2 boneW(vec2 q, vec3 w, float s){ vec2 r = q;
  if (s > 0.0) { if (u_bone2.w > 0.0) r = rotP(r, u_bone2.xy, u_bone2.z * w.b); if (u_bone0.w > 0.0) r = rotP(r, u_bone0.xy, u_bone0.z * w.r); if (u_bone1.w > 0.0) r = rotP(r, u_bone1.xy, u_bone1.z * w.g); }
  else { if (u_bone1.w > 0.0) r = rotP(r, u_bone1.xy, -u_bone1.z * w.g); if (u_bone0.w > 0.0) r = rotP(r, u_bone0.xy, -u_bone0.z * w.r); if (u_bone2.w > 0.0) r = rotP(r, u_bone2.xy, -u_bone2.z * w.b); }
  return r; }
vec3 boneT(vec2 q){ return textureLod(u_wtex, q, 0.0).rgb; }
float boneSc(vec2 q, float e){ if (e > 1.5 || q.x < 0.0 || q.x > 1.0 || q.y < 0.0 || q.y > 1.0) return -1.0;
  vec3 w = boneT(q); return textureLod(u_tex, mix(u_src.xy, u_src.zw, q), 0.0).a * 2.0 + max(max(w.r * u_bone0.w, w.g * u_bone1.w), w.b * u_bone2.w) * 0.5 - e * 0.01; }
vec2 boneInv(vec2 p, out float err){
  vec2 best = p; float be = length((boneW(p, boneT(p), 1.0) - p) * u_wsz), bs = boneSc(p, be);
  for (int i = 0; i < 12; i++) { int b = i / 4; float k = float(i - b * 4 + 1) * 0.25;
    if ((b == 0 ? u_bone0.w : b == 1 ? u_bone1.w : u_bone2.w) <= 0.0) continue;
    vec2 q = boneW(p, b == 0 ? vec3(k, 0.0, 0.0) : b == 1 ? vec3(0.0, k, 0.0) : vec3(1.0, 0.0, k), -1.0);
    for (int it = 0; it < 4; it++) q = boneW(p, boneT(q), -1.0);
    float e = length((boneW(q, boneT(q), 1.0) - p) * u_wsz), sc = boneSc(q, e); if (sc > bs) { bs = sc; be = e; best = q; } }
  err = bs < 0.0 ? 9.0 : be; return best; }
void main(){
  vec2 uv = (v_uv - u_pad) / (1.0 - 2.0 * u_pad);
  // mip level from the undeformed mapping (a warped lookup has no usable derivatives across its seams)
  vec2 tsz = vec2(textureSize(u_tex, 0)) * (u_src.zw - u_src.xy), du = dFdx(uv) * tsz, dv = dFdy(uv) * tsz;
  float lod0 = max(0.0, 0.5 * log2(max(dot(du, du), dot(dv, dv))));
  if (u_sway.w > 0.5) {
    float w = u_sway.w < 1.5 ? pow(clamp(1.0 - uv.y, 0.0, 1.0), 1.6) : pow(clamp(uv.y, 0.0, 1.0), 1.3);
    float s = sin(u_sway.z + uv.x * u_sway.y + uv.y * 2.0) + 0.45 * sin(u_sway.z * 1.73 + uv.x * u_sway.y * 2.3 + 1.7);
    uv.x += u_sway.x * w * s;
    if (u_sway.w > 1.5 && u_sway.w < 2.5) uv.y += u_sway.x * 0.25 * w * sin(u_sway.z * 1.31 + uv.x * 9.0);
  }
  if (u_sway.w > 2.5) {          // anchored at uv.x = 1: a wave travels to the free end (uv.x = 0)
    uv = (v_uv - u_pad) / (1.0 - 2.0 * u_pad);
    float w = pow(clamp(1.0 - uv.x, 0.0, 1.0), 1.4);
    uv.y += u_sway.x * w * sin(u_sway.z + uv.x * u_sway.y);
  }
  if (u_lean.x != 0.0) { float r = clamp(u_lean.y > 0.5 ? uv.y : 1.0 - uv.y, 0.0, 1.0); uv.x -= u_lean.x * r * r; if (u_lean.y < 0.5) uv.y += abs(u_lean.x) * 0.18 * r * r; }
  if (u_bend.w > 0.0) uv.y -= u_bend.x * (0.6 * sin(3.14159 * clamp(uv.x, 0.0, 1.0)) + 0.4 * exp(-pow((uv.x - u_bend.y) / u_bend.z, 2.0)));
  if (u_bulge.w > 0.0) { vec2 d = uv - u_bulge.xy; float r = length(d) / u_bulge.z; if (r < 1.0) uv = u_bulge.xy + d * (1.0 - u_bulge.w * (1.0 - r * r)); }
  float bErr = 0.0; if (u_bone0.w > 0.0 || u_bone1.w > 0.0 || u_bone2.w > 0.0) { uv = boneInv(uv, bErr); if (bErr > 1.5) discard; }
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) discard;
  vec2 tuv = mix(u_src.xy, u_src.zw, uv);
  vec4 c = (u_bone0.w > 0.0 || u_bone1.w > 0.0 || u_bone2.w > 0.0) ? textureLod(u_tex, tuv, lod0 + u_lod) : texture(u_tex, tuv, u_lod);
  c *= smoothstep(0.0, max(u_fade.x, 1e-4), uv.x) * smoothstep(1.0, 1.0 - max(u_fade.y, 1e-4), uv.x) ;
  if (u_tfade > 0.0) c *= smoothstep(0.0, u_tfade, uv.y);
  if (u_disc > 0.0) c *= smoothstep(0.5, 0.5 - u_disc, length(uv - 0.5));
  if (u_vfade > 0.0) c *= smoothstep(1.0, 1.0 - u_vfade, uv.y + u_vfade * 0.8 * (fbm(vec2(uv.x * 60.0, 0.0)) - 0.3));
  if (c.a < 0.002) discard;
  vec3 rgb = c.rgb / c.a;
  float l = dot(rgb, vec3(0.299, 0.587, 0.114));
  rgb = mix(vec3(l), rgb, u_grade.x) * u_grade.y;
  rgb = (rgb - 0.5) * u_grade.w + 0.5;
  rgb = mix(rgb, u_haze, u_grade.z);
  rgb = mix(rgb, rgb * u_tint.rgb, u_tint.a);
  if (u_rim.x > 0.0) {
    float a2 = texture(u_tex, mix(u_src.xy, u_src.zw, uv + u_rim.yz * u_rim.w), u_lod).a;
    rgb += u_rimCol * u_rim.x * smoothstep(0.2, 1.0, c.a) * (1.0 - a2);
  }
  o = vec4(max(rgb, 0.0) * c.a, c.a) * u_alpha;
}`;
  const GLOW = `
uniform vec3 u_col; uniform float u_k, u_amt;
void main(){ float d = length(v_uv * 2.0 - 1.0); float g = exp(-d * d * u_k) * smoothstep(1.0, 0.7, d) * u_amt; o = vec4(u_col * g, 0.0); }`;
  const SHADOW = `
uniform float u_amt;
void main(){ float d = length(v_uv * 2.0 - 1.0); float a = smoothstep(1.0, 0.1, d) * u_amt; o = vec4(vec3(0.02, 0.05, 0.03) * a, a); }`;
  const FOG = `
uniform vec4 u_p;      // scale, speed, threshold, density
uniform vec3 u_col; uniform vec2 u_sun; uniform float u_seed, u_scat;
void main(){
  vec2 p = v_px * u_p.x + vec2(u_t * u_p.y + u_seed * 13.0, u_seed * 7.0);
  float n = fbm(p * vec2(1.0, 2.4)) * 0.75 + fbm(p * vec2(2.7, 5.0) + vec2(u_t * u_p.y * 0.6, 0.0)) * 0.35;
  float prof = smoothstep(0.0, 0.4, v_uv.y) * smoothstep(1.0, 0.55, v_uv.y);
  float a = clamp((n - u_p.z) * 2.2, 0.0, 1.0) * prof * u_p.w;
  float sc = exp(-length(v_px - u_sun) / 650.0) * u_scat;
  vec3 col = mix(u_col, vec3(1.0, 0.93, 0.72), sc);
  o = vec4(col * a, a);
}`;
  const FALL = `
uniform sampler2D u_tex; uniform float u_aspect;
void main(){
  float y = v_uv.y, spread = 1.0 + 0.30 * y;
  float x = (v_uv.x - 0.5) * spread / 0.78 + 0.5;            // the sheet widens as it falls
  float Y = y * u_aspect, sp = 2.6;
  float s1 = fbm(vec2(x * 26.0, Y * 0.55 - u_t * sp));
  float s2 = fbm(vec2(x * 61.0 + 3.0, Y * 1.30 - u_t * sp * 1.45));
  float bund = smoothstep(0.30, 0.70, vnoise(vec2(x * 9.0, 0.5)));
  float v = s1 * 0.6 + s2 * 0.4;
  vec3 deep = vec3(0.26, 0.62, 0.68), mid = vec3(0.56, 0.87, 0.89), wht = vec3(0.95, 1.0, 1.0);
  vec3 c = mix(deep, mid, smoothstep(0.32, 0.55, v + bund * 0.1));
  c = mix(c, wht, smoothstep(0.52, 0.74, v) * (0.45 + 0.55 * bund));
  c = mix(c, wht, smoothstep(0.45, 1.0, y) * 0.55 * smoothstep(0.40, 0.65, s2));
  float lip = smoothstep(0.07, 0.0, y);
  c = mix(c, vec3(0.80, 0.96, 0.96), lip * 0.6);
  float e = abs(x - 0.5) * 2.0;
  float rag = fbm(vec2(Y * 1.6 - u_t * sp * 1.2, x * 4.0));
  float rag2 = vnoise(vec2(Y * 7.0 - u_t * sp * 2.0, x * 2.0 + 3.0));
  float a = smoothstep(1.0, 0.72 - 0.30 * rag - 0.10 * rag2, e);
  a *= smoothstep(0.0, 0.012, y) * smoothstep(1.0, 0.86, y);
  a *= mix(0.86, 1.0, smoothstep(0.45, 0.7, v));
  o = vec4(c * a, a);
}`;
  const FOAM = `
uniform float u_amt;
void main(){
  vec2 uv = v_uv;
  float n = fbm(vec2(uv.x * 7.0, uv.y * 3.0 + u_t * 0.9)) + 0.6 * fbm(vec2(uv.x * 15.0 - u_t * 0.3, uv.y * 7.0 + u_t * 1.7));
  float sh = 1.0 - length((uv - vec2(0.5, 0.78)) * vec2(1.6, 2.2));
  float a = smoothstep(0.55, 0.95, n * 0.7 + sh * 0.9) * u_amt;
  float lit = fbm(vec2(uv.x * 10.0, uv.y * 6.0 + u_t)) ;
  vec3 col = mix(vec3(0.70, 0.86, 0.88), vec3(1.0, 1.0, 0.98), smoothstep(0.35, 0.7, lit));
  o = vec4(col * a, a);
}`;
  const WATER = `
uniform sampler2D u_scene; uniform float u_wy; uniform vec2 u_sun, u_fall; uniform vec4 u_gust;   // front x, amp (two fronts)
void main(){
  vec2 p = v_px; float d = clamp((p.y - u_wy) / (u_res.y - u_wy), 0.0, 1.0);
  float pers = mix(0.35, 1.0, d);
  // gentle waves only displace the reflection
  float wv = sin(p.x * 0.012 / pers + u_t * 1.3 + d * 9.0) * 0.5 + sin(p.x * 0.031 / pers - u_t * 1.9 + d * 17.0) * 0.5;
  vec3 rc = texture(u_scene, scr(vec2(p.x + wv * 6.0, u_wy - (p.y - u_wy) * 1.5 - 8.0 + wv * 5.0 * pers))).rgb;
  // three cartoon depth bands with soft wavy borders
  float b = d + (fbm(vec2(p.x * 0.004, u_t * 0.05)) - 0.5) * 0.22;
  vec3 c1 = vec3(0.36, 0.88, 0.84), c2 = vec3(0.17, 0.71, 0.75), c3 = vec3(0.08, 0.52, 0.62);
  vec3 col = mix(c1, c2, smoothstep(0.28, 0.33, b)); col = mix(col, c3, smoothstep(0.66, 0.71, b));
  // posterised reflection near the far edge
  float fres = (1.0 - smoothstep(0.0, 0.5, d)) * 0.55;
  vec3 rq = floor(rc * 6.0 + 0.5) / 6.0;
  col = mix(col, mix(col, rq * vec3(0.85, 1.05, 1.02), 0.75), fres);
  // white ripple dashes drifting with the current
  vec2 g = vec2((p.x + u_t * 18.0) / (95.0 * pers), (p.y - u_wy) / (15.0 * pers));
  vec2 id = floor(g), f = fract(g) - 0.5; float h = hash(id), life = sin(3.1416 * fract(h * 7.0 + u_t * 0.22 * (0.5 + h)));
  f.x += (h - 0.5) * 0.5;
  float dash = smoothstep(0.5, 0.3, abs(f.x) / (0.30 + 0.35 * h)) * smoothstep(0.2, 0.06, abs(f.y)) * step(0.52, h) * life;
  col = mix(col, vec3(0.93, 1.0, 0.98), dash * (0.8 - 0.45 * d));
  // sparkling sun path: small twinkling horizontal glints
  vec2 g2 = vec2(p.x / (34.0 * pers), (p.y - u_wy) / (7.0 * pers)); vec2 i2 = floor(g2), f2 = fract(g2) - 0.5; float h2 = hash(i2 + 3.7);
  float tw = max(0.0, sin(u_t * (3.0 + 4.0 * h2) + h2 * 40.0));
  float glint = smoothstep(0.5, 0.1, abs(f2.x + (h2 - 0.5) * 0.4) * 2.2) * smoothstep(0.35, 0.05, abs(f2.y)) * step(0.80, h2) * tw * tw;
  col += glint * exp(-abs(p.x - u_sun.x) / 320.0) * vec3(1.0, 0.96, 0.80) * 0.9 * (1.0 - 0.7 * d);
  // churn under the waterfall
  float fx = exp(-pow((p.x - u_fall.x) / u_fall.y, 2.0));
  float fn = fbm(vec2(p.x * 0.02, (p.y - u_wy) * 0.08 - u_t * 0.6));
  col = mix(col, vec3(0.92, 0.99, 0.98), smoothstep(0.50, 0.60, fn + fx * 0.5 - d * 0.6) * fx);
  // gust cat's paw: a darker, rippled patch that races across with the wind front
  for (int i = 0; i < 2; i++){ float fx2 = i == 0 ? u_gust.x : u_gust.z, am = i == 0 ? u_gust.y : u_gust.w; float dd = p.x - fx2;
    float m = am * exp(-pow(dd / (dd > 0.0 ? 160.0 : 460.0), 2.0)) * smoothstep(0.0, 0.25, d);
    float st = fbm(vec2(p.x * 0.03 - u_t * 3.0, (p.y - u_wy) * 0.25 / pers));
    col = mix(col, col * vec3(0.72, 0.86, 0.93), min(1.0, m) * 0.7 * smoothstep(0.30, 0.60, st)); col += vec3(0.9, 1.0, 1.0) * min(1.0, m) * 0.55 * smoothstep(0.62, 0.70, st) * (1.0 - 0.6 * d); }
  // wavy shoreline foam
  float sh = (p.y - u_wy) - 5.0 - 4.0 * sin(p.x * 0.03 + u_t * 1.5) - 3.0 * fbm(vec2(p.x * 0.02, u_t * 0.3));
  col = mix(col, vec3(0.90, 1.0, 0.97), smoothstep(3.0, 0.0, sh) * 0.85);
  o = vec4(col, 1.0);
}`;
  // CRACK — ground impact fissures (a slam, a stomp, a meteor) on the ground ellipse of the quad (2R × R). Nine jagged main cracks race out from the
  // impact (tips first), each with two branches; the centre shatters into plates (cell edges) round a shallow crater.
  // u_mode 0 = the ground decal (dark fissures, a pale broken lip, scorch; lit like the ground), 1 = the emissive pass
  // after the light (magma in the fissures cooling from the tips inward, a halo, late embers), hidden wherever a sprite
  // covers the ground: u_mask = the frame before the light pass, whose alpha is 0 on the ground and 1 on sprites.
  const CRACK = `
uniform float u_seed, u_age, u_mode, u_amt; uniform sampler2D u_mask;
float h1(float n){ return fract(sin(n * 127.1 + u_seed * 311.7) * 43758.5453); }
float n1(float x, float k){ float i = floor(x), f = fract(x); return mix(h1(i + k * 17.0), h1(i + 1.0 + k * 17.0), f) * 2.0 - 1.0; }
vec2 ray(vec2 q, vec2 p0, float th, float L, float k){ vec2 d = vec2(cos(th), sin(th)), n = vec2(-d.y, d.x), v = q - p0; float s = dot(v, d), t = dot(v, n), u = s / L;
  float off = (n1(s * 11.0, k) * 0.65 + n1(s * 29.0, k + 3.0) * 0.35) * 0.075 * smoothstep(0.0, 0.25, u) * (0.4 + u);
  return vec2(abs(t - off), u); }
vec2 h2(vec2 p){ return vec2(hash(p + u_seed), hash(p.yx * 1.7 + u_seed * 3.1)); }
void main(){
  vec2 q = v_uv * 2.0 - 1.0; float r = length(q);
  float grow = smoothstep(0.0, 0.17, u_age), fade = (1.0 - smoothstep(3.0, 4.6, u_age)) * u_amt;
  float core = 0.0, edge = 0.0, hot = 0.0;
  for (int k = 0; k < 9; k++) { float fk = float(k), th = (fk + 0.6 * h1(fk)) / 9.0 * 6.2832, L = 0.55 + 0.42 * h1(fk + 20.0), W = 0.03 + 0.016 * h1(fk + 40.0);
    vec2 a = ray(q, vec2(0.0), th, L, fk); float w = W * pow(max(0.0, 1.0 - a.y), 0.75), on = step(0.0, a.y) * step(a.y, grow);
    float c = smoothstep(w, w * 0.3, a.x) * on; core = max(core, c); edge = max(edge, smoothstep(w * 2.8 + 0.006, w, a.x) * on); hot = max(hot, c * (1.0 - a.y * a.y));
    for (int b = 0; b < 2; b++) { float fb = float(b), sb = (0.25 + 0.4 * h1(fk * 3.0 + fb + 60.0)) * L, tb = th + (fb * 2.0 - 1.0) * (0.35 + 0.45 * h1(fk * 5.0 + fb + 80.0));
      float Lb = (0.22 + 0.3 * h1(fk * 7.0 + fb)) * L; vec2 bb = ray(q, vec2(cos(th), sin(th)) * sb, tb, Lb, fk * 4.0 + fb + 9.0);
      float wb = W * 0.6 * pow(max(0.0, 1.0 - sb / L), 0.7) * pow(max(0.0, 1.0 - bb.y), 0.9), ob = step(0.0, bb.y) * step(bb.y, (grow * L - sb) / Lb * 1.6);
      float cb = smoothstep(wb, wb * 0.3, bb.x) * ob; core = max(core, cb); edge = max(edge, smoothstep(wb * 2.8 + 0.005, wb, bb.x) * ob); hot = max(hot, cb * 0.7 * (1.0 - bb.y)); } }
  // shattered plates round the crater: cell edges (F2 − F1) of a small Voronoi field
  { vec2 g = q * 7.5, ip = floor(g), fp = fract(g); float F1 = 9.0, F2 = 9.0;
    for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) { vec2 o2 = vec2(float(i), float(j)), pp = o2 + h2(ip + o2) - fp; float d = dot(pp, pp); if (d < F1) { F2 = F1; F1 = d; } else if (d < F2) F2 = d; }
    float cell = smoothstep(0.07, 0.015, sqrt(F2) - sqrt(F1)) * smoothstep(0.36, 0.12, r) * step(r, 0.4 * grow + 0.02);
    core = max(core, cell * 0.85); edge = max(edge, cell); hot = max(hot, cell * 0.8); }
  float crater = smoothstep(0.24, 0.02, r), lip = smoothstep(0.17, 0.23, r) * smoothstep(0.32, 0.23, r);
  if (u_mode < 0.5) {
    vec3 dark = vec3(0.035, 0.026, 0.02), pale = vec3(0.52, 0.43, 0.31);
    float aE = edge * (1.0 - core) * 0.32, aC = core * 0.95, aS = crater * 0.45 + smoothstep(0.75, 0.0, r) * 0.18, aL = lip * 0.22 * grow;
    float A = clamp(aC + aE + aS * (1.0 - aC) + aL, 0.0, 1.0) * fade;
    vec3 col = (dark * (aC + aS) + pale * (aE + aL)) / max(1e-3, aC + aE + aS + aL);
    o = vec4(col * A, A);
  } else {
    float heat = exp(-u_age / 0.42), ember = smoothstep(0.45, 0.9, vnoise(q * 18.0 + u_age * 0.6)) * exp(-u_age / 1.6) * (1.0 - smoothstep(0.0, 0.7, r));
    vec3 hotC = mix(vec3(1.0, 0.32, 0.06), vec3(1.0, 0.85, 0.45), hot * heat);
    float mask = 1.0 - texture(u_mask, scr(v_px)).a;
    float I = (hot * heat * 1.3 + edge * heat * 0.2 + crater * heat * 0.5 + core * ember * 0.9) * fade * mask;
    o = vec4(hotC * I, 0.0);
  } }`;
  // RAIN — weather for a 2:1 ground view (u_cam = camera px; ground point = (x + cam.x, (y + cam.y) · 2)).
  // WET (ground decal pass): the ground darkens and patches of puddles darker still. RAINFX (after the light pass, mode 0):
  // splash rings and puddle sheen on the ground only (u_mask alpha = sprites) brightened by the light map; mode 1: three
  // layers of slanted streaks with parallax over everything, each streak lit by the light map where it falls (drops glow
  // round a fire or a lamp).
  const WET = `uniform float u_amt; uniform vec2 u_cam;
float pud(vec2 g){ return smoothstep(0.6, 0.66, fbm(g * 0.0045 + 4.0)); }
void main(){ vec2 g = vec2(v_px.x + u_cam.x, (v_px.y + u_cam.y) * 2.0); float a = u_amt * (0.22 + 0.32 * pud(g));
  o = vec4(vec3(0.02, 0.025, 0.04) * a, a); }`;
  const RAINFX = `uniform float u_amt, u_mode, u_wind; uniform vec2 u_cam; uniform sampler2D u_mask, u_light;
float pud(vec2 g){ return smoothstep(0.6, 0.66, fbm(g * 0.0045 + 4.0)); }
float lum(vec3 c){ return dot(c, vec3(0.3, 0.55, 0.15)); }
float streaks(vec2 px, float cw, float per, float speed, float len, float seed, float dens){
  vec2 q = px; q.x += q.y * u_wind; float col = floor(q.x / cw), fx = fract(q.x / cw);
  float r1 = hash(vec2(col, seed)), r2 = hash(vec2(col, seed + 7.3)), r3 = hash(vec2(col, seed + 1.9));
  float y = (q.y - u_t * speed * (0.85 + 0.3 * r1)) / per + r2 * 9.0, s = fract(y), k = floor(y);
  float on = step(hash(vec2(col, k + seed)), dens), x0 = 0.25 + 0.5 * r3, w = 0.55 / cw;
  return on * smoothstep(w, 0.0, abs(fx - x0)) * smoothstep(0.0, len, s) * step(s, len) * (0.35 + 0.65 * s / len); }
void main(){ vec3 lt = texture(u_light, scr(v_px)).rgb;
  if (u_mode < 0.5) { vec2 g = vec2(v_px.x + u_cam.x, (v_px.y + u_cam.y) * 2.0); float m = 1.0 - texture(u_mask, scr(v_px)).a, sp = 0.0;
    for (int i = 0; i < 2; i++) { float cs = 46.0 + 30.0 * float(i); vec2 c = floor(g / cs), f = g - (c + 0.5) * cs; f += (vec2(hash(c + float(i)), hash(c.yx + 3.0 + float(i))) - 0.5) * cs * 0.8;
      float ph = fract(u_t * (1.6 + hash(c * 1.3 + float(i))) + hash(c + 9.1 + float(i))), r = ph * 7.0, d = length(f * vec2(1.0, 1.0));
      sp += smoothstep(1.6, 0.0, abs(d - r * 2.0)) * (1.0 - ph) * step(hash(c * 2.7 + float(i) + 0.5), 0.55 + 0.4 * u_amt); }
    // puddles only catch strong lights (a fire, a lamp, a lightning flash), as broken glints that the drops stir
    float sheen = pud(g) * min(1.0, smoothstep(0.75, 2.2, lum(lt))) * (0.35 + 0.65 * smoothstep(0.3, 0.75, fbm(g * vec2(0.012, 0.02) + vec2(u_t * 0.35, 0.0))) + 1.5 * sp);
    vec3 c = (vec3(0.55, 0.62, 0.75) * sp * (0.06 + 0.3 * min(1.0, lum(lt))) + min(lt, vec3(1.4)) * sheen * 0.16) * u_amt * m; o = vec4(c, 0.0); }
  else { vec2 p = v_px; float a = streaks(p + u_cam * 0.95, 21.0, 230.0, 1500.0, 0.34, 1.0, 0.5 * u_amt) * 0.55
      + streaks(p + u_cam * 0.8, 13.0, 160.0, 1150.0, 0.3, 2.0, 0.55 * u_amt) * 0.35 + streaks(p + u_cam * 0.6, 8.0, 110.0, 850.0, 0.26, 3.0, 0.6 * u_amt) * 0.22;
    vec3 c = vec3(0.6, 0.66, 0.78) * (0.32 + 1.1 * lum(lt)) + lt * 0.5; a *= u_amt; o = vec4(c * a, a * 0.7); } }`;
  const SOLID = `uniform vec3 u_col; uniform float u_a; void main(){ o = vec4(u_col * u_a, u_a); }`;
  const JOINT = `
uniform vec3 u_col; uniform float u_dark;
void main(){ vec2 q = v_uv * 2.0 - 1.0; float d = length(q);
  float a = smoothstep(1.0, 0.88, d), ink = smoothstep(0.74, 0.86, d);
  vec3 c = u_col * mix(1.08, 0.80, smoothstep(-0.6, 0.8, q.x * 0.5 + q.y));
  c = mix(c, vec3(0.12, 0.07, 0.02), ink); o = vec4(c * u_dark * a, a); }`;
  const PUFF = `
uniform vec3 u_col; uniform float u_amt, u_seed;
void main(){ vec2 q = v_uv * 2.0 - 1.0; float d = length(q);
  float n = vnoise(q * 2.6 + u_seed * 7.3) * 0.45 + vnoise(q * 5.0 - u_seed * 3.1) * 0.25;
  float a = smoothstep(1.0, 0.25, d + n * 0.55 - 0.1) * u_amt;
  vec3 c = u_col * mix(1.08, 0.82, smoothstep(-0.8, 0.9, q.y));
  o = vec4(c * a, a); }`;
  const STAR = `
uniform vec3 u_col; uniform float u_amt;
void main(){ vec2 q = v_uv * 2.0 - 1.0; float d = length(q);
  float s = 0.035 / (abs(q.x * q.y) * 6.0 + 0.035) * smoothstep(1.0, 0.0, d);
  float core = exp(-d * d * 18.0);
  float a = clamp(s * 0.9 + core, 0.0, 1.0) * u_amt; o = vec4(u_col * a, 0.0); }`;
  const RING = `
uniform vec3 u_col; uniform float u_amt, u_w;
void main(){ float d = length(v_uv * 2.0 - 1.0); float a = smoothstep(u_w, 0.0, abs(d - 0.85)) * u_amt; o = vec4(u_col * a, a * 0.6); }`;
  const COPY = `uniform sampler2D u_src; void main(){ o = texture(u_src, scr(v_px)); }`;
  const RMASK = `
uniform sampler2D u_src; uniform vec2 u_sun;
void main(){ vec3 c = texture(u_src, scr(v_px)).rgb; float l = dot(c, vec3(0.299, 0.587, 0.114));
  float m = smoothstep(0.78, 0.96, l) * smoothstep(0.0, 0.10, c.r - c.b);
  m *= smoothstep(0.75, 0.45, v_px.y / u_res.y);
  m *= 0.15 + 0.85 * exp(-length(v_px - u_sun) / (u_res.x * 0.22));
  vec2 dv = v_px - u_sun; float ang = atan(dv.y, dv.x);
  m *= 0.25 + 0.75 * smoothstep(0.38, 0.72, fbm(vec2(ang * 7.0, u_t * 0.04)));
  o = vec4(vec3(m), 1.0); }`;
  const RAYS = `
uniform sampler2D u_src; uniform vec2 u_sun;
void main(){ vec2 uv = scr(v_px), su = scr(u_sun); vec2 dir = uv - su; float acc = 0.0, dec = 1.0, w = 0.0;
  float j = hash(v_px) * 0.9;
  for (int i = 0; i < 72; i++){ float f = (float(i) + j) / 72.0; acc += texture(u_src, uv - dir * f * 0.92).r * dec; w += dec; dec *= 0.975; }
  acc /= w;
  float fall = smoothstep(1.4, 0.0, length((v_px - u_sun) / u_res.x));
  o = vec4(vec3(acc * fall), 1.0); }`;
  const RAYADD = `
uniform sampler2D u_src; uniform float u_amt; uniform vec3 u_col;
void main(){ float r = texture(u_src, scr(v_px)).r; o = vec4(u_col * r * u_amt, 0.0); }`;
  const BRIGHT = `
uniform sampler2D u_src;
void main(){ vec3 c = texture(u_src, scr(v_px)).rgb; float l = max(c.r, max(c.g, c.b)); o = vec4(c * smoothstep(0.90, 1.08, l), 1.0); }`;
  const BLUR = `
uniform sampler2D u_src; uniform vec2 u_dir;
void main(){ vec2 uv = scr(v_px); vec2 d = u_dir / u_res; vec3 s = texture(u_src, uv).rgb * 0.2270;
  s += (texture(u_src, uv + d * 1.3846).rgb + texture(u_src, uv - d * 1.3846).rgb) * 0.3162;
  s += (texture(u_src, uv + d * 3.2308).rgb + texture(u_src, uv - d * 3.2308).rgb) * 0.0703; o = vec4(s, 1.0); }`;
  const FINAL = `
uniform sampler2D u_src, u_bloom, u_bloom2; uniform vec2 u_bloomA; uniform float u_vig, u_warm, u_roll, u_dither;
void main(){ vec2 uv = scr(v_px); vec3 c = texture(u_src, uv).rgb;
  c += texture(u_bloom, uv).rgb * u_bloomA.x + texture(u_bloom2, uv).rgb * u_bloomA.y;
  float l = dot(c, vec3(0.299, 0.587, 0.114));
  c += vec3(0.020, 0.010, -0.018) * (smoothstep(0.4, 1.0, l) * u_warm) + vec3(-0.012, 0.004, 0.016) * (smoothstep(0.5, 0.0, l) * u_warm);
  float mx = max(c.r, max(c.g, c.b));
  if (mx > 0.8 && u_roll > 0.0) { float k = (0.8 + (1.0 - exp(-(mx - 0.8) * 3.0)) * 0.19) / mx; c *= u_roll < 1.0 ? mix(1.0, k, u_roll) : k; }
  vec2 q = (v_px / u_res - 0.5) * vec2(1.0, 0.85);
  c *= mix(u_vig, 1.0, smoothstep(0.85, 0.3, length(q) * 1.25));
  if (u_dither > 0.5) c += (hash(v_px + fract(u_t) * 100.0) - 0.5) / 255.0;
  o = vec4(c, 1.0); }`;
  const MOTE = `
uniform sampler2D u_rays; uniform float u_amt; uniform vec3 u_col;
void main(){ float d = length(v_uv * 2.0 - 1.0); float g = exp(-d * d * 5.0) * smoothstep(1.0, 0.5, d);
  float r = texture(u_rays, scr(v_px)).r; o = vec4(u_col * g * u_amt * (0.15 + 3.0 * r), 0.0); }`;

  // anti-aliased rounded rectangle with a vertical gradient (HUD panels, slots, bars, bubbles at full resolution)
  const RRECT = `uniform vec2 u_sz; uniform float u_r, u_a; uniform vec3 u_c0, u_c1;
void main(){ vec2 p = (v_uv - 0.5) * u_sz; vec2 q = abs(p) - (u_sz * 0.5 - u_r); float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - u_r;
  float m = 1.0 - smoothstep(-0.7, 0.7, d); vec3 c = mix(u_c0, u_c1, v_uv.y); o = vec4(c * m * u_a, m * u_a); }`;
  const SH = { SPRITE, GLOW, SHADOW, FOG, FALL, FOAM, WATER, CRACK, WET, RAINFX, SOLID, JOINT, PUFF, STAR, RING, COPY, RMASK, RAYS, RAYADD, BRIGHT, BLUR, FINAL, MOTE, RRECT };
  L.SH = SH;
  let P, T = {}, W, H;
  // extra: { name: fragmentSource } for scene-specific shaders. pixel: k > 1 renders bg/comp into W/k × H/k targets (still drawn
  // in W×H view px) that finish upscales with nearest: crisp pixel art (pair with SCENE.NEAREST, positions snapped to k px)
  L.init = (w, h, extra = {}, { pixel = 1 } = {}) => {
    W = L.W = w; H = L.H = h; P = L.P = {}; L.PIXEL = Math.max(1, pixel);
    for (const k in SH) P[k.toLowerCase()] = G.program(k.toLowerCase(), SH[k]);
    for (const k in extra) P[k] = G.program(k, extra[k]);
    const px = L.PIXEL, lo = { view: [w, h], nearest: px > 1 };
    T.bg = G.target(Math.round(w / px), Math.round(h / px), true, lo); T.comp = G.target(Math.round(w / px), Math.round(h / px), true, lo);
    T.mask = G.target(w / 2, h / 2, true); T.rays = G.target(w / 2, h / 2, true);
    T.b1 = G.target(w / 4, h / 4); T.b2 = G.target(w / 4, h / 4); T.c1 = G.target(w / 8, h / 8); T.c2 = G.target(w / 8, h / 8);
    L.T = T; L.SUN = [w * 0.31, h * 0.25];
  };

  // ---------------- math ----------------
  // affine 2x3 [a, b, c, d, e, f]: x' = a x + c y + e, y' = b x + d y + f  (y down, angles clockwise on screen)
  const M = L.M = {
    mul: (A, B) => [A[0] * B[0] + A[2] * B[1], A[1] * B[0] + A[3] * B[1], A[0] * B[2] + A[2] * B[3], A[1] * B[2] + A[3] * B[3], A[0] * B[4] + A[2] * B[5] + A[4], A[1] * B[4] + A[3] * B[5] + A[5]],
    t: (x, y) => [1, 0, 0, 1, x, y], r: (a) => [Math.cos(a), Math.sin(a), -Math.sin(a), Math.cos(a), 0, 0], s: (x, y) => [x, 0, 0, y, 0, 0],
    ap: (A, p) => [A[0] * p[0] + A[2] * p[1] + A[4], A[1] * p[0] + A[3] * p[1] + A[5]],
    of: (...Ls) => Ls.reduce((a, b) => M.mul(a, b)),
  };
  L.D2R = Math.PI / 180;
  L.SS = (e0, e1, x) => { const q = Math.max(0, Math.min(1, (x - e0) / (e1 - e0))); return q * q * (3 - 2 * q); };
  L.rnd = (a, b) => { const v = Math.sin(a * 127.1 + b * 311.7) * 43758.5453; return v - Math.floor(v); };   // deterministic hash → [0,1)
  L.lerpP = (a, b, w) => a.map((v, i) => v + (b[i] - v) * w);
  L.hsz = (n, h) => G.tex(n).w * h / G.tex(n).h;                          // width of texture n drawn at height h
  L.sz = (n, k) => [G.tex(n).w * k, G.tex(n).h * k];

  // ---------------- sprite ----------------
  const DEF = { alpha: 1, lod: 0, src: [0, 0, 1, 1], grade: [1, 1, 0, 1], haze: [0.93, 0.88, 0.76], sway: [0, 0, 0, 0], pad: [0, 0], rim: [0, 0, 0, 0],
    rimCol: [1, 0.85, 0.55], tint: [1, 1, 1, 0], fade: [0, 0], vfade: 0, tfade: 0, bulge: [0, 0, 0, 0], bend: [0, 0, 0, 0], lean: [0, 0], disc: 0, bone0: [0, 0, 0, 0], bone1: [0, 0, 0, 0], bone2: [0, 0, 0, 0], wsz: [1, 1] };
  L.sp = null;   // pass override: { dx, dy, a, lod } = soft drop shadow, { ..., ink: [r,g,b] } = flat ink silhouette
  // sprite(name, x, y, { w | h, src, pad, flip, rot, pivot, m, u: { uniforms without the u_ prefix } })
  //   x,y = top-left of the visible image. pad grows the quad (fraction of w/h) so deformed pixels are not clipped.
  //   m = rig matrix (M.*): the quad's pivot (px in the drawn image) sits at m's origin; x,y are ignored.
  L.sprite = (n, x, y, o = {}) => {
    if (L.ONLY.length && !L.ONLY.includes(n)) return { w: 0, h: 0 };
    const tx = G.tex(n), src = o.src || [0, 0, 1, 1];
    const sw = tx.w * (src[2] - src[0]), sh = tx.h * (src[3] - src[1]);
    let w = o.w, h = o.h; if (w && !h) h = w * sh / sw; if (h && !w) w = h * sw / sh; if (!w) { w = sw; h = sh; }
    const pad = o.pad || 0, pw = w * pad, ph = h * pad;
    const U = Object.assign({}, DEF, o.u || {}, { u_tex: tx });
    if (L.sp) { const sp = L.sp;
      Object.assign(U, { grade: sp.ink ? [0, 0, 1, 1] : [0, 0, 0, 1], haze: sp.ink || U.haze, alpha: sp.a * (U.alpha === undefined ? 1 : U.alpha), lod: sp.lod || 0, rim: [0, 0, 0, 0], tint: [1, 1, 1, 0] });
      x += sp.dx; y += sp.dy; if (o.m) o = Object.assign({}, o, { m: M.mul(M.t(sp.dx, sp.dy), o.m) }); }
    const uni = {}; for (const k in U) uni[k.startsWith('u_') ? k : 'u_' + k] = U[k];
    uni.u_pad = [pad / (1 + 2 * pad), pad / (1 + 2 * pad)];
    uni.u_src = src;
    const rot = o.rot || 0, piv = o.pivot || [0, 0];
    if (o.m) { const F = M.mul(o.m, [w + 2 * pw, 0, 0, h + 2 * ph, -pw - piv[0], -ph - piv[1]]);
      G.draw(P.sprite, uni, [F[0], F[1], 0, F[2], F[3], 0, F[4], F[5], 1], [o.flip ? 1 : 0, 0]); return { w, h }; }
    G.draw(P.sprite, uni, G.xf(x - pw, y - ph, w + 2 * pw, h + 2 * ph, rot, piv[0] + pw, piv[1] + ph), [o.flip ? 1 : 0, 0]);
    return { w, h };
  };
  // rig joint trace for qa.mjs (animation.md §14): while L.TRACE is an object, rigs report screen points per actor instance
  L.TRACE = null;
  L.joint = (id, name, p) => { if (L.TRACE) (L.TRACE[id] = L.TRACE[id] || {})[name] = [p[0], p[1]]; };
  // soft contact shadow of a group of sprites cast onto what is behind (draw it before the group itself)
  L.dropShadow = (draw, sp = { dx: 16, dy: 30, a: 0.45, lod: 4.5 }) => { L.sp = sp; draw(); L.sp = null; };
  // one weighted ink silhouette around a whole puppet: n offset flat-ink copies, then the puppet itself
  L.inked = (draw, { r = 2.4, n = 8, col = [0.12, 0.08, 0.03], dy = 0.6 } = {}) => {
    for (let i = 0; i < n; i++) { const an = i * 2 * Math.PI / n; L.sp = { dx: Math.cos(an) * r, dy: Math.sin(an) * r + dy, a: 1, lod: 0, ink: col }; draw(); }
    L.sp = null; draw(); };

  // ---------------- primitives ----------------
  L.glow = (x, y, r, col, amt, k = 3.0) => { G.blend('add'); G.draw(P.glow, { u_col: col, u_k: k, u_amt: amt }, G.xf(x - r, y - r, 2 * r, 2 * r)); G.blend(); };
  L.shadow = (x, y, rx, ry, amt = 0.5) => G.draw(P.shadow, { u_amt: amt }, G.xf(x - rx, y - ry, 2 * rx, 2 * ry));
  L.solid = (x, y, w, h, col, rot = 0, px = 0, py = 0, a = 1) => G.draw(P.solid, { u_col: col, u_a: a }, G.xf(x, y, w, h, rot, px, py));   // a: opacity (premultiplied)
  L.rrect = (x, y, w, h, r, c0, c1 = c0, a = 1) => G.draw(P.rrect, { u_sz: [w, h], u_r: r, u_a: a, u_c0: c0, u_c1: c1 }, G.xf(x, y, w, h));
  L.puff = (x, y, r, col, amt, seed) => G.draw(P.puff, { u_col: col, u_amt: amt, u_seed: seed }, G.xf(x - r, y - r, 2 * r, 2 * r));
  L.star = (x, y, r, col, amt) => { G.blend('add'); G.draw(P.star, { u_col: col, u_amt: amt }, G.xf(x - r, y - r, 2 * r, 2 * r)); G.blend(); };
  // cracks(x, y, R, age, seed, mode): ground impact fissures centred on the impact point (screen px), R = radius on the ground
  // (the quad is 2R × R in a 2:1 view). mode 0 in the ground decal pass (under everything, lit with the ground), mode 1 after
  // the light pass for the magma glow (additive; masked by T.bg = the frame before the light, whose alpha marks sprites).
  // Over its life (age s): tips race out in 0.17 s, glow cools in ~0.4 s, embers to ~2 s, the scar fades at 3–4.6 s.
  L.cracks = (x, y, R, age, seed = 0, mode = 0, amt = 1) => { if (mode) G.blend('add');
    G.draw(P.crack, { u_seed: seed, u_age: age, u_mode: mode, u_amt: amt, u_mask: T.bg }, G.xf(x - R, y - R / 2, 2 * R, R)); if (mode) G.blend(); };
  // rain(t, amt 0..1, cam, phase): 'ground' in the ground decal pass (wet ground, puddles), 'fx' after the light pass (splashes,
  // puddle sheen lit by the light map — needs the light target as T.light or o.light), 'sky' for the streaks over everything.
  // t drives the falling streaks and the splashes (uniforms are per program: a draw that omits u_t freezes them)
  L.rain = (t, amt, cam, phase, o = {}) => { if (amt <= 0.003 || L.NOFX) return;
    if (phase === 'ground') { G.draw(P.wet, { u_amt: amt, u_cam: cam }, G.xf(0, 0, W, H)); return; }
    const lt = o.light || T.light; if (!lt) return;
    if (phase === 'fx') { G.blend('add'); G.draw(P.rainfx, { u_t: t, u_amt: amt, u_mode: 0, u_wind: o.wind || 0.12, u_cam: cam, u_mask: T.bg, u_light: lt }, G.xf(0, 0, W, H)); G.blend(); return; }
    G.draw(P.rainfx, { u_t: t, u_amt: amt, u_mode: 1, u_wind: o.wind || 0.12, u_cam: cam, u_mask: T.bg, u_light: lt }, G.xf(0, 0, W, H)); };
  L.ring = (x, y, rx, ry, col, amt, w = 0.1) => G.draw(P.ring, { u_col: col, u_amt: amt, u_w: w }, G.xf(x - rx, y - ry, 2 * rx, 2 * ry));
  // fbm fog band: p = [scale, speed, threshold, density]; scatters warm light near L.SUN
  L.fog = (y, h, p, col, seed, t, scat = 0.7) => L.NOFX ? 0 :
    G.draw(P.fog, { u_p: p, u_col: col, u_seed: seed, u_sun: L.SUN, u_scat: scat, u_t: t }, G.xf(-40, y, W + 80, h));
  L.ph = (t, period, k = 0) => 2 * Math.PI * t / period + k;

  // ---------------- cut-out rig ----------------
  // Two-bone limb from ONE drawing cut at the joint (sub-rects), upper bone drawn over the lower one, plus a round joint cap.
  // o: { tex, p:[x,y] root in screen px, a1, a2 (deg, 0 = hanging down, + = clockwise when face = 1), face (±1), rot (deg, body),
  //      w, h (drawn size), split (v of the cut), root:[u,v], joint:[u,v] (in the drawing), r (cap radius), col (cap rgb), u (uniforms), capDark }
  // returns the joint position (knee/elbow) in screen px
  L.twoBone = (o) => {
    const { tex, p, a1, a2, face = 1, rot = 0, w, h, split: ys, root, joint, r = 0, col = [0.7, 0.4, 0.1], u = {}, capDark = 1 } = o, ov = 0.035;
    const Mu = M.of(M.t(p[0], p[1]), M.s(face, 1), M.r((rot + a1) * L.D2R));
    const kp = M.ap(Mu, [(joint[0] - root[0]) * w, (joint[1] - root[1]) * h]);
    const Ml = M.of(M.t(kp[0], kp[1]), M.s(face, 1), M.r((rot + a1 + a2) * L.D2R));
    L.sprite(tex, 0, 0, { m: Ml, w, h: h * (1 - ys + ov), src: [0, ys - ov, 1, 1], pivot: [joint[0] * w, (joint[1] - ys + ov) * h], u });
    L.sprite(tex, 0, 0, { m: Mu, w, h: h * (ys + ov), src: [0, 0, 1, ys + ov], pivot: [root[0] * w, root[1] * h], u });
    if (r > 0 && !L.sp) G.draw(P.joint, { u_col: col, u_dark: capDark * (u.alpha === undefined ? 1 : u.alpha) }, G.xf(kp[0] - r, kp[1] - r, 2 * r, 2 * r));
    return kp;
  };

  // ---------------- QA hooks (scripts/qa.mjs reads them after each render; reset by beginBG) ----------------
  // uiBox: a HUD container (panel, slot, backdrop) — every text must sit inside one, `pad` px from its edge.
  // uiText: a drawn text's box (L.text and L.label record themselves).
  // anchor: where the SIM emits something (anything shot, thrown or shone) vs where the scene DRAWS what emits it (the held
  //   item's tip, a hand, a barrel), in view px. qa.mjs fails when they are more than tol apart (an effect leaving from the feet).
  L.UI = []; L.ANCH = [];
  L.uiBox = (id, x, y, w, h, pad = 6) => L.UI.push({ k: 'box', id, x, y, w, h, pad });
  L.uiText = (id, s, x, y, w, h) => L.UI.push({ k: 'text', id, s, x, y, w, h });
  L.anchor = (name, sim, drawn, tol = 8) => L.ANCH.push({ name, sim, drawn, tol, d: Math.hypot(sim[0] - drawn[0], sim[1] - drawn[1]) });
  L.qaReset = () => { L.UI = window.__UI = []; L.ANCH = window.__ANCHORS = []; };

  // ---------------- smooth HUD labels: any string (Cyrillic, CJK…) in a system font, one texture per slot ----------------
  // label(slot, str, x, y, { size, col, out, al, a, font, weight }) draws at 1:1 (crisp, anti-aliased) with an ink outline
  // and a soft drop shadow; the texture is re-rendered only when the string or style changes. Returns the text width.
  // labelW(...) measures without drawing (size panels to their content — never hard-code a panel width for variable text).
  const LBL = {};
  const lblTex = (slot, str, { size = 30, col = '#f6e7c8', out = '#2d1315', font = '"Trebuchet MS", "Segoe UI", Verdana, sans-serif', weight = 'bold' } = {}) => {
    let r = LBL[slot]; const key = [str, size, col, out, font, weight].join('|'); if (r && r.key === key) return r;
    const cv = document.createElement('canvas'), g = cv.getContext('2d'), f = `${weight} ${size}px ${font}`, pad = Math.ceil(size * 0.3);
    g.font = f; const tw = g.measureText(str).width, w = Math.ceil(tw) + 2 * pad, h = Math.ceil(size * 1.3) + 2 * pad;
    cv.width = Math.max(1, w); cv.height = h; g.font = f; g.textBaseline = 'middle'; g.lineJoin = 'round';
    g.fillStyle = 'rgba(15,5,8,0.6)'; g.fillText(str, pad, h / 2 + Math.max(2, size * 0.09));
    if (out) { g.lineWidth = Math.max(3, size * 0.16); g.strokeStyle = out; g.strokeText(str, pad, h / 2); }
    g.fillStyle = col; g.fillText(str, pad, h / 2);
    if (!r) r = LBL[slot] = { rec: G.canvasTex('lbl_' + slot, cv) };
    else { const gl = G.gl; gl.bindTexture(gl.TEXTURE_2D, r.rec.t); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, cv); gl.generateMipmap(gl.TEXTURE_2D); r.rec.w = w; r.rec.h = h; }
    Object.assign(r, { key, pad, tw }); return r; };
  L.labelW = (slot, str, o = {}) => lblTex(slot, str, o).tw;
  L.label = (slot, str, x, y, o = {}) => { const r = lblTex(slot, str, o), size = o.size || 30, a = o.a === undefined ? 1 : o.a, x0 = Math.round(x - r.tw * (o.al || 0));
    L.sprite('lbl_' + slot, x0 - r.pad, Math.round(y - r.rec.h / 2), { w: r.rec.w, h: r.rec.h, u: { alpha: a } });
    if (a > 0.05) L.uiText(slot, str, x0, y - size * 0.62, r.tw, size * 1.24); return r.tw; };

  // ---------------- HUD text: canvas glyph atlas → texture ----------------
  L.glyphs = (chars = '0123456789×+/:', { size = 76, font = '"Arial Rounded MT Bold", "Arial Black", sans-serif', stroke = '#2a1606', fill = ['#fffbe2', '#ffd76a', '#e89a22'] } = {}) => {
    const cv = document.createElement('canvas'), g = cv.getContext('2d'), f = `900 ${size}px ${font}`; g.font = f;
    const ws = [...chars].map((c) => Math.ceil(g.measureText(c).width) + 22); cv.width = ws.reduce((a, b) => a + b, 0); cv.height = size + 34;
    g.font = f; g.textBaseline = 'middle'; g.lineJoin = 'round'; let x = 0; L.GLYPH = {};
    const grd = g.createLinearGradient(0, 10, 0, size + 20); fill.forEach((c, i) => grd.addColorStop(i / (fill.length - 1), c));
    [...chars].forEach((c, i) => { const cx = x + 11; g.lineWidth = 13; g.strokeStyle = stroke; g.strokeText(c, cx, cv.height / 2 + 2);
      g.fillStyle = grd; g.fillText(c, cx, cv.height / 2 + 2); L.GLYPH[c] = [x / cv.width, ws[i]]; x += ws[i]; });
    G.canvasTex('glyphs', cv); L.GLYPH_H = cv.height;
  };
  L.text = (str, x, y, h, al = 0, alpha = 1) => {        // al: 0 left, 0.5 centre, 1 right
    const k = h / L.GLYPH_H, gw = G.tex('glyphs').w; let w = 0; for (const c of str) w += (L.GLYPH[c] || [0, 0])[1] * k * 0.86;
    let cx = x - w * al; if (alpha > 0.05) L.uiText(str, str, cx, y - h / 2, w, h);
    for (const c of str) { const g = L.GLYPH[c]; if (!g) { cx += h * 0.3; continue; }
      L.sprite('glyphs', cx, y - h / 2, { w: g[1] * k, h, src: [g[0], 0, g[0] + g[1] / gw, 1], u: { alpha } }); cx += g[1] * k * 0.86; }
  };

  // ---------------- frame pipeline ----------------
  L.beginBG = (clear = [0.08, 0.1, 0.06, 1]) => { L.qaReset(); G.bind(T.bg, clear); G.blend(); };     // first call of every frame
  // god rays: bright, warm, sky-ish pixels of the background near the sun, radially blurred, screened back onto it
  L.godRays = (t, { sun = L.SUN, amt = 0.42, col = [1.0, 0.80, 0.55] } = {}) => {
    G.blend('none'); G.bind(T.mask); G.full(P.rmask, { u_t: t, u_src: T.bg, u_sun: [sun[0] / 2, sun[1] / 2] });
    G.bind(T.rays); G.full(P.rays, { u_src: T.mask, u_sun: [sun[0] / 2, sun[1] / 2] });
    G.bind(T.bg); G.blend('screen'); if (!L.NOFX) G.full(P.rayadd, { u_src: T.rays, u_amt: amt, u_col: col }); G.blend(); };
  L.beginComp = () => { G.bind(T.comp); G.blend('none'); G.full(P.copy, { u_src: T.bg }); G.blend(); };
  // cartoon water from y to the bottom, reflecting the background; fall = [x, width] churn, gust = [x0, amp0, x1, amp1]
  L.water = (t, { y, sun = L.SUN, fall = [-9999, 1], gust = [-9999, 0, -9999, 0] }) =>
    G.draw(P.water, { u_scene: T.bg, u_wy: y, u_sun: sun, u_t: t, u_fall: fall, u_gust: gust }, G.xf(0, y, W, H - y));
  L.waterfall = (t, x, y, w, h) => G.draw(P.fall, { u_t: t, u_aspect: h / w }, G.xf(x - w * 0.15, y, w * 1.3, h));
  L.foam = (t, x, y, w, h, amt = 1) => G.draw(P.foam, { u_t: t, u_amt: amt }, G.xf(x, y, w, h));
  // a thin veil of the shafts over the play plane, then dust motes that light up inside the shafts
  L.veil = (amt = 0.14, col = [1.0, 0.86, 0.6]) => { G.blend('screen'); if (!L.NOFX) G.full(P.rayadd, { u_src: T.rays, u_amt: amt, u_col: col }); G.blend(); };
  L.motes = (t, { n = 140, amt = 0.35, col = [1.0, 0.92, 0.7], h = 900 } = {}) => { G.blend('add');
    for (let i = 0; i < n; i++) { const h1 = L.rnd(i, 1), h2 = L.rnd(i, 2), h3 = L.rnd(i, 3);
      const mx = ((h1 * W + t * (8 + 10 * h3) + 30 * Math.sin(t * 0.5 + i)) % W + W) % W, my = ((h2 * (h - 100) + 40 + 20 * Math.sin(t * 0.7 + i * 1.3)) % h + h) % h, r = 3 + 4 * h3;
      G.draw(P.mote, { u_rays: T.rays, u_amt: amt, u_col: col }, G.xf(mx - r, my - r, 2 * r, 2 * r)); }
    G.blend(); };
  // bloom (two radii) + final grade (warm highs, cool lows, hue-keeping roll-off, vignette, dither) → screen, then HUD-ready.
  // warm scales the warm-high/cool-low tint, roll the highlight roll-off (0 = none), dither 0/1. Pixel/flat/neon styles that
  // need exact palette colours: { bloom: [0, 0], warm: 0, roll: 0, dither: 0 }
  L.finish = (t, { bloom = [0.22, 0.20], vignette = 0.92, warm = 1, roll = 1, dither = 1 } = {}) => {
    G.blend('none');
    G.bind(T.b1); G.full(P.bright, { u_src: T.comp });
    G.bind(T.b2); G.full(P.blur, { u_src: T.b1, u_dir: [1.5, 0] }); G.bind(T.b1); G.full(P.blur, { u_src: T.b2, u_dir: [0, 1.5] });
    G.bind(T.c1); G.full(P.copy, { u_src: T.b1 });
    G.bind(T.c2); G.full(P.blur, { u_src: T.c1, u_dir: [2, 0] }); G.bind(T.c1); G.full(P.blur, { u_src: T.c2, u_dir: [0, 2] });
    G.bind(null); G.full(P.final, { u_src: T.comp, u_bloom: T.b1, u_bloom2: T.c1, u_t: t, u_bloomA: bloom, u_vig: vignette, u_warm: warm, u_roll: roll, u_dither: dither });
    G.blend(); };
})();
