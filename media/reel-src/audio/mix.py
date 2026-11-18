"""Soundtrack for the RVTSS reel: an original 120 BPM D-minor score plus SFX on the picture's own cue list.
Everything is synthesized here (numpy only), so the track is free of third-party rights.
  python3 audio/mix.py            -> out/soundtrack_raw.wav (loudness is normalised afterwards with ffmpeg loudnorm)
Section map (beats, = the picture): open 0-8 · reveal 8-18 · tools 18-22 · drop 22-38 · breakdown 38-46 ·
tension 46-52 · silence 52-56 · riser 56-60 · drop 60-72 · outro 72-80
"""
import json, os, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR, DUR, BPM = 48000, 40.0, 120
BEAT = 60 / BPM
N = int(SR * (DUR + 0.5))
R = np.random.default_rng(7)

def B(k): return k * BEAT
def idx(t): return int(round(t * SR))
def hz(m): return 440.0 * 2 ** ((m - 69) / 12)
def env_exp(n, tau): return np.exp(-np.arange(n) / (tau * SR))

def add(buf, x, t, gain=1.0, pan=0.0):
    i = idx(t)
    if i >= buf.shape[1] or len(x) == 0: return
    j = min(buf.shape[1], i + len(x)); x = x[: j - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, i:j] += x * gain * l * 1.414; buf[1, i:j] += x * gain * r * 1.414

def fft_filter(x, lo=None, hi=None, order=2):
    """Zero-phase Butterworth-shaped band filter in the frequency domain (lo = highpass corner, hi = lowpass corner)."""
    n = len(x); X = np.fft.rfft(x, n); f = np.fft.rfftfreq(n, 1 / SR) + 1e-6
    g = np.ones_like(f)
    if hi: g /= np.sqrt(1 + (f / hi) ** (2 * order))
    if lo: g /= np.sqrt(1 + (lo / f) ** (2 * order))
    return np.fft.irfft(X * g, n)

def onepole_sweep(x, f0, f1):
    """Lowpass whose cutoff glides exponentially f0 -> f1 (risers)."""
    y = np.empty_like(x); s = 0.0
    fc = f0 * (f1 / f0) ** np.linspace(0, 1, len(x))
    a = 1 - np.exp(-2 * np.pi * fc / SR)
    for i in range(len(x)):
        s += a[i] * (x[i] - s); y[i] = s
    return y

def saw(f, n, phase=0.0):
    t = np.arange(n) / SR
    return 2 * ((f * t + phase) % 1.0) - 1

def noise(n): return R.standard_normal(n)

def adsr(n, a=0.01, d=0.1, s=0.7, r=0.2):
    e = np.full(n, s); na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    na = min(na, n); e[:na] = np.linspace(0, 1, na)
    nd = min(nd, n - na); e[na:na + nd] = np.linspace(1, s, nd)
    if nr < n: e[n - nr:] *= np.linspace(1, 0, nr)
    return e

# ------------------------------------------------------------------ instruments
def kick(k=1.0):
    n = int(0.45 * SR); t = np.arange(n) / SR
    f = 42 + 110 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(n, 0.16)
    click = fft_filter(noise(n), lo=2500) * env_exp(n, 0.004) * 0.35
    return np.tanh(1.6 * (body + click)) * k

def clap(k=1.0):
    n = int(0.3 * SR); x = fft_filter(noise(n), lo=900, hi=6000)
    e = np.zeros(n)
    for o in (0, 0.009, 0.018): e[int(o * SR):] += env_exp(n - int(o * SR), 0.012 if o < 0.018 else 0.09)
    tone = np.sin(2 * np.pi * 190 * np.arange(n) / SR) * env_exp(n, 0.04) * 0.4
    return (x * e * 0.6 + tone) * k

def hat(k=1.0, open_=False):
    n = int((0.18 if open_ else 0.05) * SR)
    return fft_filter(noise(n), lo=7000, order=3) * env_exp(n, 0.06 if open_ else 0.012) * k

def pluck(m, k=1.0, dur=0.22, bright=2600):
    n = int(dur * SR)
    x = saw(hz(m), n) + 0.6 * saw(hz(m) * 1.004, n, 0.3)
    return fft_filter(x, hi=bright, order=2) * env_exp(n, dur * 0.35) * k

