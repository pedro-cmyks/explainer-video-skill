// Renders an explainer HTML (house style, see ../SKILL.md) to MP4 by stepping window.renderAt(t).
//
// Run it in place, from wherever this folder lives (the repo, or ~/.claude/skills/explainer-video):
//   node templates/render.mjs --html explainer.html --out video.mp4       full video + poster + contact sheet
//   node templates/render.mjs --html explainer.html --stills 2,4.5,9      PNG stills only (fast review)
//   npm run render -- --html explainer.html --out video.mp4                same, through package.json
//
// Options
//   --html <file>          page exposing window.renderAt(t) and window.TOTAL_DURATION   (default ./explainer.html)
//   --out <file.mp4>       output video                                                  (default <html name>.mp4)
//   --fps <n>              frames per second                                             (default 30)
//   --duration <s>         override the length; default reads window.TOTAL_DURATION
//   --width/--height <px>  viewport                                                      (default 1920x1080)
//   --poster <t>           time for the poster frame                                     (default duration - 2)
//   --contact-every <s>    contact sheet interval                       (default 1 under 40 s, else 2)
//                          tiles show t = N/2, 3N/2, 5N/2 ... (half an interval in, so tile 1 is not the
//                          empty t = 0 frame); the exact times are printed. 5..8 tiles per row, chosen to fill.
//   --stills <t,t,...>     write PNG stills and exit
//   --stills-dir <dir>     where stills go                                               (default <html dir>/stills)
//   --no-extras            skip poster and contact sheet
//   --crf <n>              x264 quality                                                  (default 18)
//
// Playwright is resolved from: $PLAYWRIGHT_DIR, the current directory, the html directory and this
// script's directory (Node walks up from each, so the repo's own node_modules is found). If it is
// missing, run `npm install` and `npx playwright install chromium` inside the repo.
// Browser: the newest chromium_headless_shell in the Playwright cache ($PLAYWRIGHT_BROWSERS_PATH, or the
// platform default) is used as executablePath when present, else Playwright's default Chromium.
import { createRequire } from 'node:module';
import { spawn, execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';

// ---------- args
const argv = process.argv.slice(2);
const opt = (name, def) => { const i = argv.indexOf('--' + name); return i >= 0 && argv[i + 1] != null && !argv[i + 1].startsWith('--') ? argv[i + 1] : def; };
const flag = name => argv.includes('--' + name);
if (flag('help')) { console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').filter(l => l.startsWith('//')).join('\n')); process.exit(0); }

const HTML = path.resolve(opt('html', 'explainer.html'));
if (!fs.existsSync(HTML)) { console.error(`html not found: ${HTML}`); process.exit(1); }
const DIR = path.dirname(HTML), BASE = path.basename(HTML, path.extname(HTML));
const OUT = path.resolve(opt('out', path.join(DIR, BASE + '.mp4')));
const FPS = Number(opt('fps', 30));
const W = Number(opt('width', 1920)), H = Number(opt('height', 1080));
const CRF = String(opt('crf', 18));
const STEM = OUT.replace(/\.mp4$/i, '');
const POSTER = STEM + '-poster.png', CONTACT = STEM + '-contact.png';

// ---------- tools
function findFfmpeg() {
  for (const p of [process.env.FFMPEG, '/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg']) if (p && fs.existsSync(p)) return p;
  try { return execFileSync('which', ['ffmpeg']).toString().trim(); } catch { return 'ffmpeg'; }
}
const FFMPEG = findFfmpeg();

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_DIR = path.dirname(SCRIPT_DIR);

function loadPlaywright() {
  const bases = [process.env.PLAYWRIGHT_DIR, process.cwd(), DIR, SCRIPT_DIR].filter(Boolean);
  for (const b of bases) {
    try { return createRequire(path.join(b, 'noop.js'))('playwright'); } catch {}
  }
  console.error([
    'Playwright was not found. Install it once, inside the repo folder:',
    `  cd "${REPO_DIR}"`,
    '  npm install',
    '  npx playwright install chromium',
    'Or set PLAYWRIGHT_DIR to a folder whose node_modules already has playwright.',
  ].join('\n'));
  process.exit(1);
}
const { chromium } = loadPlaywright();

// Playwright's browser cache: $PLAYWRIGHT_BROWSERS_PATH, else the per platform default.
function playwrightCache() {
  const env = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (env && env !== '0') return env;
  const home = os.homedir();
  if (process.platform === 'darwin') return path.join(home, 'Library', 'Caches', 'ms-playwright');
  if (process.platform === 'win32') return path.join(process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'ms-playwright');
  return path.join(process.env.XDG_CACHE_HOME || path.join(home, '.cache'), 'ms-playwright');
}
function newestHeadlessShell() {
  try {
    const cache = playwrightCache();
    const dirs = fs.readdirSync(cache).filter(d => /^chromium_headless_shell-\d+$/.test(d))
      .sort((a, b) => Number(a.split('-')[1]) - Number(b.split('-')[1]));
    for (const d of dirs.reverse()) {
      for (const sub of fs.readdirSync(path.join(cache, d))) {
        for (const exe of ['chrome-headless-shell', 'chrome-headless-shell.exe']) {
          const p = path.join(cache, d, sub, exe);
          if (fs.existsSync(p)) return p;
        }
      }
    }
  } catch {}
  return null;
}
const shellBin = newestHeadlessShell();
let browser;
try { browser = await chromium.launch(shellBin ? { executablePath: shellBin } : {}); }
catch (e) {
  if (shellBin) console.warn(`cached headless shell failed (${shellBin}), using the Playwright default`);
  try { browser = await chromium.launch(); }
  catch (e2) {
    console.error(`Could not start Chromium: ${e2.message.split('\n')[0]}\nRun \`npx playwright install chromium\` inside the repo, then try again.`);
    process.exit(1);
  }
}

const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
page.on('console', m => { if (m.type() === 'warning' || m.type() === 'error') console.warn('[page]', m.text()); });
page.on('pageerror', e => { console.error('[page error]', e.message); });
await page.goto(pathToFileURL(HTML).href + '#manual');
await page.evaluate(() => document.fonts.ready);
const hasRender = await page.evaluate(() => typeof window.renderAt === 'function');
if (!hasRender) { console.error('window.renderAt(t) is missing'); await browser.close(); process.exit(1); }
const total = Number(opt('duration', 0)) || await page.evaluate(() => window.TOTAL_DURATION);
if (!total) { console.error('no duration: set window.TOTAL_DURATION or pass --duration'); await browser.close(); process.exit(1); }
const POSTER_T = Number(opt('poster', Math.max(0, total - 2)));

async function frameAt(t) {
  await page.evaluate(tt => new Promise(res => { window.renderAt(tt); requestAnimationFrame(() => requestAnimationFrame(res)); }), t);
  return page.screenshot({ type: 'png' });
}
function run(cmd, args) {
  return new Promise((res, rej) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'inherit', 'inherit'] });
    p.on('close', c => (c === 0 ? res() : rej(new Error(`${cmd} exited ${c}`))));
  });
}

