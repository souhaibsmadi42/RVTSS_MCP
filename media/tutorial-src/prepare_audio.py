"""Prepare the voiceover and build timeline.json.

    python prepare_audio.py <raw_dir with s01.mp3..s13.mp3> <out_dir>

Trims leading/trailing silence, speeds each take up 5 % (pitch preserved), writes <out_dir>/sNN.wav,
then lays the scenes out (1.4 s lead-in, 0.75 s between scenes, 3.4 s tail) and records the pauses
inside each take, which scenes.js and captions.py use to snap cues to the spoken words.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEAD, GAP, TAIL, TEMPO = 1.4, 0.75, 3.4, 1.05
raw, out = sys.argv[1:3]
os.makedirs(out, exist_ok=True)
script = json.load(open(os.path.join(HERE, 'script.json'), encoding='utf-8'))

trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
t, scenes = LEAD, []
for s in script:
    f, tmp = os.path.join(out, f"{s['id']}.wav"), os.path.join(out, f"{s['id']}.trim.wav")
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', os.path.join(raw, f"{s['id']}.mp3"),
                    '-af', trim, '-ar', '48000', '-ac', '1', tmp], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-af', f"atempo={TEMPO}", '-ar', '48000', '-ac', '1', f], check=True)
    os.remove(tmp)
    d = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]))
    log = subprocess.run(['ffmpeg', '-i', f, '-af', 'silencedetect=noise=-38dB:d=0.16', '-f', 'null', '-'],
                         capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', log)]
    en = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', log)]
    scenes.append(dict(id=s['id'], title=s['title'], vo=s['vo'], start=round(t, 3), dur=round(d, 3),
                       pauses=[[round(a, 3), round(b, 3)] for a, b in zip(st, en)]))
    t += d + GAP
total = round(t - GAP + TAIL, 3)
json.dump(dict(total=total, scenes=scenes), open(os.path.join(HERE, 'timeline.json'), 'w', encoding='utf-8'),
          indent=1, ensure_ascii=False)
print('timeline.json: total', total, 's')
