// Render the reel frames (1080x1920) with headless Chromium and pipe them to ffmpeg.
//   node render.mjs preview 12.5 40 ...          -> stills in ./build/preview_<t>.png
//   node render.mjs video [--fps 30] [--workers 4] -> ./build/video_noaudio.mp4
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.dirname(fileURLToPath(import.meta.url));
const BUILD = path.join(DIR, 'build');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json' };

function serve() {
  return new Promise(res => {
    const srv = createServer(async (req, rep) => {
      try {
        const p = path.join(DIR, decodeURIComponent(new URL(req.url, 'http://x').pathname));
        const body = await readFile(p.endsWith('/') ? p + 'index.html' : p);
        rep.writeHead(200, { 'content-type': TYPES[path.extname(p)] || 'application/octet-stream' });
        rep.end(body);
      } catch { rep.writeHead(404); rep.end(); }
    }).listen(0, '127.0.0.1', () => res(srv));
  });
}

async function openPage(browser, port) {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => console.error('pageerror', e.message));
  await page.goto(`http://127.0.0.1:${port}/index.html`);
  await page.waitForFunction(() => window.READY || window.BOOT_ERROR, null, { timeout: 30000 });
  const err = await page.evaluate(() => window.BOOT_ERROR);
  if (err) throw new Error(err);
  await page.evaluate(() => document.fonts.ready);
  return page;
}

async function renderChunk(browser, port, fps, f0, f1, out) {
  const page = await openPage(browser, port);
  const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', String(fps), out], { stdio: ['pipe', 'inherit', 'inherit'] });
  for (let f = f0; f < f1; f++) {
    await page.evaluate(t => window.renderAt(t), f / fps);
    const buf = await page.screenshot({ type: 'jpeg', quality: 94 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if ((f - f0) % 300 === 0) console.log(`${path.basename(out)}: ${f - f0}/${f1 - f0}`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await page.close();
}

const [mode, ...rest] = process.argv.slice(2);
await mkdir(BUILD, { recursive: true });
const srv = await serve();
const port = srv.address().port;
const browser = await chromium.launch();
try {
  if (mode === 'preview') {
    const page = await openPage(browser, port);
    for (const t of rest.map(Number)) {
      await page.evaluate(t => window.renderAt(t), t);
      await page.screenshot({ path: path.join(BUILD, `preview_${t.toFixed(1).padStart(6, '0')}.png`) });
    }
  } else if (mode === 'video') {
    const arg = (k, d) => { const i = rest.indexOf(k); return i >= 0 ? Number(rest[i + 1]) : d; };
    const fps = arg('--fps', 30), workers = arg('--workers', 4);
    const page = await openPage(browser, port);
    const total = await page.evaluate(() => window.TOTAL);
    await page.close();
    const N = Math.ceil(total * fps), per = Math.ceil(N / workers);
    const parts = [];
    await Promise.all(Array.from({ length: workers }, (_, w) => {
      const out = path.join(BUILD, `part${w}.mp4`); parts.push(out);
      return renderChunk(browser, port, fps, w * per, Math.min(N, (w + 1) * per), out);
    }));
    const list = path.join(BUILD, 'parts.txt');
    await (await import('node:fs/promises')).writeFile(list, parts.map(p => `file '${p}'`).join('\n'));
    await new Promise((res, rej) => spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', path.join(BUILD, 'video_noaudio.mp4')], { stdio: 'inherit' })
      .on('close', c => c ? rej(new Error('concat failed')) : res()));
    console.log('frames', N, 'duration', total);
  }
} finally {
  await browser.close();
  srv.close();
}