// ---------- stills mode
const stills = opt('stills', null);
if (stills) {
  const times = stills.split(',').filter(Boolean).map(Number);
  const dir = path.resolve(opt('stills-dir', path.join(DIR, 'stills')));
  fs.mkdirSync(dir, { recursive: true });
  for (const t of times) fs.writeFileSync(path.join(dir, `t${t.toFixed(2).padStart(6, '0')}.png`), await frameAt(t));
  await browser.close();
  console.log(`wrote ${times.length} stills to ${dir}`);
  process.exit(0);
}

// ---------- video: PNG frames piped into ffmpeg
const frames = Math.round(total * FPS);
console.log(`${path.basename(HTML)}: ${total} s at ${FPS} fps = ${frames} frames -> ${OUT}`);
const ff = spawn(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
  '-c:v', 'libx264', '-preset', 'slow', '-crf', CRF, '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-r', String(FPS), OUT],
  { stdio: ['pipe', 'inherit', 'inherit'] });
const ffDone = new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error(`ffmpeg exited ${c}`)))));

const started = Date.now();
for (let i = 0; i < frames; i++) {
  const buf = await frameAt(i / FPS);
  if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
  if (i % (FPS * 5) === 0) console.log(`frame ${i}/${frames}  ${((Date.now() - started) / 1000).toFixed(0)}s`);
}
ff.stdin.end();
await ffDone;

if (!flag('no-extras')) fs.writeFileSync(POSTER, await frameAt(POSTER_T));
await browser.close();

// ---------- contact sheet: frame index off + k*step (t = N/2 + k*N), 5..8 per row
if (!flag('no-extras')) {
  const every = Number(opt('contact-every', total < 40 ? 1 : 2));
  const step = Math.max(1, Math.round(every * FPS)), off = Math.floor(step / 2);
  const n = Math.floor((frames - 1 - off) / step) + 1;
  const waste = c => Math.ceil(n / c) * c - n;
  const cols = [6, 5, 7, 8].reduce((b, c) => (waste(c) < waste(b) ? c : b)), rows = Math.ceil(n / cols);
  await run(FFMPEG, ['-y', '-loglevel', 'error', '-i', OUT, '-vf',
    `select='eq(mod(n\\,${step})\\,${off})',scale=480:-1,tile=${cols}x${rows}:padding=6:color=0x05080c`, '-frames:v', '1', CONTACT]);
  const times = Array.from({ length: n }, (_, k) => ((off + k * step) / FPS).toFixed(2));
  console.log(`poster:  ${POSTER}\ncontact: ${CONTACT}  (${n} tiles, ${cols} per row, t = ${times.slice(0, 4).join(', ')} ... ${times[n - 1]})`);
}
console.log(`done:    ${OUT}`);
