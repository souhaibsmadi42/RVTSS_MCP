// RVTSS install & use tutorial: deterministic motion graphics.
// window.renderAt(t) draws the frame at time t (seconds); render.mjs captures frames headlessly.
// Scene timing comes from timeline.json (voiceover start/duration + detected pauses per scene),
// so every on-screen cue lands on the word that the narrator is saying.

const W = 1920, H = 1080;
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

// ---------- shared components ----------
function stepColumn(root, k, title, sub) {
  const col = div('abs stepcol', root);
  const kk = div('k grad', col, null, k);
  const h = el('h2', null, col, null, title);
  const p = sub ? el('p', null, col, null, sub) : null;
  const crumbs = div('crumbs', col);
  col.update = (t, t0) => {
    enter(kk, t, t0, { dy: 18 });
    enter(h, t, t0 + .12, { dy: 30 });
    if (p) enter(p, t, t0 + .3, { dy: 20 });
  };
  col.crumbs = crumbs;
  return col;
}
function crumbRow(parent, items) {
  const out = [];
  items.forEach((s, i) => {
    if (i) out.push({ e: div('crumb sep', parent, null, '›'), sep: true });
    out.push({ e: div('crumb', parent, null, s) });
  });
  return out;
}
function windowBox(root, x, y, w, h, title) {
  const win = div('win', root, { left: px(x), top: px(y), width: px(w), height: px(h) });
  const bar = div('bar', win);
  bar.innerHTML = `<span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="t">${title}</span>`;
  win.body = div('', win, { position: 'relative', height: `calc(100% - 46px)`, overflow: 'hidden' });
  return win;
}

// ---------- scenes ----------
// each builder(root, C, sc) returns update(t)
const SCENES = {};

SCENES.s01 = (root, C, sc) => {
  const mark = logoMark(220, root, { left: '850px', top: '250px' });
  const word = div('abs', root, { left: 0, width: '1920px', top: '500px', textAlign: 'center', fontSize: '190px', fontWeight: 800, letterSpacing: '-.03em' }, '<span class="grad">RVTSS</span>');
  const sub = div('abs', root, { left: 0, width: '1920px', top: '730px', textAlign: 'center', fontSize: '40px', fontWeight: 600 }, 'Revit MCP for Claude');
  const tag = div('abs mono', root, { left: 0, width: '1920px', top: '800px', textAlign: 'center', fontSize: '20px', letterSpacing: '.3em', color: 'var(--dim)' }, 'INSTALL &amp; USE GUIDE · V2.1');

  // phase B: Claude <-> Revit
  const pb = div('abs', root, { inset: 0 });
  const nodeC = div('card', pb, { left: '330px', top: '470px', width: '420px', height: '170px', display: 'flex', alignItems: 'center', gap: '22px', padding: '0 34px' },
    `<div style="width:84px;height:84px;border-radius:20px;background:linear-gradient(135deg,#d97757,#b35a3c);display:flex;align-items:center;justify-content:center">${icon('spark', 46, '#fff')}</div><div><div style="font-size:40px;font-weight:800">Claude</div><div style="font-size:20px;color:var(--dim)">Desktop · Code</div></div>`);
  const nodeR = div('card', pb, { left: '1170px', top: '470px', width: '420px', height: '170px', display: 'flex', alignItems: 'center', gap: '22px', padding: '0 34px' },
    `<div style="width:84px;height:84px;border-radius:20px;background:linear-gradient(135deg,#1e6fd9,#1652a3);display:flex;align-items:center;justify-content:center;font-size:52px;font-weight:800;color:#fff">R</div><div><div style="font-size:40px;font-weight:800">Revit</div><div style="font-size:20px;color:var(--dim)">your live model</div></div>`);
  const link = div('abs', pb, { left: '760px', top: '553px', width: '400px', height: '4px', background: 'var(--grad)', transformOrigin: 'left center', borderRadius: '2px' });
  const dots = [0, 1, 2].map(() => div('abs', pb, { width: '14px', height: '14px', borderRadius: '50%', background: '#fff', boxShadow: '0 0 18px #00c6ff', top: '548px' }));
  const chips = ['search:Inspect', 'edit:Edit', 'shield:Check'].map((s, i) => {
    const [ic, lb] = s.split(':');
    return div('chip abs', pb, { left: `${600 + i * 260}px`, top: '720px' }, `${icon(ic, 28, '#00c6ff')}${lb}`);
  });
  // phase C: roadmap
  const pc = div('abs', root, { inset: 0 });
  const steps = [['1', 'Install', 'the extension'], ['2', 'Connect', 'Claude'], ['3', 'Use', 'your first commands']].map(([n, a, b], i) => {
    const c = div('card', pc, { left: `${240 + i * 520}px`, top: '430px', width: '440px', height: '230px', padding: '36px 40px' },
      `<div class="mono grad" style="font-size:26px;font-weight:800;letter-spacing:.2em">STEP ${n}</div><div style="font-size:58px;font-weight:800;margin-top:12px">${a}</div><div style="font-size:24px;color:var(--dim);margin-top:4px">${b}</div>`);
    return c;
  });
  const arrows = [0, 1].map(i => div('abs', pc, { left: `${688 + i * 520}px`, top: '520px', color: 'var(--mute)' }, icon('arrow', 64)));

  const tB = C('It connects', -0.3), tC = C('In the next', -0.25);
  return t => {
    const lt = t - sc.vstart;
    mark.draw(E.out(prog(lt, .25, .9)), E.out(prog(lt, .85, .45)));
    const shrink = E.inOut(prog(t, tB - .5, .7));
    const gone = prog(t, tB - .5, .5);
    mark.style.opacity = 1 - gone; mark.style.transform = `translateY(${-60 * shrink}px) scale(${1 - .2 * shrink})`;
    enter(word, t, sc.vstart + .9, { dy: 40, s0: .94, out: tB - .5 });
    enter(sub, t, sc.vstart + 1.5, { out: tB - .5 });
    enter(tag, t, sc.vstart + 1.9, { out: tB - .5 });
    pb.style.opacity = 1 - prog(t, tC - .4, .4);
    enter(nodeC, t, tB, { dx: -40, dy: 0 });
    enter(nodeR, t, tB + .25, { dx: 40, dy: 0 });
    const lp = E.out(prog(t, tB + .4, .7));
    link.style.transform = `scaleX(${lp})`; link.style.opacity = lp > 0 ? 1 : 0;
    dots.forEach((d, i) => {
      const ph = ((t - tB) * .55 + i / 3) % 1;
      d.style.left = `${760 + ph * 386}px`;
      d.style.opacity = lp >= 1 ? Math.sin(ph * Math.PI) : 0;
    });
    enter(chips[0], t, C('inspect'), { s0: .8, ease: E.back });
    enter(chips[1], t, C('edit,'), { s0: .8, ease: E.back });
    enter(chips[2], t, C('check'), { s0: .8, ease: E.back });
    enter(steps[0], t, C("install it"), { dy: 40 });
    enter(steps[1], t, C("connect it"), { dy: 40 });
    enter(steps[2], t, C("run your"), { dy: 40 });
    enter(arrows[0], t, C("connect it") - .2, { dx: -20, dy: 0 });
    enter(arrows[1], t, C("run your") - .2, { dx: -20, dy: 0 });
    pc.style.opacity = t < tC - .2 ? 0 : 1;
  };
};

