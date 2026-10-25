// RVTSS v2.1 — 40 s vertical reel (1080×1920, 60 fps, 80 beats @ 120 BPM).
// Look: dark 3D holographic BIM plates (GPT Image 2.5) + neon type, glass tool-call cards, bloom, grain.
// Motif: "The Section Plane" — a cyan scan line sweeps the frame at every section change.
// Section map (beats): open 0–8 · reveal 8–18 · tools 18–22 · DROP features 22–38 · breakdown clash 38–46 ·
//                      tension safety 46–52 · silence 52–56 · riser 56–60 · DROP proof 60–72 · outro 72–80
// Every number on screen is a verified RVTSS v2.1 fact (README / CHANGELOG / UPGRADE_REPORT); the clash rows are labelled illustrative.
import {
  W, H, FPS, DURATION, BEAT, B, clamp, lerp, inv, Ease, fmtN, COL, DISPLAY, MONO, SANS,
  loadPlates, plate, shade, text, slam, rise, typed, rrect, glowLine, ring, glass,
  hit, punch, flash, invert, glitch, rumble, caRamp, scan, tilt, fxAt, post, fctx, FR,
} from './engine.js';

const GRAD = [COL.cyan, COL.blue, COL.violet];
const ER = [];
const ev = (t, kind, k = 1, d) => ER.push(Object.assign({ t: +t.toFixed(4), kind, k }, d ? { d } : {}));
const SHOTS = [];
const shot = (a, b, draw) => SHOTS.push({ a, b, draw });

function gradeAt(t) {
  if (t >= B(52) && t < B(56)) return { grain: 0.1, bloom: 0.3, vig: 0.6 };
  if (t >= B(38) && t < B(46)) return { grain: 0.085 };
  if (t >= B(59.75) && t < B(60)) return { black: 1 };
  if (t >= DURATION - 1.4) return { black: Ease.inOut(clamp((t - (DURATION - 1.4)) / 1.35)) };
  return {};
}

// focus reticle: four corner brackets snapping in around a point
function reticle(ctx, cx, cy, size, p, col = COL.cyan, label = '') {
  const s = lerp(size * 1.6, size, Ease.outExpo(p)), L = 34, h = s / 2;
  ctx.save(); ctx.globalAlpha = clamp(p * 3); ctx.strokeStyle = col; ctx.lineWidth = 4; ctx.shadowColor = col; ctx.shadowBlur = 16;
  for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    ctx.beginPath(); ctx.moveTo(cx + sx * h, cy + sy * (h - L)); ctx.lineTo(cx + sx * h, cy + sy * h); ctx.lineTo(cx + sx * (h - L), cy + sy * h); ctx.stroke();
  }
  ctx.restore();
  if (label) {
    ctx.save(); ctx.globalAlpha = clamp(p * 3);
    ctx.font = `700 20px ${MONO}`; ctx.letterSpacing = '3px';
    const w = ctx.measureText(label).width + 28;
    rrect(ctx, cx - h, cy - h - 52, w, 38, 6); ctx.fillStyle = col; ctx.fill();
    ctx.fillStyle = '#04060D'; ctx.textBaseline = 'middle'; ctx.fillText(label, cx - h + 14, cy - h - 32);
    ctx.restore();
  }
}

function toolCard(ctx, y, p, tool, args, result) {
  if (p <= 0) return;
  const e = Ease.outExpo(clamp(p)), x = 70, w = 940, h = 262;
  ctx.save(); ctx.translate(0, (1 - e) * 50);
  glass(ctx, x, y, w, h, { a: clamp(p * 4) });
  ctx.globalAlpha = clamp(p * 4);
  text(ctx, 'CLAUDE ▸ TOOL CALL', x + 40, y + 56, { size: 20, family: MONO, weight: 500, color: COL.dim, align: 'left', ls: 4 });
  text(ctx, tool, x + 40, y + 116, { size: 42, family: MONO, weight: 700, color: COL.ink, align: 'left', maxW: w - 80 });
  text(ctx, args, x + 40, y + 164, { size: 25, family: MONO, weight: 500, color: '#9AA6D0', align: 'left', maxW: w - 80 });
  rrect(ctx, x + 40, y + 192, 250, 42, 8); ctx.fillStyle = 'rgba(41,224,255,.15)'; ctx.fill();
  text(ctx, 'STATUS · SUCCESS', x + 58, y + 220, { size: 18, family: MONO, weight: 700, color: COL.cyan, align: 'left', ls: 3 });
  text(ctx, result, x + 312, y + 220, { size: 20, family: MONO, weight: 500, color: COL.dim, align: 'left', ls: 1 });
  ctx.restore();
}

