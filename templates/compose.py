#!/usr/bin/env python3
"""Original music bed plus synced sound effects for house style explainers (see ../SKILL.md).

Everything is synthesized here with numpy: no samples, loops or downloaded
audio, so the result carries no third party license.

Copy this file into the work folder first and edit the copy: local_events() holds per video timings.
  cp <this repo or skill folder>/templates/compose.py .
  python3 compose.py --html explainer.html --video name.mp4 --mux-out name-music.mp4 --outdir audio
  python3 compose.py --html explainer.html --no-mux       audio only
Defaults: --html ./explainer.html, --video <html stem>.mp4, --mux-out <video stem>-music.mp4,
--outdir <html dir>/audio (created when missing).

How it follows the animation
  * Scene starts, durations and TOTAL are parsed from the SCENES array in explainer.html.
  * Every sound effect is written below as an offset local to its scene (the same
    numbers the scene code uses: click times, packet send/arrive, dropT, onT ...),
    so moving or stretching a scene in SCENES moves its effects with it.
  * The music grid is fitted to the timeline: the tempo is the value nearest 104 BPM
    that puts a whole number of bars between the drop (start of scene 2) and the
    final logo (start of the outro), so both land exactly on a downbeat.

Outputs (in --outdir)
  music_sfx.wav   final mix, 48 kHz stereo 24 bit
  music_bed.wav   music stem at the same gain as in the mix
  sfx.wav         effects stem at the same gain as in the mix
  events.json     every effect time used, plus the music grid
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import wave

import numpy as np

SR = 48000


def find_tool(name):
    # $FFMPEG / $FFPROBE, Homebrew, /usr/local, then PATH (same order as render.mjs)
    for p in (os.environ.get(name.upper()), f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}', shutil.which(name)):
        if p and os.path.exists(p):
            return p
    return name


FFMPEG = find_tool('ffmpeg')
FFPROBE = find_tool('ffprobe')
HERE = os.path.dirname(os.path.abspath(__file__))

TARGET_MUSIC_LUFS = -18.0
TP_CEILING_DB = -1.5          # limiter ceiling (true peak, 4x oversampled); AAC adds a little
TARGET_BPM = 104.0          # house default; parse_theme() overrides it from the HTML's THEME block
TRANSPOSE = 0               # semitones from D major; parse_theme() overrides it


# =====================================================================================
# small DSP toolkit
# =====================================================================================
def db(x):
    return 10 ** (x / 20)


def midi_hz(m):
    return 440.0 * 2 ** ((m + TRANSPOSE - 69) / 12)


def pan_gains(p):
    a = (np.clip(p, -1, 1) + 1) * math.pi / 4
    return math.cos(a) * math.sqrt(2), math.sin(a) * math.sqrt(2)


def place(bus, sig, t, pan=0.0, gain=1.0):
    """Add a mono or stereo signal into a (2, n) bus at time t (seconds)."""
    if sig.ndim == 1:
        gl, gr = pan_gains(pan)
        sig = np.vstack([sig * gl, sig * gr])
    i0 = int(round(t * SR))
    s0 = 0
    if i0 < 0:
        s0, i0 = -i0, 0
    n = min(sig.shape[1] - s0, bus.shape[1] - i0)
    if n > 0:
        bus[:, i0:i0 + n] += sig[:, s0:s0 + n] * gain


def fft_filter(x, fn):
    """Zero phase filter: fn(freqs) -> gain."""
    X = np.fft.rfft(x, axis=-1)
    X *= fn(np.fft.rfftfreq(x.shape[-1], 1 / SR))
    return np.fft.irfft(X, x.shape[-1], axis=-1)


def lp_gain(fc, order=2):
    return lambda f: 1 / np.sqrt(1 + (f / fc) ** (2 * order))


def hp_gain(fc, order=2):
    return lambda f: 1 / np.sqrt(1 + (fc / np.maximum(f, 1e-3)) ** (2 * order))


def fftconv(x, h):
    n = len(x) + len(h) - 1
    N = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(h, N), N)[:n]


def fade_edges(x, a=0.002, b=0.01):
    na, nb = int(a * SR), int(b * SR)
    if na:
        x[..., :na] *= np.linspace(0, 1, na)
    if nb:
        x[..., -nb:] *= np.linspace(1, 0, nb)
    return x


def norm_peak(x):
    m = np.max(np.abs(x))
    return x / m if m > 0 else x


def shaped_noise(dur, fc_fn, amp_fn, bw_oct=0.8, seed=0, stereo=True, N=1024, H=256):
    """Noise built frame by frame in the STFT domain with a moving band pass.
    fc_fn and amp_fn take an array of times (0..dur) and return Hz / gain."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    nfr = n // H + N // H + 1
    freqs = np.fft.rfftfreq(N, 1 / SR)
    tc = (np.arange(nfr) * H - N / 2) / SR
    tcc = np.clip(tc, 0, dur)
    fc = np.maximum(fc_fn(tcc), 30)
    G = np.exp(-0.5 * (np.log2(np.maximum(freqs, 10)[None, :] / fc[:, None]) / bw_oct) ** 2)
    G *= np.maximum(amp_fn(tcc), 0)[:, None]
    win = np.hanning(N)
    chans = []
    for c in range(2 if stereo else 1):
        spec = (rng.standard_normal(G.shape) + 1j * rng.standard_normal(G.shape)) * G
        fr = np.fft.irfft(spec, N, axis=1) * win
        out = np.zeros(nfr * H + N)
        for k in range(nfr):
            out[k * H:k * H + N] += fr[k]
        chans.append(out[N // 2:N // 2 + n])
    return np.vstack(chans) if stereo else chans[0]


def adsr(n, a, d, s, r, gate):
    t = np.arange(n) / SR
    att = 0.5 - 0.5 * np.cos(np.pi * np.clip(t / a, 0, 1))
    dec = s + (1 - s) * np.exp(-np.maximum(t - a, 0) / max(d, 1e-4))
    env = np.where(t < a, att, dec)
    env *= np.where(t < gate, 1.0, np.exp(-np.maximum(t - gate, 0) / r))
    return env


# =====================================================================================
# instruments
# =====================================================================================
def saw_lp(freq, n, fc_dec, dec=64, phase=0.0):
    """Band limited saw built additively, each harmonic weighted by a 3 pole low pass
    response at the (time varying) cutoff fc_dec, given every `dec` samples."""
    t = np.arange(n) / SR
    th = 2 * np.pi * freq * t + phase
    s1 = np.sin(th)
    c2 = 2 * np.cos(th)
    s_prev, s_cur = np.zeros(n), s1
    out = np.zeros(n)
    hmax = int(min(SR * 0.45 / freq, 80))
    for h in range(1, hmax + 1):
        w_dec = (1 / h) / np.sqrt(1 + (h * freq / fc_dec) ** 6)
        if w_dec.max() < 0.0015:
            break
        out += np.repeat(w_dec, dec)[:n] * s_cur
        s_prev, s_cur = s_cur, c2 * s_cur - s_prev
    return out


def pad_note(midi, gate, fc_fn, t0, rng, a=0.35, r=0.7, detune=9.0, width=0.65):
    """Three detuned saws spread across the stereo field."""
    n = int((gate + 3.2 * r) * SR)
    dec = 64
    tdec = t0 + np.arange(n // dec + 1) * dec / SR
    fc = fc_fn(tdec)
    f = midi_hz(midi)
    env = adsr(n, a, 1.2, 0.85, r, gate)
    out = np.zeros((2, n))
    for k, (cents, p) in enumerate(((-detune, -width), (0.0, 0.0), (detune, width))):
        v = saw_lp(f * 2 ** (cents / 1200), n, fc, dec, rng.uniform(0, 2 * np.pi)) * env
        gl, gr = pan_gains(p)
        out[0] += v * gl
        out[1] += v * gr
    return fade_edges(out, 0.0, 0.02)


def fm_pluck(freq, bright=1.0, decay=0.2, dur=0.75):
    n = int(dur * SR)
    t = np.arange(n) / SR
    idx = (0.6 + 1.5 * bright) * np.exp(-t / 0.06)
    y = np.sin(2 * np.pi * freq * t + idx * np.sin(2 * np.pi * freq * t))
    y += 0.25 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-t / 0.05)
    amp = (1 - np.exp(-t / 0.0025)) * np.exp(-t / decay)
    return fade_edges(y * amp, 0.0, 0.02)


def bell(freq, dur=1.6, decay=0.55, bright=1.0):
    """Soft FM mallet bell, used for the lead line."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    vib = 1 + 0.0025 * np.sin(2 * np.pi * 5.2 * t) * np.clip((t - 0.15) / 0.3, 0, 1)
    ph = 2 * np.pi * freq * np.cumsum(vib) / SR
    idx = bright * (0.4 + 1.1 * np.exp(-t / 0.09))
    y = np.sin(ph + idx * np.sin(ph * 1.0))
    y += 0.18 * np.sin(2 * ph) * np.exp(-t / 0.3)
    amp = (1 - np.exp(-t / 0.006)) * np.exp(-t / decay)
    return fade_edges(y * amp, 0.0, 0.03)


def chime_tone(freq, dur=1.4, decay=0.5):
    """Glassy UI chime: sine plus a few soft partials."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * freq * t) * np.exp(-t / decay)
    y += 0.30 * np.sin(2 * np.pi * 2.0 * freq * t) * np.exp(-t / (decay * 0.45))
    y += 0.10 * np.sin(2 * np.pi * 3.01 * freq * t) * np.exp(-t / (decay * 0.2))
    y *= 1 - np.exp(-t / 0.002)
    return fade_edges(y, 0.0, 0.03)


def bass_note(freq, gate, r=0.06):
    n = int((gate + 5 * r) * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * freq * t) + 0.22 * np.sin(4 * np.pi * freq * t) + 0.06 * np.sin(6 * np.pi * freq * t)
    y = np.tanh(1.6 * y) / np.tanh(1.6)
    env = adsr(n, 0.006, 0.25, 0.75, r, gate)
    return fade_edges(y * env, 0.0, 0.01)


def kick(soft=1.0):
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    f = 46 + 105 * np.exp(-t / 0.032)
    ph = 2 * np.pi * np.cumsum(f) / SR
    y = np.sin(ph) * np.exp(-t / (0.22 * soft)) * (1 - np.exp(-t / 0.0015))
    rng = np.random.default_rng(7)
    click = fft_filter(rng.standard_normal(n), lambda fr: np.exp(-0.5 * (np.log2(np.maximum(fr, 10) / 3000) / 1.0) ** 2)) * np.exp(-t / 0.002)
    y = np.tanh(1.3 * (y + 0.12 * norm_peak(click)))
    return fade_edges(y, 0.0, 0.02)


def hat(seed, decay=0.028):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(100 + seed)
    y = fft_filter(rng.standard_normal(n), lambda f: hp_gain(7000, 3)(f) * lp_gain(14000, 2)(f))
    y = norm_peak(y) * np.exp(-t / decay) * (1 - np.exp(-t / 0.0008))
    return fade_edges(y, 0.0, 0.01)


def clap():
    n = int(0.6 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(55)
    nz = fft_filter(rng.standard_normal(n), lambda f: np.exp(-0.5 * (np.log2(np.maximum(f, 10) / 1500) / 0.9) ** 2))
    env = np.zeros(n)
    for k, o in enumerate((0.0, 0.011, 0.022)):
        env += np.where(t >= o, np.exp(-np.maximum(t - o, 0) / (0.006 if k < 2 else 0.11)), 0)
    return fade_edges(norm_peak(nz * env), 0.0, 0.02)


# =====================================================================================
# sound effects
# =====================================================================================
def sfx_click():
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    tr = fft_filter(rng.standard_normal(n), lambda f: hp_gain(1500, 2)(f) * lp_gain(6500, 2)(f)) * np.exp(-t / 0.0015)
    body = 0.55 * np.sin(2 * np.pi * 1450 * t) * np.exp(-t / 0.009) + 0.2 * np.sin(2 * np.pi * 2900 * t) * np.exp(-t / 0.004)
    low = 0.55 * np.sin(2 * np.pi * 210 * t) * np.exp(-t / 0.016)
    y = 0.6 * norm_peak(tr) + body + low
    return fade_edges(norm_peak(y), 0.0003, 0.01)


def sfx_whoosh(dur=0.9, peak=0.55, f0=260, f1=2400, f2=900, seed=0, bw=0.9, p0=-0.5, p1=0.5):
    def fc(t):
        u = np.clip(t / peak, 0, 1)
        v = np.clip((t - peak) / (dur - peak), 0, 1)
        return np.where(t < peak, f0 * (f1 / f0) ** (u ** 1.4), f1 * (f2 / f1) ** v)

    def amp(t):
        u = np.clip(t / peak, 0, 1)
        v = np.clip((t - peak) / (dur - peak), 0, 1)
        return np.where(t < peak, u ** 2.2, (1 - v) ** 1.8)
    x = shaped_noise(dur, fc, amp, bw, seed, stereo=False)
    x = norm_peak(x)
    t = np.arange(len(x)) / SR
    p = p0 + (p1 - p0) * np.clip(t / dur, 0, 1)
    a = (p + 1) * np.pi / 4
    return np.vstack([x * np.cos(a) * np.sqrt(2), x * np.sin(a) * np.sqrt(2)])


def sfx_pop(freq=900):
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    f = freq * (1 + 0.55 * np.exp(-t / 0.01))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.045) * (1 - np.exp(-t / 0.0015))
    y += 0.25 * np.sin(2 * np.pi * np.cumsum(2 * f) / SR) * np.exp(-t / 0.02)
    return fade_edges(norm_peak(y), 0.0, 0.01)


def sfx_tick(freq=2600):
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.028) + 0.35 * np.sin(2 * np.pi * 1.5 * freq * t) * np.exp(-t / 0.012)
    y *= 1 - np.exp(-t / 0.0007)
    return fade_edges(norm_peak(y), 0.0, 0.01)


def sfx_chime(notes, gap=0.085, decay=0.5):
    dur = gap * (len(notes) - 1) + 1.6
    y = np.zeros(int(dur * SR))
    for k, m in enumerate(notes):
        c = chime_tone(midi_hz(m), 1.5, decay) * (0.85 ** k)
        i0 = int(k * gap * SR)
        y[i0:i0 + len(c)] += c[:len(y) - i0]
    return norm_peak(y)


def sfx_alert():
    """Gentle two note drop with a warm, rounded timbre (attention, not alarm)."""
    dur = 1.0
    y = np.zeros(int(dur * SR))
    for k, m in enumerate((71, 66)):
        n = int(0.8 * SR)
        t = np.arange(n) / SR
        f = midi_hz(m)
        v = (np.sin(2 * np.pi * f * t) + 0.18 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t / 0.05)) * np.exp(-t / 0.22) * (1 - np.exp(-t / 0.004))
        i0 = int(k * 0.13 * SR)
        y[i0:i0 + n] += v[:len(y) - i0]
    return fade_edges(norm_peak(y), 0.0, 0.02)


