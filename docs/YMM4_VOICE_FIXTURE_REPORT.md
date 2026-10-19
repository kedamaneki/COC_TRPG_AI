# YMM4 Voice Fixture Technical Report

## Measurements

| Character | Variant | Duration | Integrated loudness | True peak | Trailing silence | SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Reimu | Baseline | 6.635875 s | -19.97 LUFS | -5.29 dBTP | 0.032021 s | `f46a0df6650c5eb5a032e28a9bea62d764ac20fc27327137eda38d9e6271a017` |
| Reimu | Exact-compatible | 5.757250 s | -20.62 LUFS | -5.79 dBTP | 0.031917 s | `439c25f20144cdbd7f62a449dc99fac58f9f07d6314ca45c8cf8a8afb10c2fc4` |
| Marisa | Baseline | 6.860000 s | -20.38 LUFS | -4.73 dBTP | 0.032021 s | `a77e1df572a4ed41d19810bca558faeac2319017c8d5545f6349e2d4678bf25b` |
| Marisa | Exact-compatible | 5.757250 s | -21.72 LUFS | -5.99 dBTP | 0.032188 s | `4bff866c59cdc1b83771934f7fd925af0a884fc32e76be13e6cb0df1db1aae7d` |
| Sakuya | Baseline | 7.164500 s | -20.10 LUFS | -5.34 dBTP | 0.031917 s | `5a74bb73b3061f6237dfed240b542344eaa568eb754dc486d60701f248f8a165` |
| Sakuya | Exact-compatible | 5.716667 s | -20.45 LUFS | -5.42 dBTP | 0.026687 s | `7403d0ae26d2bcefeae97f0aaffcf6882f69168ff4dac8c27e3c89fe607c620b` |

All outputs are mono 16-bit PCM at 48 kHz. Trailing silence is measured at a -50 dBFS threshold. The configured 0.15 second post-speech tail is a timeline property and is not baked into the fixture WAV.

## Interpretation

The current baseline renderer applies loudness normalization after synthesis. Its historical `pitch_playback` and `volume` profile fields are retained, but the current AquesTalk baseline path does not consume them. The Exact-compatible path explicitly applies the recovered playback rate and source volume without baseline loudness normalization.

The exact numeric evidence is preserved in `fixtures/ymm4_voice_compat/fixture_manifest.json` and mirrored in `docs/YMM4_VOICE_TECHNICAL_REPORT.json`.

