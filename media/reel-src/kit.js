// Helpers shared with the tutorial film (copied from ../tutorial-src/scenes.js).
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, p) => a + (b - a) * p;
const E = {
  out: p => 1 - Math.pow(1 - p, 3),
  inOut: p => (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  back: p => { const c1 = 1.5, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); },
};
const prog = (t, a, d) => clamp((t - a) / d);

// ---------- DOM helpers ----------
function el(tag, cls, parent, css, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (css) Object.assign(e.style, css);
  if (html != null) e.innerHTML = html;
  if (parent) parent.appendChild(e);
  return e;
}
const div = (cls, parent, css, html) => el('div', cls, parent, css, html);
const px = v => (typeof v === 'number' ? v + 'px' : v);
function at(e, x, y) { e.style.left = px(x); e.style.top = px(y); return e; }

// enter animation: fade + rise (+ optional scale); returns progress
function enter(e, t, a, o = {}) {
  const { d = .6, dy = 28, dx = 0, s0 = 1, ease = E.out, out = null, outD = .4 } = o;
  let p = ease(prog(t, a, d));
  let op = clamp((t - a) / (d * .7));
  if (out != null) { const q = prog(t, out, outD); op *= 1 - q; }
  e.style.opacity = op;
  e.style.transform = `translate(${(1 - p) * dx}px, ${(1 - p) * dy}px) scale(${lerp(s0, 1, p)})`;
  e.style.visibility = op <= 0.001 ? 'hidden' : 'visible';
  return p;
}
function typed(e, t, a, text, cps = 38, caret = true) {
  const n = Math.max(0, Math.min(text.length, Math.floor((t - a) * cps)));
  const done = n >= text.length;
  const blink = caret && (t >= a) && (!done || Math.floor(t * 2) % 2 === 0);
  e.innerHTML = esc(text.slice(0, n)) + (blink && t >= a - 0.3 ? '<span class="cursor"></span>' : '');
  return done;
}
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// ---------- icons (24-unit stroke icons) ----------
const ICONS = {
  building: '<path d="M4 21V7l8-4 8 4v14"/><path d="M9 21v-5h6v5"/><path d="M8 9h2M14 9h2M8 13h2M14 13h2"/>',
  plug: '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>',
  check: '<path d="M5 12l5 5 9-10"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  flask: '<path d="M9 3h6M10 3v6L4 19a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-10V3"/><path d="M7 15h10"/>',
  hand: '<path d="M8 13V5a1.5 1.5 0 0 1 3 0v6M11 11V4a1.5 1.5 0 0 1 3 0v7M14 11V5.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-1a6 6 0 0 1-5-3l-2.5-4a1.5 1.5 0 0 1 2.5-1.6L8 15"/>',
  ruler: '<path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M15 8l2 2"/>',
  cube: '<path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M12 22V12M3 7l9 5 9-5"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  sheet: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  clash: '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  warn: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.01"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  book: '<path d="M4 4h6a3 3 0 0 1 3 3v14a2 2 0 0 0-2-2H4z"/><path d="M20 4h-6a3 3 0 0 0-3 3v14a2 2 0 0 1 2-2h7z"/>',
  chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};
const icon = (name, size = 28, color = 'currentColor') =>
  `<svg class="ic" width="${size}" height="${size}" viewBox="0 0 24 24" style="color:${color}">${ICONS[name]}</svg>`;

function logoMark(size, parent, css) {
  const wrap = div('abs', parent, Object.assign({ width: px(size), height: px(size) }, css));
  wrap.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 220 220">
    <defs><linearGradient id="lg${size}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#00c6ff"/><stop offset=".55" stop-color="#e8f4ff"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient></defs>
    <rect class="lm-box" x="14" y="14" width="192" height="192" rx="40" fill="none" stroke="url(#lg${size})" stroke-width="16" pathLength="1" stroke-dasharray="1 1"/>
    <path class="lm-cut" d="M58 162 L162 58" fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" pathLength="1" stroke-dasharray="1 1"/></svg>`;
  wrap.draw = (p1, p2) => {
    wrap.querySelector('.lm-box').style.strokeDashoffset = 1 - p1;
    wrap.querySelector('.lm-cut').style.strokeDashoffset = 1 - p2;
  };
  return wrap;
}

// ---------- cue mapping: phrase -> time, snapped to detected voiceover pauses ----------
function makeCue(sc) {
  const text = sc.vo, wpos = [];
  let acc = 0;
  for (let i = 0; i < text.length; i++) {
    wpos[i] = acc;
    const c = text[i];
    acc += c === ' ' ? 0.9 : ',;:'.includes(c) ? 7 : '.?!'.includes(c) ? 10 : c === '—' ? 8 : c === '…' ? 14 : 1;
  }
  wpos[text.length] = acc;
  const dur = sc.dur;
  const est = w => (w / acc) * dur;
  // candidate boundaries: just after punctuation (start of the next word)
  const bounds = [];
  for (let i = 0; i < text.length; i++) {
    if (',;:.?!—…'.includes(text[i])) {
      let j = i + 1; while (j < text.length && text[j] === ' ') j++;
      if (j < text.length) bounds.push({ w: wpos[j], t: est(wpos[j]) });
    }
  }
  const anchors = [{ w: 0, t: 0 }];
  for (const [a, b] of sc.pauses) {
    if (a < 0.2 || b > dur - 0.15) continue;
    const mid = (a + b) / 2;
    let best = null, bd = 1.3;
    for (const bo of bounds) { const dd = Math.abs(bo.t - mid); if (dd < bd) { bd = dd; best = bo; } }
    if (best) anchors.push({ w: best.w, t: b });
  }
  anchors.push({ w: acc, t: dur });
  anchors.sort((x, y) => x.w - y.w);
  const mono = [anchors[0]];
  for (const a of anchors.slice(1)) if (a.w > mono[mono.length - 1].w && a.t > mono[mono.length - 1].t) mono.push(a);
  const map = w => {
    for (let k = 1; k < mono.length; k++) {
      if (w <= mono[k].w) {
        const A = mono[k - 1], B = mono[k];
        return A.t + (B.t - A.t) * ((w - A.w) / (B.w - A.w));
      }
    }
    return dur;
  };
  const C = (phrase, off = 0) => {
    const i = text.indexOf(phrase);
    if (i < 0) throw new Error(`cue not found in ${sc.id}: ${phrase}`);
    return sc.start + map(wpos[i]) + off;
  };
  C.map = map; C.wpos = wpos; C.end = sc.start + dur;
  return C;
}


export { clamp, lerp, E, prog, el, div, px, enter, typed, esc, ICONS, icon, logoMark, makeCue };
