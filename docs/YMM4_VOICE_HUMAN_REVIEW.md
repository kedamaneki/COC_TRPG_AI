# YMM4 Exact Voice Compatibility v1 — Human Review

## Review state

- `HUMAN_REVIEW = PENDING`
- `ACTIVE_MAPPING_CHANGED = false`
- `MAIN_VIDEO_RERENDERED = false`

All pairs use the same line:

> これは、おんせいせっていの、かくにんです。きこえかたと、はなすすぴーどを、かくにんしてください。

For each character, compare A (current baseline) and B (YMM4 Exact-compatible candidate). Review voice height, pace, character likeness, similarity to the remembered YMM4 voice, clarity, and suitability for the video.

## Reimu

- A: `fixtures/ymm4_voice_compat/reimu_baseline.wav`
- B: `fixtures/ymm4_voice_compat/reimu_exact.wav`
- Candidate: f1 / reading 125 / playback 100% / source volume 50%

Decision: `[ ] A baseline  [ ] B candidate  [ ] re-adjust`

Notes:

## Marisa

- A: `fixtures/ymm4_voice_compat/marisa_baseline.wav`
- B: `fixtures/ymm4_voice_compat/marisa_exact.wav`
- Candidate: f2 / reading 125 / playback 100% / source volume 50%

Decision: `[ ] A baseline  [ ] B candidate  [ ] re-adjust`

Notes:

## Sakuya

- A: `fixtures/ymm4_voice_compat/sakuya_baseline.wav`
- B: `fixtures/ymm4_voice_compat/sakuya_exact.wav`
- Candidate: f1 / reading 105 / playback 120% / source volume 50%

Sakuya B intentionally raises both playback speed and pitch. It does not use pitch-preserving time stretch.

Decision: `[ ] A baseline  [ ] B candidate  [ ] re-adjust`

Notes:

## Activation gate

After review, record an explicit per-character decision. Only approved candidates may replace the active Character Registry mapping. Approval for one character does not imply approval for the other two.

