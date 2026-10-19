# YMM4 Exact Voice Compatibility v1

## Result

- `YMM4_VOICE_COMPATIBILITY_V1 = PASS`
- `PLAYBACK_RATE_SEMANTICS = PITCH_AND_SPEED_COUPLED`
- `ENGINE_VERSION_MATCH = PASS`
- `BASELINE_PROFILE_PRESERVED = PASS`
- `ACTIVE_CHARACTER_MAPPING_UNCHANGED = PASS`
- `FIXTURE_RENDER = PASS`
- `HUMAN_REVIEW = PENDING`
- `HISTORICAL_ARTIFACTS_CHANGED = 0`

The compatibility implementation and deterministic fixtures are complete. The three new profiles remain review candidates and are not active production mappings.

## Authority and semantics

The source authority is the recovered YMM4 runtime configuration:

| Character | Voice | Reading speed | Playback rate | Source volume |
| --- | --- | ---: | ---: | ---: |
| Reimu | f1 | 125 | 100% | 50% |
| Marisa | f2 | 125 | 100% | 50% |
| Sakuya | f1 | 105 | 120% | 50% |

Reading speed is passed to AquesTalk synthesis. Playback rate is applied afterward and is stored as a separate field. Source volume is mapped to linear gain (`50% = 0.5`).

YMM4's official documentation describes the control as changing both pitch and playback speed. The compatibility path therefore uses sample-rate conversion (`asetrate` followed by `aresample`) and does not use pitch-preserving `atempo`. Authority: <https://manjubox.net/ymm4/faq/ゆっくりボイス/声質を変更する/>.

The recovered source and installed runtime both identify AquesTalk 1.7.3.1. The recorded runtime SHA-256 is `50d4871eb5853e6e6f74f999c9017e4aea80b162c959e3ce9aab78f874459e4b`.

## Compatibility layer

The following profiles were added with `usage_status=HUMAN_REVIEW_CANDIDATE`, `human_review_status=PENDING`, and `auto_use=false`:

- `ymm_exact_reimu_v1`
- `ymm_exact_marisa_v1`
- `ymm_exact_sakuya_v1`

The current baselines are preserved:

- Reimu: `m1_aq_f1`
- Marisa: `aq_marisa_default`
- Sakuya: `aq_kp_sakuya_v21`

The Character Registry still resolves those three baseline IDs. No active mapping changed.

The compatibility path records synthesis speed, playback rate, volume, source runtime identity, DSP implementation, and output hash independently. It is only selected by profiles with `compatibility_mode=YMM4_EXACT_COMPAT`.

## Compatibility confidence

`MEDIUM` for all three candidates.

The recovered parameters, voice DLL family, engine version, and pitch/speed intent are known. Bit-identical output is not claimed because the exact internal resampling and mixer implementation used by YMM4 was not exposed as an authoritative runtime contract. The fixture uses FFmpeg `asetrate` plus `aresample`, which reproduces the documented pitch-and-speed coupling.

`YMM_PLAYBACK_RATE_SEMANTICS_UNRESOLVED` is not emitted because the pitch behavior is documented. The remaining unresolved point is DSP-level bit identity, recorded as `bit_identical_claim=false`.

## Fixture and verification

The same phonetic line was rendered through each current baseline and candidate profile. Six WAV files and `fixture_manifest.json` are under `fixtures/ymm4_voice_compat/`.

Automated verification:

- Focused compatibility tests: `6 passed`
- Full Video Agent suite: `227 passed`
- Candidate output: mono PCM WAV, 48 kHz
- Fixture hashes and measurements: PASS
- Main video re-render: not performed

## Preservation

V13 Accepted source and the V1, V2, and V2.1 video artifacts were not modified. Existing baseline profile entries were not deleted or rewritten. This work stops at human review; no candidate is activated automatically.

