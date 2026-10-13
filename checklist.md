# Explainer critique checklist

Run on every render. Look at the contact sheet first (tiles sit at t = N/2 + kN, times printed by render.mjs),
then stills at every click time, every landing, every caption change and 0.3 s either side of each scene boundary
(`node $SK/render.mjs --html explainer.html --stills ... --stills-dir critique/vN`). Every box must be ticked before delivery.
Write down what failed, fix it in the HTML, re-render, and check again.

## Composition
- [ ] No frame outside a transition leaves two thirds of the stage empty. Split layouts have something
      in the middle (flow line, packets, page fan) or the group is shifted to recentre.
- [ ] Content stays inside y 120..860 and x 140..1780. Nothing sits in the caption band or under the brand bug,
      including the resting cursor (tip at y <= 800).
- [ ] One idea per scene; at most two main cards plus one detail card.
- [ ] Cards, rows and chips use the house tokens (radius 26 cards, s1 / s2 / bd, shadows). No stray colours.
- [ ] Semantic colour holds: green done or live, amber attention, red loss only, blue action.

## Cursor
- [ ] The arrow tip lands exactly on the control it clicks (check a still at the click time).
- [ ] It arrives at least 0.15 s before the click, squashes on the click, and the burst is centred on the tip.
- [ ] The clicked control reacts (press dip, state change) on the same frame as the burst.
- [ ] It never covers the thing being explained while that thing animates; it rests somewhere quiet, clear of the caption band.
- [ ] It enters from off frame and fades with its scene; it never pops in or out mid frame.

## Motion
- [ ] Every flying icon, packet or page has landed before the frame that receives it solidifies
      (check landing times against the solidify or count change times).
- [ ] Counters and labels change exactly when the thing they count arrives.
- [ ] Something moves in every hold (flowing dashes, breathing glow, bob). No frozen frames.
- [ ] Easing matches the kit: E for moves, EB for pops, no linear motion except dash flow and spinners.
- [ ] Scene cross fades read as deliberate dips. A near blank still exactly at a scene start (e.g. t = 5.0 and
      14.0 in the reference) is the transition, not a bug. Any other blank frame is a bug.

## Text
- [ ] Captions readable: 50 px, weight 600, on the dark band, one or two lines, about 48 characters max per line.
- [ ] Each caption is visible at least 1 s per 4 words and never less than 2.5 s.
- [ ] No clipped text: nothing runs past a card edge, row end, chip pill or the frame.
- [ ] Strikes, underlines, highlight boxes and pills that follow text end with the text (sized with `textW`, no fixed widths).
- [ ] No overlapping text: labels, values and status words have clear space; right aligned values do not hit left labels.
- [ ] No dashes used as punctuation anywhere on screen. English, sentence case, final period on captions.
- [ ] Every claim is true and every number came from the user or the product. No PLACEHOLDER values left; without true
      numbers the outro `STATS` are words.
- [ ] No real client data: names, account numbers, balances and emails are fictional.

## Determinism and file
- [ ] `renderAt(t)` gives the same frame for the same t (no Math.random, no Date, no state between frames).
- [ ] `TOTAL` equals the end of the last scene; SCENES entries keep the `{ id, start, dur` one line shape;
      `const STATS = [...]` is one line.
- [ ] `compose.py` is the work folder copy and has a block for every scene id with sounds; `events.json` outro
      events match what the outro shows (count ticks for numbers, pops for words).
- [ ] No console errors or warnings in the render log.

## Output specs (ffprobe)
- [ ] Video: h264, 1920x1080, r_frame_rate 30/1, pix_fmt yuv420p, faststart.
- [ ] Duration equals TOTAL and nb_frames equals TOTAL x 30.
- [ ] With audio: aac, 48000 Hz, 2 channels, integrated loudness about -18 LUFS, true peak below -1 dBTP.
- [ ] Sounds land on their visuals: clicks on bursts, chimes on arrivals, whooshes centred on boundaries
      (spot check `events.json` against stills).
- [ ] Poster PNG and contact sheet written next to the MP4.
