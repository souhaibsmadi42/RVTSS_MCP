// Frame engine for a 9:16 motion reel. Every pixel is a pure function of t (seconds): no timers, no Math.random.
// The page draws the clean frame into FR, then post() applies camera, lens and film effects into the visible canvas.
export const W = 1080, H = 1920, FPS = 60, DURATION = 40, BPM = 120;
export const BEAT = 60 / BPM;
export const B = k => k * BEAT;

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, t) => a + (b - a) * t;
export const inv = (t, a, b) => clamp((t - a) / (b - a));
export const Ease = {
  lin: t => t,
  out: t => 1 - Math.pow(1 - t, 3),
  in: t => t * t * t,
  inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  outQ: t => 1 - Math.pow(1 - t, 4),
  outExpo: t => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  inExpo: t => (t <= 0 ? 0 : Math.pow(2, 10 * t - 10)),
  sine: t => -(Math.cos(Math.PI * t) - 1) / 2,
};
export function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
export const fmtN = n => Math.round(n).toLocaleString('en-US');

export const COL = { bg: '#04060D', ink: '#EEF3FF', dim: '#8C96B8', cyan: '#29E0FF', blue: '#3D7BFF', violet: '#8B5CFF', red: '#FF3D71', amber: '#FFB020', green: '#3DFFB0' };
export const DISPLAY = '"Inter Display", "Inter", sans-serif';
export const MONO = '"JetBrains Mono", monospace';
export const SANS = '"Inter", sans-serif';

function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }

// ------------------------------------------------------------------ plates (GPT Image 2.5 key art)
export const P = {};
export async function loadPlates(names) {
  await Promise.all(names.map(n => new Promise((res, rej) => {
    const i = new Image(); i.onload = () => { P[n] = i; res(); }; i.onerror = () => rej(new Error('plate ' + n)); i.src = `../plates/${n}.jpg`;
  })));
}
// cover-fit the plate, zoom z around image focus (fx, fy), keep the frame covered
export function plate(ctx, name, o = {}) {
  const img = P[name]; if (!img) return;
  const z = o.z ?? 1, s = Math.max(W / img.width, H / img.height) * z;
  const dw = img.width * s, dh = img.height * s;
  let x = W / 2 - (o.fx ?? 0.5) * dw + (o.dx || 0), y = H / 2 - (o.fy ?? 0.5) * dh + (o.dy || 0);
  x = clamp(x, W - dw, 0); y = clamp(y, H - dh, 0);
  ctx.save();
  ctx.globalAlpha = o.a ?? 1;
  const f = [];
  if ((o.br ?? 1) !== 1) f.push(`brightness(${o.br.toFixed(3)})`);
  if ((o.sat ?? 1) !== 1) f.push(`saturate(${o.sat.toFixed(3)})`);
  if (o.hue) f.push(`hue-rotate(${o.hue}deg)`);
  if (f.length) ctx.filter = f.join(' ');
  if (o.rot) { ctx.translate(W / 2, H / 2); ctx.rotate(o.rot); ctx.translate(-W / 2, -H / 2); }
  ctx.drawImage(img, x, y, dw, dh);
  ctx.restore();
  return { x, y, s };   // screen = x + px * s
}
// darken top / bottom bands so type stays readable over a plate
export function shade(ctx, top = 0.75, bottom = 0.7, mid = 0.0) {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, `rgba(4,6,13,${top})`); g.addColorStop(0.36, `rgba(4,6,13,${mid})`);
  g.addColorStop(0.62, `rgba(4,6,13,${mid})`); g.addColorStop(1, `rgba(4,6,13,${bottom})`);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
}

