// RVTSS 40 s vertical reel (1080x1920): one voiceover, scenes cut on the narrator's words.
// window.renderAt(t) draws the frame at time t; render.mjs captures frames headlessly.
import { clamp, lerp, E, prog, div, px, enter, typed, esc, icon, logoMark, makeCue } from './kit.js';

const SCENES = [];  // { from: phrase, build(root, C, at) -> update(t) }
const scene = (from, build) => SCENES.push({ from, build });

function chat(root, title) {
  const win = div('win', root, { left: '60px', top: '190px', width: '960px', height: '1040px' });
  const bar = div('bar', win, { height: '64px', fontSize: '22px' });
  bar.innerHTML = `<span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="t">${title}</span>`;
  win.body = div('', win, { position: 'relative', height: 'calc(100% - 64px)', overflow: 'hidden', padding: '34px' });
  return win;
}
const bubble = (parent) => div('', parent, { marginLeft: 'auto', maxWidth: '780px', padding: '22px 28px', borderRadius: '26px 26px 6px 26px', background: '#22263a', fontSize: '38px', lineHeight: 1.3, minHeight: '96px' });
const toolChip = (parent, name, args) => div('', parent, { display: 'inline-flex', alignItems: 'center', gap: '14px', fontFamily: 'JetBrains Mono', fontSize: '26px', padding: '12px 18px', borderRadius: '14px', background: '#141829', border: '1px solid rgba(0,198,255,.55)', boxShadow: '0 0 24px rgba(0,198,255,.25)', margin: '26px 12px 0 0' },
  `${icon('cube', 30, '#00c6ff')}<b>${name}</b>${args ? `<span style="color:var(--dim)">${args}</span>` : ''}`);
function stamp(root, top) {
  return div('abs', root, { left: 0, width: '1080px', top: px(top), display: 'flex', justifyContent: 'center' },
    `<div style="display:flex;align-items:center;gap:18px;padding:18px 40px;border-radius:999px;background:rgba(52,211,153,.14);border:2px solid #34d399;color:#34d399;font-size:56px;font-weight:900;letter-spacing:.06em;box-shadow:0 0 60px rgba(52,211,153,.35)">${icon('check', 58, '#34d399')} DONE</div>`);
}

