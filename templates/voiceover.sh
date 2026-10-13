#!/usr/bin/env bash
# Optional voiceover for a house style explainer (see ../SKILL.md), macOS only (uses `say`).
#
# Voices from `say` are licensed by Apple for personal, non commercial use. Use this for drafts and
# internal versions. A video meant for publishing should ship with the synthesized music only.
#
# Usage
#   templates/voiceover.sh --video name.mp4 --lines lines.tsv [options]
#
# Required
#   --video <file.mp4>     the rendered video (silent or with music; its video stream is copied)
#   --lines <file.tsv>     narration, one line per scene: id<TAB>scene start<TAB>scene end<TAB>text
#                          (blank lines and lines starting with # are skipped)
# Options
#   --voice <name>         any installed voice, see `say -v '?'`        (default Samantha)
#                          "Ava (Premium)" is a good one; download it in System Settings,
#                          Accessibility, Spoken Content, System voice, Manage Voices.
#   --rate <wpm>           words per minute, keep it within 175..185    (default 180)
#   --bed <file.wav>       music and effects to duck under the voice    (default audio/mix.wav, else
#                          audio/music_sfx.wav next to the video; none found means voice only)
#   --out <file.mp4>       output video                                 (default <video stem>-voice.mp4)
#   --workdir <dir>        where the per line and mix files go          (default audio/vo next to the video)
#   --lead <s>             delay after the scene start                  (default 0.4; 0.3 for a scene at 0)
#
# What it does
#   1. Speaks each line with `say`, converts to 48 kHz mono and trims the silence `say` adds.
#   2. Measures each line's loudness and applies a fixed gain to -16 LUFS. It does not run loudnorm
#      in the filter chain: that shifted every line about 0.3 s early.
#   3. Places each line at scene start + lead and warns when a line runs past its scene end
#      (shorten the wording rather than raising the rate).
#   4. Mixes the lines with amix duration=longest, then pads and trims to the video length, so the
#      audio never ends early. The mux does not use -shortest.
#   5. Ducks the bed under the voice (sidechaincompress threshold 0.02, ratio 6, attack 15, release 400),
#      gains the result to -16 LUFS and limits it, then muxes AAC 256 kbps 48 kHz.
#   6. Prints the final stream info, loudness and the measured start of every line.
set -euo pipefail

die() { echo "voiceover: $*" >&2; exit 1; }
tool() {
  local name=$1 up
  up=$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]')
  for p in "${!up:-}" "/opt/homebrew/bin/$name" "/usr/local/bin/$name"; do
    [ -n "$p" ] && [ -x "$p" ] && { echo "$p"; return; }
  done
  command -v "$name" || die "$name not found (install ffmpeg)"
}

VIDEO=""; LINES=""; VOICE="Samantha"; RATE=180; BED=""; OUT=""; WORK=""; LEAD=0.4
while [ $# -gt 0 ]; do
  case "$1" in
    --video) VIDEO=$2; shift 2 ;;
    --lines) LINES=$2; shift 2 ;;
    --voice) VOICE=$2; shift 2 ;;
    --rate) RATE=$2; shift 2 ;;
    --bed) BED=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --workdir) WORK=$2; shift 2 ;;
    --lead) LEAD=$2; shift 2 ;;
    -h|--help) sed -n '2,35p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done

[ -n "$VIDEO" ] && [ -f "$VIDEO" ] || die "--video is required and must exist"
[ -n "$LINES" ] && [ -f "$LINES" ] || die "--lines is required and must exist"
command -v say >/dev/null || die "say not found: the voiceover needs macOS"
say -v '?' | grep -F "$VOICE " >/dev/null || die "voice '$VOICE' is not installed. List voices with: say -v '?'"

FF=$(tool ffmpeg); FP=$(tool ffprobe)
VDIR=$(cd "$(dirname "$VIDEO")" && pwd); VSTEM=$(basename "${VIDEO%.*}")
OUT=${OUT:-$VDIR/$VSTEM-voice.mp4}
WORK=${WORK:-$VDIR/audio/vo}
if [ -z "$BED" ]; then
  for c in "$VDIR/audio/mix.wav" "$VDIR/audio/music_sfx.wav"; do [ -f "$c" ] && { BED=$c; break; }; done
fi
[ -z "$BED" ] || [ -f "$BED" ] || die "bed not found: $BED"
mkdir -p "$WORK"

