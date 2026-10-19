# Sakuya Voice Tuning v1 — Final Selection

## Final state

- `SAKUYA_TUNING_V1 = PASS`
- `SAKUYA_TUNING_HUMAN_REVIEW = PASS`
- `SAKUYA_HUMAN_SELECTION = Candidate A`
- `SELECTED_PROFILE = sakuya_tune_110_v1`
- `SELECTED_PLAYBACK_RATE_PERCENT = 110`
- `VOICE_TYPE = f1`
- `READING_SPEED = 105`
- `SOURCE_VOLUME_PERCENT = 50`
- `PITCH_SPEED_COUPLING = PASS`
- `PITCH_PRESERVING_PROCESS = 0`
- `KP_ACTIVE_MAPPING = sakuya_tune_110_v1`
- `PC1_PC2_SYSTEM_MAPPING_CHANGED = false`
- `VIDEO_AGENT_REGRESSION = 235 passed`
- `VIDEO_V2_2_ACCEPTED_FOR_HUMAN_REVIEW = true`
- `AUTO_PUBLISH = prohibited`
- `LICENSE_REVIEW = REQUIRED`
- `HISTORICAL_ARTIFACTS_CHANGED = 0`

## Human Review resolution

The private `fixtures/sakuya_voice_tuning/anonymous_mapping_manifest.json` was read as the selection authority. Candidate A resolves to `sakuya_tune_110_v1` with a 110% playback rate. This mapping was validated against the registered profile; it was not inferred from ordering or filenames.

- `sakuya_tune_110_v1`: `APPROVED`, `auto_use=true`
- `sakuya_tune_120_v1`: `NOT_SELECTED`, `auto_use=false`
- `sakuya_tune_115_v1`: `NOT_SELECTED`, `auto_use=false`
- `sakuya_tune_105_v1`: `NOT_SELECTED`, `auto_use=false`

`ymm_exact_sakuya_v1` remains the `TUNING_REFERENCE`. `aq_kp_sakuya_v21` remains the `HISTORICAL_REFERENCE`; neither was deleted or rewritten as the selected candidate.

## Compatibility behavior

The approved profile uses AquesTalk `f1`, reading speed 105, source volume 50%, and pitch-and-speed-coupled playback at 110%. The compatibility filter uses `asetrate` followed by `aresample`, so playback speed and pitch change together. No pitch-preserving `atempo` processing is used.

The V2.2 render cache identity includes the selected profile ID, source text, voice type, reading speed, playback rate, source volume, and raw-synthesis SHA-256. This prevents reuse of a historical Sakuya voice cache entry.

## Fixtures and verification

The original tuning fixture set remains available for all four anonymous candidates and three shared lines. The approved selection was additionally verified through V2.2 rendering and QA.

- Anonymous manifest resolution: PASS
- Approved/NOT_SELECTED profile validation: PASS
- KP ACTIVE mapping validation: PASS
- Selected profile used for every KP line: PASS
- Historical profile use in V2.2: 0
- Unapproved candidate use in V2.2: 0
- SYSTEM voice assignments: 0
- Focused compatibility tests: PASS
- Full Video Agent regression: `235 passed`
- V2.2 Technical QA: PASS
- V2.2 Content QA: PASS
- V2.2 Voice-specific QA: PASS

V13 Accepted source and V1, V2, and V2.1 were not modified. V2.2 is a separate derived artifact and still requires final Human Review and License Review.