SCENES.s02 = (root, C, sc) => {
  const k = div('abs kicker', root, { left: '120px', top: '150px' }, 'BEFORE YOU START');
  const h = div('abs title', root, { top: '185px' }, 'What you need');
  const items = [
    ['building', '#3b82f6', 'Autodesk Revit', '2021 – 2027', 'Autodesk Revit'],
    ['plug', '#a78bfa', 'pyRevit', '4.8+ or 5.x · with Routes', 'pyRevit'],
    ['terminal', '#34d399', 'Python 3.11+', 'and the uv package manager', 'Python 3.11'],
    ['spark', '#e08a6a', 'Claude', 'Claude Desktop or Claude Code', 'And Claude'],
  ];
  const cards = items.map(([ic, col, name, ver], i) => {
    const c = div('card', root, { left: `${120 + i * 430}px`, top: '360px', width: '400px', height: '440px', padding: '44px 40px' });
    c.innerHTML = `<div style="width:96px;height:96px;border-radius:24px;background:${col}22;border:1px solid ${col}66;display:flex;align-items:center;justify-content:center">${icon(ic, 50, col)}</div>
      <div style="font-size:42px;font-weight:800;margin-top:44px;letter-spacing:-.01em">${name}</div>
      <div style="font-size:24px;color:var(--dim);margin-top:12px;line-height:1.35">${ver}</div>
      <div class="ok abs" style="left:40px;bottom:40px;display:flex;align-items:center;gap:10px;font-size:20px;font-weight:700;color:var(--ok)">${icon('check', 26, '#34d399')} REQUIRED</div>`;
    c.ok = c.querySelector('.ok');
    return c;
  });
  return t => {
    enter(k, t, sc.vstart + .1); enter(h, t, sc.vstart + .2, { dy: 30 });
    items.forEach((it, i) => {
      const a = C(it[4], -.15);
      enter(cards[i], t, a, { dy: 60, s0: .96 });
      enter(cards[i].ok, t, a + .7, { dy: 10 });
    });
  };
};

SCENES.s03 = (root, C, sc) => {
  const k = div('abs kicker', root, { left: '120px', top: '150px' }, 'ARCHITECTURE');
  const h = div('abs title', root, { top: '185px' }, 'How it works');
  const nodes = [
    ['spark', '#e08a6a', 'Claude', 'Desktop / Code'],
    ['cube', '#00c6ff', 'RVTSS MCP server', 'main.py · on your PC'],
    ['plug', '#a78bfa', 'pyRevit Routes', 'inside Revit · :48884'],
    ['building', '#3b82f6', 'Revit API', 'your live model'],
  ].map(([ic, col, a, b], i) => {
    const c = div('card', root, { left: `${120 + i * 440}px`, top: '440px', width: '360px', height: '250px', padding: '34px 32px' });
    c.innerHTML = `<div style="width:76px;height:76px;border-radius:20px;background:${col}22;border:1px solid ${col}66;display:flex;align-items:center;justify-content:center">${icon(ic, 40, col)}</div>
      <div style="font-size:34px;font-weight:800;margin-top:26px">${a}</div><div style="font-size:21px;color:var(--dim);margin-top:6px">${b}</div>`;
    return c;
  });
  const links = [0, 1, 2].map(i => {
    const l = div('abs', root, { left: `${480 + i * 440}px`, top: '563px', width: '80px', height: '4px', background: 'var(--grad)', transformOrigin: 'left', borderRadius: '2px' });
    const lab = div('abs mono', root, { left: `${450 + i * 440}px`, width: '140px', textAlign: 'center', top: '520px', fontSize: '15px', color: 'var(--dim)', letterSpacing: '.08em' }, ['MCP', 'HTTP JSON', 'API'][i]);
    const dot = div('abs', root, { width: '12px', height: '12px', borderRadius: '50%', background: '#fff', boxShadow: '0 0 16px #00c6ff', top: '559px' });
    return { l, lab, dot };
  });
  const port = div('abs pill', root, { left: '1020px', top: '720px', fontSize: '22px' }, 'PORT 48884');
  const tx = div('abs pill ok', root, { left: '1440px', top: '720px', fontSize: '22px' }, '✓ INSIDE A TRANSACTION');
  const flow = div('abs', root, { left: '120px', top: '820px', fontSize: '24px', color: 'var(--dim)' }, 'Every request: Claude → MCP tool → HTTP → Revit API → JSON result back to Claude');
  const tN = [C('Claude talks', -.1), C('RVTSS MCP'), C('pyRevit Routes'), C('Routes runs', -.1)];
  return t => {
    enter(k, t, sc.vstart + .1); enter(h, t, sc.vstart + .2, { dy: 30 });
    nodes.forEach((n, i) => enter(n, t, tN[i], { dy: 50, s0: .95 }));
    links.forEach((L, i) => {
      const a = tN[i + 1] - .1;
      const p = E.out(prog(t, a, .5));
      L.l.style.transform = `scaleX(${p})`; L.l.style.opacity = p > 0 ? 1 : 0;
      enter(L.lab, t, a + .3, { dy: 8 });
      const ph = ((t - a) * .9) % 1;
      L.dot.style.left = `${480 + i * 440 + ph * 70}px`;
      L.dot.style.opacity = p >= 1 ? Math.sin(ph * Math.PI) : 0;
    });
    enter(port, t, C('port 48884'), { s0: .8, ease: E.back });
    enter(tx, t, C('inside a transaction'), { s0: .8, ease: E.back });
    enter(flow, t, C('inside a transaction') + .6, { dy: 14 });
  };
};

