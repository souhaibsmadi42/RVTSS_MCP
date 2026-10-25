"""Mix the tutorial soundtrack: voiceover segments on the timeline + ducked music, normalised to -16 LUFS.

    python mix.py <vo_dir with s01.wav..s13.wav> <music.mp3> <out.wav>

vo_dir holds the ElevenLabs voiceover takes, silence-trimmed and sped up 5 % (atempo=1.05);
timeline.json (same folder as this script) gives each segment's start time.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
vo_dir, music, out = sys.argv[1:4]
tl = json.load(open(os.path.join(HERE, 'timeline.json')))
total = tl['total']

# music: take the tail of the track so its resolving outro lands on the last frame
mus_len = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', music]))
offset = max(0.0, mus_len - total)

# duck envelope: 1 while the narrator speaks, 0 in the gaps, with short ramps
wins = []
for s in tl['scenes']:
    a, b = s['start'] - 0.30, s['start'] + s['dur'] + 0.25
    wins.append(f"min(clip((t-{a:.3f})/0.30,0,1),clip(({b + 0.45:.3f}-t)/0.45,0,1))")
duck = wins[0]
for w in wins[1:]:
    duck = f"max({duck},{w})"
BASE, DUCKED = 0.42, 0.13   # ~ -7.5 dB in the gaps, ~ -17.7 dB under the voice
gain = f"({BASE}-({BASE - DUCKED})*{duck})"

inputs, filters, labels = [], [], []
for i, s in enumerate(tl['scenes']):
    inputs += ['-i', os.path.join(vo_dir, f"{s['id']}.wav")]
    ms = int(round(s['start'] * 1000))
    filters.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms},apad[v{i}]")
    labels.append(f"[v{i}]")
n = len(tl['scenes'])
inputs += ['-ss', f"{offset:.3f}", '-i', music]
filters.append(f"{''.join(labels)}amix=inputs={n}:normalize=0:duration=longest,atrim=0:{total:.3f},pan=stereo|c0=c0|c1=c0[vo]")
filters.append(f"[{n}:a]aresample=48000,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
               f"volume='{gain}':eval=frame,afade=t=in:d=1.2,afade=t=out:st={total - 3.5:.3f}:d=3.5[mu]")
filters.append("[vo][mu]amix=inputs=2:normalize=0:duration=first[mix]")

tmp = out + '.pre.wav'
subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', ';'.join(filters), '-map', '[mix]',
                '-ar', '48000', '-c:a', 'pcm_s16le', tmp], check=True)
# two-pass loudness normalisation
stats = subprocess.run(['ffmpeg', '-hide_banner', '-i', tmp, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'],
                       capture_output=True, text=True).stderr
j = json.loads(stats[stats.rindex('{'):stats.rindex('}') + 1])
ln = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
      f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-af', ln, '-ar', '48000', out], check=True)
os.remove(tmp)
print('music offset', round(offset, 2), 's; input', j['input_i'], 'LUFS -> -16 LUFS;', out)