TOTAL=$("$FP" -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
echo "video $VIDEO, $TOTAL s; voice '$VOICE' at $RATE wpm; bed ${BED:-none}"

# integrated loudness of a file (measurement only; the gain is applied later as a fixed volume)
lufs() { "$FF" -nostdin -hide_banner -nostats -i "$1" -af loudnorm=print_format=json -f null - 2>&1 | awk -F'"' '/"input_i"/ { v = $4 } END { print v }'; }
num() { [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "$2 is not a number: '$1'"; }

ins=(); flt=""; n=0; planned=()
while IFS=$'\t' read -r id s e text || [ -n "${id:-}" ]; do
  [ -z "${id:-}" ] && continue
  case "$id" in \#*) continue ;; esac
  [ -n "${text:-}" ] || die "line '$id' has no text (expected id<TAB>start<TAB>end<TAB>text)"
  num "$s" "scene start of '$id'"; num "$e" "scene end of '$id'"
  raw="$WORK/$id.aiff"; wav="$WORK/$id.wav"
  say -v "$VOICE" -r "$RATE" -o "$raw" "$text"
  "$FF" -nostdin -v error -y -i "$raw" -af "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.02,areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse" -ac 1 -ar 48000 -c:a pcm_s24le "$wav"
  dur=$("$FP" -v error -show_entries format=duration -of csv=p=0 "$wav")
  read -r at ends over < <(awk -v s="$s" -v e="$e" -v d="$dur" -v L="$LEAD" 'BEGIN {
    lead = (s == 0 && L == 0.4) ? 0.3 : L; at = s + lead; end = at + d
    printf "%.3f %.2f %d\n", at, end, (end > e) ? 1 : 0 }')
  li=$(lufs "$wav"); gain=$(awk -v i="$li" 'BEGIN { printf "%.2f", -16 - i }')
  printf '  %-10s at %7.3f s, %5.2f s long, ends %6.2f s (scene ends %s), %s LUFS, gain %s dB\n' "$id" "$at" "$dur" "$ends" "$e" "$li" "$gain"
  [ "$over" = 1 ] && echo "  WARNING: '$id' runs past its scene end. Shorten the wording." >&2
  ms=$(awk -v a="$at" 'BEGIN { printf "%d", a * 1000 + 0.5 }')
  ins+=(-i "$wav")
  flt+="[${n}:a]highpass=f=90,volume=${gain}dB,aresample=48000,adelay=${ms}:all=1[v${n}];"
  planned+=("$at")
  n=$((n + 1))
done < "$LINES"
[ "$n" -gt 0 ] || die "no lines found in $LINES"

mixin=""; for ((k = 0; k < n; k++)); do mixin+="[v${k}]"; done
"$FF" -nostdin -v error -y "${ins[@]}" -filter_complex "${flt}${mixin}amix=inputs=${n}:normalize=0:duration=longest,apad=whole_dur=${TOTAL},atrim=0:${TOTAL},pan=stereo|c0=c0|c1=c0[vo]" \
  -map "[vo]" -ar 48000 -c:a pcm_s24le "$WORK/voice_track.wav"

if [ -n "$BED" ]; then
  "$FF" -nostdin -v error -y -i "$BED" -i "$WORK/voice_track.wav" -filter_complex \
    "[1:a]asplit=2[vk][vm];[0:a]apad=whole_dur=${TOTAL},atrim=0:${TOTAL}[bed];[bed][vk]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=400[duck];[duck][vm]amix=inputs=2:normalize=0[out]" \
    -map "[out]" -ar 48000 -c:a pcm_s24le "$WORK/voice_premix.wav"
else
  cp "$WORK/voice_track.wav" "$WORK/voice_premix.wav"
fi
I=$(lufs "$WORK/voice_premix.wav"); G=$(awk -v i="$I" 'BEGIN { printf "%.2f", -16 - i }')
echo "premix $I LUFS, gain $G dB"
"$FF" -nostdin -v error -y -i "$WORK/voice_premix.wav" -af "volume=${G}dB,alimiter=limit=0.84:level=false:attack=3:release=60" -ar 48000 -c:a pcm_s24le "$WORK/mix_vo.wav"

"$FF" -nostdin -v error -y -i "$VIDEO" -i "$WORK/mix_vo.wav" -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 256k -ar 48000 -movflags +faststart "$OUT"

echo "out: $OUT"
"$FP" -v error -show_entries stream=codec_name,sample_rate,channels:format=duration -of compact "$OUT"
"$FF" -nostdin -hide_banner -nostats -i "$OUT" -af loudnorm=print_format=json -f null - 2>&1 | grep -E '"input_i"|"input_tp"' | tr -d ' \n'; echo
# measured start of each line: the first sound after a window that opens 0.25 s before the planned start
echo "line starts, planned -> measured:"
for at in "${planned[@]}"; do
  w0=$(awk -v a="$at" 'BEGIN { w = a - 0.25; printf "%.3f", (w < 0) ? 0 : w }')
  se=$("$FF" -nostdin -hide_banner -nostats -ss "$w0" -t 2 -i "$WORK/voice_track.wav" -af silencedetect=n=-45dB:d=0.05 -f null - 2>&1 |
    awk '/silence_end/ && !got { for (i = 1; i <= NF; i++) if ($i == "silence_end:") { v = $(i + 1); got = 1 } } END { print v }')
  if [ -n "$se" ]; then awk -v a="$at" -v w="$w0" -v e="$se" 'BEGIN { printf "  %.3f -> %.3f\n", a, w + e }'
  else printf '  %s -> no silence before it (check that the previous line ends in time)\n' "$at"; fi
done