def sfx_blip():
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    f = 650 * (2.0 ** np.clip(t / 0.07, 0, 1))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.035) * (1 - np.exp(-t / 0.003))
    return fade_edges(norm_peak(y), 0.0, 0.01)


def sfx_scan(dur=1.5):
    x = shaped_noise(dur, lambda t: 900 * (4.5 ** (t / dur)), lambda t: np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5, 0.5, 21, stereo=True)
    return norm_peak(x)


def sfx_scribble(dur, speed_fn):
    x = shaped_noise(dur, lambda t: 1800 + 1600 * speed_fn(t), lambda t: 0.15 + 0.85 * speed_fn(t), 0.7, 31, stereo=False)
    t = np.arange(len(x)) / SR
    x *= np.clip(t / 0.12, 0, 1) * np.clip((dur - t) / 0.12, 0, 1)
    return norm_peak(x)


def sfx_thump():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 70 + 80 * np.exp(-t / 0.03)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.1) * (1 - np.exp(-t / 0.002))
    p = sfx_pop(620)
    y[:len(p)] += 0.35 * p
    return fade_edges(norm_peak(y), 0.0, 0.02)


def sfx_land(freq=2350):
    n = int(0.2 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(77)
    nz = fft_filter(rng.standard_normal(n), lambda f: lp_gain(2500, 2)(f) * hp_gain(300, 1)(f)) * np.exp(-t / 0.018)
    y = 0.8 * norm_peak(nz) + 0.6 * np.sin(2 * np.pi * 260 * t) * np.exp(-t / 0.025)
    y[:len(sfx_tick(freq))] += 0.35 * sfx_tick(freq)[:n]
    return fade_edges(norm_peak(y), 0.0003, 0.01)


def sfx_lock():
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(91)
    y = np.zeros(n)
    for o, g in ((0.0, 0.6), (0.018, 1.0)):            # latch, then the snap
        tt = np.maximum(t - o, 0)
        on = t >= o
        nz = fft_filter(rng.standard_normal(n), hp_gain(2500, 2)) * np.exp(-tt / 0.0025)
        ring = sum(a * np.sin(2 * np.pi * f * tt) * np.exp(-tt / d) for f, a, d in ((2950, 0.5, 0.03), (4370, 0.3, 0.02), (6100, 0.15, 0.012)))
        knock = 0.6 * np.sin(2 * np.pi * 320 * tt) * np.exp(-tt / 0.02)
        y += g * on * (0.5 * norm_peak(nz) + ring + knock)
    return fade_edges(norm_peak(y), 0.0003, 0.01)


SFX_SEND = {'chime': 0.28, 'confirm': 0.28, 'alert': 0.22, 'pop': 0.12, 'tick': 0.15, 'whoosh': 0.18,
            'gather': 0.2, 'swish': 0.12, 'scan': 0.15, 'scribble': 0.08, 'click': 0.06, 'lock': 0.1,
            'land': 0.08, 'thump': 0.1, 'blip': 0.15, 'count': 0.1}


def render_sfx(ev):
    k, a = ev['kind'], ev.get('args', {})
    if k == 'click':
        return sfx_click()
    if k == 'whoosh':
        return sfx_whoosh(**a)
    if k == 'gather':
        return sfx_whoosh(dur=a['dur'], peak=a['dur'] * 0.82, f0=380, f1=1900, f2=700, seed=5, bw=1.0, p0=a.get('p0', 0.0), p1=0.0)
    if k == 'swish':
        return sfx_whoosh(dur=0.42, peak=0.2, f0=1200, f1=4200, f2=2200, seed=a.get('seed', 9), bw=0.8, p0=-0.3, p1=0.4)
    if k == 'pop':
        return sfx_pop(a.get('freq', 900))
    if k in ('tick', 'count'):
        return sfx_tick(a.get('freq', 2600))
    if k in ('chime', 'confirm'):
        return sfx_chime(a['notes'], a.get('gap', 0.085), a.get('decay', 0.5))
    if k == 'alert':
        return sfx_alert()
    if k == 'blip':
        return sfx_blip()
    if k == 'scan':
        return sfx_scan(a['dur'])
    if k == 'scribble':
        return sfx_scribble(a['dur'], a['speed'])
    if k == 'thump':
        return sfx_thump()
    if k == 'land':
        return sfx_land(a.get('freq', 2350))
    if k == 'lock':
        return sfx_lock()
    raise ValueError(k)


# =====================================================================================
# timeline: scenes from the HTML, effects as scene local offsets
# =====================================================================================
def parse_timeline(html_path):
    src = open(html_path, encoding='utf-8').read()
    total = float(re.search(r'const TOTAL\s*=\s*([\d.]+)', src).group(1))
    scenes = [(m.group(1), float(m.group(2)), float(m.group(3)))
              for m in re.finditer(r"\{\s*id:\s*'(\w+)',\s*start:\s*([\d.]+),\s*dur:\s*([\d.]+)", src)]
    if not scenes:
        raise SystemExit('could not find SCENES in ' + html_path)
    return total, scenes


def parse_theme(html_path):
    """Music settings from the HTML's THEME block (`const THEME = {...};` between THEME START and THEME END).
    Sets TARGET_BPM, TRANSPOSE, PROG and ARP16 so the same theme always gives the same music.
    Files without a THEME block (the reference, older videos) keep the house defaults."""
    global TARGET_BPM, TRANSPOSE, PROG, ARP16
    src = open(html_path, encoding='utf-8').read()
    m = re.search(r"/\* THEME START \*/\s*const THEME\s*=\s*(\{.*?\});\s*/\* THEME END \*/", src, re.S)
    if not m:
        return None
    try:
        theme = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise SystemExit(f'THEME block is not valid JSON (write it with apply-theme.mjs or as strict JSON): {e}')
    mu = theme.get('music', {})
    TARGET_BPM = float(mu.get('bpm', TARGET_BPM))
    TRANSPOSE = int(mu.get('transpose', TRANSPOSE))
    prog = mu.get('prog')
    if prog:
        bad = [x for x in prog if x not in CHORDS]
        if bad:
            raise SystemExit(f'THEME music.prog has unknown chords {bad}; use I, V, vi, IV')
        PROG = list(prog)
    arp = mu.get('arp')
    if arp:
        if len(arp) != 16 or any(int(x) not in (0, 1, 2, 3) for x in arp):
            raise SystemExit('THEME music.arp needs 16 steps of 0..3')
        ARP16 = [int(x) for x in arp]
    return theme


def parse_stats(html_path):
    """Outro pills from the one line `const STATS = [...]` (or the reference's `const stats`).
    Returns numbers for counter pills ([n, 'label']) or labels for word pills ('Simple lists')."""
    with open(html_path, encoding='utf-8') as fh:
        m = re.search(r"^[ \t]*const\s+(?:STATS|stats)\s*=\s*\[(.*)\];", fh.read(), re.M)
    if not m:
        return []
    nums = re.findall(r"\[\s*([\d.]+)\s*,", m.group(1))
    if nums:
        return [int(float(x)) if float(x).is_integer() else float(x) for x in nums]
    return re.findall(r"'([^']*)'", m.group(1))


PENTA = [62, 64, 66, 69, 71, 74, 76, 78, 81, 83, 86, 88, 90, 93]   # D major pentatonic


def local_events(stats=()):
    """(scene id, local time, kind, gain dB, pan, args, source note). Local times mirror explainer.html.
    Events for scene ids missing from SCENES are skipped, so unused blocks are harmless."""
    E = []

    def add(sc, lt, kind, gdb, pan=0.0, src='', **args):
        E.append(dict(scene=sc, lt=lt, kind=kind, gain_db=gdb, pan=pan, source=src, args=args))

    def cpan(x):                       # cursor x in px -> subtle pan
        return round((x - 960) / 960 * 0.4, 3)

    # 1. hook
    add('hook', 0.32, 'pop', -24, 0, 'logo scales in, EB(lt, 0.25, 0.95)', freq=820)
    add('hook', 0.90, 'swish', -31, 0, 'wordmark wipe, E(lt, 0.9, 1.7)', seed=4)
    add('hook', 1.33, 'chime', -24, 0, 'logo check finishes drawing, E(lt, 0.7, 1.35)', notes=[86, 90], gap=0.07)

    # 2. before: icons pop, lasso, click, fly in, dashboard
    for i in range(9):
        add('before', 0.24 + i * 0.12, 'tick', -34, round(-0.35 + 0.08 * i, 2), f'mess icon {i} pops, EB(lt, 0.2 + {i}*0.12, ...)',
            freq=midi_hz([76, 81, 78, 83, 79, 86, 81, 88, 83][i]) * 2)
    lasso_t0, lasso_t1 = 1.7, 4.2

    def lasso_speed(t, a=lasso_t0, b=lasso_t1):          # derivative of esine(lin(t)), normalized to 0..1
        u = np.clip(t / (b - a), 0, 1)
        return np.sin(np.pi * u)
    add('before', lasso_t0, 'scribble', -37, 0.1, 'cursor draws the lasso, LASSO.t0..t1', dur=lasso_t1 - lasso_t0, speed=lasso_speed)
    add('before', lasso_t1, 'chime', -27, 0.35, 'lasso closes, LASSO.t1', notes=[81, 88], gap=0.05, decay=0.35)
    add('before', lasso_t1 + 0.15, 'click', -16, cpan(1800), 'cursor click, clicks: [LASSO.t1 + 0.15]')
    add('before', 4.45, 'gather', -24, 0, 'icons fly into the frame, fly0 = 4.45, land by 5.8', dur=1.3)
    add('before', 5.85, 'thump', -22, 0, 'dashboard solidifies, solid0 = 5.85')
    for i in range(3):
        add('before', 6.0 + (0.2 + i * 0.08) * 1.7 + 0.08, 'tick', -33, -0.2 + 0.2 * i, f'KPI card {i} pops', freq=midi_hz([81, 83, 86][i]) * 2)

    # 3. automatic close: clock ding, packets, done badge
    add('close', 0.3, 'pop', -28, -0.1, 'clock pops in, EB(lt, 0.2, 0.8)', freq=760)
    add('close', 2.6, 'chime', -22, -0.15, 'clock hits 4:30, ding = lin(lt, 2.6, 3.4)', notes=[81, 86], gap=0.0, decay=0.7)
    arrive_notes = [81, 83, 86, 88, 90]
    for i in range(5):
        send = 2.9 + i * 0.75
        add('close', send, 'blip', -33, -0.45, f'VPS 0{i + 1} sends its close, send({i})')
        add('close', send + 1.45, 'chime', -25, 0.35, f'packet {i} arrives, arrive({i})', notes=[arrive_notes[i]], decay=0.4)
    add('close', 8.05, 'confirm', -23, -0.1, "'Done automatically' badge, EB(lt, 8.0, 8.6)", notes=[86, 90, 93], gap=0.07)

    # 4. live status
    for i in range(6):
        add('status', 0.9 + i * 0.35, 'tick', -30, -0.3, f'status dot {i} lights green, onT({i})', freq=midi_hz([74, 76, 78, 81, 83, 86][i]) * 2)
    add('status', 3.2, 'scan', -33, 0, 'refresh scan band, scan0..scan1', dur=1.5)
    add('status', 3.2 + 1.5 * 3.5 / 6, 'alert', -24, -0.3, 'ACC 04 turns amber, amberT')
    add('status', 6.45, 'click', -16, cpan(254), 'cursor click, clicks: [6.45]')
    add('status', 6.8, 'pop', -25, 0.4, 'detail card opens, EB(lt, 6.75, 7.45)', freq=880)

    # 5. algorithms
    add('algos', 1.85, 'pop', -26, 0.0, "'Hot' badge, EB(lt, 1.8, 2.3)", freq=980)
    add('algos', 3.5, 'click', -16, cpan(202), 'cursor click Algo A, c1 = 3.5')
    add('algos', 4.2, 'click', -16, cpan(202), 'cursor click Algo B, c2 = 4.2')
    add('algos', 7.0, 'chime', -29, -0.2, 'combined line completes, uc = E(lt, 5.5, 7.0)', notes=[86], decay=0.35)
    add('algos', 7.25, 'swish', -33, 0.3, 'desk dot strip appears, 7.2 + k*0.05', seed=12)
    add('algos', 7.85, 'tick', -30, 0.35, 'outlier dot starts pulsing, lt > 7.8', freq=midi_hz(81) * 2)
    add('algos', 9.0, 'click', -16, cpan(1522), 'cursor click outlier, c3 = 9.0')
    add('algos', 9.85, 'tick', -29, 0.3, "'Differs' highlight, EB(lt, c3 + 0.8, c3 + 1.3)", freq=midi_hz(78) * 2)

    # 6. reports
    add('reports', 2.35, 'click', -15, cpan(400), "cursor click 'Build report', click = 2.35")
    add('reports', 2.55, 'swish', -28, 0, 'pages fan out, t0 = 2.55 + k*0.13', seed=7)
    for k in range(4):
        add('reports', 4.7 + k * 0.55 + 0.95, 'land', -27, 0.45, f'report page {k} lands in the tray, dropT({k}) + 0.95',
            freq=midi_hz([81, 83, 86, 88][k]) * 2)
    add('reports', 4.7 + 3 * 0.55 + 1.05, 'confirm', -23, 0.45, "all four in, '4 reports ready to send'", notes=[81, 86, 90], gap=0.08)

    # 7. history (music carries it; one soft mark when the curve finishes)
    add('history', 7.6, 'chime', -28, 0.4, 'cumulative curve finishes drawing, curveU = E(lt, 3.9, 7.6)', notes=[86, 93], gap=0.06, decay=0.4)

    # 8. each rep, their book
    for k in range(3):
        add('book', 0.35 + k * 0.15, 'pop', -30, [-0.4, 0, 0.4][k], f'Rep {k + 1} avatar, EB(lt, 0.2 + {k}*0.15, ...)', freq=[700, 790, 880][k])
        add('book', 2.4 + k * 0.12, 'lock', -24, [-0.4, 0, 0.4][k], f'lock {k + 1} snaps shut, E(lt, 2.1 + {k}*0.12, 2.4 + {k}*0.12)')
    add('book', 3.4, 'click', -16, cpan(972), 'cursor click Manager, mc = 3.4')
    add('book', 4.85, 'pop', -26, 0, "'Whole desk' chip, EB(lt, mc + 1.3, mc + 1.8)", freq=900)

    # ---- skill template scenes (explainer-template.html): 'title' and 'cards'.
    # For a new video, add a block per scene with your own scene ids and the local times from the scene code.
    # The reference blocks above (hook .. book) only fire for those scene ids; delete them or leave them.
    add('title', 0.32, 'pop', -24, 0, 'logo scales in, EB(lt, 0.25, 0.95)', freq=820)
    add('title', 0.90, 'swish', -31, 0, 'wordmark wipe, E(lt, 0.9, 1.7)', seed=4)
    add('title', 1.33, 'chime', -24, 0, 'logo check finishes drawing, E(lt, 0.7, 1.35)', notes=[86, 90], gap=0.07)
    for i in range(4):
        add('cards', 0.8 + i * 0.3, 'tick', -30, -0.35, f'status dot {i} lights, onT({i})', freq=midi_hz([74, 76, 78, 81][i]) * 2)
        send = 3.2 + 0.3 + i * 0.35
        add('cards', send, 'blip', -33, -0.3, f'packet {i} leaves, send({i})')
        add('cards', send + 1.2, 'chime', -25, 0.35, f'packet {i} arrives, arrive({i})', notes=[[81, 83, 86, 88][i]], decay=0.4)
    add('cards', 3.2, 'click', -16, cpan(490), "cursor click 'Sync now', click = 3.2")
    add('cards', 3.5 + 3 * 0.35 + 1.2 + 0.4, 'confirm', -23, 0, "'Done automatically' badge, doneT", notes=[86, 90, 93], gap=0.07)

    # outro (template and reference share it): logo check, then the STATS pills parsed from the HTML.
    # Word pills pop on EB(lt, t0, t0 + 0.6); counter pills tick while counting and on the settle.
    add('outro', 1.0, 'chime', -24, 0, 'outro logo check drawn, E(lt, 0.4, 1.0)', notes=[86, 90, 93], gap=0.09, decay=0.6)
    for i, st in enumerate(stats):
        t0 = 1.1 + i * 0.2
        pan = round(-0.4 + 0.8 * i / max(1, len(stats) - 1), 2)
        if isinstance(st, str):
            add('outro', round(t0 + 0.08, 4), 'pop', -28, pan, f"word pill {i} '{st}' pops, EB(lt, {t0:.1f}, {t0 + 0.6:.1f})",
                freq=[760, 850, 940][i % 3])
            continue
        nmax = st
        # two soft ticks while the number runs (value at 50% and 90%), then a brighter tick
        # when the shown number settles on its final value (eased value within 0.5 of n)
        for j, frac in enumerate((0.5, 0.9, 1 - 0.5 / nmax)):
            x = 1 - (1 - frac) ** (1 / 5)      # invert the 1 - (1 - x)^5 easing
            final = j == 2
            add('outro', round(t0 + x, 4), 'count', -27 if final else -34, pan,
                f'stat chip {i} counts to {nmax}, lin(lt, {t0:.1f}, {t0 + 1:.1f}) eased' + (' (settles)' if final else ''),
                freq=midi_hz([86, 88, 90][i % 3]) * 2 if final else 1750 + 120 * j + 90 * i)
    # keep the counters from chattering: no two count ticks closer than 70 ms (settle ticks win)
    cnt = sorted([e for e in E if e['kind'] == 'count'], key=lambda e: e['lt'])
    keep, last = [], -9.0
    for e in cnt:
        if e['lt'] - last >= 0.07 or '(settles)' in e['source']:
            if keep and e['lt'] - last < 0.07:
                keep.pop()
            keep.append(e)
            last = e['lt']
    E = [e for e in E if e['kind'] != 'count'] + keep
    return E


def build_events(scenes, stats=()):
    starts = {sid: st for sid, st, _ in scenes}
    out = []
    for ev in local_events(stats):
        if ev['scene'] not in starts:
            continue
        ev = dict(ev)
        ev['t'] = round(starts[ev['scene']] + ev['lt'], 4)
        out.append(ev)
    # a gentle whoosh on every scene transition, peaking on the boundary
    for k, (sid, st, _) in enumerate(scenes[1:], 1):
        d = 1 if k % 2 else -1
        out.append(dict(scene=sid, lt=0.0, t=round(st - 0.5, 4), kind='whoosh', gain_db=-21, pan=0.0,
                        source=f'scene transition into {sid} at {st:g} s (cross fade {st - 0.5:g}..{st + 0.5:g})',
                        args=dict(dur=0.95, peak=0.5, f0=240, f1=2300 + 150 * (k % 3), f2=800, seed=40 + k, p0=-0.45 * d, p1=0.45 * d)))
    out.sort(key=lambda e: e['t'])
    return out


# =====================================================================================
# music
# =====================================================================================
CHORDS = {
    'I':  dict(pad=[50, 62, 66, 69], arp=[62, 66, 69, 74], bass=38),
    'V':  dict(pad=[57, 61, 64, 69], arp=[61, 64, 69, 73], bass=45),
    'vi': dict(pad=[59, 62, 66, 71], arp=[62, 66, 71, 74], bass=47),
    'IV': dict(pad=[55, 62, 67, 71], arp=[62, 67, 71, 74], bass=43),
}
PROG = ['I', 'V', 'vi', 'IV']
ARP16 = [0, 1, 2, 3, 2, 1, 2, 3, 0, 1, 2, 3, 2, 3, 1, 2]
LEAD_P1 = [[(0, 78, 1.0), (1, 76, 0.5), (1.5, 74, 1.0), (2.5, 76, 0.5), (3, 78, 1.0)],
           [(0, 76, 1.5), (1.5, 73, 0.5), (2, 76, 1.0), (3, 81, 1.0)],
           [(0, 78, 1.5), (1.5, 74, 0.5), (2, 71, 1.0), (3, 74, 1.0)],
           [(0, 79, 1.0), (1, 78, 0.5), (1.5, 76, 1.0), (2.5, 74, 0.5), (3, 76, 1.0)]]
LEAD_P2 = [[(0, 81, 1.0), (1, 78, 0.5), (1.5, 81, 1.0), (2.5, 83, 0.5), (3, 86, 1.0)],
           [(0, 85, 1.5), (1.5, 81, 0.5), (2, 76, 1.0), (3, 81, 1.0)],
           [(0, 83, 1.0), (1, 81, 0.5), (1.5, 78, 1.0), (2.5, 74, 0.5), (3, 78, 1.0)],
           [(0, 79, 1.5), (1.5, 81, 0.5), (2, 83, 1.0), (3, 81, 1.0)]]
LEAD_PREP = [[(0, 78, 2.0), (2, 81, 2.0)],
             [(0, 79, 2.0), (2, 83, 2.0)],
             [(0, 81, 1.5), (1.5, 85, 0.5), (2, 88, 2.0)]]


def music_grid(total, scenes):
    drop = scenes[1][1]
    land = scenes[-1][1]
    span = land - drop
    nbars = max(4, round(span / (240.0 / TARGET_BPM)))
    bar = span / nbars
    intro_bars = 2 if drop >= 2 * bar + 0.2 else 1
    g = dict(bpm=round(240.0 / bar, 3), bar=bar, beat=bar / 4, drop=drop, land=land, nbars=nbars,
             intro_bars=intro_bars, start=drop - intro_bars * bar, total=total)
    n = nbars
    if n >= 16:
        g['sections'] = dict(a1=[0, min(4, n // 4)], a2=[min(4, n // 4), max(8, round(n * 0.26))],
                             b=[max(8, round(n * 0.26)), round(n * 0.52)], c=[round(n * 0.52), n - 3],
                             prep=[n - 3, n], land=[n, n + 1])
    else:
        # short videos (skill template, teasers): same arc, sections scaled to the bars available,
        # always at least one bar of the full energy section 'c'
        pr = min(3, max(1, n // 4))
        r = n - pr
        a1 = max(1, round(r * 0.15))
        a2 = max(a1, round(r * 0.3))
        b_ = max(a2, round(r * 0.55))
        b_ = min(b_, r - 1)
        a2, a1 = min(a2, b_), min(a1, b_)
        g['sections'] = dict(a1=[0, a1], a2=[a1, a2], b=[a2, b_], c=[b_, r], prep=[r, n], land=[n, n + 1])
    return g


def section_of(g, b):
    if b < 0:
        return 'intro'
    for k, (a, z) in g['sections'].items():
        if a <= b < z:
            return k
    return 'land'


def chord_of(g, b):
    n = g['nbars']
    if b >= n:
        return 'I'
    if b == n - 1:
        return 'V'
    if b == n - 2:
        return 'IV'
    return PROG[b % 4]


def render_music(g, n_total):
    rng = np.random.default_rng(2026)
    bar, beat, drop = g['bar'], g['beat'], g['drop']
    s16 = bar / 16
    T = lambda b, step=0.0: drop + b * bar + step * s16
    secs = g['sections']
    nb = g['nbars']
    sec_t = {k: (T(a), T(z)) for k, (a, z) in secs.items()}

    buses = {k: np.zeros((2, n_total)) for k in ('pad', 'pluck', 'bass', 'kick', 'hat', 'clap', 'lead', 'fx')}

    # pad cutoff curve: closed in the intro, opening with each section, settling at the end
    fc_pts = [(g['start'], 320), (drop - 0.1, 1050), (sec_t['a2'][0], 1250), (sec_t['b'][0], 1650),
              (sec_t['c'][0], 2200), (sec_t['prep'][0], 2400), (g['land'] - 0.05, 3000), (g['land'] + 0.4, 2300), (g['total'], 650)]
    fx_, fy_ = zip(*fc_pts)

    def pad_fc(t):
        return np.interp(t, fx_, fy_) * (1 + 0.12 * np.sin(2 * np.pi * 0.11 * t))

    kicks = []
    for b in range(-g['intro_bars'], nb + 1):
        sec = section_of(g, b)
        ch = CHORDS[chord_of(g, b)]
        t0 = T(b)
        # ---- pad
        if sec == 'land':
            gate = g['total'] - t0 - 1.5
            for m in [38 + 12, 57, 62, 66, 69, 74, 78]:
                place(buses['pad'], pad_note(m, gate, pad_fc, t0, rng, a=0.08, r=1.4, detune=8), t0, gain=0.8 if m < 56 else 0.62)
        else:
            a = 1.1 if b == -g['intro_bars'] else (0.45 if b == -1 else 0.18)
            for m in ch['pad']:
                place(buses['pad'], pad_note(m, bar - 0.02, pad_fc, t0, rng, a=a, r=0.55), t0, gain=0.75 if m < 60 else 1.0)
        # ---- pluck arpeggio
        if sec == 'land':
            notes = [86, 81, 78, 74, 69, 66, 62]
            for k, m in enumerate(notes):
                place(buses['pluck'], fm_pluck(midi_hz(m), 0.6, 0.35, 1.2), t0 + k * beat * 0.5, pan=0.3 * (-1) ** k, gain=0.9 * 0.86 ** k)
        else:
            for st in range(16):
                if sec in ('intro', 'a1') and st % 2:
                    if not (b == -1 and st >= 8):
                        continue
                idx = ARP16[st]
                m = ch['arp'][idx]
                if sec in ('c', 'prep') and st in (6, 14):
                    m += 12
                vel = 1.0 if st % 4 == 0 else (0.78 if st % 2 == 0 else 0.6)
                bright = {'intro': 0.25, 'a1': 0.5, 'a2': 0.65, 'b': 0.85, 'c': 1.0, 'prep': 1.0}[sec]
                if sec == 'intro':
                    prog = (T(b, st) - g['start']) / (drop - g['start'])
                    vel *= 0.35 + 0.65 * prog
                    bright = 0.15 + 0.6 * prog
                jitter = rng.normal(0, 0.002)
                place(buses['pluck'], fm_pluck(midi_hz(m), bright, 0.16 + 0.08 * bright), T(b, st) + jitter,
                      pan=0.28 * (1 if st % 2 else -1), gain=vel)
        # ---- bass
        if sec in ('a2',):
            place(buses['bass'], bass_note(midi_hz(ch['bass']), bar * 0.5 - 0.05), t0, gain=0.7)
            place(buses['bass'], bass_note(midi_hz(ch['bass']), bar * 0.5 - 0.05), T(b, 8), gain=0.6)
        elif sec in ('b', 'c', 'prep'):
            for e8 in range(8):
                m = ch['bass'] + (12 if e8 == 7 else 0)
                place(buses['bass'], bass_note(midi_hz(m), s16 * 2 * 0.8), T(b, e8 * 2), gain=1.0 if e8 % 2 == 0 else 0.8)
        elif sec == 'land':
            place(buses['bass'], bass_note(midi_hz(38), 3.2, r=0.9), t0, gain=1.0)
        # ---- drums
        kick_beats = []
        if sec == 'a1':
            kick_beats = [0, 2]
        elif sec in ('a2', 'b', 'c') or (sec == 'prep' and b < nb - 1):
            kick_beats = [0, 1, 2, 3]
        elif sec == 'prep':
            kick_beats = [0, 1]
        elif sec == 'land':
            kick_beats = [0]
        for kb in kick_beats:
            kicks.append(T(b, kb * 4))
            place(buses['kick'], kick(1.6 if sec == 'land' else 1.0), T(b, kb * 4), gain=1.0 if kb % 2 == 0 else 0.88)
        if sec in ('a1', 'a2', 'b', 'c', 'prep') or b == -1:
            for st in range(16):
                ramp_bar = (b == -1) or (sec == 'prep' and b == nb - 1)
                if ramp_bar:
                    vel = 0.12 + 0.75 * (st / 15) ** 1.5
                elif st % 4 == 2:
                    vel = 0.85 if sec != 'a1' else 0.65
                elif sec in ('b', 'c', 'prep') and st % 2 == 1:
                    vel = 0.28 if st % 4 == 3 else 0.2
                else:
                    continue
                dec = 0.075 if (st == 14 and sec in ('b', 'c') and b % 2 == 1) else 0.028
                place(buses['hat'], hat(st + 16 * (b % 3), dec), T(b, st) + rng.normal(0, 0.0015), pan=0.22, gain=vel)
        if sec in ('b', 'c') or (sec == 'prep' and b < nb - 1):
            for st in (4, 12):
                place(buses['clap'], clap(), T(b, st), pan=-0.05, gain=1.0)
        # ---- lead bell
        if sec in ('c', 'prep', 'land'):
            if sec == 'c':
                rel = b - secs['c'][0]
                phrase = LEAD_P2 if (rel // 4) % 2 == 1 else LEAD_P1
                line = phrase[rel % 4]
            elif sec == 'prep':
                line = LEAD_PREP[b - secs['prep'][0]]
            else:
                line = [(0, 86, 4.0)]
            for (bt, m, du) in line:
                place(buses['lead'], bell(midi_hz(m), dur=max(1.2, du * beat + 1.0), decay=0.35 + 0.25 * du * beat),
                      T(b, bt * 4), pan=0.0, gain=0.9)

    # ---- risers and impacts (music fx)
    def riser(t_end, dur, seed):
        x = shaped_noise(dur, lambda t: 300 * (25 ** (t / dur) ** 1.3), lambda t: (t / dur) ** 2.2, 0.9, seed, stereo=True)
        place(buses['fx'], norm_peak(x), t_end - dur)

    def impact(t, big=1.0, seed=3):
        n = int(3.0 * SR)
        tt = np.arange(n) / SR
        boom = np.sin(2 * np.pi * np.cumsum(42 + 30 * np.exp(-tt / 0.08)) / SR) * np.exp(-tt / (0.6 * big))
        rr = np.random.default_rng(seed)
        spl = fft_filter(rr.standard_normal((2, n)), lambda f: hp_gain(3000, 2)(f) * lp_gain(11000, 1)(f)) * np.exp(-tt / (0.5 * big))
        x = np.vstack([boom, boom]) * 0.7 + 0.35 * spl / np.max(np.abs(spl))
        place(buses['fx'], fade_edges(x * (1 - np.exp(-tt / 0.002)), 0, 0.05), t)
    riser(drop, g['drop'] - g['start'], 61)
    impact(drop, 0.6)
    riser(g['land'], bar * 1.0, 62)
    impact(g['land'], 1.3, 4)

    # ---- sidechain pump from the kick
    t = np.arange(n_total) / SR
    duck = np.zeros(n_total)
    for tk in kicks:
        i0 = int(tk * SR)
        m = min(n_total - i0, int(0.45 * SR))
        if m <= 0:
            continue
        tt = np.arange(m) / SR
        shape = np.clip(tt / 0.006, 0, 1) * np.exp(-tt / 0.13)
        duck[i0:i0 + m] = np.maximum(duck[i0:i0 + m], shape)
    for k, depth in (('pad', 0.38), ('bass', 0.55), ('pluck', 0.2), ('lead', 0.12)):
        buses[k] *= 1 - depth * duck

    # ---- balance each bus by its RMS over the full energy section
    c0, c1 = int(sec_t['c'][0] * SR), int(sec_t['c'][1] * SR)
    target = dict(pad=-23.0, pluck=-25.5, bass=-25.0, kick=-23.5, hat=-35.0, clap=-34.0, lead=-28.0)
    for k, tdb in target.items():
        r = np.sqrt(np.mean(buses[k][:, c0:c1] ** 2)) if c1 > c0 else 0.0
        if not r > 0:                       # bus silent in 'c' (very short timeline): measure the whole bus
            r = np.sqrt(np.mean(buses[k] ** 2))
        if r > 0:
            buses[k] *= db(tdb) / r
    fx = buses['fx']
    act = np.abs(fx).max(axis=0) > 1e-4
    buses['fx'] *= db(-27.0) / np.sqrt(np.mean(fx[:, act] ** 2))

    # ---- ping pong delay (dotted eighth) on pluck and lead
    dsend = 0.32 * buses['pluck'].mean(axis=0) + 0.38 * buses['lead'].mean(axis=0)
    dsend = fft_filter(dsend, lambda f: lp_gain(3500, 2)(f) * hp_gain(250, 1)(f))
    wet = ping_pong(dsend, 0.75 * beat, 0.42, 7, n_total)

    # ---- reverb
    rsend = (0.22 * buses['pad'] + 0.3 * buses['pluck'] + 0.42 * buses['lead'] + 0.35 * buses['clap']
             + 0.05 * buses['hat'] + 0.3 * buses['fx']).mean(axis=0) + 0.3 * wet.mean(axis=0)
    rev = reverb(rsend, n_total, seed=11, rt=1.9)

    dry = sum(buses.values())
    music = dry + 0.75 * wet + 0.5 * rev
    music = fft_filter(music, hp_gain(28, 2))
    return music, kicks, buses


def ping_pong(x, d, fb, reps, n_total):
    out = np.zeros((2, n_total))
    D = int(round(d * SR))
    cur = x.copy()
    for r in range(1, reps + 1):
        cur = np.convolve(cur, [0.2, 0.6, 0.2], mode='same') * fb
        ch = (r + 1) % 2
        out[ch, r * D:] += cur[:n_total - r * D]
    return out


_IR_CACHE = {}


def make_ir(seed, rt):
    key = (seed, rt)
    if key in _IR_CACHE:
        return _IR_CACHE[key]
    rng = np.random.default_rng(seed)
    L = int(rt * 1.25 * SR)
    t = np.arange(L) / SR
    bands = [(0, 250, 1.1), (250, 1200, 1.0), (1200, 4000, 0.75), (4000, 24000, 0.45)]
    ir = np.zeros((2, L))
    for c in range(2):
        nz = rng.standard_normal(L)
        X = np.fft.rfft(nz)
        f = np.fft.rfftfreq(L, 1 / SR)
        for lo, hi, k in bands:
            Xb = np.where((f >= lo) & (f < hi), X, 0)
            ir[c] += np.fft.irfft(Xb, L) * np.exp(-6.9 * t / (rt * k))
    pre = int(0.018 * SR)
    ir = np.concatenate([np.zeros((2, pre)), ir], axis=1)
    ir *= np.clip(np.arange(ir.shape[1]) / (0.012 * SR), 0, 1)       # soft onset
    for c in range(2):                                               # a few early reflections
        for dt, a in ((0.011, 0.5), (0.019, 0.35), (0.029, 0.28), (0.041, 0.2)):
            ir[c, pre + int((dt + 0.003 * c) * SR)] += a * np.std(ir[c, pre:pre + 4800]) * 6
    ir /= np.sqrt(np.sum(ir ** 2) / 2)
    _IR_CACHE[key] = ir
    return ir


def reverb(x, n_total, seed=11, rt=1.8):
    ir = make_ir(seed, rt)
    x = fft_filter(x, lambda f: hp_gain(180, 1)(f) * lp_gain(7000, 1)(f))
    out = np.vstack([fftconv(x, ir[0])[:n_total], fftconv(x, ir[1])[:n_total]])
    return out


# =====================================================================================
# mastering helpers
# =====================================================================================
def write_wav(path, x):
    x = np.clip(x, -1, 1 - 2 ** -23)
    q = np.ascontiguousarray(np.round(x.T * (2 ** 23 - 1)).astype("<i4"))
    b = q.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(b)


def ffmpeg_ebur128(path):
    p = subprocess.run([FFMPEG, '-hide_banner', '-nostats', '-i', path, '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True)
    txt = p.stderr[p.stderr.rfind('Summary:'):]
    I = float(re.search(r'I:\s+(-?[\d.]+) LUFS', txt).group(1))
    tp = float(re.search(r'True peak:\s+Peak:\s+(-?[\d.inf]+) dBFS', txt).group(1))
    lra = float(re.search(r'LRA:\s+(-?[\d.]+) LU', txt).group(1))
    return I, tp, lra


def true_peak_env(x, os_=4):
    """Per sample max of |x| over both channels, from a 4x FFT oversampled copy."""
    n = x.shape[1]
    env = np.zeros(n)
    for c in range(2):
        X = np.fft.rfft(x[c])
        y = np.fft.irfft(X, n * os_) * os_
        env = np.maximum(env, np.abs(y).reshape(n, os_).max(axis=1))
    return env


def maxfilt(x, w):
    h = w // 2
    pad = np.pad(x, (h, h + (-(len(x) + 2 * h)) % w))
    blk = pad.reshape(-1, w)
    g = np.maximum.accumulate(blk, axis=1).ravel()
    hh = np.maximum.accumulate(blk[:, ::-1], axis=1)[:, ::-1].ravel()
    return np.maximum(hh[:len(x)], g[w - 1:w - 1 + len(x)])


def limiter_gain(x, ceiling_db, win_ms=12.0):
    """Look ahead peak limiter on the 4x oversampled envelope. Returns the gain curve.
    The reduction is spread with a max filter then smoothed with a Hann window of the
    same width, so every over-ceiling sample is fully covered with smooth attack/release."""
    ceil = db(ceiling_db)
    gain = np.ones(x.shape[1])
    for _ in range(3):
        env = true_peak_env(x * gain)
        if env.max() <= ceil:
            break
        red = 1 - np.minimum(1, ceil / np.maximum(env, 1e-9))
        w = int(win_ms * 1e-3 * SR) | 1
        red = maxfilt(red, w)
        k = np.hanning(w)
        k /= k.sum()
        red = fftconv(red, k)[w // 2:w // 2 + len(red)]
        gain *= 1 - np.clip(red * 1.02, 0, 0.95)
    return gain


def master_fades(n, fade_in=1.5, tail_end=None, tail=2.0):
    t = np.arange(n) / SR
    g = np.ones(n)
    g *= np.sin(0.5 * np.pi * np.clip(t / fade_in, 0, 1)) ** 2
    te = tail_end if tail_end is not None else n / SR
    u = np.clip((te - t) / tail, 0, 1)
    g *= np.sin(0.5 * np.pi * u) ** 2
    return g


# =====================================================================================
def main():
    ap = argparse.ArgumentParser(description='Music bed plus synced SFX for a house style explainer.')
    ap.add_argument('--html', default='explainer.html')
    ap.add_argument('--video', help='default <html stem>.mp4 next to the html')
    ap.add_argument('--mux-out', help='default <video stem>-music.mp4')
    ap.add_argument('--outdir', help='default <html dir>/audio, created when missing')
    ap.add_argument('--no-mux', action='store_true')
    args = ap.parse_args()
    args.html = os.path.abspath(args.html)
    if not os.path.exists(args.html):
        raise SystemExit('html not found: ' + args.html)
    stem = os.path.splitext(args.html)[0]
    args.video = os.path.abspath(args.video or stem + '.mp4')
    args.mux_out = os.path.abspath(args.mux_out or os.path.splitext(args.video)[0] + '-music.mp4')
    args.outdir = os.path.abspath(args.outdir or os.path.join(os.path.dirname(args.html), 'audio'))
    os.makedirs(args.outdir, exist_ok=True)
    if os.path.basename(HERE) == 'templates' and os.path.exists(os.path.join(os.path.dirname(HERE), 'SKILL.md')):
        print('note: this is the skill copy of compose.py. Copy it into the work folder and edit local_events() there.')

    total, scenes = parse_timeline(args.html)
    theme = parse_theme(args.html)
    if theme:
        print(f"theme {theme.get('name', '?')}: {TARGET_BPM:g} BPM target, transpose {TRANSPOSE:+d}, prog {' '.join(PROG)}")
    stats = parse_stats(args.html)
    n_total = int(round(total * SR))
    g = music_grid(total, scenes)
    print(f"timeline {total} s, {len(scenes)} scenes; tempo {g['bpm']} BPM, bar {g['bar']:.4f} s, "
          f"music starts {g['start']:.3f} s, drop {g['drop']} s, final logo {g['land']} s ({g['nbars']} bars)")
    if g['nbars'] < 8:
        print(f"note: only {g['nbars']} bars between the drop and the outro, so each section gets about one bar "
              f"(minimal arc, some sections empty). Expected for teasers under about 25 s.")

    # ---------------- music
    music, kicks, buses = render_music(g, n_total)
    tail_end = total - 0.06
    music *= master_fades(n_total, 1.5, tail_end, 2.0)
    tmp = os.path.join(args.outdir, '_music_tmp.wav')
    write_wav(tmp, music / np.max(np.abs(music)) * db(-3))
    I0, _, _ = ffmpeg_ebur128(tmp)
    music *= db(-3) / np.max(np.abs(music)) * db(TARGET_MUSIC_LUFS - I0)
    os.remove(tmp)

    # ---------------- effects
    events = build_events(scenes, stats)
    sfx = np.zeros((2, n_total))
    rs = np.zeros(n_total)
    for ev in events:
        sig = render_sfx(ev)
        place(sfx, sig, ev['t'], pan=ev['pan'], gain=db(ev['gain_db']))
        s = SFX_SEND.get(ev['kind'], 0.1)
        mono = sig if sig.ndim == 1 else sig.mean(axis=0)
        i0 = int(round(ev['t'] * SR))
        m = min(len(mono), n_total - i0)
        if m > 0:
            rs[i0:i0 + m] += mono[:m] * db(ev['gain_db']) * s
    sfx += 0.6 * reverb(rs, n_total, seed=12, rt=1.4)
    sfx *= master_fades(n_total, 0.01, tail_end, 0.4)

    # ---------------- master
    mix = music + sfx
    lg = limiter_gain(mix, TP_CEILING_DB)
    print(f'limiter: max gain reduction {-20 * np.log10(lg.min()):.2f} dB, '
          f'active on {100 * np.mean(lg < 0.999):.2f}% of samples')
    # the same gain curve goes on the stems, so music_bed.wav + sfx.wav == music_sfx.wav
    write_wav(os.path.join(args.outdir, 'music_sfx.wav'), mix * lg)
    write_wav(os.path.join(args.outdir, 'music_bed.wav'), music * lg)
    write_wav(os.path.join(args.outdir, 'sfx.wav'), sfx * lg)

    mI, mtp, mlra = ffmpeg_ebur128(os.path.join(args.outdir, 'music_bed.wav'))
    xI, xtp, xlra = ffmpeg_ebur128(os.path.join(args.outdir, 'music_sfx.wav'))
    print(f'music stem: {mI:.1f} LUFS, true peak {mtp:.2f} dBTP, LRA {mlra:.1f}')
    print(f'final mix : {xI:.1f} LUFS, true peak {xtp:.2f} dBTP, LRA {xlra:.1f}')

    # ---------------- events.json
    secs = {k: [round(g['drop'] + a * g['bar'], 3), round(g['drop'] + z * g['bar'], 3)] for k, (a, z) in g['sections'].items()}
    meta = dict(
        source_html=os.path.relpath(args.html, args.outdir), total=total, sample_rate=SR,
        scenes=[dict(id=s, start=st, end=st + du) for s, st, du in scenes],
        music=dict(bpm=g['bpm'], bar_seconds=round(g['bar'], 5), key='D major', progression='I V vi IV, cadence IV V I on the final logo',
                   starts=round(g['start'], 3), drop=g['drop'], final_logo=g['land'], sections_seconds=secs,
                   kick_times=[round(k, 3) for k in kicks], fade_in_seconds=1.5, tail_seconds=2.0, tail_ends=round(tail_end, 3)),
        loudness=dict(music_stem_lufs=mI, music_stem_true_peak_dbtp=mtp, mix_lufs=xI, mix_true_peak_dbtp=xtp, mix_lra=xlra),
        events=[dict(t=e['t'], scene=e['scene'], local_t=round(e['t'] - dict((s, st) for s, st, _ in scenes)[e['scene']], 4),
                     kind=e['kind'], gain_db=e['gain_db'], pan=e['pan'], source=e['source']) for e in events],
    )
    with open(os.path.join(args.outdir, 'events.json'), 'w') as fh:
        json.dump(meta, fh, indent=2)
    print(f'{len(events)} effect events -> events.json')

    # ---------------- mux
    if not args.no_mux:
        subprocess.run([FFMPEG, '-y', '-loglevel', 'error', '-i', args.video, '-i', os.path.join(args.outdir, 'music_sfx.wav'),
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-ar', str(SR),
                        '-movflags', '+faststart', '-shortest', args.mux_out], check=True)
        print('muxed ->', args.mux_out)


if __name__ == '__main__':
    main()
