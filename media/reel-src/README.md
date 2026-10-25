# RVTSS 40 s reel source

`../rvtss-reel-40s.mp4` is a vertical social cut: 1080×1920, 30 fps, exactly 40 s, captions burned in, −14 LUFS.
It works for Instagram Reels, TikTok, YouTube Shorts, Facebook, LinkedIn and WhatsApp Status. The cover image is
`../rvtss-reel-cover.jpg`.

Key content stays between y = 190 and 1460 px, and captions stay between x = 110 and 970 px. That keeps them clear
of the platforms' top bar, bottom caption area and right-hand buttons.

| File | Role |
|---|---|
| `script.json` | voiceover text (and the ElevenLabs prompt with its delivery tags) |
| `prepare_audio.py` | trims the voiceover, detects its pauses, writes `timeline.json` |
| `index.html`, `scenes.js`, `kit.js` | the 8 scenes and word-by-word captions; `kit.js` is shared with the tutorial |
| `render.mjs` | headless Chromium → ffmpeg renderer |
| `mix.py` | voice + ducked music that swells for the end card, −14 LUFS |

**Audio:** ElevenLabs voice *Kayleigh – Poised Tech Tutorial Narrator* (`eleven_v4`, one take) and an ElevenLabs
Music v2.5 instrumental at 124 BPM.

**To re-render:**

```bash
python prepare_audio.py vo.mp3 vo.wav
node render.mjs preview 3 12 30            # stills in build/
node render.mjs video --fps 30 --workers 4 # build/video_noaudio.mp4
python mix.py vo.wav music.mp3 build/mix.wav
ffmpeg -i build/video_noaudio.mp4 -i build/mix.wav -map 0:v -map 1:a -c:v libx264 -profile:v high -preset slow \
       -crf 19 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart -shortest ../rvtss-reel-40s.mp4
```

The chat results (14 doors, 23 clashes) are sample data, like those in the tutorial.
