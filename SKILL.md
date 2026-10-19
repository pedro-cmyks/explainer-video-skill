---
name: explainer-video
description: Use when the user asks for an animated product explainer, launch video, demo reel or social video in this house style (dark navy stage, stylized UI cards, a cartoon cursor that glides and clicks, captions at the bottom), rendered from a single HTML file to MP4 with an optional synthesized music bed. Also use when editing or re-rendering an existing video built this way.
---

# Explainer video, house style

Every video shares one look and one motion language, first built for a CRM explainer.
The gold reference is `reference/desk-crm-explainer.html` (84.5 s, 9 scenes, a fictional product called Desk CRM)
and its frame grid `reference/contact.png`. When in doubt, open the reference and copy the pattern.

Files in this skill:

| Path | What it is |
|---|---|
| `templates/explainer-template.html` | Start here. Full helper kit plus 3 example scenes (title, cards with cursor click, outro). |
| `templates/apply-theme.mjs` | Stamps a theme from `themes/` into a video's HTML (`--theme studio --html explainer.html`, `--list`). Run in place. |
| `themes/*.json` | Look and sound per theme: colours, gradients, font, card radius, logo mark, music key, progression, tempo, arpeggio. `house` is the default. |
| `templates/render.mjs` | Playwright frame stepper piped to ffmpeg. Video, poster, contact sheet, stills. Run in place, never copied. |
| `templates/compose.py` | Numpy music bed plus SFX synced to scene local times, mastered and muxed. Copy it per video. |
| `templates/voiceover.sh` | Optional macOS `say` voiceover, ducked under the music. Run in place with arguments. |
| `checklist.md` | Critique checklist. Every item must pass before delivery. |
| `reference/` | The reference HTML and its contact sheet. Never edit. |
| `examples/tidy-tasks/` | A short finished video (20 s) built from the template: HTML, its `compose.py` and contact sheet. |

Setup, once per machine: `npm install` and `npx playwright install chromium` in the skill folder (it has a
`package.json`), plus ffmpeg and Python 3 with numpy. `render.mjs` explains what is missing when it cannot start.

## The look

One motion language, many looks. Everything below describes the default theme, `house`. A theme changes the
palette tokens, the gradients, the font, the card radius, the logo mark and the music; it never changes the motion,
the cursor, the captions or the checklist. Same theme plus same scenes gives the same video, frame for frame.
Themes live in `themes/*.json` (`house`, `studio`, `ember`); `node $SK/apply-theme.mjs --list` shows them, and
`--theme <name> --html explainer.html` stamps one into the `THEME` block at the top of the HTML. `compose.py` reads
the music settings from that same block. The brief names the theme; without one, use `house`. For a new theme, copy a
json, change the tokens, keep `gr`, `am` and `rd` recognisable as green, amber and red, pick a font that exists on
the machine that renders, and check the contact sheet for contrast before using it.
Theme per scene (optional): paste more theme objects into `THEMES` and give a scene `theme: 'studio'`. Palette,
gradients and card radius morph across the 1 s cross fade; font and logo mark switch on the boundary; the music stays
the first theme's. Use it when the video is about variety itself; one theme is the normal case.

Stage: 1920x1080 SVG, font `'Avenir Next', 'Helvetica Neue', Helvetica, Arial, sans-serif` (theme `font`).

Background, three layers, never changed within a theme:
- radial gradient centred at 50% / 30%, r 75%: `#172638` -> `#111b26` (60%) -> `#0f1720`
- dot grid: 40 px pattern, r 1.6 dots `#22303f` at 70% opacity
- caption band: bottom 200 px (y 880..1080) fading to `#0b121a` at 90%

Palette tokens (`C` in the template, keep the names):