def bass_note(m, dur, k=1.0):
    n = int(dur * SR); t = np.arange(n) / SR
    x = np.sin(2 * np.pi * hz(m) * t) + 0.35 * np.tanh(3 * saw(hz(m), n))
    return fft_filter(x, hi=420) * adsr(n, 0.005, 0.08, 0.75, 0.04) * k

def pad_chord(notes, dur, k=1.0, hi=1600):
    n = int(dur * SR); x = np.zeros(n)
    for m in notes:
        for det, ph in ((-0.12, 0.0), (0.0, 0.33), (0.12, 0.71)):
            x += saw(hz(m + det), n, ph)
    x = fft_filter(x / (3 * len(notes)), hi=hi, order=2)
    return x * adsr(n, 0.25, 0.4, 0.8, 0.45) * k

# ------------------------------------------------------------------ SFX
def impact(k=1.0, big=False):
    n = int((2.2 if big else 1.2) * SR); t = np.arange(n) / SR
    sub = np.sin(2 * np.pi * np.cumsum(38 + 70 * np.exp(-t / 0.06)) / SR) * env_exp(n, 0.5 if big else 0.28)
    crack = fft_filter(noise(n), lo=200, hi=9000) * env_exp(n, 0.05) * 0.7
    tail = fft_filter(noise(n), hi=900) * env_exp(n, 0.6 if big else 0.3) * 0.25
    return np.tanh(1.3 * (sub + crack + tail)) * k

def hit_s(k=1.0):
    n = int(0.35 * SR); t = np.arange(n) / SR
    body = np.sin(2 * np.pi * np.cumsum(60 + 160 * np.exp(-t / 0.02)) / SR) * env_exp(n, 0.09)
    return np.tanh(1.5 * (body + fft_filter(noise(n), lo=1500) * env_exp(n, 0.02) * 0.6)) * k

def scan_fx(k=1.0):
    # the motif: a bright "shing" sweeping down + air rip + sub
    n = int(1.1 * SR); t = np.arange(n) / SR
    f = 5200 * np.exp(-t / 0.18) + 700
    shing = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(n, 0.16) * 0.35
    rip = fft_filter(noise(n), lo=2000, hi=12000) * (np.minimum(1, t / 0.02)) * env_exp(n, 0.12) * 0.5
    sub = np.sin(2 * np.pi * 45 * t) * env_exp(n, 0.35) * 0.8
    return (shing + rip + sub) * k

def tick(k=1.0):
    n = int(0.03 * SR); return np.sin(2 * np.pi * 3200 * np.arange(n) / SR) * env_exp(n, 0.006) * k

def blip(k=1.0):
    n = int(0.09 * SR); t = np.arange(n) / SR
    return np.sin(2 * np.pi * (1500 + 900 * (t > 0.03)) * t) * adsr(n, 0.002, 0.02, 0.6, 0.03) * 0.5 * k

def click(k=1.0):
    n = int(0.02 * SR); return fft_filter(noise(n), lo=3000) * env_exp(n, 0.003) * k

def glitch_fx(k=1.0):
    n = int(0.18 * SR); x = np.zeros(n); r = np.random.default_rng(11)
    for _ in range(10):
        L = int(r.integers(200, 1600)); a = int(r.integers(0, n - L))
        x[a:a + L] += np.sign(np.sin(2 * np.pi * r.uniform(200, 2400) * np.arange(L) / SR)) * r.uniform(0.2, 0.6)
    return np.round(x * 6) / 6 * k * 0.5

def whoosh(k=1.0, dur=0.5):
    n = int(dur * SR); t = np.linspace(0, 1, n)
    e = np.sin(np.pi * t) ** 2
    return onepole_sweep(noise(n), 400, 6000) * e * k

def riser(k=1.0, dur=1.0):
    n = int(dur * SR); t = np.linspace(0, 1, n)
    nz = onepole_sweep(noise(n), 300, 9000) * t ** 2
    tone = np.sin(2 * np.pi * np.cumsum(220 * 2 ** (2 * t)) / SR) * t ** 3 * 0.25
    return (nz * 0.8 + tone) * k

