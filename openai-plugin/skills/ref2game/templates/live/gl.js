// live/gl.js — a tiny deterministic WebGL2 layer renderer: textures (premultiplied, mipmapped or nearest), programs, render
// targets, pixel-space quads (y down) with an affine transform. Everything the scene draws is a quad with a shader.
(function () {
  const G = (window.G = {});
  let gl, quadBuf, cur = null;
  const progs = {}, texs = {};

  G.init = (canvas, W, H) => {
    canvas.width = W; canvas.height = H;
    gl = G.gl = canvas.getContext('webgl2', { premultipliedAlpha: true, alpha: false, antialias: false, preserveDrawingBuffer: true });
    if (!gl) throw new Error('WebGL2 not available');
    gl.getExtension('EXT_color_buffer_float'); gl.getExtension('EXT_color_buffer_half_float'); gl.getExtension('OES_texture_float_linear');
    quadBuf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, quadBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    G.W = W; G.H = H;
  };

  // nearest: NEAREST min/mag, no mipmaps (pixel art: crisp texels; lod bias has no effect)
  G.load = (name, url, { repeat = false, nearest = false } = {}) => new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => {
      const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, im);
      if (!nearest) gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, nearest ? gl.NEAREST : gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, nearest ? gl.NEAREST : gl.LINEAR);
      const wr = repeat ? gl.REPEAT : gl.CLAMP_TO_EDGE;
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wr); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wr);
      texs[name] = { t, w: im.width, h: im.height }; res(texs[name]);
    };
    im.onerror = () => rej(new Error('failed to load ' + url)); im.src = url;
  });
  G.canvasTex = (name, cv) => {
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, cv); gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return (texs[name] = { t, w: cv.width, h: cv.height });
  };
  G.tex = (n) => { const t = texs[n]; if (!t) throw new Error('no texture ' + n); return t; };

  const VS = `#version 300 es
in vec2 a_pos; uniform vec2 u_res; uniform mat3 u_xf; uniform vec2 u_flip;
out vec2 v_uv; out vec2 v_px;
void main(){ vec3 p = u_xf * vec3(a_pos, 1.0); v_px = p.xy; v_uv = mix(a_pos, 1.0 - a_pos, u_flip);
  gl_Position = vec4(p.x / u_res.x * 2.0 - 1.0, 1.0 - p.y / u_res.y * 2.0, 0.0, 1.0); }`;
  const COMMON = `#version 300 es
precision highp float;
in vec2 v_uv; in vec2 v_px; out vec4 o;
uniform vec2 u_res; uniform float u_t;
float hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1,0)), u.x), mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x), u.y); }
float fbm(vec2 p){ float a = 0.5, s = 0.0; for (int i = 0; i < 5; i++){ s += a * vnoise(p); p = p * 2.03 + vec2(17.1, 9.7); a *= 0.5; } return s; }
vec2 scr(vec2 px){ return vec2(px.x / u_res.x, 1.0 - px.y / u_res.y); }   // screen px -> render-target uv
`;
  G.COMMON = COMMON;

  G.program = (name, fs) => {
    if (progs[name]) return progs[name];
    const mk = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(name + ': ' + gl.getShaderInfoLog(s)); return s; };
    const p = gl.createProgram(); gl.attachShader(p, mk(gl.VERTEX_SHADER, VS)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, COMMON + fs));
    gl.bindAttribLocation(p, 0, 'a_pos'); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(name + ': ' + gl.getProgramInfoLog(p));
    const loc = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const u = gl.getActiveUniform(p, i); loc[u.name.replace('[0]', '')] = { l: gl.getUniformLocation(p, u.name), type: u.type }; }
    return (progs[name] = { p, loc, name });
  };

  // view: the coordinate space draws use (default w×h), e.g. a W/k × H/k target drawn in W×H view px; nearest: sample it crisp
  G.target = (w, h, float = false, { view = [w, h], nearest = false } = {}) => {
    const t = gl.createTexture(), f = nearest ? gl.NEAREST : gl.LINEAR; gl.bindTexture(gl.TEXTURE_2D, t);
    if (float) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, w, h, 0, gl.RGBA, gl.HALF_FLOAT, null);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, f); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, f);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const fb = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0);
    return { fb, t, w, h, vw: view[0], vh: view[1] };
  };
  G.bind = (tg, clear) => {
    cur = tg; gl.bindFramebuffer(gl.FRAMEBUFFER, tg ? tg.fb : null);
    gl.viewport(0, 0, tg ? tg.w : G.W, tg ? tg.h : G.H);
    if (clear) { gl.clearColor(clear[0], clear[1], clear[2], clear[3]); gl.clear(gl.COLOR_BUFFER_BIT); }
  };
  G.blend = (mode) => {
    gl.enable(gl.BLEND);
    if (mode === 'add') gl.blendFunc(gl.ONE, gl.ONE);
    else if (mode === 'screen') gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_COLOR);
    else if (mode === 'none') gl.disable(gl.BLEND);
    else gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  };

  // affine: place the unit quad at x,y (top-left) with size w,h, rotated by rot (rad) about pivot (px,py) in local px
  G.xf = (x, y, w, h, rot = 0, px = 0, py = 0) => {
    const c = Math.cos(rot), s = Math.sin(rot);
    // local (u*w - px, v*h - py) rotated, then + (x + px, y + py)
    return [w * c, w * s, 0, -h * s, h * c, 0, x + px - (px * c - py * s), y + py - (px * s + py * c), 1];
  };

  let unit = 0;
  const setU = (P, k, v) => {
    const u = P.loc[k]; if (!u) return;
    const T = gl;
    if (u.type === T.SAMPLER_2D) { const tx = v.t || v; gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, tx); gl.uniform1i(u.l, unit++); }
    else if (u.type === T.FLOAT) gl.uniform1f(u.l, v);
    else if (u.type === T.FLOAT_VEC2) gl.uniform2fv(u.l, v);
    else if (u.type === T.FLOAT_VEC3) gl.uniform3fv(u.l, v);
    else if (u.type === T.FLOAT_VEC4) gl.uniform4fv(u.l, v);
    else if (u.type === T.FLOAT_MAT3) gl.uniformMatrix3fv(u.l, false, v);
    else if (u.type === T.INT) gl.uniform1i(u.l, v);
  };
  G.draw = (P, U, xf, flip = [0, 0]) => {
    gl.useProgram(P.p); unit = 0;
    const res = cur ? [cur.vw, cur.vh] : [G.W, G.H];
    setU(P, 'u_res', res); setU(P, 'u_xf', xf); setU(P, 'u_flip', flip);
    for (const k in U) setU(P, k, U[k]);
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuf); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };
  G.full = (P, U) => { const res = cur ? [cur.vw, cur.vh] : [G.W, G.H]; G.draw(P, U, G.xf(0, 0, res[0], res[1])); };
})();