| Token | Hex | Use |
|---|---|---|
| bg | `#0f1720` | page, fade to black target |
| s1 | `#141d27` | card surface |
| s2 | `#1b2733` | rows, insets, inner panels |
| bd | `#2a3a4b` | borders, gridlines, empty dots |
| tx | `#e6edf3` | primary text |
| mu | `#a0b1c5` | secondary text, column headers |
| bl | `#3b82f6` | action, selection, packets, cursor burst, brand accent word |
| gr | `#2fca73` | done, live, gain, success |
| am | `#f59e0b` | attention, hot, outlier |
| rd | `#ef4444` | loss or error only |
| off | `#3a4a5c` | inactive status dot |
| paper / ink | `#f3f6fa` / `#1b2733` | light document pages |
| light blue | `#93c5fd`, core `#dbeafe` | lasso, highlights, packet core |
| click spark | `#ffd166` | alternate spokes of the click burst |

Gradients: `logoG` blue `#3b82f6` to green `#2fca73` (diagonal) for the logo tile and underline bar;
`hotG` amber to red for "hot" bars; `blueBar` `#2563eb` to `#3b82f6`; `areaG` green 38% to 0 under charts.

Shapes:
- Card: radius 26, fill s1, 2 px bd stroke, shadow `dy 16, blur 20, black 42%` (`card()`).
- Row: radius 14..18, fill s2, height 52..80, pitch 64..96 px.
- Chip: full pill, height 40, colour at 16% fill, label 24 px / 600 in the colour (`chip()`).
- Primary button: radius 22, height 84, solid bl, white 34 px / 700 label, soft glow pulse until clicked.
- Small shadow for icons and pills: `dy 8, blur 8, black 45%` (`#shs`).
- App window (reference `dashboard()`): 66 px top bar in s2 with traffic light dots r 8 (rd, am, gr at 80%),
  214 px sidebar in `#111922`, nav items 48 high radius 14, active item bl at 20%, KPI tiles radius 18.
- Status dot r 14; avatar ring 4 px plus a 25% halo; padlock from `lock()`.
- Brand bug: logo 46 px plus name 28 / 700 at (56, 40), 85% opacity, shown from scene 2 until the outro.

Type scale (px / weight): wordmark 132 / 700 (outro 96), tagline 58 / 500 mu, closing line 56 / 600,
caption 50 / 600, big numbers 52..64 / 700 tabular, card titles 34..40 / 700, row text 26..28 / 600,
labels and chips 24 / 600, nothing below 22. Wordmark letter spacing -1%.

Composition rules:
- Content lives in y 120..860 and x 140..1780. The caption band and the brand bug corner stay clear.
  That includes the resting cursor: keep its tip at y <= 800 (the arrow reaches about 75 px below the tip).
- Anything sized to text (strikes, underlines, highlight boxes, pills) takes its width from `textW(str, size, weight)`,
  never a guessed constant.
- Never leave two thirds of the frame empty. When content splits left and right, connect the middle
  with flow lines, packets or a fan of pages. Shift a whole scene group (`G(s, {x: SX})`) to recentre.
- One idea per scene. At most two cards side by side plus one detail card.
- Data is always fictional: Client A, Northwind, Maple Ridge, Bluebird, Harbor Point, ACC 01.

## Motion language

Easing kit (in the template): `E` cubic in out (default for everything), `EO` cubic out (settling),
`EB` back out with ~10% overshoot (pops: cards, chips, badges, icons), `esine` for drawn paths,
`fadeIO(t, a, b, 0.35)` for cursor opacity, ease out quint `1 - (1 - x)^5` for counters.
Determinism: `rng(seed)` only, never `Math.random` or wall clock.

Entrances:
- Cards: fade over 0.5 s plus rise 20 px over 0.6 s, or scale `mix(0.92, 1, EB)` over 0.7 s.
- List rows: stagger 0.08..0.12 s, slide in from x -20 / -30 or y +16, 0.5 s each.
- Pops: `EB` over 0.5..0.7 s. Badges scale 0.7 -> 1.
- Wordmark: clip wipe opening from the centre over 0.8 s with a 34 px rise; the logo mark draws with `pathLength`.