SCENES.s04 = (root, C, sc) => {
  const col = stepColumn(root, 'STEP 1 / 5', 'Install the extension', 'Clone RVTSS into your pyRevit extensions folder.');
  const win = windowBox(root, 790, 230, 1010, 400, 'Windows PowerShell');
  const term = div('term', win.body);
  const l1 = div('', term), l2 = div('', term), o1 = div('o', term), o2 = div('g', term);
  const warn = div('card', root, { left: '790px', top: '670px', width: '1010px', height: '230px', padding: '30px 36px', borderColor: '#5a4a1a' });
  warn.innerHTML = `<div style="display:flex;align-items:center;gap:14px;font-size:32px;font-weight:800;color:var(--warn)">${icon('warn', 36, '#fbbf24')} Keep only ONE copy</div>
    <div style="display:flex;gap:26px;margin-top:26px">
      <div style="display:flex;align-items:center;gap:12px;font-size:24px;font-family:'JetBrains Mono'">${icon('folder', 30, '#34d399')} RVTSS.extension <span class="pill ok">KEEP</span></div>
      <div class="old" style="position:relative;display:flex;align-items:center;gap:12px;font-size:24px;font-family:'JetBrains Mono';color:var(--dim)">${icon('folder', 30, '#f87171')} revit-mcp-python.extension <span class="pill bad">REMOVE</span><div class="strike" style="position:absolute;left:40px;right:120px;top:50%;height:3px;background:#f87171;transform-origin:left"></div></div>
    </div>`;
  const strike = warn.querySelector('.strike'), old = warn.querySelector('.old');
  const tWin = C('Open PowerShell', -.1), tCd = C('go to your'), tClone = C('clone the'), tWarn = C('Keep only'), tRm = C('remove it first');
  const cmd1 = '> cd "$env:APPDATA\\pyRevit\\Extensions"';
  const cmd2 = '> git clone https://github.com/souhaibsmadi42/RVTSS_MCP RVTSS.extension';
  return t => {
    col.update(t, sc.vstart + .1);
    enter(win, t, Math.min(tWin, sc.vstart + .5), { dy: 40, s0: .97 });
    // long clone line wraps at the window edge: render as two visual lines
    typed(l1, t, tCd, cmd1, 46, t < tClone);
    const d2 = typed(l2, t, tClone, cmd2.replace(' RVTSS.extension', '\n    RVTSS.extension'), 40, t >= tClone && t < tClone + 3.2);
    if (t < tClone) l2.innerHTML = '';
    o1.textContent = t > tClone + 2.5 ? "Cloning into 'RVTSS.extension'..." : '';
    o2.textContent = t > tClone + 3.1 ? 'done.' : '';
    enter(warn, t, tWarn - .1, { dy: 40 });
    strike.style.transform = `scaleX(${E.out(prog(t, tRm, .5))})`;
    old.style.opacity = 1 - .45 * prog(t, tRm + .3, .4);
  };
};

SCENES.s05 = (root, C, sc) => {
  const col = stepColumn(root, 'STEP 2 / 5', 'Turn on Routes', 'pyRevit’s Routes server lets RVTSS talk to Revit.');
  const cr = crumbRow(col.crumbs, ['pyRevit tab', 'Settings', 'Routes']);
  const win = windowBox(root, 790, 210, 1010, 560, 'pyRevit Settings');
  const nav = div('abs', win.body, { left: 0, top: 0, bottom: 0, width: '250px', background: '#10121d', borderRight: '1px solid #23273c', padding: '24px 0' });
  const navItems = ['Core Settings', 'Engines', 'Telemetry', 'Routes', 'Extensions', 'Environment'].map(s =>
    div('', nav, { fontSize: '21px', padding: '14px 28px', color: 'var(--dim)' }, s));
  const pane = div('abs', win.body, { left: '290px', top: '34px', right: '40px' });
  const r1 = div('', pane, { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '28px', fontWeight: 700 }, '<span>Routes Server</span>');
  const tog = div('', r1, { width: '86px', height: '46px', borderRadius: '23px', background: '#2a2f47', position: 'relative' });
  const knob = div('', tog, { position: 'absolute', top: '5px', left: '5px', width: '36px', height: '36px', borderRadius: '50%', background: '#fff' });
  const lab = (s, top) => div('abs', pane, { left: 0, top: px(top), fontSize: '20px', color: 'var(--dim)' }, s);
  lab('Host', 110); lab('Port', 230);
  const host = div('abs mono', pane, { left: 0, top: '142px', width: '440px', height: '58px', borderRadius: '10px', background: '#151827', border: '1px solid #2a2f47', fontSize: '26px', padding: '12px 18px' });
  div('abs mono', pane, { left: 0, top: '262px', width: '200px', height: '58px', borderRadius: '10px', background: '#151827', border: '1px solid #2a2f47', fontSize: '26px', padding: '12px 18px', color: 'var(--dim)' }, '48884');
  const save = div('abs', pane, { left: 0, top: '380px', padding: '16px 28px', borderRadius: '12px', background: 'var(--grad)', fontSize: '22px', fontWeight: 800, color: '#06070c' }, 'Save Settings and Reload');
  const ribbon = div('card', root, { left: '120px', top: '830px', width: '1680px', height: '90px', borderRadius: '14px', display: 'flex', alignItems: 'center', gap: '40px', padding: '0 34px', fontSize: '22px', color: 'var(--dim)' },
    ['File', 'Architecture', 'Structure', 'Systems', 'Insert', 'Annotate', 'View', 'Manage', 'pyRevit'].map(s => `<span>${s}</span>`).join(''));
  const rt = div('', ribbon, { padding: '10px 22px', borderRadius: '10px', background: 'rgba(0,198,255,.14)', color: '#fff', fontWeight: 800, boxShadow: '0 0 30px rgba(0,198,255,.35)', border: '1px solid rgba(0,198,255,.5)' }, 'RVTSS');
  const tCr = [C('open the pyRevit'), C('then Settings'), C('then Routes')];
  const tEn = C('Enable'), tHost = C('set the host'), tSave = C('save, and'), tTab = C('A new RVTSS');
  return t => {
    col.update(t, sc.vstart + .1);
    [0, 2, 4].forEach((ix, i) => { enter(cr[ix].e, t, tCr[i], { dy: 14 }); if (ix) enter(cr[ix - 1].e, t, tCr[i] - .1, { dy: 0 }); });
    enter(win, t, sc.vstart + .5, { dy: 40, s0: .97 });
    const navOn = t >= tCr[2];
    navItems.forEach((n, i) => { const on = i === 3 && navOn; n.style.background = on ? 'rgba(0,198,255,.14)' : 'none'; n.style.color = on ? '#fff' : 'var(--dim)'; n.style.borderLeft = on ? '4px solid #00c6ff' : '4px solid transparent'; });
    const tp = E.inOut(prog(t, tEn, .35));
    knob.style.left = `${5 + tp * 40}px`;
    tog.style.background = tp > .5 ? 'linear-gradient(90deg,#00c6ff,#8b5cf6)' : '#2a2f47';
    typed(host, t, tHost + .2, '127.0.0.1', 14, t >= tHost && t < tSave);
    if (t < tHost) host.innerHTML = '<span style="color:var(--mute)">(all interfaces)</span>';
    const press = prog(t, tSave, .25);
    save.style.transform = `scale(${1 - .06 * Math.sin(press * Math.PI)})`;
    save.style.boxShadow = press > 0 ? `0 0 ${40 * (1 - prog(t, tSave + .25, .8))}px rgba(0,198,255,.8)` : 'none';
    enter(ribbon, t, tTab - .3, { dy: 40 });
    enter(rt, t, tTab + .3, { dy: 0, s0: .5, ease: E.back });
  };
};

