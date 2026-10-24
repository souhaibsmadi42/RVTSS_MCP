# RVTSS tutorial film source

The install & use tutorial (`../rvtss-tutorial.mp4`, 3:54, 1920×1080, 30 fps) is rendered from this folder.

| File | Role |
|---|---|
| `script.json` | voiceover script, one entry per scene (13 scenes) |
| `prepare_audio.py` | trims and speeds up the voiceover takes, writes `timeline.json` |
| `timeline.json` | each scene's voiceover start, duration and detected pauses (drives every on-screen cue) |
| `index.html`, `scenes.js` | the motion graphics: `window.renderAt(t)` draws the frame at time `t` |
| `render.mjs` | headless Chromium → ffmpeg frame renderer (`preview` stills or the full `video`) |
| `mix.py` | voiceover placement + ducked music, two-pass loudness normalisation to −16 LUFS |
| `captions.py` → `captions.vtt` | English WebVTT captions from the same timing |

**Audio:** narration with the ElevenLabs voice *Kayleigh – Poised Tech Tutorial Narrator* (`eleven_v4`). Music
is an instrumental from ElevenLabs Music v2.5. The narration was silence-trimmed and sped up 5 %
(`atempo=1.05`) to keep the film under four minutes.

**To re-render** (Node 18+ with Playwright and Chromium, ffmpeg, Python 3):

```bash
python prepare_audio.py raw_vo vo          # raw_vo/s01.mp3..s13.mp3 -> vo/*.wav + timeline.json
node render.mjs preview 10 60 120          # spot-check stills in build/
node render.mjs video --fps 30 --workers 4 # build/video_noaudio.mp4
python mix.py vo music.mp3 build/mix.wav
ffmpeg -i build/video_noaudio.mp4 -i build/mix.wav -c:v libx264 -crf 22 -preset slow -pix_fmt yuv420p \
       -c:a aac -b:a 192k -movflags +faststart ../rvtss-tutorial.mp4
python captions.py
```

Changing a line of narration: edit `script.json`, regenerate that scene's audio, run `prepare_audio.py`, then
re-render. Cues are written as phrases (`C('clone the')`), so they
follow the new timing automatically.

The Revit, pyRevit and Claude screens are illustrations. The chat results in the "Using RVTSS" scene are sample
data and are labelled as such on screen.