Cursor kit (`drawCursor`, `curPos`):
- White arrow path `ARROW`, `#0b1118` 3.4 px outline, drop shadow dx 4 dy 7 blur 4 at 50%, base scale 1.1.
- `keys: [[t, x, y], ...]` in local seconds, (x, y) is the arrow tip. Glide uses cubic in out plus a sideways
  arc of 12% of the distance (max 110 px). Tilt follows horizontal speed (0.35 deg per px, max 14 deg).
- Typical glide 0.7..1.5 s. Enter from off frame at (1880, 1080) about 1.5 s into the scene.
- Arrive at least 0.15 s before the click and sit exactly on the control's centre.
- Click: squash x +16% and y -22% peaking on the click (window 0.34 s starting 0.1 s early), then a 0.6 s
  burst: blue ring r 8 -> 54 thinning 6 -> 1 px, plus 8 spokes alternating white / `#ffd166`.
- The clicked control dips with `press()` to scale 0.93 and its glow pulse stops.
- After the action, glide to a quiet rest spot (between cards, e.g. (1010, 800)) and hold. Fade out with the scene.
- `trail` adds a 12 dot blue comet while drawing; `pos` replaces keys for custom paths (the lasso).

Signature moves (reference scene to copy from):
- Lasso: cursor draws a wobbling ellipse with `esine`, dashed `#93c5fd` 5 px (16 12, flowing), closes solid
  with a 0.35 s glow flash and 7% fill, then icons fly along curved paths into a ghost frame that
  solidifies into the app window (`sBefore`).
- Packets: glowing dot (r 22 glow plus r 12 `#dbeafe` core) with a 6 dot comet tail on an S curve, cubic in out
  over 1.2..1.45 s, dashed guide line flowing at 24 px/s, sender flashes blue, green ring on arrival (`packet()`, `sClose`).
- Status dots: grey -> green with a ring burst (r 14 -> 40, 0.6 s) and a 1.25x pop, then breathing glow
  `0.25 + 0.2 sin(3t)`. Warning: amber, repeating ring every 1.3 s, short shake (`statusDot()`, `sStatus`).
- Charts draw: `pathFrom` reveals the line over 1.5..3.7 s, 6..7 px green, `areaG` fill, glowing head dot
  (r 18 glow plus r 10 white). Bars grow from zero staggered 0.18 s. Heatmap cells pop staggered (`sAlgos`, `sHistory`).
- Counters: count up with ease out quint over 1.0 s, tabular numerals.
- Page fan: pages leave the button, fan through the centre (rotations -10, -3.5, 3.5, 10 deg, 60 px hop),
  then each hops 110 px into a tray at scale 0.56, staggered 0.55 s; tray glows green when full (`sReports`).
- Org fan: lines draw from a clicked avatar to team columns, locks snap shut, a dashed outline groups the desk (`sBook`).
- Checklists (template kit): `checkbox()` round check that dips, pops green and draws its tick on the click;
  `strike(x, y, textW(...) + 8, u)` crosses the label out; each check sends a `packet()` to a `progressRing()`
  that eases one step per arrival and glows when closed. A list scene is checkbox + strike + packet + ring
  (see `examples/tidy-tasks/`).

Transitions: scenes are back to back. Each fades out over its last 0.5 s and the next fades in over its first
0.5 s with a 0.985 -> 1 scale settle (a dip through the background). The first scene starts solid, the outro
ends with its own 0.6 s fade to bg. A transition frame is intentionally near blank; do not "fix" it.

Holds and idle motion: something moves in every frame. Use flowing dash offsets, breathing glows (`sin(3t)`),
`bob()` floats of 3..5 px, slow spinners (60 deg/s), drifting icons (18 / 14 px). Keep at least 1.5 s of hold
after the last beat of a scene so the caption finishes reading.