function hud(ctx, t, chapter) {
  ctx.save();
  ctx.strokeStyle = 'rgba(238,243,255,.5)'; ctx.lineWidth = 2;
  for (const [x, y, sx, sy] of [[48, 92, 1, 1], [1032, 92, -1, 1], [48, 1872, 1, -1], [1032, 1872, -1, -1]]) {
    ctx.beginPath(); ctx.moveTo(x, y + sy * 26); ctx.lineTo(x, y); ctx.lineTo(x + sx * 26, y); ctx.stroke();
  }
  ctx.restore();
  text(ctx, 'RVTSS ▸ REVIT MCP', 84, 124, { size: 19, family: MONO, weight: 500, color: COL.ink, align: 'left', ls: 3 });
  const f = Math.floor(t * FPS + 1e-6), ss = Math.floor(f / FPS), ff = f % FPS;
  text(ctx, `TC 00:00:${String(ss).padStart(2, '0')}:${String(ff).padStart(2, '0')}`, 996, 124, { size: 19, family: MONO, weight: 500, color: COL.dim, align: 'right', ls: 3 });
  text(ctx, chapter, 84, 158, { size: 17, family: MONO, weight: 500, color: COL.cyan, align: 'left', ls: 3 });
  fctx.fillStyle = 'rgba(238,243,255,.18)'; fctx.fillRect(84, 174, 150, 2);
  fctx.fillStyle = COL.cyan; fctx.fillRect(84, 174, 150 * t / DURATION, 2);
}