// ------------------------------------------------------------------ type
// text(ctx, str, x, y, {size, weight, family, color, grad, align, ls, alpha, glow, glowColor, sc, rot, maxW, stroke})
export function text(ctx, str, x, y, o = {}) {
  if ((o.alpha ?? 1) <= 0.002 || !str) return 0;
  let size = o.size || 100;
  const fam = o.family || DISPLAY, wt = o.weight || 900;
  ctx.save();
  ctx.font = `${wt} ${size}px ${fam}`;
  ctx.letterSpacing = (o.ls || 0) + 'px';
  let w = ctx.measureText(str).width;
  if (o.maxW && w > o.maxW) { size *= o.maxW / w; ctx.font = `${wt} ${size}px ${fam}`; ctx.letterSpacing = ((o.ls || 0) * o.maxW / w) + 'px'; w = o.maxW; }
  const align = o.align || 'center';
  ctx.textAlign = 'left'; ctx.textBaseline = o.base || 'alphabetic';
  const x0 = align === 'center' ? -w / 2 + (o.ls || 0) / 2 : align === 'right' ? -w : 0;
  ctx.translate(x, y);
  if (o.rot) ctx.rotate(o.rot);
  if (o.sc && o.sc !== 1) ctx.scale(o.sc, o.sc);
  ctx.globalAlpha = o.alpha ?? 1;
  let fill = o.color || COL.ink;
  if (o.grad) { const g = ctx.createLinearGradient(x0, 0, x0 + w, 0); o.grad.forEach((c, i) => g.addColorStop(i / (o.grad.length - 1), c)); fill = g; }
  if (o.stroke) { ctx.lineWidth = o.stroke; ctx.strokeStyle = fill; }
  ctx.fillStyle = fill;
  const paint = () => (o.stroke ? ctx.strokeText(str, x0, 0) : ctx.fillText(str, x0, 0));
  if (o.glow) { ctx.shadowColor = o.glowColor || COL.cyan; ctx.shadowBlur = o.glow; paint(); ctx.shadowBlur = o.glow * 0.35; paint(); ctx.shadowBlur = 0; }
  paint();
  ctx.restore();
  return w;
}
// slam-in envelope: hard cut in at a with scale s0 -> 1 (outExpo over d), hold, hard cut out at b
export function slam(t, a, b, o = {}) {
  if (t < a || t >= b) return null;
  const d = o.d ?? 0.22, p = Ease.outExpo(clamp((t - a) / d));
  return { p, sc: lerp(o.s0 ?? 1.18, 1, p), dy: (o.dy || 0) * (1 - p), dx: (o.dx || 0) * (1 - p), a: o.fade ? Ease.out(clamp((t - a) / o.fade)) : 1 };
}
// line rising out of a mask (clip at baseline)
export function rise(ctx, t, a, str, x, y, o = {}) {
  if (t < a) return;
  const p = Ease.outExpo(clamp((t - a) / (o.d || 0.3)));
  const size = o.size || 100;
  ctx.save();
  ctx.beginPath(); ctx.rect(0, y - size * 1.0, W, size * 1.22); ctx.clip();
  text(ctx, str, x, y + (1 - p) * size * 1.15, o);
  ctx.restore();
}
export function typed(str, t, a, step) { const n = clamp(Math.floor((t - a) / step), 0, str.length); return t < a ? '' : str.slice(0, n) + (n < str.length && Math.floor(t * 8) % 2 ? '▍' : ''); }

// ------------------------------------------------------------------ vector bits
export function rrect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
export function glowLine(ctx, x1, y1, x2, y2, col, w = 2, glow = 18, a = 1) {
  ctx.save(); ctx.globalAlpha = a; ctx.strokeStyle = col; ctx.lineCap = 'round';
  ctx.shadowColor = col; ctx.shadowBlur = glow; ctx.lineWidth = w;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  ctx.shadowBlur = 0; ctx.strokeStyle = '#FFFFFF'; ctx.globalAlpha = a * 0.8; ctx.lineWidth = Math.max(1, w * 0.4); ctx.stroke();
  ctx.restore();
}
export function ring(ctx, x, y, r, col, w = 3, a = 1, glow = 20) {
  ctx.save(); ctx.globalAlpha = a; ctx.strokeStyle = col; ctx.lineWidth = w; ctx.shadowColor = col; ctx.shadowBlur = glow;
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
}
// glass card with gradient hairline border and a soft cyan glow
export function glass(ctx, x, y, w, h, o = {}) {
  ctx.save();
  ctx.globalAlpha = o.a ?? 1;
  ctx.shadowColor = 'rgba(41,224,255,.28)'; ctx.shadowBlur = 50;
  rrect(ctx, x, y, w, h, o.r ?? 26); ctx.fillStyle = o.fill || 'rgba(8,12,26,.78)'; ctx.fill();
  ctx.shadowBlur = 0;
  const g = ctx.createLinearGradient(x, y, x + w, y + h);
  g.addColorStop(0, 'rgba(41,224,255,.85)'); g.addColorStop(0.5, 'rgba(61,123,255,.25)'); g.addColorStop(1, 'rgba(139,92,255,.8)');
  ctx.strokeStyle = g; ctx.lineWidth = 2; ctx.stroke();
  const hl = ctx.createLinearGradient(0, y, 0, y + h * 0.5);
  hl.addColorStop(0, 'rgba(255,255,255,.07)'); hl.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = hl; ctx.fill();
  ctx.restore();
}