def typing(k=1.0, dur=1.6):
    n = int(dur * SR); x = np.zeros(n); r = np.random.default_rng(5)
    for i in range(int(dur / (BEAT / 8))):
        a = int(i * BEAT / 8 * SR); c = click(r.uniform(0.4, 0.9)); x[a:a + len(c)] += c[: n - a]
    return x * k * 0.5

def swell(k=1.0, dur=2.0):
    n = int(dur * SR); t = np.linspace(0, 1, n)
    x = pad_chord([62, 65, 69, 74], dur, 1.0, hi=2400)
    return x * t ** 2 * k * 1.6

# ------------------------------------------------------------------ score
mus = np.zeros((2, N)); drm = np.zeros((2, N)); sfx = np.zeros((2, N)); send = np.zeros((2, N))
PROG = [([62, 65, 69], 38), ([58, 62, 65], 34), ([60, 65, 69], 41), ([60, 64, 67], 36)]   # Dm · Bb · F · C
def sec(b, a, z): return a <= b < z

def drums_on(b): return sec(b, 8, 38) or sec(b, 46, 52) or sec(b, 60, 72)
def full(b): return sec(b, 22, 38) or sec(b, 60, 72)

for b in range(80):
    t = B(b)
    if drums_on(b):
        add(drm, kick(1.0 if full(b) else 0.85), t, 0.9)
        if (full(b) or sec(b, 12, 22)) and b % 2 == 1: add(drm, clap(0.8 if full(b) else 0.5), t, 0.55, 0.05)
        if sec(b, 8, 22): add(drm, hat(0.5), t + BEAT / 2, 0.35, 0.25)
        if full(b):
            for s in range(4): add(drm, hat(0.55 if s % 2 else 0.3, open_=(s == 2 and b % 4 == 3)), t + s * BEAT / 4, 0.35, 0.3 if s % 2 else -0.2)

# sidechain envelope from the kick grid (pumping on pad / bass)
duck = np.ones(N)
for b in range(80):
    if drums_on(b):
        i = idx(B(b)); n = int(0.32 * SR); j = min(N, i + n)
        duck[i:j] = np.minimum(duck[i:j], 1 - 0.7 * np.exp(-np.arange(j - i) / (0.07 * SR)))

for bar in range(20):
    b0 = bar * 4; t0 = B(b0); chord, root = PROG[bar % 4]
    if b0 >= 56 and b0 < 60: continue                       # riser bar: music drops out
    silence = sec(b0, 52, 56)
    hi = 900 if b0 < 8 else 700 if silence else 1200 if sec(b0, 38, 46) else 2000 if full(b0) else 1500
    k = 0.35 if silence else 0.5 if b0 < 8 else 0.45
    p = pad_chord(chord + [chord[0] + 12], 4 * BEAT + 0.4, k, hi=hi)
    add(mus, p, t0, 0.9, -0.15); add(mus, p, t0 + 0.012, 0.9, 0.15); add(send, p, t0, 0.5)
    # sub / bass
    if b0 < 8 or silence: add(mus, bass_note(root, 4 * BEAT, 0.5 if b0 < 8 else 0.3), t0, 0.7)
    elif sec(b0, 38, 46): add(mus, bass_note(root, 4 * BEAT, 0.55), t0, 0.7)
    elif b0 < 72:
        for e in range(8): add(mus, bass_note(root + (12 if full(b0) and e % 4 == 3 else 0), BEAT / 2 - 0.01, 0.7), t0 + e * BEAT / 2, 0.75)
    # 16th arp in drops, softer filtered arp in the breakdown
    if full(b0) or sec(b0, 38, 46):
        notes = chord + [chord[1] + 12, chord[2] + 12, chord[0] + 12]
        for s in range(16):
            m = notes[[0, 1, 2, 3, 4, 3, 2, 1][s % 8]] + 12
            pk = pluck(m, 0.5 if full(b0) else 0.35, bright=3200 if full(b0) else 1400)
            add(mus, pk, t0 + s * BEAT / 4, 0.32, -0.35 if s % 2 else 0.35); add(send, pk, t0 + s * BEAT / 4, 0.25)
    # chord stab on drop downbeats
    if b0 in (8, 24, 32, 60, 68) or b0 == 22:
        st = pad_chord(chord + [chord[0] + 12, chord[0] + 24], 0.6, 1.0, hi=4000) * env_exp(int(0.6 * SR) + 1, 0.18)[: int(0.6 * SR)]
        add(mus, st, t0, 0.5); add(send, st, t0, 0.6)