// ---- A. hook
scene(null, (root, C) => {
  const tiles = div('abs', root, { left: 0, width: '1080px', top: '230px', display: 'flex', justifyContent: 'center', gap: '200px' });
  const tc = div('', tiles, { width: '150px', height: '150px', borderRadius: '36px', background: 'linear-gradient(135deg,#d97757,#b35a3c)', display: 'flex', alignItems: 'center', justifyContent: 'center' }, icon('spark', 84, '#fff'));
  const tr = div('', tiles, { width: '150px', height: '150px', borderRadius: '36px', background: 'linear-gradient(135deg,#1e6fd9,#1652a3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '96px', fontWeight: 900 }, 'R');
  const link = div('abs', root, { left: '465px', top: '303px', width: '150px', height: '5px', borderRadius: '3px', background: 'var(--grad)', transformOrigin: 'left' });
  const dot = div('abs', root, { top: '298px', width: '15px', height: '15px', borderRadius: '50%', background: '#fff', boxShadow: '0 0 18px #00c6ff' });
  const line = (html, top, size) => div('abs', root, { left: 0, width: '1080px', top: px(top), textAlign: 'center', fontSize: px(size), fontWeight: 900, letterSpacing: '-.035em', lineHeight: 1 }, html);
  const l1 = line('Your Revit', 560, 150), l2 = line('model…', 720, 150), l3 = line('can now talk', 900, 116), l4 = line('<span class="grad">to Claude.</span>', 1040, 150);
  return t => {
    enter(tc, t, 0.05, { dy: 0, s0: .6, ease: E.back, d: .45 });
    enter(tr, t, 0.15, { dy: 0, s0: .6, ease: E.back, d: .45 });
    const lp = E.out(prog(t, C('can now'), .5));
    link.style.transform = `scaleX(${lp})`;
    const ph = ((t - C('can now')) * 1.2) % 1;
    dot.style.left = `${465 + ph * 138}px`; dot.style.opacity = lp >= 1 ? Math.sin(ph * Math.PI) : 0;
    enter(l1, t, C('Your Revit') - .05, { dy: 0, s0: 1.25, d: .3 });
    enter(l2, t, C('model') - .05, { dy: 0, s0: 1.25, d: .3 });
    enter(l3, t, C('can now') - .05, { dy: 0, s0: 1.25, d: .3 });
    enter(l4, t, C('to Claude') - .05, { dy: 0, s0: 1.35, d: .35 });
  };
});

// ---- B. brand
scene('This is', (root, C) => {
  const mark = logoMark(280, root, { left: '400px', top: '250px' });
  const word = div('abs', root, { left: 0, width: '1080px', top: '600px', textAlign: 'center', fontSize: '230px', fontWeight: 900, letterSpacing: '-.04em', lineHeight: 1 }, '<span class="grad">RVTSS</span>');
  const sub = div('abs', root, { left: 0, width: '1080px', top: '880px', textAlign: 'center', fontSize: '54px', fontWeight: 700 }, 'Free Revit MCP for Claude');
  const chips = div('abs', root, { left: 0, width: '1080px', top: '1000px', display: 'flex', justifyContent: 'center', gap: '18px' });
  const cs = ['77 tools', 'Revit 2021–2027', 'Open source'].map(s => div('chip', chips, { fontSize: '30px' }, s));
  return t => {
    const a = C('This is');
    mark.draw(E.out(prog(t, a, .6)), E.out(prog(t, a + .45, .3)));
    enter(word, t, C('RVTSS') - .1, { dy: 0, s0: 1.2, d: .35 });
    enter(sub, t, C('a free'), { dy: 24 });
    cs.forEach((c, i) => enter(c, t, C('Revit MCP. Just') + i * .12, { dy: 18, s0: .9 }));
  };
});

// ---- C. demo: find doors
scene('Just ask', (root, C, at) => {
  const win = chat(root, 'Claude · RVTSS Revit connected');
  const b = bubble(win.body);
  const res = div('', win.body);
  const chip = toolChip(res, 'find_elements', 'Doors · Level 2 · &gt; 900 mm');
  const out = div('', res, { fontSize: '40px', marginTop: '26px' }, 'Found <b class="grad">14 doors</b>');
  // simple plan: rooms along a corridor, doors as swing arcs
  const plan = div('', res, { marginTop: '28px' });
  let svg = `<svg width="892" height="400" viewBox="0 0 892 400" fill="none" stroke-linecap="round">
    <rect x="6" y="6" width="880" height="388" rx="6" stroke="#3a4060" stroke-width="5"/>
    <path d="M6 168 H886 M6 232 H886" stroke="#3a4060" stroke-width="5"/>`;
  for (let i = 1; i < 7; i++) svg += `<path d="M${i * 126 + 6} 6 V168 M${i * 126 + 6} 232 V394" stroke="#3a4060" stroke-width="5"/>`;
  const doors = [];
  for (let i = 0; i < 7; i++) for (const top of [true, false]) {
    const x = i * 126 + 40, y = top ? 168 : 232, s = top ? -1 : 1;
    doors.push(`<path class="door" d="M${x} ${y} v${s * 52} M${x} ${y + s * 52} A52 52 0 0 ${top ? 1 : 0} ${x + 52} ${y}" stroke="#00c6ff" stroke-width="4" opacity="0"/>`);
  }
  plan.innerHTML = svg + doors.join('') + '</svg>';
  const doorEls = plan.querySelectorAll('.door');
  const st = stamp(root, 1110);
  const tq = C('Just ask') + .2, tr = C('millimetres'), tDone = at('Done.', 0);
  return t => {
    typed(b, t, tq, 'Find every door on Level 2 wider than 900 mm', 30, t < tr + .3);
    if (t < tq) b.innerHTML = '';
    enter(chip, t, tr + .1, { dy: 14, d: .3 });
    enter(out, t, tr + .45, { dy: 14, d: .3 });
    enter(plan, t, tr + .6, { dy: 20, d: .35 });
    doorEls.forEach((d, i) => { d.setAttribute('opacity', t > tr + .7 + i * .04 ? 1 : 0); });
    enter(st, t, tDone - .05, { dy: 0, s0: 1.6, ease: E.back, d: .35 });
  };
});

// ---- D. demo: clashes
scene('Check clashes', (root, C, at) => {
  const win = chat(root, 'Claude · RVTSS Revit connected');
  const b = bubble(win.body);
  const res = div('', win.body);
  const c1 = toolChip(res, 'check_clashes', 'Ducts × Beams');
  const c2 = toolChip(res, 'export_clash_report', 'html');
  const viz = div('', res, { marginTop: '30px', position: 'relative', height: '330px', borderRadius: '18px', background: '#0e1220', border: '1px solid #23273c', overflow: 'hidden' });
  const beam = div('abs', viz, { left: '-20px', right: '-20px', top: '150px', height: '54px', background: 'linear-gradient(180deg,#5b6b8f,#3b4766)', transform: 'rotate(-4deg)' });
  const duct = div('abs', viz, { left: '360px', width: '120px', top: '-20px', bottom: '-20px', background: 'linear-gradient(90deg,rgba(0,198,255,.55),rgba(0,198,255,.3))', border: '2px solid #00c6ff', transform: 'rotate(8deg)' });
  const ring = div('abs', viz, { left: '330px', top: '86px', width: '180px', height: '180px', borderRadius: '50%', border: '6px solid #f87171', boxShadow: '0 0 40px rgba(248,113,113,.6)' });
  const out = div('', res, { fontSize: '40px', marginTop: '26px' }, '<b style="color:#f87171">23 clashes</b> · <span style="color:var(--dim)">report.html saved</span>');
  const st = stamp(root, 1110);
  const tq = C('Check clashes'), tr = C('export a report'), tDone = at('Done.', 1);
  return t => {
    typed(b, t, tq, 'Check clashes: ducts vs beams, export a report', 30, t < tr + .8);
    enter(c1, t, tr - .3, { dy: 14, d: .3 });
    enter(c2, t, tr + .2, { dy: 14, d: .3 });
    enter(viz, t, tr - .1, { dy: 20, d: .35 });
    const pulse = .5 + .5 * Math.sin((t - tr) * 8);
    ring.style.opacity = t > tr + .3 ? .55 + .45 * pulse : 0;
    ring.style.transform = `scale(${.9 + .12 * pulse})`;
    enter(out, t, tr + .6, { dy: 14, d: .3 });
    enter(st, t, tDone - .05, { dy: 0, s0: 1.6, ease: E.back, d: .35 });
  };
});

// ---- E. features
scene('Build parametric', (root, C) => {
  const head = div('abs', root, { left: '60px', top: '190px', fontSize: '84px', fontWeight: 900, letterSpacing: '-.03em' }, 'Do it all <span class="grad">by asking</span>');
  const items = [
    ['cube', '#a78bfa', 'Parametric families', 'Build parametric'],
    ['sliders', '#c084fc', 'Parameters', 'manage parameters'],
    ['sheet', '#34d399', 'Sheets & views', 'create sheets'],
    ['shield', '#00c6ff', 'ISO 19650 checks', 'run ISO'],
  ];
  const tiles = items.map(([ic, col, name], i) => div('card', root, { left: `${60 + (i % 2) * 490}px`, top: `${360 + Math.floor(i / 2) * 330}px`, width: '470px', height: '300px', padding: '40px' },
    `<div style="width:100px;height:100px;border-radius:26px;background:${col}22;border:1px solid ${col}66;display:flex;align-items:center;justify-content:center">${icon(ic, 56, col)}</div><div style="font-size:44px;font-weight:800;margin-top:34px;line-height:1.1">${name}</div>`));
  const big = div('abs', root, { left: 0, width: '1080px', top: '1050px', textAlign: 'center', fontSize: '110px', fontWeight: 900, letterSpacing: '-.03em', lineHeight: 1 });
  return t => {
    enter(head, t, C('Build parametric') - .1, { dy: 30, d: .35 });
    items.forEach((it, i) => enter(tiles[i], t, C(it[3]) - .1, { dy: 50, s0: .9, d: .35, ease: E.back }));
    const a = C('77 tools');
    big.innerHTML = `<span class="grad">${Math.round(77 * E.out(prog(t, a - .2, .7)))}</span> tools`;
    big.style.opacity = clamp((t - a + .25) / .2);
  };
});

// ---- F. safety
scene('And every change', (root, C) => {
  const sh = div('abs', root, { left: '330px', top: '230px' }, `<svg width="420" height="420" viewBox="0 0 24 24" class="ic" style="stroke-width:1"><defs><linearGradient id="sg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00c6ff"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient></defs><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" stroke="url(#sg)" fill="rgba(0,198,255,.06)"/><path class="sc" d="M8.5 12l2.5 2.5 4.5-5" stroke="#fff" stroke-width="1.4" pathLength="1" stroke-dasharray="1 1"/></svg>`);
  const sc = sh.querySelector('.sc');
  const txt = div('abs', root, { left: 0, width: '1080px', top: '720px', textAlign: 'center', fontSize: '86px', fontWeight: 900, letterSpacing: '-.03em', lineHeight: 1.05 }, 'Every change<br><span class="grad">can be undone</span>');
  const keys = div('abs', root, { left: 0, width: '1080px', top: '990px', display: 'flex', justifyContent: 'center', gap: '22px', alignItems: 'center', fontSize: '50px', fontWeight: 800 });
  const k1 = div('', keys, { padding: '18px 34px', borderRadius: '18px', background: '#1a1e30', border: '2px solid #2f3552', boxShadow: '0 8px 0 #0b0d16' }, 'Ctrl');
  div('', keys, { color: 'var(--mute)' }, '+');
  const k2 = div('', keys, { padding: '18px 40px', borderRadius: '18px', background: '#1a1e30', border: '2px solid #2f3552', boxShadow: '0 8px 0 #0b0d16' }, 'Z');
  return t => {
    const a = C('And every change');
    enter(sh, t, a - .1, { dy: 30, s0: .85, d: .4 });
    sc.style.strokeDashoffset = 1 - E.out(prog(t, C('transaction'), .5));
    enter(txt, t, a + .1, { dy: 30, d: .35 });
    enter(keys, t, C('you can undo') - .3, { dy: 20, d: .3 });
    const press = Math.sin(clamp((t - C('undo')) / .3) * Math.PI);
    [k1, k2].forEach(k => { k.style.transform = `translateY(${press * 6}px)`; k.style.boxShadow = `0 ${8 - press * 6}px 0 #0b0d16`; k.style.borderColor = press > .1 ? '#00c6ff' : '#2f3552'; });
  };
});

// ---- G. install
scene('Install it', (root, C) => {
  const head = div('abs', root, { left: '60px', top: '190px', fontSize: '84px', fontWeight: 900, letterSpacing: '-.03em', lineHeight: 1.05 }, 'Install in<br><span class="grad">5 steps</span>');
  const steps = ['Clone the extension', 'Turn on pyRevit Routes', 'Check the status page', 'Run the self-test', 'Connect Claude'];
  const tut = div('abs', root, { left: 0, width: '1080px', top: '1190px', display: 'flex', justifyContent: 'center' },
    `<div class="chip" style="font-size:34px;padding:16px 28px;border-color:rgba(0,198,255,.6)">${icon('play', 34, '#00c6ff')} Full 4-min tutorial + user manual</div>`);
  const rows = steps.map((s, i) => div('abs', root, { left: '60px', top: `${430 + i * 150}px`, width: '960px', height: '124px', display: 'flex', alignItems: 'center', gap: '28px', padding: '0 30px', borderRadius: '22px', background: '#121524', border: '1px solid #262a3f', fontSize: '42px', fontWeight: 700 },
    `<span class="grad mono" style="font-size:54px;font-weight:900;width:56px">${i + 1}</span>${s}<span class="ck" style="margin-left:auto"></span>`));
  return t => {
    const a = C('Install it');
    enter(head, t, a - .1, { dy: 30, d: .35 });
    rows.forEach((r, i) => {
      const ti = a + .2 + i * .22;
      enter(r, t, ti, { dx: -60, dy: 0, d: .3 });
      r.querySelector('.ck').innerHTML = t > ti + .35 ? icon('check', 50, '#34d399') : '';
    });
    enter(tut, t, C('Watch the full') - .1, { dy: 20, s0: .9, ease: E.back, d: .35 });
  };
});

// ---- H. call to action (holds to the end)
scene('get RVTSS', (root, C) => {
  const mark = logoMark(220, root, { left: '430px', top: '250px' });
  const l1 = div('abs', root, { left: 0, width: '1080px', top: '560px', textAlign: 'center', fontSize: '120px', fontWeight: 900, letterSpacing: '-.035em', lineHeight: 1 }, 'Get <span class="grad">RVTSS</span><br>free');
  const gh = div('abs', root, { left: 0, width: '1080px', top: '860px', display: 'flex', justifyContent: 'center' },
    `<div class="chip" style="font-size:32px;padding:20px 30px">${icon('terminal', 38, '#8b5cf6')}<span class="mono">github.com/souhaibsmadi42/RVTSS_MCP</span></div>`);
  const l2 = div('abs', root, { left: 0, width: '1080px', top: '1000px', textAlign: 'center', fontSize: '40px', fontWeight: 600, color: 'var(--dim)' }, 'Tutorial · user manual · 77 tools · open source');
  const by = div('abs mono', root, { left: 0, width: '1080px', top: '1120px', textAlign: 'center', fontSize: '24px', letterSpacing: '.24em', color: 'var(--mute)' }, 'REVIT MCP FOR CLAUDE · BY SUHAIB AL SMADI');
  return t => {
    const a = C('get RVTSS');
    mark.draw(E.out(prog(t, a - .1, .6)), E.out(prog(t, a + .4, .3)));
    enter(l1, t, a, { dy: 0, s0: 1.2, d: .35 });
    enter(gh, t, C('on GitHub') - .1, { dy: 24, d: .35, s0: .9, ease: E.back });
    enter(l2, t, C('on GitHub') + .5, { dy: 16, d: .35 });
    enter(by, t, C('on GitHub') + .9, { dy: 0 });
  };
});

// ---------- captions: word-by-word, hidden where the scene already shows the words ----------
function buildCaptions(sc, C) {
  const text = sc.vo, words = [];
  const re = /\S+/g; let m;
  while ((m = re.exec(text))) words.push({ w: m[0], t: sc.start + C.map(C.wpos[m.index]) });
  const chunks = []; let cur = [];
  words.forEach((wd, i) => {
    cur.push(wd);
    const len = cur.map(x => x.w).join(' ').length;
    const endP = /[.!?:…]$/.test(wd.w), comma = /,$/.test(wd.w);
    const next = words[i + 1];
    if (!next || endP || (comma && cur.length >= 2) || cur.length >= 4 || len + (next ? next.w.length : 0) > 24) { chunks.push(cur); cur = []; }
  });
  chunks.forEach((ch, i) => { ch.t0 = ch[0].t - .05; ch.t1 = i < chunks.length - 1 ? chunks[i + 1][0].t - .05 : sc.start + sc.dur + .3; });
  return chunks;
}

async function boot() {
  const tl = await (await fetch('timeline.json')).json();
  const sc = tl.vo;
  const C = makeCue(sc);
  const occurrences = (phrase, n) => { let i = -1; for (let k = 0; k <= n; k++) i = sc.vo.indexOf(phrase, i + 1); return sc.start + C.map(C.wpos[i]); };
  const total = tl.total;
  const root = document.getElementById('scenes');
  const built = SCENES.map((s, i) => {
    const el = div('scene', root);
    const from = s.from ? C(s.from) - .15 : 0;
    return { el, from, update: s.build(el, C, occurrences) };
  });
  built.forEach((b, i) => { b.to = i < built.length - 1 ? built[i + 1].from : total; });
  const chunks = buildCaptions(sc, C);
  const cap = document.getElementById('cap'), fill = document.querySelector('#bar .fill');
  const capOn = [C('This is') - .15, C('get RVTSS') - .15];
  const g1 = document.getElementById('g1'), g2 = document.getElementById('g2'), grid = document.getElementById('grid');

  window.renderAt = t => {
    g1.style.left = `${-420 + 140 * Math.sin(t * .2)}px`; g1.style.top = `${-300 + 120 * Math.cos(t * .17)}px`;
    g2.style.left = `${300 + 140 * Math.cos(t * .19)}px`; g2.style.top = `${1150 + 130 * Math.sin(t * .15)}px`;
    grid.style.transform = `translate(${(t * 14) % 60}px, ${(t * 8) % 60}px)`;
    built.forEach((b, i) => {
      const vis = t >= b.from && t < b.to + .25;
      b.el.style.display = vis ? 'block' : 'none';
      if (!vis) return;
      const pin = i === 0 ? 1 : E.out(prog(t, b.from, .3));
      const pout = i < built.length - 1 ? E.inOut(prog(t, b.to, .25)) : 0;
      b.el.style.opacity = pin * (1 - pout);
      b.el.style.transform = `translateY(${(1 - pin) * 60 - pout * 60}px) scale(${lerp(.97, 1, pin)})`;
      b.update(t);
    });
    // captions
    const ch = chunks.find(c => t >= c.t0 && t < c.t1);
    if (ch && t >= capOn[0] && t < capOn[1]) {
      cap.style.opacity = 1;
      cap.innerHTML = '<div class="box">' + ch.map((wd, k) => {
        const nxt = ch[k + 1] ? ch[k + 1].t : ch.t1;
        const cls = t >= wd.t && t < nxt ? 'w now' : t >= wd.t ? 'w on' : 'w';
        return `<span class="${cls}">${esc(wd.w)}</span>`;
      }).join(' ') + '</div>';
    } else cap.style.opacity = 0;
    fill.style.width = `${(t / total) * 100}%`;
    document.getElementById('stage').style.opacity = Math.min(clamp(t / .15), 1 - prog(t, total - .5, .5));
  };
  window.TOTAL = total;
  window.renderAt(0);
  window.READY = true;
}
boot().catch(e => { window.BOOT_ERROR = String(e && e.stack || e); console.error(e); });