## Copy rules

- English captions, sentence case, ending with a period. One or two lines, about 48 characters max per line.
- Time on screen (caption fades in 0.45..1.05 s, out at `dur - 0.75`) must be at least 1 s per 4 words and
  never under 2.5 s. In practice a scene is never shorter than about 5 s.
- No dashes as punctuation (no em dash, en dash or spaced hyphen) in captions or on screen. Use commas and periods.
- Only true claims. Numbers on screen (clients, accounts, intervals) come from the user or the product, never invented.
  Template numbers are marked PLACEHOLDER. No true numbers (teaser, fictional product)? Make the outro `STATS`
  plain words, `['Simple lists', 'Daily focus', 'Clear progress']`: the pills pop instead of counting.
- No real client data: no real names, account numbers, balances, emails or logos of clients. Use the fictional set.
- Title and outro carry no caption; the tagline and closing line do that job.

## Architecture

- One self contained HTML file, no network, no libraries. SVG stage plus one IIFE script.
- `render(t)` is pure: it rebuilds `#frame` innerHTML from t alone. Exposed as `window.renderAt(t)`,
  with `window.TOTAL_DURATION` and `window.SCENES_INFO`. Without `#manual` in the URL it loops in real time.
- `SCENES = [{ id, start, dur, fn, cap }]`, back to back. Keep each entry on one line in that key order and
  `const TOTAL = <number>;` as a literal: `compose.py` parses both with regexes.
- A scene is `fn(lt, dur) -> { svg, cursor? }` with local time `lt`. All beat times inside a scene are local
  constants (`click`, `send(i)`, `onT(i)`), which is what the audio script mirrors.
- Helpers: math (`clamp lin E EO EB mix f rng fadeIO bob`), svg (`T G R Ci card chip check avatar lock logo wordmark textW`),
  charts (`pathFrom walk scalePts spark areaChart bez`), motion (`ring statusDot packet press progressRing checkbox strike`),
  cursor (`curPos drawCursor`), `caption`. `G()` returns '' when opacity is ~0, so hidden layers are free.
- Draw order: scene content, caption, brand bug, cursor last.
- `const STATS = [...]` stays one line at the start of a line: `compose.py` reads it for the outro sounds.

## Workflow

1. Brief. Audience, product, 3..6 true claims with real numbers, length (60..90 s full, 20..40 s teaser), where it will post,
   and the theme (`house`, `studio`, `ember`, or a new json).
2. Storyboard. A table with scene id, duration, caption, visual metaphor, cursor action and beat times.
   Arc: hook (logo, tagline) -> before (the pain) -> one feature per scene -> outro (stats or word pills, closing line).
   Check caption timing against the copy rules before building.
3. Build. In the work folder, with `SK` set to this skill's `templates` folder
   (for example `SK=~/.claude/skills/explainer-video/templates`):
   `cp $SK/explainer-template.html explainer.html && cp $SK/compose.py .` Never edit the skill copies.
   Apply the theme: `node $SK/apply-theme.mjs --theme <name> --html explainer.html` (skip for `house`).
   Set `BRAND`, replace the example cards scene, add scenes in the marked block, update starts and `TOTAL`,
   set `STATS`. Lift patterns from the reference.
4. Preview. Open the HTML in a browser (it loops), then render stills at every click, landing and boundary:
   `node $SK/render.mjs --html explainer.html --stills 3.2,4.9,8.6 --stills-dir critique/v1`.
5. Render. `node $SK/render.mjs --html explainer.html --out name.mp4` writes the MP4, `-poster.png` and `-contact.png`.
6. Critique. Read the contact sheet and the stills against `checklist.md`. Every item must pass; fix, re-render,
   re-check. Use a new `--stills-dir critique/vN` per iteration so runs do not overwrite each other.
7. Polish. Audio (below), final ffprobe, then hand over the MP4, poster and contact sheet.

