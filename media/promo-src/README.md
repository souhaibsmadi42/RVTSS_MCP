# RVTSS promo film source

The 40 s promo (`../rvtss-promo-40s.mp4`) was made with the
[catana skill](https://github.com/souhaibsmadi42/catana-skill), a Katana-style motion film engine that renders
a page frame by frame in headless Chrome. This folder holds the film's only custom file, `scenes.js`.

**Format:** 40 s (80 beats at 120 BPM), 1920×1080, 60 fps.

**Sound:** no music track was supplied, so the soundtrack is SFX only (procedural, mixed to −14 LUFS).

**Sections:**

| Beats | Section |
|---|---|
| 0–7 | open |
| 8–11 | logo |
| 12–15 | 77 tools |
| 16–31 | drop: 8 features with real tool calls |
| 32–39 | clash report (illustrative data, labelled as such) |
| 40–47 | safety model |
| 48–51 | silence |
| 52–55 | self-test riser |
| 56–71 | verified numbers |
| 72–79 | outro |

**To re-render** (for example with a licensed music track):

```bash
python <catana>/scripts/new_film.py film --music track.wav --duration 40
cp scenes.js film/src/scenes.js
cd film
node render.mjs video --workers 6 --crf 15 --name master_noaudio.mp4
node tools/page.mjs "src/index.html?dump=1" build/events.json && python audio/mix.py
```

Then mux, make the web copy and run QC as described in the skill's `references/pipeline.md`. With a real
track, check the BPM and offset the music scan writes to `src/lib.js`; the cuts are all expressed in beats.
