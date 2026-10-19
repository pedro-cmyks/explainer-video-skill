#!/usr/bin/env node
// Stamp a theme into an explainer HTML: replaces the block between /* THEME START */ and /* THEME END */.
// Usage: node apply-theme.mjs --theme house|studio|ember|path/to/theme.json --html explainer.html
//        node apply-theme.mjs --list
// compose.py reads the music settings from the same block, so the HTML stays the single source of truth.
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const themesDir = join(here, '..', 'themes');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };

if (args.includes('--list')) {
  for (const f of readdirSync(themesDir).filter(n => n.endsWith('.json')).sort()) {
    const t = JSON.parse(readFileSync(join(themesDir, f), 'utf8'));
    console.log(`${t.name.padEnd(8)} mark ${t.mark.padEnd(6)} bpm ${String(t.music.bpm).padEnd(4)} key ${t.music.transpose >= 0 ? '+' : ''}${t.music.transpose}  ${t.font.split(',')[0]}`);
  }
  process.exit(0);
}
const name = opt('--theme'), html = opt('--html', 'explainer.html');
if (!name) { console.error('usage: apply-theme.mjs --theme <name|file.json> --html explainer.html   (or --list)'); process.exit(2); }
const file = existsSync(name) ? resolve(name) : join(themesDir, name + '.json');
if (!existsSync(file)) { console.error(`theme not found: ${file}`); process.exit(2); }
const theme = JSON.parse(readFileSync(file, 'utf8'));
for (const k of ['name', 'font', 'colors', 'gradients', 'shape', 'mark', 'music']) if (!(k in theme)) { console.error(`theme is missing "${k}"`); process.exit(2); }
for (const k of ['bg', 's1', 's2', 'bd', 'tx', 'mu', 'bl', 'gr', 'am', 'rd', 'off', 'paper', 'ink', 'purple', 'light', 'core', 'spark']) if (!(k in theme.colors)) { console.error(`theme.colors is missing "${k}"`); process.exit(2); }
for (const k of ['transpose', 'prog', 'bpm', 'arp']) if (!(k in theme.music)) { console.error(`theme.music is missing "${k}"`); process.exit(2); }
if (theme.music.arp.length !== 16) { console.error('theme.music.arp needs 16 steps'); process.exit(2); }

const src = readFileSync(html, 'utf8');
const re = /\/\* THEME START \*\/[\s\S]*?\/\* THEME END \*\//;
if (!re.test(src)) { console.error(`${html} has no THEME block (markers /* THEME START */ and /* THEME END */)`); process.exit(2); }
const out = src.replace(re, `/* THEME START */\nconst THEME = ${JSON.stringify(theme)};\n/* THEME END */`);
writeFileSync(html, out);
console.log(`theme "${theme.name}" applied to ${html}: mark ${theme.mark}, ${theme.music.bpm} BPM, key ${theme.music.transpose >= 0 ? '+' : ''}${theme.music.transpose}, font ${theme.font.split(',')[0]}`);