// diagonal light sweep across the frame (additive)
function sweep(ctx, p, a = 0.3, w = 380) {
  if (p <= 0 || p >= 1) return;
  const x = lerp(-w * 2, W + w * 2, Ease.inOut(p));
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = a;
  ctx.translate(x, H / 2); ctx.rotate(-0.42);
  const g = ctx.createLinearGradient(-w, 0, w, 0);
  g.addColorStop(0, 'rgba(41,224,255,0)'); g.addColorStop(0.5, 'rgba(160,240,255,.9)'); g.addColorStop(1, 'rgba(139,92,255,0)');
  ctx.fillStyle = g; ctx.fillRect(-w, -H * 1.5, 2 * w, H * 3);
  ctx.restore();
}
function radialDark(ctx, a = 0.6, r0 = 120, r1 = 760, cy = H / 2) {
  const g = ctx.createRadialGradient(W / 2, cy, r0, W / 2, cy, r1);
  g.addColorStop(0, `rgba(4,6,13,${a})`); g.addColorStop(1, 'rgba(4,6,13,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
}

function initScenes() {
  // ---- 1. cold open (beats 0–8): near black, plate glimpses on the kicks, staccato words, strobe + riser
  {
    const words = [['YOUR', 2, 3, 250], ['REVIT MODEL', 3, 5, 200], ['NOW TALKS', 5, 6, 220], ['TO CLAUDE.', 6, 7.75, 220]];
    shot(0, B(8), (ctx, t, lt) => {
      let br = 0.1 * Ease.out(clamp(lt / 3));
      for (const k of [2, 3, 5, 6]) if (t >= B(k)) br = Math.max(br, 0.55 * Math.exp(-(t - B(k)) * 7));
      plate(ctx, 'hero', { z: lerp(1.28, 1.18, lt / 4), fy: 0.52, br, sat: 0.9 });
      radialDark(ctx, 0.55, 80, 700, 980);
      if (t < B(2)) {
        const w = 40 + 820 * Ease.outQ(clamp(lt / 0.95));
        glowLine(ctx, W / 2 - w / 2, 960, W / 2 + w / 2, 960, COL.cyan, 2, 14, 0.9);
        text(ctx, typed('PYREVIT ROUTES ▸ :48884 ▸ MCP', t, B(0.5), BEAT / 8), W / 2, 1020, { size: 24, family: MONO, weight: 500, color: COL.dim, ls: 5 });
      }
      for (const [w, a, b, size] of words) {
        const s = slam(t, B(a), B(b), { s0: 1.25, d: 0.18 }); if (!s) continue;
        const g = w === 'TO CLAUDE.';
        text(ctx, w, W / 2, 1040, { size, maxW: 960, sc: s.sc, grad: g ? GRAD : null, glow: g ? 40 : 18, glowColor: g ? COL.cyan : 'rgba(150,200,255,.6)' });
      }
    });
    ev(B(0.5), 'type', 0.5);
    [2, 3, 5, 6].forEach(k => { hit(B(k), 0.7); ev(B(k), 'hitS', 0.75); });
    for (let i = 0; i < 4; i++) invert(B(7) + i * BEAT / 4, 2 / 60);
    rumble(B(7), BEAT, 1.2); caRamp(B(7), BEAT, 1); ev(B(6), 'riser', 1, 2 * BEAT);
  }

  // ---- 2. reveal (beats 8–18): the model appears, light sweep, RVTSS lockup
  {
    shot(B(8), B(18), (ctx, t, lt) => {
      plate(ctx, 'hero', { z: lerp(1.42, 1.06, Ease.out(clamp(lt / 5))), fy: 0.56, dy: lerp(60, 0, Ease.out(clamp(lt / 5))), br: 1.06 });
      sweep(ctx, inv(t, B(8.5), B(11)), 0.28);
      sweep(ctx, inv(t, B(15), B(17.5)), 0.2);
      shade(ctx, 0.92, 0.55, 0.0);
      radialDark(ctx, 0.7 * clamp((t - B(9.5)) / 0.4), 40, 520, 520);
      // wordmark: tracking collapse, never letter by letter
      if (t >= B(10)) {
        const p = Ease.outExpo(clamp((t - B(10)) / 0.55));
        text(ctx, 'RVTSS', W / 2, 470, { size: 270, ls: lerp(90, -4, p), grad: GRAD, glow: 46, glowColor: 'rgba(41,224,255,.85)', sc: lerp(1.06, 1, p) });
      } else {
        text(ctx, typed('LIVE REVIT MODEL ▸ CONNECTED', t, B(8.5), BEAT / 8), W / 2, 440, { size: 26, family: MONO, weight: 500, color: COL.cyan, ls: 5 });
      }
      const s1 = slam(t, B(12), B(18), { s0: 1.06, dy: 14, fade: 0.25 });
      if (s1) text(ctx, 'REVIT MCP FOR CLAUDE', W / 2, 568 + s1.dy, { size: 40, family: SANS, weight: 700, color: COL.ink, ls: 12, alpha: s1.a });
      const s2 = slam(t, B(14), B(18), { s0: 1, fade: 0.3 });
      if (s2) text(ctx, 'BY SUHAIB AL SMADI  ·  V2.1', W / 2, 628, { size: 24, family: MONO, weight: 700, color: '#C9D3F5', ls: 6, alpha: s2.a });
    });
    scan(B(8), 0.34); flash(B(8), 3, 1); hit(B(8), 1.3); ev(B(8), 'drop', 1.1); ev(B(8), 'scan', 1.1);
    hit(B(10), 1); ev(B(10), 'impact', 0.9);
    [12, 14, 16].forEach(k => { punch(B(k), 0.025); ev(B(k), 'blip', 0.5); });
    glitch(B(17.75) - 0.04, 0.14, 0.8); ev(B(17.75) - 0.04, 'glitch', 0.6);
  }

  // ---- 3. proof number (beats 18–22): 77 tools, the structure tunnel spinning behind
  {
    shot(B(18), B(22), (ctx, t, lt) => {
      plate(ctx, 'tunnel', { z: lerp(1.15, 1.45, lt / 2), rot: lt * 0.08, br: 0.8 });
      radialDark(ctx, 0.82, 60, 620, 1000);
      const p = clamp((t - B(18)) / 0.6), n = Math.round(77 * Ease.outQ(p));
      const pulse = 1 + 0.04 * (1 - clamp(((t - B(18)) % BEAT) / 0.3));
      const s = slam(t, B(18), B(22), { s0: 1.22 });
      text(ctx, String(n), W / 2, 1140, { size: 560, sc: s.sc * pulse, color: COL.ink, glow: 50, glowColor: 'rgba(41,224,255,.8)' });
      if (t - B(18) < 0.26) text(ctx, '77', W / 2, 1140, { size: 560, sc: 1 + 0.3 * (t - B(18)) / 0.26, stroke: 3, color: COL.cyan, alpha: 0.7 * (1 - (t - B(18)) / 0.26) });
      text(ctx, 'RVTSS V2.1', W / 2, 640, { size: 24, family: MONO, weight: 500, color: COL.dim, ls: 8, alpha: clamp((t - B(18.5)) / 0.15) });
      const l = slam(t, B(19), B(22), { s0: 1.05 });
      if (l) text(ctx, 'TOOLS  ·  10 TOOLSETS  ·  7 PROMPTS', W / 2, 1250, { size: 28, family: MONO, weight: 700, color: COL.cyan, ls: 5, sc: l.sc, maxW: 940 });
    });
    scan(B(18), 0.3); hit(B(18), 1.1); flash(B(18), 2, 0.8); ev(B(18), 'impact', 1); ev(B(18), 'scan', 0.8);
    for (let k = 19; k < 22; k++) { punch(B(k), 0.025); ev(B(k), 'tick', 0.5); }
    rumble(B(21), BEAT, 0.9); ev(B(21), 'riser', 0.8, BEAT);
  }

  // ---- 4. DROP: what it does (beats 22–38), one feature per 2 beats, real tool calls
  {
    const items = [
      ['INSPECT.', 'hero2', { z: 1.55, fy: 0.62 }, 'DOORS · LEVEL 2', 'find_elements', '{categories: ["Doors"], level: "Level 2"}', '→ ids · counts'],
      ['EDIT.', 'section', { z: 1.4, fy: 0.5 }, 'DRY RUN', 'set_parameters', '{dry_run: true, unit: "mm"}', '→ before / after'],
      ['FAMILIES.', 'family', { z: 1.08, fx: 0.62, fy: 0.62 }, 'W 900 · D 600 · H 750', 'family_build_parametric_box', '{width: 900, depth: 600, height: 750}', '→ flex test passed'],
      ['PARAMETERS.', 'family2', { z: 1.45, fx: 0.32, fy: 0.6 }, 'SHARED · BIND', 'shared_parameters', '{action: "bind", categories: ["Doors"]}', '→ GUIDs kept'],
      ['CLASHES.', 'clash', { z: 1.3, fx: 0.514, fy: 0.4375 }, 'HARD CLASH', 'check_clashes', '{clearance: 50, group_by: ["grid_zone"]}', '→ hard + clearance'],
      ['ISO 19650.', 'section2', { z: 1.3, fy: 0.42 }, 'NAMING · VIEWS', 'run_model_checks', '{checks: ["iso19650", "view_audit"]}', '→ field by field'],
      ['EXCEL.', 'tunnel2', { z: 1.25, fy: 0.42 }, '.XLSX', 'export_to_excel', '{categories: ["Doors"], parameters: [...]}', '→ units in headers'],
      ['IFC / COBIE.', 'outro', { z: 1.75, fy: 0.84 }, 'MAPPING PRESET', 'map_parameters', '{preset: "cobie_type", dry_run: true}', '→ presets'],
    ];
    shot(B(22), B(38), (ctx, t) => {
      const i = clamp(Math.floor((t - B(22)) / (2 * BEAT)), 0, items.length - 1);
      const [word, pl, po, tag, tool, args, res] = items[i];
      const a = B(22 + 2 * i), b = B(24 + 2 * i), lt = t - a, right = i % 2 === 1;
      plate(ctx, pl, { ...po, z: po.z * (1 + 0.06 * lt), br: 1.0 });
      shade(ctx, 0.9, 0.85, 0.15);
      const red = word === 'CLASHES.', col = red ? COL.red : COL.cyan;
      if (red) for (let r = 0; r < 2; r++) { const q = ((lt + r * BEAT) % (2 * BEAT)) / (2 * BEAT); ring(ctx, W / 2, 960, 30 + 170 * q, COL.red, 3, 1 - q, 24); }
      reticle(ctx, W / 2, 960, 300, clamp((t - a - 0.06) / 0.3), col, tag);
      text(ctx, `0${i + 1} / 08`, right ? 1010 : 70, 300, { size: 24, family: MONO, weight: 700, color: col, align: right ? 'right' : 'left', ls: 6 });
      const s = slam(t, a, b, { s0: 1.28, dx: right ? 70 : -70, d: 0.2 });
      text(ctx, word, (right ? 1010 : 70) + s.dx, 470, { size: 200, maxW: 940, align: right ? 'right' : 'left', sc: s.sc, color: COL.ink, grad: word === 'EXCEL.' ? GRAD : null, glow: 24, glowColor: 'rgba(41,224,255,.55)' });
      toolCard(ctx, 1190, (t - a - BEAT / 2) / 0.3, tool, args, res);
    });
    scan(B(22), 0.3); flash(B(22), 2, 1); hit(B(22), 1.4); ev(B(22), 'drop', 1.1); ev(B(22), 'scan', 1);
    for (let i = 0; i < items.length; i++) {
      const k = 22 + 2 * i;
      if (i) { hit(B(k), 1.05); ev(B(k), 'impact', 0.75); }
      punch(B(k + 0.5), 0.02); ev(B(k + 0.5), 'blip', 0.45);
      punch(B(k + 1), 0.03); ev(B(k + 1), 'hitS', 0.4);
      if (i % 3 === 2) { glitch(B(k) - 0.05, 0.15, 0.85); ev(B(k) - 0.05, 'glitch', 0.65); }
    }
    ev(B(37.5), 'whoosh', 0.9);
  }

  // ---- 5. breakdown (beats 38–46): one slow push into the clash, text rising, report rows
  {
    const rows = [['A-B/1-2', 'L2', 'DUCT × FRAMING', 'HARD', '0'], ['A-B/1-2', 'L2', 'PIPE × FRAMING', 'CLEAR', '32 mm'], ['B-C/2-3', 'L3', 'DUCT × COLUMN', 'CLEAR', '41 mm']];
    shot(B(38), B(46), (ctx, t, lt) => {
      const z = lerp(1.12, 1.5, Ease.sine(clamp(lt / 4)));
      const pr = plate(ctx, 'clash', { z, fx: 0.514, fy: 0.4375, br: 1.0 });
      const mx = pr.x + 0.514 * 1152 * pr.s, my = pr.y + 0.4375 * 2048 * pr.s;
      shade(ctx, 0.92, 0.9, 0.1);
      for (let r = 0; r < 3; r++) { const q = ((lt + r * BEAT * 0.67) % (2 * BEAT)) / (2 * BEAT); ring(ctx, mx, my, 24 + 220 * q, COL.red, 3, 0.9 * (1 - q), 26); }
      rise(ctx, t, B(38), 'EVERY CLASH,', W / 2, 360, { size: 140, maxW: 940, color: COL.ink, glow: 18, glowColor: 'rgba(255,61,113,.5)' });
      rise(ctx, t, B(40), 'LOCATED.', W / 2, 510, { size: 140, maxW: 940, grad: [COL.red, COL.amber], glow: 30, glowColor: 'rgba(255,61,113,.8)' });
      if (t >= B(42)) {
        const p = Ease.outQ(clamp((t - B(42)) / 0.35));
        ctx.save(); ctx.globalAlpha = p; ctx.setLineDash([8, 8]); ctx.strokeStyle = 'rgba(255,61,113,.8)'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(mx, my + 30); ctx.lineTo(mx, lerp(my + 30, 1196, p)); ctx.stroke(); ctx.restore();
        ctx.save(); ctx.globalAlpha = p; rrect(ctx, 120, 1196, 840, 50, 25); ctx.fillStyle = 'rgba(4,6,13,.85)'; ctx.fill();
        ctx.strokeStyle = 'rgba(255,61,113,.7)'; ctx.lineWidth = 1.5; ctx.stroke(); ctx.restore();
        text(ctx, typed('GRID ZONE A-B/1-2 · NEAREST B/2 · LEVEL 2', t, B(42), BEAT / 10), W / 2, 1230, { size: 24, family: MONO, weight: 700, color: COL.ink, ls: 2, maxW: 800 });
      }
      const cp = clamp((t - B(38.5)) / 0.4);
      if (cp > 0) {
        const y = 1272 + (1 - Ease.outExpo(cp)) * 40;
        glass(ctx, 70, y, 940, 270, { a: cp });
        text(ctx, 'EXPORT_CLASH_REPORT ▸ CSV + HTML', 110, y + 52, { size: 18, family: MONO, weight: 500, color: COL.dim, align: 'left', ls: 3, alpha: cp });
        text(ctx, 'ILLUSTRATIVE DATA', 970, y + 52, { size: 18, family: MONO, weight: 700, color: COL.amber, align: 'right', ls: 3, alpha: cp });
        rows.forEach((r, i) => {
          const o = clamp((t - B(39 + i)) / 0.15) * cp; if (o <= 0) return;
          const yy = y + 112 + i * 56;
          fctx.fillStyle = `rgba(42,48,72,${o})`; fctx.fillRect(110, yy - 38, 860, 1);
          text(ctx, r[0], 110, yy, { size: 22, family: MONO, weight: 700, color: COL.cyan, align: 'left', alpha: o });
          text(ctx, r[1], 290, yy, { size: 22, family: MONO, weight: 500, color: '#C9CEE6', align: 'left', alpha: o });
          text(ctx, r[2], 360, yy, { size: 22, family: MONO, weight: 500, color: '#C9CEE6', align: 'left', alpha: o });
          text(ctx, r[3], 750, yy, { size: 22, family: MONO, weight: 700, color: r[3] === 'HARD' ? COL.red : COL.amber, align: 'left', alpha: o });
          text(ctx, r[4], 970, yy, { size: 22, family: MONO, weight: 500, color: '#C9CEE6', align: 'right', alpha: o });
        });
      }
    });
    ev(B(38), 'swell', 0.9);
    for (let i = 0; i < 3; i++) ev(B(39 + i), 'tick', 0.35);
    ev(B(42), 'type', 0.4); ev(B(40), 'blip', 0.5);
  }

  // ---- 6. tension (beats 46–52): the safety model, one word per 2 beats
  {
    const items = [['DRY RUN.', 'REVIT VALIDATES, THEN ROLLS BACK'], ['CONFIRM.', 'PREVIEW FIRST · YOU APPROVE'], ['UNDO.', 'ONE NAMED TRANSACTION PER CHANGE']];
    shot(B(46), B(52), (ctx, t, lt) => {
      plate(ctx, 'section', { z: lerp(1.08, 1.2, lt / 3), fy: 0.48, br: 0.42, sat: 0.6 });
      radialDark(ctx, 0.7, 80, 760, 1000);
      // a section plane breathing through the frame
      const py = lerp(1500, 520, Ease.inOut(clamp(lt / 3)));
      glowLine(ctx, 0, py, W, py, COL.violet, 2, 26, 0.55);
      text(ctx, 'SAFE BY DEFAULT', W / 2, 640, { size: 24, family: MONO, weight: 700, color: COL.violet, ls: 8 });
      items.forEach(([w, c], i) => {
        const a = B(46 + 2 * i), b = B(48 + 2 * i);
        const s = slam(t, a, b, { s0: 1.22, d: 0.2 }); if (!s) return;
        if (t - a < 0.25) text(ctx, w, W / 2, 1060, { size: 230, maxW: 960, stroke: 3, color: COL.violet, sc: 1 + 0.3 * (t - a) / 0.25, alpha: 0.7 * (1 - (t - a) / 0.25) });
        text(ctx, w, W / 2, 1060, { size: 230, maxW: 960, sc: s.sc, color: COL.ink, glow: 30, glowColor: 'rgba(139,92,255,.75)' });
        const sc = slam(t, a + BEAT / 2, b, { s0: 1.04 });
        if (sc) text(ctx, c, W / 2, 1160, { size: 26, family: MONO, weight: 500, color: COL.dim, ls: 4, sc: sc.sc, maxW: 940 });
      });
    });
    scan(B(46), 0.32, -1, COL.violet); ev(B(46), 'scan', 0.7);
    for (let i = 0; i < 3; i++) { hit(B(46 + 2 * i), 0.8); ev(B(46 + 2 * i), 'hitS', 0.85); punch(B(47 + 2 * i), 0.015); ev(B(47 + 2 * i), 'click', 0.5); }
    invert(B(50), 2 / 60); invert(B(50) + 4 / 60, 2 / 60);
    ev(B(51), 'whooshL', 0.6);
  }

  // ---- 7. silence (beats 52–56): one calm sentence
  {
    shot(B(52), B(56), (ctx, t, lt) => {
      plate(ctx, 'outro', { z: lerp(1.0, 1.05, lt / 2), br: 0.32, a: Ease.out(clamp(lt / 1.2)) });
      text(ctx, 'Built by a BIM coordinator,', W / 2, 900, { size: 64, family: SANS, weight: 600, color: COL.ink, alpha: Ease.out(clamp(lt / 0.5)), maxW: 940 });
      text(ctx, 'for BIM coordinators.', W / 2, 990, { size: 64, family: SANS, weight: 600, color: COL.dim, alpha: Ease.out(clamp((t - B(53)) / 0.5)), maxW: 940 });
    });
  }

  // ---- 8. riser (beats 56–60): self-test charging, strobes, black on the last eighth
  {
    shot(B(56), B(59.75), (ctx, t, lt) => {
      plate(ctx, 'tunnel', { z: lerp(1.7, 1.2, Ease.in(clamp(lt / 1.875))), rot: -lt * 0.3, br: lerp(0.05, 0.6, Ease.in(clamp(lt / 1.875))) });
      radialDark(ctx, 0.7, 60, 640, 960);
      text(ctx, typed('RUN SELF-TEST ▸ RVTSS_LIVE_REPORT.MD', t, B(56), BEAT / 10), W / 2, 920, { size: 26, family: MONO, weight: 700, color: COL.ink, ls: 3, maxW: 940 });
      const p = Ease.in(clamp(lt / 1.875)), bw = 820;
      fctx.fillStyle = 'rgba(238,243,255,.12)'; fctx.fillRect(W / 2 - bw / 2, 970, bw, 6);
      glowLine(ctx, W / 2 - bw / 2, 973, W / 2 - bw / 2 + Math.max(2, bw * p), 973, COL.cyan, 6, 24, 1);
      text(ctx, `${Math.round(p * 100)}%`, W / 2, 1050, { size: 34, family: MONO, weight: 700, color: COL.cyan, ls: 4 });
    });
    ev(B(56), 'riser', 1.2, 4 * BEAT); ev(B(56), 'type', 0.4);
    rumble(B(58), 2 * BEAT, 1.4); caRamp(B(58), 2 * BEAT, 1.2);
    for (let i = 0; i < 5; i++) invert(B(58.5) + i * BEAT / 4, 2 / 60);
  }

  // ---- 9. DROP proof (beats 60–72): verified numbers, one per 3 beats
  {
    const items = [
      { v: 245, f: v => String(Math.round(v)), l: 'UNIT TESTS PASSING', pl: 'tunnel2', po: { z: 1.3 }, rot: 0.06 },
      { v: 40, f: v => '−' + Math.round(v) + '%', l: 'TOOL CONTEXT VS V2.0', pl: 'hero', po: { z: 1.3, fy: 0.5 } },
      { v: 16, f: v => String(Math.round(v)), l: 'MODEL QC CHECKS', pl: 'section', po: { z: 1.25, fy: 0.45 } },
      { v: 1, f: () => '2021–27', l: 'REVIT VERSIONS SUPPORTED', pl: 'hero2', po: { z: 1.15, fy: 0.55 } },
    ];
    shot(B(60), B(72), (ctx, t) => {
      const i = clamp(Math.floor((t - B(60)) / (3 * BEAT)), 0, 3), it = items[i];
      const a = B(60 + 3 * i), b = B(63 + 3 * i), lt = t - a;
      plate(ctx, it.pl, { ...it.po, z: it.po.z * (1 + 0.08 * lt), rot: (it.rot || 0) * lt, br: 0.75 });
      radialDark(ctx, 0.75, 60, 700, 1000);
      shade(ctx, 0.6, 0.6, 0);
      const s = slam(t, a, b, { s0: 1.25 });
      const str = it.f(it.v * Ease.outQ(clamp(lt / 0.5)));
      if (lt < 0.26) text(ctx, it.f(it.v), W / 2, 1110, { size: 400, maxW: 960, stroke: 3, color: COL.cyan, sc: 1 + 0.3 * lt / 0.26, alpha: 0.7 * (1 - lt / 0.26) });
      text(ctx, str, W / 2, 1110, { size: 400, maxW: 960, sc: s.sc, grad: i === 1 ? GRAD : null, color: COL.ink, glow: 44, glowColor: 'rgba(41,224,255,.8)' });
      const l = slam(t, a + BEAT, b, { s0: 1.05 });
      if (l) text(ctx, it.l, W / 2, 1230, { size: 30, family: MONO, weight: 700, color: COL.cyan, ls: 6, sc: l.sc, maxW: 940 });
      text(ctx, `0${i + 1} / 04  ·  VERIFIED`, W / 2, 640, { size: 22, family: MONO, weight: 500, color: COL.dim, ls: 6 });
    });
    scan(B(60), 0.3); flash(B(60), 3, 1); hit(B(60), 1.5); ev(B(60), 'drop', 1.25); ev(B(60), 'scan', 1.2);
    for (let k = 61; k < 72; k++) {
      if ((k - 60) % 3 === 0) { hit(B(k), 1.2); ev(B(k), 'impact', 0.9); if (k === 66) { glitch(B(k) - 0.05, 0.16, 0.9); ev(B(k) - 0.05, 'glitch', 0.7); } }
      else { punch(B(k), 0.025); ev(B(k), 'hitS', 0.45); }
    }
    for (let i = 0; i < 4; i++) invert(B(71) + i * BEAT / 4, 2 / 60);
    ev(B(71), 'riser', 0.7, BEAT);
  }

  // ---- 10. outro (beats 72–80): lockup, tagline, repo, fade
  {
    shot(B(72), 99, (ctx, t, lt) => {
      plate(ctx, 'outro', { z: lerp(1.14, 1.0, Ease.out(clamp(lt / 4))), br: lerp(1.3, 1.0, clamp(lt / 1.5)) });
      sweep(ctx, inv(t, B(73), B(76)), 0.18);
      const p = Ease.outExpo(clamp(lt / 0.6));
      text(ctx, 'RVTSS', W / 2, 640, { size: 270, ls: lerp(90, -4, p), grad: GRAD, glow: 50, glowColor: 'rgba(41,224,255,.9)', sc: lerp(1.05, 1, p) });
      const s1 = slam(t, B(74), 99, { s0: 1, fade: 0.35, dy: 14 });
      if (s1) text(ctx, 'Revit MCP for Claude', W / 2, 750 + s1.dy, { size: 58, family: SANS, weight: 600, color: COL.ink, alpha: s1.a });
      const s2 = slam(t, B(75), 99, { s0: 1, fade: 0.35 });
      if (s2) text(ctx, 'GITHUB.COM/SOUHAIBSMADI42/RVTSS_MCP', W / 2, 840, { size: 24, family: MONO, weight: 700, color: COL.cyan, ls: 3, alpha: s2.a, maxW: 940 });
      const s3 = slam(t, B(76), 99, { s0: 1, fade: 0.35 });
      if (s3) text(ctx, 'BY SUHAIB AL SMADI', W / 2, 892, { size: 22, family: MONO, weight: 500, color: COL.dim, ls: 8, alpha: s3.a });
    });
    scan(B(72), 0.34); flash(B(72), 2, 0.85); hit(B(72), 1); ev(B(72), 'scan', 1); ev(B(72), 'outro', 1);
    ev(B(74), 'blip', 0.35);
  }
}

function draw(t) {
  fctx.save(); fctx.fillStyle = COL.bg; fctx.fillRect(0, 0, W, H); fctx.restore();
  for (const s of SHOTS) if (t >= s.a && t < s.b) { fctx.save(); s.draw(fctx, t, t - s.a); fctx.restore(); }
  const ch = t < B(8) ? '00 — OPEN' : t < B(22) ? '01 — RVTSS' : t < B(38) ? '02 — WHAT IT DOES' : t < B(46) ? '03 — COORDINATION' : t < B(52) ? '04 — SAFETY' : t < B(60) ? '05 — SELF-TEST' : '06 — PROOF';
  if (t >= 0.2 && !(t >= B(10) && t < B(18)) && !(t >= B(52) && t < B(56)) && t < B(72)) hud(fctx, t, ch);
}

window.renderFrame = (f, fmt = 'jpeg') => {
  const t = f / FPS;
  draw(t);
  post(fxAt(t, gradeAt(t)), f);
  return fmt === 'none' ? true : document.getElementById('out').toDataURL(fmt === 'png' ? 'image/png' : 'image/jpeg', 0.95);
};
window.ready = (async () => {
  await Promise.all([`900 100px ${DISPLAY}`, `500 40px ${MONO}`, `700 40px ${MONO}`, `600 40px ${SANS}`, `700 40px ${SANS}`].map(f => document.fonts.load(f)));
  await loadPlates(['hero', 'hero2', 'clash', 'family', 'family2', 'section', 'section2', 'tunnel', 'tunnel2', 'outro']);
  initScenes();
  window.EVENTS = ER.slice().sort((a, b) => a.t - b.t);
  window.renderFrame(0, 'none');
  return { frames: Math.round(DURATION * FPS), fps: FPS, w: W, h: H };
})();
const q = new URLSearchParams(location.search);
if (q.has('t')) window.ready.then(() => window.renderFrame(Math.round(parseFloat(q.get('t')) * FPS), 'none'));
