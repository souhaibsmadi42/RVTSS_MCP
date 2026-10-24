"""Write WebVTT captions for the tutorial from timeline.json (same pause-snapped mapping as scenes.js makeCue)."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
tl = json.load(open(os.path.join(HERE, 'timeline.json')))


def mapper(sc):
    text, wpos, acc = sc['vo'], [], 0.0
    for c in text:
        wpos.append(acc)
        acc += 0.9 if c == ' ' else 7 if c in ',;:' else 10 if c in '.?!' else 8 if c == '—' else 14 if c == '…' else 1
    wpos.append(acc)
    dur = sc['dur']
    bounds = []
    for i, c in enumerate(text):
        if c in ',;:.?!—…':
            j = i + 1
            while j < len(text) and text[j] == ' ':
                j += 1
            if j < len(text):
                bounds.append((wpos[j], wpos[j] / acc * dur))
    anchors = [(0.0, 0.0)]
    for a, b in sc['pauses']:
        if a < 0.2 or b > dur - 0.15:
            continue
        mid = (a + b) / 2
        best = min(bounds, key=lambda bo: abs(bo[1] - mid), default=None)
        if best and abs(best[1] - mid) < 1.3:
            anchors.append((best[0], b))
    anchors.append((acc, dur))
    anchors.sort()
    mono = [anchors[0]]
    for w, t in anchors[1:]:
        if w > mono[-1][0] and t > mono[-1][1]:
            mono.append((w, t))

    def at(i):
        w = wpos[i]
        for (w0, t0), (w1, t1) in zip(mono, mono[1:]):
            if w <= w1:
                return sc['start'] + t0 + (t1 - t0) * (w - w0) / (w1 - w0)
        return sc['start'] + dur
    return at


def ts(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}"


cues = []
for sc in tl['scenes']:
    at = mapper(sc)
    text = sc['vo']
    # clauses end at punctuation followed by a space (so "4.8" and "127.0.0.1" stay whole);
    # pack them into lines of <= 64 chars, breaking early after a sentence end
    parts = list(re.finditer(r'.+?(?:[.?!:…—,](?=\s|$)|$)\s*', text))
    chunk_start, chunk = None, ''
    for m in parts:
        piece = m.group(0)
        if chunk and (len(chunk) + len(piece.strip()) > 64 or (chunk.rstrip()[-1] in '.?!…' and len(chunk) > 12)):
            cues.append([chunk_start, m.start(), chunk.strip(' —')])
            chunk_start, chunk = None, ''
        if chunk_start is None:
            chunk_start = m.start()
        chunk += piece
    if chunk:
        cues.append([chunk_start, len(text), chunk.strip(' —')])
    for c in cues:
        if isinstance(c[0], int):
            end_i = c[1]
            c[0] = at(c[0])
            c[1] = at(end_i) if end_i < len(text) else sc['start'] + sc['dur'] + 0.3

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'captions.vtt')
with open(out, 'w', encoding='utf-8') as f:
    f.write('WEBVTT\n\n')
    for i, (a, b, s) in enumerate(cues, 1):
        f.write(f"{i}\n{ts(a)} --> {ts(max(b - 0.05, a + 0.8))}\n{s}\n\n")
print(len(cues), 'cues ->', out)