## Render pipeline

`templates/render.mjs` (Node ESM, Playwright, ffmpeg):
- Loads the page with `#manual`, waits for fonts, reads `window.TOTAL_DURATION` (or `--duration`).
- For each frame i: `renderAt(i / fps)`, waits two animation frames, screenshots PNG, pipes into
  `ffmpeg -f image2pipe -c:v png -i -` -> `libx264 -preset slow -crf 18 -pix_fmt yuv420p -movflags +faststart`.
- Options: `--html --out --fps (30) --duration --width --height --poster --contact-every --stills --stills-dir --no-extras --crf`.
- Playwright is resolved from `$PLAYWRIGHT_DIR`, the current directory, the html folder and the script folder
  (Node walks up from each, so the skill's own `node_modules` is found). When it is missing, the script says to run
  `npm install` and `npx playwright install chromium` in the skill folder.
- The newest `chromium_headless_shell-*` in the Playwright cache (`$PLAYWRIGHT_BROWSERS_PATH`, or the platform
  default such as `~/Library/Caches/ms-playwright` on macOS) is passed as `executablePath`; it falls back to
  Playwright's default browser.
- ffmpeg from `$FFMPEG`, `/opt/homebrew/bin/ffmpeg`, `/usr/local/bin/ffmpeg`, or PATH. Speed is about 5..6 frames
  per second at 1080p on a recent laptop (a 20 s video takes about 2 minutes).
- Contact sheet: N = `--contact-every` (default 1 s under 40 s, else 2 s). Tiles show t = N/2, 3N/2, 5N/2 ...
  (half an interval in, so tile 1 is not the empty t = 0 frame); the times are printed. 480 px tiles, 5..8 per row
  chosen to fill the grid, padding 6, colour `0x05080c`. Clicks and boundaries need stills, not tiles.

## Audio pipeline

`templates/compose.py` (Python 3 + numpy + ffmpeg, everything synthesized, no samples, no licences):
- Parses `TOTAL`, `SCENES` and the outro `STATS` from the HTML. Effects are written as scene local offsets in
  `local_events()` using the same numbers as the scene code, so retiming a scene moves its sounds. In your copy,
  add a block per new scene (the `title`, `cards` and `outro` blocks match the template; `hook` .. `book` match the
  reference). Blocks for scene ids not in `SCENES` are skipped. The outro block follows `STATS` by itself:
  count ticks for numbers, pops for words.
- Music: D major, I V vi IV, cadence IV V I on the final logo. Tempo nearest 104 BPM that fits whole bars between
  the drop (start of scene 2) and the outro start, so both land on a downbeat. Sections build from a sparse
  intro to full energy with pad, pluck arpeggio, bass, kick with sidechain pump, hats, claps and a bell lead,
  plus risers and impacts on the drop and the final logo. Short timelines (under 16 bars) scale the sections;
  teasers under about 25 s get under 8 bars, so each section is about a bar and the build is quick (it warns; expected).
- SFX kit: click, pop, tick, chime, confirm, alert, blip, whoosh, swish, gather, scan, scribble, thump, land, lock, count.
  Every click time gets a click, every arrival a chime, every badge a confirm, every scene boundary a whoosh
  centred on the cross fade. Pan follows cursor x, subtle (max 0.4).
- Mastering targets: music stem normalised to -18 LUFS integrated, 1.5 s fade in, 2 s tail; SFX on top with a shared
  reverb send; true peak limiter at -1.5 dBTP (4x oversampled). Final mix lands near -18 LUFS, peaks near -3.5 dBTP.
  Outputs `music_sfx.wav`, `music_bed.wav`, `sfx.wav` (48 kHz, 24 bit stereo, stems sum to the mix) and `events.json`.
- Run your copy: `python3 compose.py --html explainer.html --video name.mp4 --mux-out name-music.mp4 --outdir audio`
  (`--no-mux` for audio only). Defaults sit next to the html (`<stem>.mp4`, `<video stem>-music.mp4`, `audio/`, created
  when missing). ffmpeg and ffprobe resolve like render.mjs. Mux is AAC 256 kbps 48 kHz with the video stream copied.

House mix (the preferred final balance, applied after compose.py): effects forward, music a step back, and the
music ducks under every effect. From the two stems compose.py writes:

```bash
ffmpeg -i audio/music_bed.wav -i audio/sfx.wav -filter_complex \
 "[1:a]volume=6dB,asplit=2[sk][sm];[0:a]volume=-3dB[mb];[mb][sk]sidechaincompress=threshold=0.015:ratio=4:attack=5:release=300[duck];[duck][sm]amix=inputs=2:normalize=0[mix]" \
 -map "[mix]" -ar 48000 -c:a pcm_s24le audio/premix.wav
# then gain to -16 LUFS integrated (measure with loudnorm=print_format=json) and limit:
ffmpeg -i audio/premix.wav -af "volume=<-16 minus measured>dB,alimiter=limit=0.84:level=false:attack=3:release=60" -c:a pcm_s24le audio/mix.wav
```

Measured on the reference video: the music dips about 6 dB under a typical effect (up to 12 in busy moments)
and stays within 0.3 dB elsewhere; the final mix sits at -16 LUFS, true peak about -2.3 dBTP. Mux `audio/mix.wav`
instead of `music_sfx.wav`. For a voiceover, duck this mix under the voice (below) and normalise to -16 again.

## Voiceover (optional, macOS)

Only when the user asks for one. The voices that macOS `say` uses are licensed by Apple for personal,
non commercial use. A video meant for publishing (a product page, a social post, an ad) ships with the
synthesized music only; keep voiced versions for drafts and internal reviews, and say so when you deliver one.

Voice: any voice installed on the user's Mac. List them with `say -v '?'`. `"Ava (Premium)"` is a good one
(downloaded in System Settings, Accessibility, Spoken Content, System voice, Manage Voices); `Samantha` ships with
macOS and is the script default. Rate 175..185 words per minute.

One line per scene in a `lines.tsv` (`id<TAB>scene start<TAB>scene end<TAB>text`), placed at scene start + 0.4 s
(0.3 s for a scene at 0), and every line must end before its scene ends: measure after trimming the silence `say`
adds, and shorten the wording rather than pushing the rate over 185. Run it in place:

```bash
$SK/voiceover.sh --video name.mp4 --lines lines.tsv --voice "Ava (Premium)" --rate 180 --out name-voice.mp4
```

It uses `audio/mix.wav` next to the video as the bed (else `audio/music_sfx.wav`, or `--bed <file>`), and prints a
warning for every line that runs past its scene. Three traps it already avoids:
- Do not `loudnorm` each line: in a filter chain it shifted every line about 0.3 s early. Measure each line's
  LUFS and apply a fixed `volume` gain instead.
- `amix` ends at its shortest input: add `duration=longest,apad=whole_dur=TOTAL,atrim=0:TOTAL`, and never mux
  with `-shortest`, or the video gets cut to the audio.
- Duck the house mix under the voice with `sidechaincompress=threshold=0.02:ratio=6:attack=15:release=400`,
  then gain the result to -16 LUFS and limit at -1.5 dBTP, same as the house mix.

The script ends by printing the planned and measured start of every line (`silencedetect`); check they match.
With a voiceover, captions still match the spoken words exactly.

## Delivery specs

Check with `ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt,nb_frames,sample_rate,channels:format=duration -of compact file.mp4`:
h264, 1920x1080, 30/1, yuv420p, duration equal to `TOTAL`, `nb_frames` = TOTAL x 30; with audio, aac 48000 Hz stereo.
Deliver the MP4 (silent and with music), the poster PNG and the contact sheet.
