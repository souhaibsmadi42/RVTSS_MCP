// RVTSS v2.1 — 40 s promo (80 beats @ 120 BPM, SFX-only cut: no music track was supplied).
// Motif: "The Cut" — a cyan blade slash opens the logo, the drop, the recap and the outro.
// Section map (beats): open 0–7 · logo 8–11 · proof 12–15 · DROP features 16–31 · breakdown clash report 32–39 ·
//                      tension safety 40–47 · silence 48–51 · riser 52–55 · DROP recap numbers 56–71 · outro 72–79
// Every number on screen is a real, verified RVTSS v2.1 fact; the clash rows in the breakdown are labelled illustrative.
import { h, s, show, tf, txt, Ease, clamp, lerp } from './lib.js';
import { B, BEAT, shot, runShots, drift, T, slam, maskLine, rise, track, echo, counter, typed, drawOn, initSlash, addSlashLine, drawSlash, SLASHES, initHud, hud } from './kit.js';
import { hit, flash, whip, slash, glitch, invert, punch, rumble, caRamp } from './post.js';

const BRAND = 'RVTSS';
const ER = [];
const ev = (t, kind, k = 1) => ER.push({ t: +t.toFixed(4), kind, k });
const MONO = { color: 'var(--ink)' };

export function gradeAt(t) {
  if (t >= B(48) && t < B(52)) return { grain: 0.085, vig: 0.5 };   // silence: grain up, calm
  if (t >= B(32) && t < B(40)) return { grain: 0.06 };
  return {};
}

function codeCard(parent, tool, args, result, css) {
  return h('div', 'ui', parent, Object.assign({ width: '760px', padding: '26px 30px', background: '#10121C', border: '1px solid #2A2E44', borderRadius: '16px', boxShadow: '0 30px 80px rgba(0,0,0,.55)' }, css),
    `<div class="kmono" style="position:static;font-size:15px">CLAUDE ▸ TOOL CALL</div>
     <div style="font-family:Mono;font-weight:700;font-size:34px;margin-top:12px;color:#F4F5FA">${tool}</div>
     <div style="font-family:Mono;font-weight:500;font-size:21px;margin-top:14px;color:#9AA3C7;white-space:pre">${args}</div>
     <div style="display:flex;gap:12px;align-items:center;margin-top:20px">
       <span style="font-family:Mono;font-weight:700;font-size:15px;letter-spacing:.14em;padding:6px 12px;border-radius:6px;background:rgba(0,198,255,.14);color:#00C6FF">STATUS · SUCCESS</span>
       <span style="font-family:Mono;font-weight:500;font-size:15px;letter-spacing:.1em;color:#8A90A8">${result}</span></div>`);
}

