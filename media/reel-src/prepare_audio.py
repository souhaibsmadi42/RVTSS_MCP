"""Trim the reel voiceover and write timeline.json.

    python prepare_audio.py <vo.mp3> <out.wav>
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
START, TOTAL = 0.3, 40.0   # voice starts at 0.3 s; the reel is exactly 40 s (end card holds the rest)
src, out = sys.argv[1:3]
trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-af', trim, '-ar', '48000', '-ac', '1', out], check=True)
d = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', out]))
log = subprocess.run(['ffmpeg', '-i', out, '-af', 'silencedetect=noise=-38dB:d=0.14', '-f', 'null', '-'], capture_output=True, text=True).stderr
st = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', log)]
en = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', log)]
script = json.load(open(os.path.join(HERE, 'script.json'), encoding='utf-8'))
assert START + d < TOTAL - 3, f'voiceover too long for a {TOTAL} s reel: {d:.2f} s'
tl = dict(total=TOTAL, vo=dict(id='reel', vo=script['vo'], start=START, dur=round(d, 3),
                               pauses=[[round(a, 3), round(b, 3)] for a, b in zip(st, en)]))
json.dump(tl, open(os.path.join(HERE, 'timeline.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print(f'voice {d:.2f} s, {len(st)} pauses, ends at {START + d:.2f} s of {TOTAL} s')