# the drop at beat 22 sits mid-bar: give it its own stab
st = pad_chord([62, 65, 69, 74, 86], 0.6, 1.0, hi=4000) * env_exp(int(0.6 * SR), 0.18); add(mus, st, B(22), 0.5); add(send, st, B(22), 0.6)
# outro: long final chord
add(mus, pad_chord([50, 62, 65, 69, 74], 4.5, 0.6, hi=1800), B(72), 0.9); add(send, pad_chord([62, 69, 74, 81], 4.5, 0.5, hi=2600), B(72), 0.7)

mus[0] *= duck; mus[1] *= duck

# ------------------------------------------------------------------ SFX on the picture's cue list
cues = json.load(open(os.path.join(ROOT, 'build', 'events.json')))
for c in cues:
    t, kind, k, d = c['t'], c['kind'], c.get('k', 1), c.get('d', 0)
    if kind == 'impact': x = impact(k, big=k > 0.85); g = 0.55
    elif kind == 'drop': x = impact(k, big=True); g = 0.6
    elif kind == 'hitS': x = hit_s(k); g = 0.5
    elif kind == 'scan': x = scan_fx(k); g = 0.45
    elif kind == 'tick': x = tick(k); g = 0.35
    elif kind == 'blip': x = blip(k); g = 0.3
    elif kind == 'click': x = click(k); g = 0.35
    elif kind == 'glitch': x = glitch_fx(k); g = 0.35
    elif kind == 'whoosh': x = whoosh(k, 0.5); t -= 0.25; g = 0.35
    elif kind == 'whooshL': x = whoosh(k, 1.0); g = 0.3
    elif kind == 'riser': x = riser(k, d or BEAT * 2); g = 0.6
    elif kind == 'swell': x = swell(k, 2.0); g = 0.3
    elif kind == 'type': x = typing(k, 1.6); g = 0.4
    elif kind == 'outro': x = impact(1.0, big=True); g = 0.6; add(send, x, t, 0.4)
    else: continue
    add(sfx, x, t, g, 0.0); add(send, x, t, 0.15 * g)

# ------------------------------------------------------------------ reverb (exponential noise IR, FFT convolution)
def reverb(x, rt=2.2, pre=0.02):
    n = int(rt * SR); ir = noise(n) * np.exp(-np.arange(n) / (rt / 6.9 * SR))
    ir = fft_filter(ir, lo=180, hi=7000); ir = np.concatenate([np.zeros(int(pre * SR)), ir]); ir /= np.sqrt(np.sum(ir ** 2))
    L = len(x) + len(ir); nf = 1 << (L - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, nf) * np.fft.rfft(ir, nf), nf)[: len(x)]
irR = reverb  # same IR shape, decorrelated noise per channel
wet = np.stack([reverb(send[0]), irR(send[1])]) * 0.35

mix = 0.8 * mus + 0.85 * drm + 0.9 * sfx + wet
mix[:, idx(B(59.75)):idx(B(60))] *= np.linspace(1, 0.15, idx(B(60)) - idx(B(59.75)))   # the gap before the drop
end = idx(DUR); fade = int(1.4 * SR)
mix[:, end - fade:end] *= np.linspace(1, 0, fade) ** 1.5; mix[:, end:] = 0
mix = np.tanh(mix * 0.9) / 0.9                                     # soft clip as a gentle bus limiter
mix = mix[:, :end]
peak = np.max(np.abs(mix)); mix *= 0.89 / peak

os.makedirs(os.path.join(ROOT, 'out'), exist_ok=True)
out = os.path.join(ROOT, 'out', 'soundtrack_raw.wav')
pcm = (np.clip(mix.T, -1, 1) * 32767).astype('<i2')
with wave.open(out, 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
for a, z, name in [(0, 8, 'open'), (8, 22, 'reveal'), (22, 38, 'drop1'), (38, 46, 'break'), (46, 52, 'tension'), (52, 56, 'silence'), (56, 60, 'riser'), (60, 72, 'drop2'), (72, 80, 'outro')]:
    seg = mix[:, idx(B(a)):idx(B(z))]; print(f'{name:8s} rms {20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9):6.1f} dBFS')
print('wrote', out)