// ------------------------------------------------------------------ FX events (registered once at init)
export const FX = [];
export const hit = (t, k = 1) => FX.push({ type: 'hit', t, k });
export const punch = (t, k = 0.03, d = 0.4) => FX.push({ type: 'punch', t, k, d });
export const flash = (t, frames = 2, k = 1, col = '255,255,255') => FX.push({ type: 'flash', t, d: frames / FPS, k, col });
export const invert = (t, d) => FX.push({ type: 'inv', t, d });
export const glitch = (t, d, k = 1) => FX.push({ type: 'glitch', t, d, k });
export const rumble = (t, d, k = 1) => FX.push({ type: 'rumble', t, d, k });
export const caRamp = (t, d, k = 1) => FX.push({ type: 'ca', t, d, k });
export const scan = (t, d = 0.32, dir = 1, col = COL.cyan) => FX.push({ type: 'scan', t, d, dir, col });   // the motif: a section plane sweeps the frame
export const tilt = (t, d, ang) => FX.push({ type: 'tilt', t, d, ang });

const NZ = (() => { const r = rng(77); const a = new Float32Array(4096); for (let i = 0; i < a.length; i++) a[i] = r() * 2 - 1; return a; })();
const noise = x => { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return lerp(NZ[i & 4095], NZ[(i + 1) & 4095], u); };

export function fxAt(t, base = {}) {
  const o = { zoom: 1, rot: 0, sx: 0, sy: 0, ca: 0.6, flash: 0, fc: '255,255,255', inv: 0, glitch: 0, scans: [], grain: 0.075, vig: 0.42, bloom: 0.55, ...base };
  let shake = 0;
  for (const e of FX) {
    const dt = t - e.t;
    if (dt < -0.05 || dt > 2.5) continue;
    switch (e.type) {
      case 'hit': if (dt >= 0) { shake += 22 * e.k * Math.exp(-dt * 9); o.ca += 9 * e.k * Math.exp(-dt * 11); o.zoom += 0.04 * e.k * Ease.outExpo(clamp(1 - dt / 0.45)); } break;
      case 'punch': if (dt >= 0 && dt < e.d) o.zoom += e.k * (1 - Ease.outQ(dt / e.d)); break;
      case 'flash': if (dt >= 0 && dt < e.d + 0.14) { const a = dt < e.d ? e.k : e.k * (1 - (dt - e.d) / 0.14) * 0.55; if (a > o.flash) { o.flash = a; o.fc = e.col; } } break;
      case 'inv': if (dt >= 0 && dt < e.d) o.inv = 1; break;
      case 'glitch': if (dt >= 0 && dt < e.d) { const k = e.k * (0.55 + 0.45 * Math.sin(dt * 47)); o.glitch = Math.max(o.glitch, k); o.ca += 6 * k; } break;
      case 'rumble': if (dt >= 0 && dt < e.d) { const p = dt / e.d; shake += 10 * e.k * p * p; o.ca += 4 * e.k * p * p; o.zoom += 0.06 * e.k * Ease.in(p); } break;
      case 'ca': if (dt >= 0 && dt < e.d) o.ca += 8 * e.k * Ease.in(dt / e.d); break;
      case 'tilt': if (dt >= 0 && dt < e.d) o.rot += e.ang * (1 - Ease.outQ(dt / e.d)); break;
      case 'scan': if (dt >= 0 && dt < e.d + 0.25) o.scans.push({ p: dt / e.d, dir: e.dir, col: e.col, fade: clamp(1 - (dt - e.d) / 0.25) }); break;
    }
  }
  if (shake > 0.05) { const f = t * 32; o.sx += noise(f) * shake; o.sy += noise(f + 911) * shake * 0.8; o.rot += noise(f + 377) * shake * 0.0008; }
  return o;
}

// ------------------------------------------------------------------ finishing pass
export const OUT = document.getElementById('out');
const octx = OUT.getContext('2d');
export const FR = canvas(W, H);                       // clean frame
export const fctx = FR.getContext('2d');
const TMP = canvas(W, H), tctx = TMP.getContext('2d');
const CH = canvas(W, H), cctx = CH.getContext('2d');
const SM = canvas(270, 480), sctx = SM.getContext('2d');
const GR = [0, 1, 2, 3].map(i => {                    // grain tiles
  const c = canvas(540, 960), x = c.getContext('2d'), d = x.createImageData(540, 960), r = rng(101 + i);
  for (let j = 0; j < d.data.length; j += 4) { const v = 128 + (r() - 0.5) * 255; d.data[j] = d.data[j + 1] = d.data[j + 2] = v; d.data[j + 3] = 255; }
  x.putImageData(d, 0, 0); return c;
});
const VIG = (() => {
  const c = canvas(W, H), x = c.getContext('2d');
  const g = x.createRadialGradient(W / 2, H * 0.46, H * 0.18, W / 2, H * 0.5, H * 0.72);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,1)');
  x.fillStyle = g; x.fillRect(0, 0, W, H); return c;
})();