export async function initScenes() {
  initSlash(document.getElementById('ov'));
  initHud(document.getElementById('hud'), { title: `${BRAND} <span style="color:var(--hot)">▸</span> REVIT MCP FOR CLAUDE`, right: 'V2.1 · 2026' });

  // ---- 1. cold open (beats 0–7): hairline, typed system label, staccato words, strobe + riser
  {
    const S = shot(0, B(8));
    S.line = h('div', null, S.root, { position: 'absolute', left: '960px', top: '540px', height: '1px', width: '0', background: 'var(--ink)' });
    S.lab = T(S.root, '', { left: '0', top: '600px', width: '1920px', textAlign: 'center', fontSize: '18px' }, 'kmono');
    const words = [['YOUR', 420], ['REVIT MODEL.', 300], ['NOW TALKS', 330], ['TO <span class="kgrad">CLAUDE.</span>', 330]];
    S.w = words.map(([w, fs]) => T(S.root, w, { left: '0', top: `${540 - fs * 0.45}px`, width: '1920px', textAlign: 'center', fontSize: `${fs}px`, color: 'var(--ink)' }));
    S.update = (t, lt) => {
      const w = 40 + 900 * Ease.outQ(clamp(lt / 1.9));
      S.line.style.left = (960 - w / 2) + 'px'; S.line.style.width = w + 'px';
      show(S.line, t < B(2) ? 1 : 0);
      show(S.lab, t < B(2) ? 1 : 0);
      typed(S.lab, t, B(0.5), 'PYREVIT ROUTES ▸ :48884 ▸ MODEL CONTEXT PROTOCOL', BEAT / 16);
      if (t >= B(2)) show(S.lab, 0);
      [2, 3, 5, 6].forEach((k, i) => slam(S.w[i], t, B(k), B(k + 1), { s0: 1.25, d: 0.18 }));
    };
    ev(B(0.5), 'type', 0.5);
    [2, 3, 5, 6].forEach(k => { hit(B(k), 0.7); ev(B(k), 'hitS', 0.7); });
    for (let i = 0; i < 4; i++) invert(B(7) + i * BEAT / 4, 2 / 60);
    rumble(B(7), BEAT, 1.2); ev(B(7), 'riser', 1);
    addSlashLine(B(8));
  }

  // ---- 2. slash -> logo lockup (beats 8–11)
  {
    const S = shot(B(8), B(12), { svg: 'ov' });
    const g = s('g', { transform: 'translate(470 430)' }, S.svg);
    S.mk = [
      s('rect', { x: 0, y: 0, width: 210, height: 210, rx: 38, fill: 'none', stroke: 'url(#slg)', 'stroke-width': 16, pathLength: 1, 'stroke-dasharray': '1 1' }, g),
      s('path', { d: 'M40 160 L170 50', fill: 'none', stroke: '#FFFFFF', 'stroke-width': 12, 'stroke-linecap': 'round', pathLength: 1, 'stroke-dasharray': '1 1' }, g),
    ];
    S.word = T(S.root, `<span class="kgrad">${BRAND}</span>`, { left: '740px', top: '405px', fontSize: '230px', fontFamily: 'Inter', fontWeight: 800, letterSpacing: '-0.03em', lineHeight: '1.1' }, 'k');
    S.sub = T(S.root, 'REVIT MCP FOR CLAUDE · V2.1', { left: '752px', top: '690px', fontSize: '24px', color: 'var(--ink)', letterSpacing: '.3em' }, 'kmono');
    S.update = (t, lt) => {
      drift(S.root, lt, 1, 1.04, 0, 0, 2);
      drawOn(S.mk[0], Ease.outQ(clamp(lt / 0.35)));
      drawOn(S.mk[1], Ease.outQ(clamp((lt - 0.2) / 0.25)));
      track(S.word, t, B(8), B(12), 0.55, 0.42);
      slam(S.sub, t, B(10), B(12), { s0: 1.06, dy: 10 });
    };
    slash(B(8), -0.42, 1.3); flash(B(8), 2, 1); hit(B(8), 1.2); ev(B(8), 'slash', 1.2);
    punch(B(10), 0.04); ev(B(10), 'hitS', 0.6);
  }

  // ---- 3. proof number (beats 12–15): 77 tools
  {
    const S = shot(B(12), B(16));
    S.n = T(S.root, '0', { left: '0', top: '210px', width: '1920px', textAlign: 'center', fontSize: '520px', color: 'var(--ink)' });
    S.l = T(S.root, 'TOOLS · 10 TOOLSETS · 7 PROMPTS', { left: '0', top: '760px', width: '1920px', textAlign: 'center', ...MONO, fontSize: '26px', letterSpacing: '.3em' }, 'kmono');
    S.update = (t) => {
      slam(S.n, t, B(12), B(16), { s0: 1.2 });
      counter(S.n, t, B(12), B(12) + 0.6, 0, 77);
      tf(S.n, `scale(${(1 + 0.04 * (1 - clamp(((t - B(12)) % BEAT) / 0.3))).toFixed(3)})`);
      slam(S.l, t, B(13), B(16), { s0: 1.05 });
    };
    hit(B(12), 1); ev(B(12), 'impact', 1); for (let k = 13; k < 16; k++) { punch(B(k), 0.02); ev(B(k), 'tick', 0.5); }
    rumble(B(15), BEAT, 0.8); ev(B(15), 'riser', 0.8);
    addSlashLine(B(16), 0.38);
  }

  // ---- 4. DROP: what it does (beats 16–31), one feature per 2 beats, alternating sides, real tool calls
  {
    const items = [
      ['INSPECT.', 'find_elements', '{categories: ["Doors"], level: "Level 2"}', '→ ids · counts · structured'],
      ['EDIT.', 'set_parameters', '{dry_run: true, unit: "mm"}', '→ before / after values'],
      ['FAMILIES.', 'family_build_parametric_box', '{width: 900, depth: 600, height: 750}', '→ flex test passed'],
      ['PARAMETERS.', 'shared_parameters', '{action: "bind", categories: ["Doors"]}', '→ GUIDs kept'],
      ['CLASHES.', 'check_clashes', '{clearance: 50, group_by: ["grid_zone"]}', '→ hard + clearance'],
      ['ISO 19650.', 'run_model_checks', '{checks: ["iso19650", "view_audit"]}', '→ field-by-field'],
      ['<span class="kgrad">EXCEL.</span>', 'export_to_excel', '{categories: ["Doors"], parameters: [...]}', '→ units in headers'],
      ['IFC / COBIE.', 'map_parameters', '{preset: "cobie_type", dry_run: true}', '→ presets'],
    ];
    const S = shot(B(16), B(32), { ui: true });
    S.w = items.map(([w]) => T(S.root, w, { top: '150px', fontSize: '250px', color: 'var(--ink)' }));
    S.n = items.map((_, i) => T(S.root, `0${i + 1} / 08`, { top: '120px', fontSize: '20px', ...MONO }, 'kmono'));
    S.c = items.map(([, tool, args, res]) => codeCard(S.ui, tool, args, res, { top: '520px', display: 'none' }));
    S.update = (t, lt) => {
      const i = clamp(Math.floor((t - B(16)) / (2 * BEAT)), 0, items.length - 1), right = i % 2 === 1;
      const a = B(16 + 2 * i), b = B(18 + 2 * i);
      S.w.forEach((e, j) => {
        if (j !== i) { show(e, 0); show(S.n[j], 0); S.c[j].style.display = 'none'; return; }
        for (const el of [e, S.n[j]]) { el.style.left = right ? 'auto' : '110px'; el.style.right = right ? '110px' : 'auto'; el.style.textAlign = right ? 'right' : 'left'; }
        slam(e, t, a, b, { s0: 1.28, dx: right ? 60 : -60, d: 0.2 });
        slam(S.n[j], t, a, b, { s0: 1 });
        const c = S.c[j];
        c.style.display = 'block'; c.style.left = right ? 'auto' : '110px'; c.style.right = right ? '110px' : 'auto';
        const p = Ease.outExpo(clamp((t - a - BEAT / 2) / 0.25));
        show(c, t >= a + BEAT / 2 ? 1 : 0);
        tf(c, `translateY(${((1 - p) * 40).toFixed(1)}px) scale(${lerp(1, 1.03, clamp((t - a) / (2 * BEAT))).toFixed(4)})`);
      });
      tf(S.ui, `scale(${lerp(1, 1.02, clamp(lt / 8)).toFixed(4)})`);
    };
    slash(B(16), 0.38, 1.3); flash(B(16), 2, 1); hit(B(16), 1.4); ev(B(16), 'slash', 1.3); ev(B(16), 'drop', 1);
    for (let i = 0; i < items.length; i++) {
      const k = 16 + 2 * i;
      if (i) { hit(B(k), 1.1); ev(B(k), 'impact', 0.75); }
      punch(B(k + 1), 0.03); ev(B(k + 1), 'blip', 0.5);
      if (i % 3 === 2) { glitch(B(k) - 0.06, 0.16, 0.8); ev(B(k) - 0.06, 'glitch', 0.7); }
    }
    whip(B(32) - 0.16, 0.32, 0, 1); ev(B(32) - 0.16, 'whoosh', 1);
  }

  // ---- 5. breakdown (beats 32–39): clash report + grid zone, one slow push, text rising
  {
    const S = shot(B(32), B(40), { ui: true, svg: true });
    S.panel = h('div', 'ui', S.ui, { left: '880px', top: '200px', width: '940px', padding: '28px 32px', background: '#10121C', border: '1px solid #2A2E44', borderRadius: '16px' },
      `<div style="display:flex;justify-content:space-between"><div class="kmono" style="position:static;font-size:15px">EXPORT_CLASH_REPORT ▸ CSV + HTML</div>
       <div class="kmono" style="position:static;font-size:15px;color:#FFB020">ILLUSTRATIVE DATA</div></div>
       <table style="margin-top:18px;border-collapse:collapse;width:100%;font-family:Mono;font-size:19px;color:#C9CEE6">
       <tr style="color:#8A90A8;font-size:15px;letter-spacing:.12em"><td>ZONE</td><td>LEVEL</td><td>PAIR</td><td>TYPE</td><td style="text-align:right">DIST</td></tr>
       ${[['A-B/1-2', 'Level 2', 'Ducts × Framing', 'hard', '0'], ['A-B/1-2', 'Level 2', 'Pipes × Framing', 'clearance', '32 mm'], ['B-C/2-3', 'Level 3', 'Ducts × Columns', 'clearance', '41 mm'], ['B-C/1-2', 'Level 3', 'Trays × Framing', 'hard', '0']]
        .map((r, i) => `<tr data-r="${i}" style="border-top:1px solid #23263A;opacity:0"><td style="padding:12px 0;color:#00C6FF">${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td style="color:${r[3] === 'hard' ? '#FF4D6D' : '#FFB020'}">${r[3]}</td><td style="text-align:right">${r[4]}</td></tr>`).join('')}
       </table>`);
    S.rows = [...S.panel.querySelectorAll('[data-r]')];
    // plan grid A–C × 1–3 with the clash marker in zone A-B/1-2 (nearest intersection B/2)
    const gx = [1000, 1250, 1500], gy = [700, 820, 940];
    S.gl = [];
    gx.forEach((x, i) => { S.gl.push(s('line', { x1: x, y1: 650, x2: x, y2: 990, stroke: '#3A4060', 'stroke-width': 2, 'stroke-dasharray': '10 6' }, S.svg)); s('text', { x: x - 8, y: 640, fill: '#8A90A8', 'font-family': 'Mono', 'font-size': 18 }, S.svg).textContent = 'ABC'[i]; });
    gy.forEach((y, i) => { S.gl.push(s('line', { x1: 950, y1: y, x2: 1560, y2: y, stroke: '#3A4060', 'stroke-width': 2, 'stroke-dasharray': '10 6' }, S.svg)); s('text', { x: 925, y: y + 6, fill: '#8A90A8', 'font-family': 'Mono', 'font-size': 18 }, S.svg).textContent = String(i + 1); });
    S.zone = s('rect', { x: 1000, y: 700, width: 250, height: 120, fill: 'rgba(0,198,255,.12)', stroke: '#00C6FF', 'stroke-width': 2 }, S.svg);
    S.dot = s('circle', { cx: 1170, cy: 780, r: 12, fill: '#FF4D6D' }, S.svg);
    S.ring = s('circle', { cx: 1170, cy: 780, r: 12, fill: 'none', stroke: '#FF4D6D', 'stroke-width': 3 }, S.svg);
    S.near = s('line', { x1: 1170, y1: 780, x2: 1250, y2: 820, stroke: '#FFFFFF', 'stroke-width': 2 }, S.svg);
    S.m = ['EVERY CLASH,', '<span class="kgrad">LOCATED.</span>'].map((w, i) => maskLine(S.root, w, { left: '110px', top: `${330 + i * 150}px`, fontSize: '130px', color: 'var(--ink)' }));
    S.cap = T(S.root, '', { left: '115px', top: '660px', fontSize: '20px', ...MONO }, 'kmono');
    S.update = (t, lt) => {
      drift(S.root, lt, 1, 1.03, 0, 0, 4);
      S.ui.style.transformOrigin = '0 0';
      tf(S.ui, `translate(${(-lt * 6).toFixed(1)}px, ${(-lt * 3).toFixed(1)}px)`);
      tf(S.svg, `translate(${(-lt * 6).toFixed(1)}px, ${(-lt * 3).toFixed(1)}px)`);
      S.rows.forEach((r, i) => { const o = clamp((t - B(33 + i)) / 0.15); if (r._o !== o) { r.style.opacity = o.toFixed(2); r._o = o; } });
      show(S.zone, t >= B(35) ? 1 : 0);
      const rp = t >= B(35) ? ((t - B(35)) % (2 * BEAT)) / (2 * BEAT) : 0;
      show(S.ring, t >= B(35) ? 1 - rp : 0); S.ring.setAttribute('r', (12 + 40 * rp).toFixed(1));
      show(S.dot, t >= B(35) ? 1 : 0);
      show(S.near, t >= B(36) ? 1 : 0);
      rise(S.m[0], t, B(32), B(40)); rise(S.m[1], t, B(34), B(40));
      typed(S.cap, t, B(36), 'GRID ZONE A-B/1-2 · NEAREST B/2 · LEVEL 2', BEAT / 8);
    };
    ev(B(32), 'swell', 0.8);
    for (let i = 0; i < 4; i++) ev(B(33 + i), 'tick', 0.35);
    ev(B(35), 'blip', 0.6);
  }

  // ---- 6. tension (beats 40–47): the safety model, one word per 2 beats, micro punches on kicks
  {
    const items = [['DRY RUN.', 'REVIT VALIDATES, THEN ROLLS BACK'], ['CONFIRM.', 'PREVIEW FIRST · ELICITATION'], ['UNDO.', 'ONE NAMED TRANSACTION PER CHANGE']];
    const S = shot(B(40), B(47.5));
    S.w = items.map(([w]) => T(S.root, w, { left: '0', top: '330px', width: '1920px', textAlign: 'center', fontSize: '360px', color: 'var(--ink)' }));
    S.c = items.map(([, c]) => T(S.root, c, { left: '0', top: '720px', width: '1920px', textAlign: 'center', fontSize: '24px', letterSpacing: '.3em', ...MONO }, 'kmono'));
    S.e = items.map(([w]) => T(S.root, w, { left: '0', top: '330px', width: '1920px', textAlign: 'center', fontSize: '360px' }, 'k anton outline hot'));
    S.update = (t) => {
      items.forEach((_, i) => {
        const a = B(40 + 2 * i), b = i === 2 ? B(47.5) : B(42 + 2 * i);
        slam(S.w[i], t, a, b, { s0: 1.22, d: 0.2 });
        slam(S.c[i], t, a + BEAT / 2, b, { s0: 1.04 });
        echo(S.e[i], t, a, 0.25, 0.3);
      });
    };
    for (let i = 0; i < 3; i++) { hit(B(40 + 2 * i), 0.8); ev(B(40 + 2 * i), 'hitS', 0.8); punch(B(41 + 2 * i), 0.015); ev(B(41 + 2 * i), 'click', 0.5); }
    invert(B(44), 0.5);
    ev(B(47), 'whooshL', 0.6);
  }

  // ---- 7. silence (beats 48–51): one calm sentence
  {
    const S = shot(B(48), B(52));
    S.a = T(S.root, 'Built by a BIM coordinator,', { left: '0', top: '440px', width: '1920px', textAlign: 'center', fontFamily: 'Inter', fontWeight: 600, fontSize: '72px', color: 'var(--ink)', lineHeight: '1.2' }, 'k');
    S.b = T(S.root, 'for BIM coordinators.', { left: '0', top: '540px', width: '1920px', textAlign: 'center', fontFamily: 'Inter', fontWeight: 600, fontSize: '72px', color: 'var(--dim)', lineHeight: '1.2' }, 'k');
    S.update = (t, lt) => {
      drift(S.root, lt, 1, 1.02, 0, 0, 2);
      slam(S.a, t, B(48), B(52), { s0: 1, fade: 0.5 });
      slam(S.b, t, B(49), B(52), { s0: 1, fade: 0.5 });
    };
  }

  // ---- 8. riser into the second drop (beats 52–55)
  {
    const S = shot(B(52), B(55.75));
    S.l = T(S.root, '', { left: '0', top: '520px', width: '1920px', textAlign: 'center', fontSize: '22px', letterSpacing: '.3em', ...MONO }, 'kmono');
    S.bar = h('div', null, S.root, { position: 'absolute', left: '560px', top: '580px', height: '3px', width: '0', background: 'linear-gradient(90deg,var(--hot),var(--hot2))' });
    S.update = (t, lt) => {
      typed(S.l, t, B(52), 'RUN SELF-TEST ▸ 40 STEPS ▸ RVTSS_LIVE_REPORT.MD', BEAT / 8, false);
      S.bar.style.width = (800 * Ease.in(clamp(lt / (B(55.75) - B(52))))).toFixed(1) + 'px';
      tf(S.root, `scale(${lerp(1, 1.08, Ease.in(clamp(lt / 1.875))).toFixed(4)})`);
    };
    ER.push({ t: +B(52).toFixed(4), kind: 'riser', k: 1.2, d: 4 * BEAT });
    rumble(B(54), 2 * BEAT, 1.4); caRamp(B(54), 2 * BEAT, 1.2);
    for (let i = 0; i < 6; i++) invert(B(54.5) + i * BEAT / 4, 2 / 60);
    addSlashLine(B(56), -0.42);
  }

  // ---- 9. DROP recap (beats 56–71): verified numbers, one per 4 beats, alternating, counters + echoes
  {
    const items = [
      { v: 245, f: v => String(Math.round(v)), l: 'UNIT TESTS · MCP 1.9 + 2.X · CI ON 3.11–3.13' },
      { v: 40, f: v => '−' + Math.round(v) + '%', l: 'TOOL CONTEXT VS V2.0' },
      { v: 16, f: v => String(Math.round(v)), l: 'QC CHECKS · ISO 19650 · VIEW AUDIT' },
      { v: 1, f: () => '1 CLICK', l: 'SELF-TEST INSIDE REVIT' },
    ];
    const S = shot(B(56), B(72));
    S.n = items.map(() => T(S.root, '0', { top: '170px', fontSize: '480px', color: 'var(--ink)' }));
    S.e = items.map(() => T(S.root, '', { top: '170px', fontSize: '480px' }, 'k anton outline hot'));
    S.l = items.map(it => T(S.root, it.l, { top: '760px', fontSize: '26px', letterSpacing: '.28em', ...MONO }, 'kmono'));
    S.update = (t) => {
      items.forEach((it, i) => {
        const a = B(56 + 4 * i), b = B(60 + 4 * i), right = i % 2 === 1;
        for (const el of [S.n[i], S.e[i], S.l[i]]) { el.style.left = right ? 'auto' : '110px'; el.style.right = right ? '110px' : 'auto'; el.style.textAlign = right ? 'right' : 'left'; }
        slam(S.n[i], t, a, b, { s0: 1.25, dx: right ? 70 : -70 });
        counter(S.n[i], t, a, a + 0.5, 0, it.v, Ease.outQ, it.f);
        txt(S.e[i], it.f(it.v)); echo(S.e[i], t, a, 0.25, 0.3);
        slam(S.l[i], t, a + BEAT, b, { s0: 1.05 });
      });
    };
    slash(B(56), -0.42, 1.4); flash(B(56), 3, 1); hit(B(56), 1.5); ev(B(56), 'slash', 1.4); ev(B(56), 'drop', 1.2);
    for (let k = 57; k < 72; k++) {
      if (k % 4 === 0) { hit(B(k), 1.2); ev(B(k), 'impact', 0.9); if (k === 64) { glitch(B(k) - 0.06, 0.18, 0.9); ev(B(k) - 0.06, 'glitch', 0.8); } }
      else { punch(B(k), 0.025); ev(B(k), 'hitS', 0.45); }
    }
    for (let i = 0; i < 4; i++) invert(B(71) + i * BEAT / 4, 2 / 60);
    addSlashLine(B(72), 0.38);
  }

  // ---- 10. outro (beats 72–79): mark + wordmark tracking collapse, tagline, repo, fade
  {
    const S = shot(B(72), 99, { svg: 'ov' });
    const g = s('g', { transform: 'translate(855 250)' }, S.svg);
    S.mk = [
      s('rect', { x: 0, y: 0, width: 210, height: 210, rx: 38, fill: 'none', stroke: 'url(#slg)', 'stroke-width': 16, pathLength: 1, 'stroke-dasharray': '1 1' }, g),
      s('path', { d: 'M40 160 L170 50', fill: 'none', stroke: '#FFFFFF', 'stroke-width': 12, 'stroke-linecap': 'round', pathLength: 1, 'stroke-dasharray': '1 1' }, g),
    ];
    S.w = T(S.root, `<span class="kgrad">${BRAND}</span>`, { left: '0', top: '490px', width: '1920px', textAlign: 'center', fontSize: '200px', fontFamily: 'Inter', fontWeight: 800, letterSpacing: '-0.03em', lineHeight: '1.1' }, 'k');
    S.t = T(S.root, 'Revit MCP for Claude', { left: '0', top: '735px', width: '1920px', textAlign: 'center', fontFamily: 'Inter', fontWeight: 600, fontSize: '44px', color: 'var(--ink)', lineHeight: '1.2' }, 'k');
    S.r = T(S.root, 'GITHUB.COM/SOUHAIBSMADI42/RVTSS_MCP', { left: '0', top: '830px', width: '1920px', textAlign: 'center', fontSize: '22px', letterSpacing: '.24em', color: 'var(--hot)' }, 'kmono');
    S.by = T(S.root, 'BY SUHAIB AL SMADI', { left: '0', top: '880px', width: '1920px', textAlign: 'center', fontSize: '18px', letterSpacing: '.3em' }, 'kmono');
    S.blk = h('div', null, S.root, { position: 'absolute', inset: '-200px', background: '#000', opacity: '0' });
    S.update = (t, lt) => {
      drift(S.root, lt, 1, 1.03, 0, 0, 4);
      drawOn(S.mk[0], Ease.outQ(clamp(lt / 0.4)));
      drawOn(S.mk[1], Ease.outQ(clamp((lt - 0.25) / 0.25)));
      track(S.w, t, B(72), 99, 0.5, 0.5);
      slam(S.t, t, B(74), 99, { s0: 1, fade: 0.3, dy: 12 });
      slam(S.r, t, B(75), 99, { s0: 1, fade: 0.3 });
      slam(S.by, t, B(76), 99, { s0: 1, fade: 0.3 });
      S.blk.style.opacity = Ease.inOut(clamp((t - (B(80) - 1.5)) / 1.45)).toFixed(3);
    };
    slash(B(72), 0.38, 1.2); flash(B(72), 2, 0.8); hit(B(72), 1); ev(B(72), 'slash', 1.1); ev(B(72), 'outro', 1);
    ev(B(74), 'blip', 0.4);
  }
}

export function updateScenes(t) {
  runShots(t);
  drawSlash(t);
  const ch = t < B(8) ? '00 — OPEN' : t < B(16) ? '01 — RVTSS' : t < B(32) ? '02 — WHAT IT DOES' : t < B(40) ? '03 — COORDINATION'
    : t < B(48) ? '04 — SAFETY' : t < B(56) ? '05 — SELF-TEST' : '06 — PROOF';
  const on = t >= 0.2 && !(t >= B(8) && t < B(12)) && !(t >= B(47.5) && t < B(52)) && t < B(72);
  hud(t, on ? 1 : 0, ch);
}
export function sceneEvents() { return { events: ER.slice().sort((a, b) => a.t - b.t), slashes: SLASHES.map(s => s.t) }; }
