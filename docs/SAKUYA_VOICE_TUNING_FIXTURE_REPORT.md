# Sakuya Voice Tuning Fixture Report

## Gate result

- `FIXTURE_ID = FIXTURE_SAKUYA_TUNING_001`
- `STATUS = PASS`
- `VOICE_TYPE_ALL = f1`
- `READING_SPEED_ALL = 105`
- `SOURCE_VOLUME_ALL = 50`
- `PLAYBACK_RATES = 120 / 115 / 110 / 105`
- `PITCH_SPEED_COUPLING = PASS`
- `PITCH_PRESERVING_PROCESS_COUNT = 0`
- `ACTIVE_MAPPING_CHANGED = false`
- `AUTO_USE = false`
- `HUMAN_REVIEW = PENDING`

## Check-line measurements

| Rate | Duration | Integrated loudness | True peak | RMS | Trailing silence | SHA-256 |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 120% | 5.716667 s | -20.45 LUFS | -5.42 dBTP | -20.288 dBFS | 0.026687 s | `7403d0ae26d2bcefeae97f0aaffcf6882f69168ff4dac8c27e3c89fe607c620b` |
| 115% | 5.965229 s | -20.47 LUFS | -5.42 dBTP | -20.288 dBFS | 0.027854 s | `3416368eff3a7501fbb05053d03011b016c73eae2a910ef3e829b3b924350b7b` |
| 110% | 6.236375 s | -20.55 LUFS | -5.42 dBTP | -20.288 dBFS | 0.029125 s | `f43503d19b16ca25bbc56b1c5561d8b783fa641e0c6851412ab38fd82fcd70a9` |
| 105% | 6.533333 s | -20.53 LUFS | -5.42 dBTP | -20.288 dBFS | 0.030500 s | `00f46d7dd318df3f367641d37201e17fc5b237c9f500335a20d8c717548f4e02` |

## KP check request measurements

| Rate | Duration | Integrated loudness | True peak | RMS | Trailing silence | SHA-256 |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 120% | 4.247187 s | -20.80 LUFS | -5.91 dBTP | -20.572 dBFS | 0.026687 s | `54d2ec5adb7a17648cb7d60f37bca099a85eb179de6102e6de1a7f75739b2454` |
| 115% | 4.431854 s | -20.87 LUFS | -5.91 dBTP | -20.572 dBFS | 0.027854 s | `bee01728070b5adf5b07f8a8abd5d70718350c101d89d0a0d0fa3f137bf39751` |
| 110% | 4.633312 s | -21.00 LUFS | -5.91 dBTP | -20.572 dBFS | 0.029125 s | `6885449b4190bc8c0a39c46f563f4cba2543f116e24b0fd24fa080518b68fc96` |
| 105% | 4.853937 s | -21.02 LUFS | -5.91 dBTP | -20.572 dBFS | 0.030500 s | `3f08aa427d01609afcc64264137ae427a6c6fe137b3254009764f2da495bc0cf` |

## KP outcome measurements

| Rate | Duration | Integrated loudness | True peak | RMS | Trailing silence | SHA-256 |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 120% | 2.862604 s | -20.35 LUFS | -5.67 dBTP | -20.279 dBFS | 0.026708 s | `35aad458c7de520f85b276d907632cde10d9781de5bc5383af750417dbf01034` |
| 115% | 2.987083 s | -20.39 LUFS | -5.67 dBTP | -20.279 dBFS | 0.027896 s | `b0e8eda4b5755bce81e96b8e711f664f2649ba4b3fb28b2b0f91481052a1acb9` |
| 110% | 3.122854 s | -20.48 LUFS | -5.67 dBTP | -20.279 dBFS | 0.029167 s | `0aa045e4a9e80110cf7593a02f8daed5e972a81bb4aad1d57d99c31b0945fabb` |
| 105% | 3.271562 s | -20.65 LUFS | -5.67 dBTP | -20.279 dBFS | 0.030542 s | `245e170713c427dce262ea68dea20656e9f6b3d607359eb2c23eb32d4cda910d` |

All fixtures are mono 16-bit PCM at 48 kHz. Full machine-readable evidence is stored in `docs/SAKUYA_VOICE_TUNING_TECHNICAL_REPORT.json`.

