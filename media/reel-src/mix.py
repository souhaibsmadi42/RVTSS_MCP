"""Mix the reel: voiceover + music ducked under the voice and swelling back for the end card, -14 LUFS.

    python mix.py <vo.wav> <music.mp3> <out.wav>
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
vo, music, out = sys.argv[1:4]
tl = json.load(open(os.path.join(HERE, 'timeline.json')))
total, start, dur = tl['total'], tl['vo']['start'], tl['vo']['dur']
end = start + dur
BASE, DUCKED = 0.55, 0.2    # -5 dB before/after the voice, -14 dB under it
gain = (f"if(lt(t,{start - .15:.3f}),{BASE},if(lt(t,{end + .1:.3f}),{DUCKED},"
        f"{DUCKED}+({BASE}-{DUCKED})*min((t-{end + .1:.3f})/0.6,1)))")
ms = int(round(start * 1000))
fc = (f"[0:a]aresample=48000,adelay={ms}|{ms},apad,atrim=0:{total},pan=stereo|c0=c0|c1=c0[v];"
      f"[1:a]aresample=48000,atrim=0:{total},asetpts=PTS-STARTPTS,volume='{gain}':eval=frame,"
      f"afade=t=out:st={total - 1.2}:d=1.2[m];[v][m]amix=inputs=2:normalize=0:duration=first[mix]")
tmp = out + '.pre.wav'
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', vo, '-i', music, '-filter_complex', fc, '-map', '[mix]', '-c:a', 'pcm_s16le', tmp], check=True)
st = subprocess.run(['ffmpeg', '-hide_banner', '-i', tmp, '-af', 'loudnorm=I=-14:TP=-1:LRA=9:print_format=json', '-f', 'null', '-'],
                    capture_output=True, text=True).stderr
j = json.loads(st[st.rindex('{'):st.rindex('}') + 1])
ln = (f"loudnorm=I=-14:TP=-1:LRA=9:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
      f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-af', ln, '-ar', '48000', out], check=True)
os.remove(tmp)
print('mixed', out)