export function post(o, frameNo) {
  const ctx = octx;
  ctx.save();
  ctx.fillStyle = COL.bg; ctx.fillRect(0, 0, W, H);
  // camera: shake / punch / roll
  ctx.translate(W / 2 + o.sx, H / 2 + o.sy); ctx.rotate(o.rot); ctx.scale(o.zoom, o.zoom); ctx.translate(-W / 2, -H / 2);
  ctx.drawImage(FR, 0, 0);
  ctx.restore();
  // section-plane scan line (the motif) — drawn on the camera image so the bloom catches it
  for (const s of o.scans) {
    const y = s.dir > 0 ? lerp(-40, H + 40, Ease.inOut(clamp(s.p))) : lerp(H + 40, -40, Ease.inOut(clamp(s.p)));
    ctx.save(); ctx.globalAlpha = s.fade; ctx.globalCompositeOperation = 'lighter';
    const band = ctx.createLinearGradient(0, y - 260 * s.dir, 0, y);
    band.addColorStop(0, 'rgba(41,224,255,0)'); band.addColorStop(1, 'rgba(41,224,255,.22)');
    ctx.fillStyle = band; ctx.fillRect(0, Math.min(y, y - 260 * s.dir), W, 260);
    ctx.shadowColor = s.col; ctx.shadowBlur = 40; ctx.fillStyle = '#E8FCFF'; ctx.fillRect(0, y - 2, W, 4);
    ctx.restore();
  }
  // glitch slices
  if (o.glitch > 0.01) {
    tctx.drawImage(OUT, 0, 0);
    const r = rng(frameNo * 31 + 7);
    for (let y = 0; y < H;) {
      const bh = 8 + Math.floor(r() * 90);
      if (r() < o.glitch * 0.5) ctx.drawImage(TMP, 0, y, W, bh, (r() - 0.5) * 300 * o.glitch, y, W, bh);
      y += bh;
    }
  }
  // radial chromatic aberration: red channel scaled out, blue scaled in
  if (o.ca > 1.2) {
    tctx.drawImage(OUT, 0, 0);
    const k = o.ca * 0.0016;
    ctx.save(); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H); ctx.globalCompositeOperation = 'lighter';
    [[1 + k, '#FF0000'], [1, '#00FF00'], [1 - k, '#0000FF']].forEach(([s, c]) => {
      cctx.save(); cctx.globalCompositeOperation = 'source-over'; cctx.fillStyle = '#000'; cctx.fillRect(0, 0, W, H);
      cctx.translate(W / 2, H / 2); cctx.scale(s, s); cctx.translate(-W / 2, -H / 2); cctx.drawImage(TMP, 0, 0); cctx.restore();
      cctx.save(); cctx.globalCompositeOperation = 'multiply'; cctx.fillStyle = c; cctx.fillRect(0, 0, W, H); cctx.restore();
      ctx.drawImage(CH, 0, 0);
    });
    ctx.restore();
  }
  // bloom: quarter-res bright pass, blurred, screened back
  if (o.bloom > 0) {
    sctx.save(); sctx.filter = 'brightness(0.75) contrast(1.9) blur(5px)'; sctx.drawImage(OUT, 0, 0, 270, 480); sctx.restore();
    ctx.save(); ctx.globalCompositeOperation = 'screen'; ctx.globalAlpha = o.bloom; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(SM, 0, 0, W, H); ctx.restore();
  }
  if (o.inv) { ctx.save(); ctx.globalCompositeOperation = 'difference'; ctx.fillStyle = '#FFF'; ctx.fillRect(0, 0, W, H); ctx.restore(); }
  if (o.flash > 0) { ctx.save(); ctx.fillStyle = `rgba(${o.fc},${o.flash.toFixed(3)})`; ctx.fillRect(0, 0, W, H); ctx.restore(); }
  ctx.save(); ctx.globalAlpha = o.vig; ctx.drawImage(VIG, 0, 0); ctx.restore();
  ctx.save(); ctx.globalCompositeOperation = 'overlay'; ctx.globalAlpha = o.grain * 2.2;
  const g = GR[frameNo % 4], r = rng(frameNo + 3);
  ctx.drawImage(g, -Math.floor(r() * 40), -Math.floor(r() * 40), W + 40, H + 40); ctx.restore();
  if (o.black > 0) { ctx.save(); ctx.fillStyle = `rgba(0,0,0,${o.black.toFixed(3)})`; ctx.fillRect(0, 0, W, H); ctx.restore(); }
}