SCENES.s06 = (root, C, sc) => {
  const col = stepColumn(root, 'STEP 3 / 5', 'Check the server', 'Open the status page in any browser.');
  const win = windowBox(root, 790, 210, 1010, 560, 'Browser');
  const url = div('abs mono', win.body, { left: '24px', right: '24px', top: '18px', height: '56px', borderRadius: '12px', background: '#151827', border: '1px solid #2a2f47', fontSize: '23px', padding: '13px 20px' });
  const json = div('abs mono', win.body, { left: '40px', top: '110px', fontSize: '27px', lineHeight: '1.65', whiteSpace: 'pre' });
  const lines = ['{', '  "status": "active",', '  "health": "healthy",', '  "revit_available": true,', '  "rvtss_version": "2.1.0",', '  "api_name": "revit_mcp"', '}'];
  const L = lines.map(s => div('', json, null, esc(s).replace(/(&quot;|")([^"]+)("):/g, '<span style="color:#7dd3fc">"$2"</span>:').replace(/: "([^"]+)"/g, ': <span style="color:#86efac">"$1"</span>').replace(/: (true)/, ': <span style="color:#c4b5fd">$1</span>')));
  const fix = div('card', root, { left: '120px', top: '810px', width: '1680px', height: '120px', display: 'flex', alignItems: 'center', gap: '24px', padding: '0 34px', fontSize: '24px' });
  fix.innerHTML = `<span class="pill bad" style="font-size:20px">Route does not exits</span>${icon('arrow', 34, '#5d6485')}
    <span>pyRevit</span><span style="color:var(--mute)">›</span><span>Extensions</span><span style="color:var(--mute)">›</span><span>RVTSS</span><span style="color:var(--mute)">›</span><b style="color:var(--ok)">Enable</b>
    <span class="rs" style="display:flex;align-items:center;gap:24px">${icon('arrow', 34, '#5d6485')}<b>Restart Revit</b></span>`;
  const rs = fix.querySelector('.rs');
  const tUrl = C('Open the status'), tH = C('health:'), tV = C('and the RVTSS'), tFix = C('If it says'), tRs = C('restart Revit');
  return t => {
    col.update(t, sc.vstart + .1);
    enter(win, t, sc.vstart + .5, { dy: 40, s0: .97 });
    typed(url, t, tUrl, 'http://127.0.0.1:48884/revit_mcp/status/', 30, t < tUrl + 2);
    L.forEach((l, i) => { enter(l, t, tUrl + 1.5 + i * .08, { dy: 10, d: .3 }); });
    const hl = (l, a) => { const p = prog(t, a, .3); l.style.background = `rgba(0,198,255,${.16 * p})`; l.style.borderRadius = '8px'; };
    hl(L[2], tH); hl(L[4], tV);
    enter(fix, t, tFix - .1, { dy: 30 });
    enter(rs, t, tRs - .2, { dx: -20, dy: 0 });
  };
};

SCENES.s07 = (root, C, sc) => {
  const col = stepColumn(root, 'STEP 4 / 5', 'Run the self&#8209;test', 'A pass/fail check of every RVTSS feature, inside Revit.');
  const rib = div('card', root, { left: '790px', top: '210px', width: '1010px', height: '210px', borderRadius: '16px', overflow: 'hidden' });
  rib.innerHTML = `<div style="height:52px;display:flex;align-items:center;gap:34px;padding:0 26px;background:#151827;border-bottom:1px solid #23273c;font-size:20px;color:var(--dim)"><span>pyRevit</span><span style="color:#fff;font-weight:800;border-bottom:3px solid #00c6ff;padding:12px 0">RVTSS</span></div>
    <div style="display:flex;padding:18px 26px;gap:20px"><div class="btn" style="width:150px;height:110px;border-radius:12px;border:1px solid #2a2f47;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;font-size:17px;font-weight:700">${icon('flask', 40, '#00c6ff')}Run Self-Test</div>
    <div style="align-self:flex-end;font-size:15px;color:var(--mute);letter-spacing:.14em" class="mono">DIAGNOSTICS</div></div>`;
  const btn = rib.querySelector('.btn');
  const cur = div('abs', root, { width: '40px', height: '40px', zIndex: 5 }, `<svg width="40" height="40" viewBox="0 0 24 24"><path d="M5 3l14 8-6 2-3 6z" fill="#fff" stroke="#06070c" stroke-width="1.2"/></svg>`);
  const ripple = div('abs', root, { width: '20px', height: '20px', borderRadius: '50%', border: '3px solid #00c6ff' });
  const rep = div('card', root, { left: '790px', top: '450px', width: '1010px', height: '470px', padding: '28px 36px' });
  const groups = ['Status & session', 'Original tools', 'Read-only tools', 'Editing · dry run, then real', 'Family workflow (.rfa)', 'Parameters · scratch file', 'QC & coordination'];
  rep.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center"><div style="font-size:28px;font-weight:800">RVTSS Self-Test</div><div class="mono" style="font-size:17px;color:var(--dim)">copy of tests/test.rvt → %TEMP%\\RVTSS_live</div></div>`;
  const rows = groups.map((g, i) => div('', rep, { display: 'flex', alignItems: 'center', gap: '16px', fontSize: '23px', marginTop: i ? '10px' : '22px' }, `<span class="st" style="width:30px;display:inline-flex"></span>${g}`));
  const pass = div('abs pill ok', rep, { right: '36px', bottom: '28px', fontSize: '24px', padding: '10px 18px' }, '✓ ALL PASSED');
  const safe = div('abs chip', root, { left: '120px', top: '700px', fontSize: '22px' }, `${icon('shield', 26, '#34d399')} Your files are never touched`);
  const tD = C('click Diagnostics'), tRun = C('then Run'), tRep = C('It works'), tSafe = C('your own files'), tEnd = C('pass or fail');
  return t => {
    col.update(t, sc.vstart + .1);
    enter(rib, t, sc.vstart + .5, { dy: 30 });
    // cursor path: from lower right to the button
    const cp = E.inOut(prog(t, tD - .2, .9));
    const bx = 790 + 26 + 75, by = 210 + 52 + 18 + 60;
    cur.style.left = `${lerp(1600, bx, cp)}px`; cur.style.top = `${lerp(700, by, cp)}px`;
    cur.style.opacity = clamp((t - tD + .4) / .3) * (1 - prog(t, tRep + .5, .3));
    const click = prog(t, tRun + .2, .5);
    ripple.style.left = `${bx - 10}px`; ripple.style.top = `${by - 10}px`;
    ripple.style.opacity = click > 0 && click < 1 ? 1 - click : 0;
    ripple.style.transform = `scale(${1 + click * 5})`;
    btn.style.background = t > tRun + .2 ? 'rgba(0,198,255,.14)' : 'transparent';
    enter(rep, t, tRep - .2, { dy: 40 });
    rows.forEach((r, i) => {
      const a = lerp(tRep + .3, tEnd, i / (rows.length - 1));
      enter(r, t, a - .25, { dy: 8, d: .3 });
      r.querySelector('.st').innerHTML = t >= a ? icon('check', 26, '#34d399') : `<span style="width:16px;height:16px;border-radius:50%;border:2px solid #5d6485;display:inline-block"></span>`;
    });
    enter(pass, t, tEnd + .3, { dy: 0, s0: .6, ease: E.back });
    enter(safe, t, tSafe, { dy: 20 });
  };
};

SCENES.s08 = (root, C, sc) => {
  const col = stepColumn(root, 'STEP 5 / 5', 'Connect Claude', 'Install the dependencies, then register the MCP server.');
  const cr = crumbRow(col.crumbs, ['Settings', 'Developer', 'Edit Config']);
  const tUv = C('run uv sync'), tDesk = C('in Claude Desktop'), tCode = C('Using Claude Code'), tRe = C('Restart Claude');
  const t1 = windowBox(root, 790, 210, 1010, 190, 'Terminal · RVTSS.extension');
  const tt = div('term', t1.body, { fontSize: '24px' });
  const tl1 = div('', tt), tl2 = div('g', tt);
  const cfg = windowBox(root, 790, 210, 1010, 520, 'claude_desktop_config.json');
  const cfgText = `{
  "mcpServers": {
    "RVTSS Revit": {
      "command": "uv",
      "args": ["run", "--project", "C:\\\\...\\\\RVTSS.extension",
               "python", "C:\\\\...\\\\RVTSS.extension\\\\main.py"],
      "env": {"RVTSS_TOOLSETS": "bim_coordinator"}
    }
  }
}`;
  const code = div('term', cfg.body, { fontSize: '22px', lineHeight: '1.55' });
  const cfgLines = cfgText.split('\n').map(s => div('', code, null, esc(s).replace(/"([^"]+)"(?=:)/g, '<span style="color:#7dd3fc">"$1"</span>')));
  const t2 = windowBox(root, 790, 760, 1010, 150, 'Claude Code');
  const cc = div('term', t2.body, { fontSize: '19px', padding: '20px 26px', lineHeight: '1.5' });
  const ok = div('abs chip', root, { left: '120px', top: '760px', fontSize: '24px', borderColor: 'rgba(52,211,153,.5)' }, `<span style="width:12px;height:12px;border-radius:50%;background:#34d399;box-shadow:0 0 12px #34d399"></span> RVTSS Revit · connected · 37 tools`);
  return t => {
    col.update(t, sc.vstart + .1);
    [0, 2, 4].forEach((ix, i) => { enter(cr[ix].e, t, C(['open Settings', 'Developer', 'Edit Config'][i]), { dy: 14 }); if (ix) enter(cr[ix - 1].e, t, C(['open Settings', 'Developer', 'Edit Config'][i]) - .1, { dy: 0 }); });
    enter(t1, t, sc.vstart + .5, { dy: 30, out: tDesk - .2 });
    typed(tl1, t, tUv, '> uv sync', 20, t < tUv + 1.4);
    tl2.textContent = t > tUv + 1.2 ? '✓ dependencies installed from uv.lock' : '';
    enter(cfg, t, tDesk, { dy: 40 });
    cfgLines.forEach((l, i) => enter(l, t, tDesk + .35 + i * .12, { dy: 6, d: .25 }));
    enter(t2, t, tCode - .1, { dy: 30 });
    typed(cc, t, tCode + .4, '> claude mcp add -s user RVTSS -- uv run --project <ext> python <ext>\\main.py', 60, t < tRe);
    if (t < tCode + .4) cc.innerHTML = '';
    enter(ok, t, tRe + .4, { dy: 0, s0: .7, ease: E.back });
  };
};

SCENES.s09 = (root, C, sc) => {
  const k = div('abs kicker', root, { left: '120px', top: '150px' }, 'TOOLSETS & PROFILES');
  const n77 = div('abs', root, { left: '120px', top: '190px', fontSize: '150px', fontWeight: 800, lineHeight: 1, letterSpacing: '-.03em' });
  const l77 = div('abs', root, { left: '120px', top: '345px', fontSize: '30px', color: 'var(--dim)' }, 'tools in <b style="color:#fff">10</b> toolsets');
  const sets = ['core', 'model', 'edit', 'families', 'parameters', 'documentation', 'qc', 'launch', 'code', 'legacy'];
  const chips = sets.map((s, i) => div('abs mono', root, { left: `${700 + (i % 5) * 222}px`, top: `${200 + Math.floor(i / 5) * 84}px`, width: '204px', height: '64px', borderRadius: '14px', border: '1px solid #2a2f47', background: '#121627', fontSize: '21px', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }, s));
  const env = div('abs mono', root, { left: '120px', top: '440px', fontSize: '28px', padding: '16px 24px', borderRadius: '14px', background: '#121627', border: '1px solid #2a2f47' }, '<span style="color:var(--dim)">RVTSS_TOOLSETS</span> = <span class="grad" style="font-weight:800">bim_coordinator</span>');
  const profiles = [
    ['bim_coordinator', 37, ['core', 'model', 'parameters', 'documentation', 'qc'], 'BIM coordinator'],
    ['family_author', 33, ['core', 'families', 'parameters'], 'family author'],
    ['modeler', 30, ['core', 'model', 'edit', 'documentation'], 'modeler'],
    ['minimal', 14, ['core', 'model'], 'or minimal'],
    ['all (default)', 77, sets, 'the default, all'],
  ];
  const bars = profiles.map(([name, n], i) => {
    const row = div('abs', root, { left: '120px', top: `${560 + i * 74}px`, width: '1680px', height: '58px' });
    div('abs mono', row, { left: 0, top: '12px', width: '300px', fontSize: '24px', fontWeight: 700 }, name);
    const bar = div('abs', row, { left: '320px', top: '8px', height: '42px', width: `${(n / 77) * 1240}px`, borderRadius: '10px', background: 'var(--grad)', transformOrigin: 'left' });
    const num = div('abs', row, { left: `${340 + (n / 77) * 1240}px`, top: '8px', fontSize: '30px', fontWeight: 800 }, `${n}`);
    return { row, bar, num };
  });
  const cost = div('abs', root, { left: '700px', top: '392px', fontSize: '24px', color: 'var(--dim)' }, 'Every loaded tool costs context on every turn — load only what you need.');
  const tEnv = C('RVTSS TOOLSETS'), tP = profiles.map(p => C(p[3]));
  return t => {
    enter(k, t, sc.vstart + .1);
    const c = Math.round(77 * E.out(prog(t, sc.vstart + .3, 1.6)));
    n77.innerHTML = `<span class="grad">${c}</span>`; n77.style.opacity = clamp((t - sc.vstart) / .3);
    enter(l77, t, C('in 10'), { dy: 14 });
    chips.forEach((ch, i) => enter(ch, t, C('in 10') + i * .07, { dy: 16, s0: .9 }));
    enter(env, t, tEnv, { dy: 20 });
    enter(cost, t, C('Every tool'), { dy: 14 });
    let active = null;
    bars.forEach((b, i) => {
      enter(b.row, t, tP[i] - .15, { dy: 0, dx: -20, d: .4 });
      b.bar.style.transform = `scaleX(${E.out(prog(t, tP[i], .7))})`;
      enter(b.num, t, tP[i] + .4, { dy: 0 });
      if (t >= tP[i]) active = profiles[i][2];
      b.row.style.filter = '';
    });
    chips.forEach((ch, i) => {
      const on = active && active.includes(sets[i]);
      ch.style.borderColor = on ? 'rgba(0,198,255,.7)' : '#2a2f47';
      ch.style.background = on ? 'rgba(0,198,255,.13)' : '#121627';
      ch.style.color = !active || on ? '#fff' : 'var(--mute)';
    });
  };
};

SCENES.s10 = (root, C, sc) => {
  const k = div('abs kicker', root, { left: '120px', top: '150px' }, 'USING RVTSS');
  const h = div('abs', root, { left: '120px', top: '190px', fontSize: '64px', fontWeight: 800, letterSpacing: '-.02em', lineHeight: 1.05 }, 'Just talk<br>to Claude');
  const note = div('abs', root, { left: '120px', top: '360px', width: '460px', fontSize: '24px', color: 'var(--dim)', lineHeight: 1.45 }, 'Claude picks the right RVTSS tools, runs them in Revit and reports back.');
  const sample = div('abs mono', root, { left: '120px', top: '880px', fontSize: '15px', color: 'var(--mute)', letterSpacing: '.12em' }, 'SAMPLE CONVERSATION · ILLUSTRATIVE RESULTS');
  const win = windowBox(root, 660, 160, 1140, 770, 'Claude  ·  RVTSS Revit connected');
  const feed = div('abs', win.body, { left: '34px', right: '34px', top: 0 });
  const tool = (name, args) => `<div class="tc" style="display:inline-flex;align-items:center;gap:12px;font-family:'JetBrains Mono';font-size:19px;padding:9px 14px;border-radius:10px;background:#141829;border:1px solid #2a2f47;margin:4px 8px 4px 0">${icon('cube', 22, '#00c6ff')}<b style="color:#fff">${name}</b><span style="color:var(--dim)">${args}</span></div>`;
  const msgs = [];
  const user = s => { const m = div('', feed, { display: 'flex', justifyContent: 'flex-end', marginTop: '22px' }, `<div style="max-width:760px;padding:16px 22px;border-radius:18px 18px 4px 18px;background:#22263a;font-size:25px">${s}</div>`); msgs.push(m); return m; };
  const bot = (tools, s) => { const m = div('', feed, { marginTop: '14px' }, `<div>${tools}</div><div style="font-size:23px;color:#d9def0;margin-top:8px;line-height:1.45">${s}</div>`); msgs.push(m); return m; };
  const u1 = user('Give me an overview of this project.');
  const b1 = bot(tool('get_project_overview', ''), '12 levels, 24 grids, 3 phases, 4 worksets. Units: millimetres.');
  const u2 = user('Find all doors on Level 2 wider than 900 mm.');
  const b2 = bot(tool('find_elements', "Doors · Level 2 · Width > 900 mm"), 'Found <b>14 doors</b>. Want me to select them in Revit?');
  const u3 = user('Check clashes between ducts and structural framing, and export a report.');
  const b3 = bot(tool('check_clashes', 'Ducts × Structural Framing') + tool('export_clash_report', 'html'), '<b>23 clashes</b>, grouped by level and grid zone. Report saved as HTML.');
  const tU = [C('Give me'), C('Find all'), C('Check clashes')], tPick = C('Claude picks');
  return t => {
    enter(k, t, sc.vstart + .1); enter(h, t, sc.vstart + .2, { dy: 30 });
    enter(note, t, tPick - .2, { dy: 16 }); enter(sample, t, sc.vstart + .6, { dy: 0 });
    enter(win, t, sc.vstart + .1, { dy: 40, s0: .98 });
    const pairs = [[u1, b1], [u2, b2], [u3, b3]];
    pairs.forEach(([u, b], i) => {
      enter(u, t, tU[i] - .1, { dy: 20, d: .4 });
      const tb = (i < 2 ? tU[i + 1] : tPick) - 1.3;
      enter(b, t, Math.max(tU[i] + 1.0, tb), { dy: 14, d: .4 });
    });
    // scroll the feed so the newest message stays in view
    feed.querySelectorAll('.tc').forEach(tc => { tc.style.boxShadow = t > tPick ? `0 0 ${18 + 8 * Math.sin(t * 5)}px rgba(0,198,255,.45)` : 'none'; tc.style.borderColor = t > tPick ? 'rgba(0,198,255,.7)' : '#2a2f47'; });
  };
};

SCENES.s11 = (root, C, sc) => {
  const k = div('abs kicker', root, { left: '120px', top: '150px' }, 'FEATURES');
  const h = div('abs title', root, { top: '185px' }, 'What’s inside');
  const feats = [
    ['search', '#00c6ff', 'Model intelligence', 'find_elements · get_project_overview · get_family_inventory · get_schedule_data', 'Model intelligence'],
    ['edit', '#60a5fa', 'Element editing', 'set_parameters · bulk_update_parameter · transform_elements · create_elements', 'Element editing'],
    ['cube', '#a78bfa', 'Families (.rfa)', 'family_create · family_add_parameters · family_flex_test · family_load_into_project', 'Full family'],
    ['sliders', '#c084fc', 'Parameters', 'shared_parameters · global_parameters · audit_parameters · export_to_excel', 'Shared, project'],
    ['sheet', '#34d399', 'Documentation', 'create_view · manage_sheets · create_schedule · batch_rename', 'Documentation automation'],
    ['clash', '#f472b6', 'Coordination & QC', 'check_clashes · export_clash_report · run_model_checks (ISO 19650) · map_parameters (IFC / COBie)', 'And coordination'],
  ];
  const tiles = feats.map(([ic, col, name, tools], i) => {
    const c = div('card', root, { left: `${120 + (i % 3) * 566}px`, top: `${320 + Math.floor(i / 3) * 302}px`, width: '536px', height: '282px', padding: '32px 34px' });
    c.innerHTML = `<div style="display:flex;align-items:center;gap:18px"><div style="width:68px;height:68px;border-radius:18px;background:${col}22;border:1px solid ${col}66;display:flex;align-items:center;justify-content:center">${icon(ic, 36, col)}</div><div style="font-size:33px;font-weight:800">${name}</div></div>
      <div class="mono" style="font-size:18px;color:var(--dim);margin-top:26px;line-height:1.6">${tools.split(' · ').join('<br>')}</div>`;
    return c;
  });
  return t => {
    enter(k, t, sc.vstart + .1); enter(h, t, sc.vstart + .2, { dy: 30 });
    feats.forEach((f, i) => enter(tiles[i], t, C(f[4], -.2), { dy: 40, s0: .96 }));
  };
};

SCENES.s12 = (root, C, sc) => {
  const k = div('abs kicker', root, { left: '120px', top: '150px' }, 'SAFETY MODEL');
  const h = div('abs title', root, { top: '185px' }, 'Built to be safe');
  const items = [
    ['undo', 'Transactions', 'every change is named and can be undone in Revit', 'Every change'],
    ['flask', 'Dry run', 'Revit validates the whole change, then rolls it back', 'Dry runs'],
    ['hand', 'Confirmation', 'large or destructive edits wait for your OK', 'Large or'],
    ['ruler', 'Units required', '"900 mm", never a bare 900', 'Dimensions'],
    ['key', 'Token', 'lock the bridge with RVTSS_TOKEN', 'And you can lock'],
  ];
  const rows = items.map(([ic, a, b], i) => div('abs', root, { left: '120px', top: `${330 + i * 112}px`, display: 'flex', alignItems: 'center', gap: '26px' },
    `<div style="width:76px;height:76px;border-radius:20px;background:rgba(0,198,255,.1);border:1px solid rgba(0,198,255,.35);display:flex;align-items:center;justify-content:center">${icon(ic, 38, '#00c6ff')}</div>
     <div><div style="font-size:34px;font-weight:800">${a}</div><div style="font-size:23px;color:var(--dim);margin-top:2px">${b}</div></div>`));
  const shield = div('abs', root, { left: '1290px', top: '330px', color: '#00c6ff' }, `<svg width="420" height="420" viewBox="0 0 24 24" class="ic" style="stroke-width:1"><defs><linearGradient id="sg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00c6ff"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient></defs><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" stroke="url(#sg)" fill="rgba(0,198,255,.06)"/><path class="sc" d="M8.5 12l2.5 2.5 4.5-5" stroke="#fff" stroke-width="1.4" pathLength="1" stroke-dasharray="1 1"/></svg>`);
  const sc2 = shield.querySelector('.sc');
  return t => {
    enter(k, t, sc.vstart + .1); enter(h, t, sc.vstart + .2, { dy: 30 });
    items.forEach((it, i) => enter(rows[i], t, C(it[3], -.15), { dx: -30, dy: 0 }));
    enter(shield, t, sc.vstart + .4, { dy: 30, s0: .9 });
    shield.style.filter = `drop-shadow(0 0 ${30 + 14 * Math.sin(t * 2)}px rgba(0,198,255,.35))`;
    sc2.style.strokeDashoffset = 1 - E.out(prog(t, C('And you can lock'), .8));
  };
};

SCENES.s13 = (root, C, sc) => {
  const mark = logoMark(150, root, { left: '885px', top: '170px' });
  const h = div('abs', root, { left: 0, width: '1920px', top: '360px', textAlign: 'center', fontSize: '96px', fontWeight: 800, letterSpacing: '-.03em' }, 'You’re <span class="grad">ready.</span>');
  const links = div('abs', root, { left: 0, width: '1920px', top: '540px', display: 'flex', justifyContent: 'center', gap: '30px' });
  const l1 = div('chip', links, { fontSize: '26px', padding: '18px 28px' }, `${icon('book', 30, '#00c6ff')} User manual &amp; video<span class="mono" style="color:var(--dim);font-size:22px;margin-left:8px">souhaibsmadi42.github.io/RVTSS_MCP</span>`);
  const l2 = div('abs chip', root, { left: '50%', top: '650px', fontSize: '26px', padding: '18px 28px', transform: 'translateX(-50%)' }, `${icon('terminal', 30, '#8b5cf6')}<span class="mono" style="font-size:24px">github.com/souhaibsmadi42/RVTSS_MCP</span>`);
  const l2w = div('abs', root, { left: 0, width: '1920px', top: '650px', display: 'flex', justifyContent: 'center' });
  l2w.appendChild(l2); l2.style.position = 'relative'; l2.style.left = '0'; l2.style.top = '0'; l2.style.transform = '';
  const steps = div('abs', root, { left: 0, width: '1920px', top: '800px', textAlign: 'center', fontSize: '30px', fontWeight: 700, color: 'var(--dim)' },
    'Install <span style="color:var(--mute)">·</span> Connect Claude <span style="color:var(--mute)">·</span> <span style="color:#fff">Talk to your models</span>');
  const by = div('abs mono', root, { left: 0, width: '1920px', top: '900px', textAlign: 'center', fontSize: '17px', letterSpacing: '.24em', color: 'var(--mute)' }, 'RVTSS · BY SUHAIB AL SMADI');
  return t => {
    const lt = t - sc.vstart;
    mark.draw(E.out(prog(lt, .1, .8)), E.out(prog(lt, .7, .4)));
    enter(h, t, sc.vstart + .3, { dy: 30, s0: .96 });
    enter(l1, t, C('The full'), { dy: 20 });
    enter(l2w, t, C('every link'), { dy: 20 });
    enter(steps, t, C('Install it'), { dy: 16 });
    enter(by, t, C('and start') + .5, { dy: 0 });
  };
};

// ---------- boot ----------
const CHAPTERS = { s01: 'INTRO', s02: 'NEEDS', s03: 'HOW', s04: 'STEP 1', s05: 'STEP 2', s06: 'STEP 3', s07: 'STEP 4', s08: 'STEP 5', s09: 'TOOLSETS', s10: 'USE', s11: 'FEATURES', s12: 'SAFETY', s13: 'END' };
const HUD_RIGHT = { s01: 'INSTALL &amp; USE GUIDE', s02: 'REQUIREMENTS', s03: 'HOW IT WORKS', s04: '<b>STEP 1</b> / 5 · INSTALL', s05: '<b>STEP 2</b> / 5 · ROUTES', s06: '<b>STEP 3</b> / 5 · CHECK', s07: '<b>STEP 4</b> / 5 · SELF-TEST', s08: '<b>STEP 5</b> / 5 · CONNECT', s09: 'TOOLSETS', s10: 'USING RVTSS', s11: 'FEATURES', s12: 'SAFETY', s13: 'RVTSS V2.1' };

async function boot() {
  const tl = await (await fetch('timeline.json')).json();
  const total = tl.total;
  const scenesRoot = document.getElementById('scenes');
  const list = tl.scenes.map((sc, i) => {
    sc.vstart = i === 0 ? 0 : sc.start - .45;
    return sc;
  });
  list.forEach((sc, i) => { sc.vend = i < list.length - 1 ? list[i + 1].vstart + .4 : total; });
  const built = list.map(sc => {
    const root = div('scene', scenesRoot);
    const C = makeCue(sc);
    const update = SCENES[sc.id](root, C, sc);
    return { sc, root, update };
  });

  // HUD
  const hl = document.getElementById('hud-left');
  const mk = logoMark(34, hl, { position: 'relative' }); mk.draw(1, 1);
  div('', hl, null, 'RVTSS <span class="sub">· Revit MCP for Claude</span>');
  const hr = document.getElementById('hud-right');
  const fill = document.querySelector('#progress .fill');
  const chap = document.getElementById('chapters');
  const prog_ = document.getElementById('progress');
  const chapEls = list.map(sc => {
    const x = (sc.vstart / total) * 100;
    if (sc.vstart > 0) div('tick', prog_, { left: `${x}%` });
    return div('', chap, { left: `${((sc.vstart + (sc.vend - sc.vstart) / 2) / total) * 100}%` }, CHAPTERS[sc.id]);
  });
  const g1 = document.getElementById('g1'), g2 = document.getElementById('g2'), grid = document.getElementById('grid');
  const hud = document.getElementById('hud');

  window.renderAt = t => {
    // background drift
    g1.style.left = `${-300 + 160 * Math.sin(t * .07)}px`; g1.style.top = `${-350 + 120 * Math.cos(t * .05)}px`;
    g2.style.left = `${1250 + 140 * Math.cos(t * .06)}px`; g2.style.top = `${450 + 130 * Math.sin(t * .045)}px`;
    grid.style.transform = `translate(${(t * 6) % 60}px, ${(t * 3) % 60}px)`;
    let cur = 0;
    built.forEach((b, i) => {
      const { sc, root } = b;
      const pin = E.out(prog(t, sc.vstart, .5));
      const pout = i < built.length - 1 ? E.inOut(prog(t, sc.vend - .45, .45)) : 0;
      const vis = t >= sc.vstart - .01 && t <= sc.vend + .01;
      root.style.display = vis ? 'block' : 'none';
      if (!vis) return;
      root.style.opacity = (i === 0 ? 1 : pin) * (1 - pout);
      root.style.transform = `translateX(${(1 - pin) * (i === 0 ? 0 : 50) - pout * 50}px)`;
      b.update(t);
      if (t >= sc.vstart + .2) cur = i;
    });
    // HUD
    const hudIn = E.out(prog(t, 2.2, .8)) * (1 - E.out(prog(t, total - 1.2, 1)));
    hud.style.opacity = hudIn;
    hr.innerHTML = HUD_RIGHT[list[cur].id];
    fill.style.width = `${(t / total) * 100}%`;
    chapEls.forEach((c, i) => c.classList.toggle('on', i === cur));
    // global fade from / to black
    document.getElementById('stage').style.opacity = Math.min(clamp(t / .5), 1 - prog(t, total - .8, .8));
  };
  window.TOTAL = total;
  window.renderAt(0);
  window.READY = true;
}
boot().catch(e => { window.BOOT_ERROR = String(e && e.stack || e); console.error(e); });
