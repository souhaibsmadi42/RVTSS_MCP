# RVTSS reel source (40 s, 9:16)

The vertical reel (`../rvtss-reel-40s-9x16.mp4`) is built from two parts:
* **Key art:** six background plates generated with **GPT Image 2.5** (`gpt-image-2.5-sunburst`, 9:16, 2K), in a dark
  holographic BIM style. The plates contain no text.
* **Code:** everything else is rendered from code, frame by frame, in headless Chromium: the type, glass tool-call
  cards, reticles, clash rings, scan-line transitions, camera shake, chromatic aberration, bloom and grain.

**Format:** 1080×1920, 60 fps, 40 s (80 beats at 120 BPM), H.264 + AAC, −14 LUFS.

**Sound:** an original D-minor score and SFX, synthesized in `audio/mix.py` with numpy. It contains no third-party
audio. The SFX are driven by the same cue list as the picture.

**Motif:** the section plane. A cyan scan line sweeps the frame at every section change.

**Sections:**

| Beats | Seconds | Section |
|---|---|---|
| 0–7 | 0–4 | open: "YOUR REVIT MODEL NOW TALKS TO CLAUDE." |
| 8–17 | 4–9 | reveal: building, light sweep, RVTSS lockup |
| 18–21 | 9–11 | 77 tools · 10 toolsets · 7 prompts |
| 22–37 | 11–19 | drop: 8 features, each with its real tool call |
| 38–45 | 19–23 | clash report (illustrative data, labelled as such) |
| 46–51 | 23–26 | safety: dry run, confirm, undo |
| 52–55 | 26–28 | silence: "Built by a BIM coordinator, for BIM coordinators." |
| 56–59 | 28–30 | self-test riser |
| 60–71 | 30–36 | verified numbers: 245 unit tests, −40 % tool context, 16 QC checks, Revit 2021–27 |
| 72–79 | 36–40 | outro: lockup, repository, author |

Every number on screen comes from the README, CHANGELOG or `docs/UPGRADE_REPORT.md`.

Keep titles and cards between y ≈ 250 and 1500 px. That band stays clear of the Instagram, TikTok and Shorts UI.

## Files

| File | Role |
|---|---|
| `src/engine.js` | frame engine: plates, type, glass cards, FX events, finishing pass |
| `src/reel.js` | the film: shots, copy and cues |
| `plates/*.jpg` | GPT Image 2.5 key art |
| `render.mjs` | Playwright renderer: stills, video, cue dump |
| `audio/mix.py` | score and SFX |
| `sheet.sh` | contact sheet of stills, for review |

## Re-render

Requires Node 18+ with Playwright and Chromium, Python 3 with numpy, ffmpeg, and the fonts Inter, Inter Display and
JetBrains Mono.

```bash
node render.mjs stills 6 14 21.9 31.2                    # check a few frames -> out/stills/
node render.mjs events                                   # cue list -> build/events.json
node render.mjs video --workers 4 --crf 16 --name master_noaudio.mp4
python3 audio/mix.py                                     # -> out/soundtrack_raw.wav
ffmpeg -i out/soundtrack_raw.wav -af loudnorm=I=-14:TP=-1.0:LRA=11 -ar 48000 out/soundtrack.wav
ffmpeg -i out/master_noaudio.mp4 -i out/soundtrack.wav -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
       -c:a aac -b:a 256k -shortest -movflags +faststart rvtss-reel-40s-9x16.mp4
```

All timing is in beats (`B(k)` in `src/reel.js`), so changing a cue keeps picture and sound in sync. After any
timing change, re-run `events` and `mix.py`.
