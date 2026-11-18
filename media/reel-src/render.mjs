// Frame-exact renderer for the reel page. The page draws frame f on demand (window.renderFrame); we grab it as JPEG
// and pipe it into ffmpeg. Workers split the frame range; segments are joined with stream copy.
//   node render.mjs stills 1.5 7 12.8            -> out/stills/t_01.500.png ...
//   node render.mjs video [--workers 4] [--from s] [--to s] [--crf 16] [--name x.mp4]
//   node render.mjs events                       -> build/events.json (audio cue list)
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');   // the machine's pre-installed Playwright

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(ROOT, 'out');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.jpg': 'image/jpeg', '.png': 'image/png', '.json': 'application/json' };

function serve() {
  return new Promise(res => {
    const srv = http.createServer((req, rsp) => {
      const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
      if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { rsp.writeHead(404); rsp.end(); return; }
      rsp.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
      fs.createReadStream(p).pipe(rsp);
    });
    srv.listen(0, '127.0.0.1', () => res(srv));
  });
}

async function openPage(browser, port) {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  page.on('console', m => { if (m.type() === 'error') console.log('[page]', m.text()); });
  await page.goto(`http://127.0.0.1:${port}/src/index.html?render=1`, { waitUntil: 'load' });
  const info = await page.evaluate(() => window.ready);
  return { page, info };
}

function args() {
  const a = process.argv.slice(3), o = { list: [] };
  for (let i = 0; i < a.length; i++) { if (a[i].startsWith('--')) { o[a[i].slice(2)] = a[i + 1]; i++; } else o.list.push(parseFloat(a[i])); }
  return o;
}

const browser = await chromium.launch({ args: ['--disable-gpu-vsync', '--ignore-gpu-blocklist', '--font-render-hinting=none'] });
const srv = await serve();
const port = srv.address().port;
const mode = process.argv[2], o = args();

if (mode === 'stills') {
  const { page, info } = await openPage(browser, port);
  fs.mkdirSync(path.join(OUT, 'stills'), { recursive: true });
  for (const t of o.list) {
    const t0 = Date.now();
    const url = await page.evaluate(f => window.renderFrame(f, 'png'), Math.round(t * info.fps));
    const f = path.join(OUT, 'stills', `t_${t.toFixed(3).padStart(6, '0')}.png`);
    fs.writeFileSync(f, Buffer.from(url.split(',')[1], 'base64'));
    console.log(f, `${Date.now() - t0} ms`);
  }
} else if (mode === 'events') {
  const { page } = await openPage(browser, port);
  const ev = await page.evaluate(() => window.EVENTS);
  fs.mkdirSync(path.join(ROOT, 'build'), { recursive: true });
  fs.writeFileSync(path.join(ROOT, 'build', 'events.json'), JSON.stringify(ev, null, 1));
  console.log('events', ev.length);
} else if (mode === 'video') {
  const workers = parseInt(o.workers || '4'), crf = String(o.crf || '16');
  const probe = await openPage(browser, port); const { fps, frames } = probe.info; await probe.page.close();
  const F0 = Math.round(parseFloat(o.from || '0') * fps), F1 = o.to ? Math.round(parseFloat(o.to) * fps) : frames;
  const segDir = path.join(OUT, 'segments'); fs.rmSync(segDir, { recursive: true, force: true }); fs.mkdirSync(segDir, { recursive: true });
  const per = Math.ceil((F1 - F0) / workers), T = Date.now();
  const jobs = [];
  for (let w = 0; w < workers; w++) {
    const a = F0 + w * per, b = Math.min(F1, a + per); if (a >= b) break;
    const file = path.join(segDir, `seg_${w}.mp4`);
    jobs.push((async () => {
      const { page } = await openPage(browser, port);
      const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
        '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', crf,
        '-tune', 'film', '-profile:v', 'high', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
        '-x264-params', `keyint=${fps * 2}:min-keyint=${fps}`, '-r', String(fps), file], { stdio: ['pipe', 'inherit', 'inherit'] });
      const done = new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error('ffmpeg ' + c)))));
      const t0 = Date.now();
      for (let f = a; f < b; f++) {
        const url = await page.evaluate(n => window.renderFrame(n), f);
        if (!ff.stdin.write(Buffer.from(url.slice(url.indexOf(',') + 1), 'base64'))) await new Promise(r => ff.stdin.once('drain', r));
        if ((f - a) % 240 === 0) console.log(`  [w${w}] frame ${f}/${b} (${((f - a + 1) / ((Date.now() - t0) / 1000)).toFixed(1)} fps)`);
      }
      ff.stdin.end(); await done; await page.close();
      return file;
    })());
  }
  const files = await Promise.all(jobs);
  const list = path.join(segDir, 'list.txt');
  fs.writeFileSync(list, files.map(f => `file '${f}'`).join('\n'));
  const out = path.join(OUT, o.name || 'video_noaudio.mp4');
  await new Promise((res, rej) => spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', out], { stdio: 'inherit' })
    .on('close', c => (c === 0 ? res() : rej(new Error('concat ' + c)))));
  console.log(`done ${out} in ${((Date.now() - T) / 60000).toFixed(1)} min`);
} else console.log('usage: node render.mjs stills <t...> | video [--workers n] | events');

await browser.close(); srv.close();
