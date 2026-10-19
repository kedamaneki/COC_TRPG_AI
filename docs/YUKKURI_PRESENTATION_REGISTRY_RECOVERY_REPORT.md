# Yukkuri Presentation Registry Recovery Report

## Result

`YUKKURI_PRESENTATION_REGISTRY_V1 = PASS`

## Source authority

- Exact runtime source: `YukkuriMovieMaker.Settings.CharacterSettings.json`
- Runtime SHA-256: `50d4871eb5853e6e6f74f999c9017e4aea80b162c959e3ce9aab78f874459e4b`
- The supplied 16 screenshots establish the intended character set and visible common settings.
- Exact numeric/color values come from the matching YMM4 runtime records. Pixel estimation was not used.
- Existing V2.1 renderer adaptations are stored separately from the immutable recovered YMM values.

## Common subtitle settings

- Font: `たぬき油性マジック`
- Font size: `100 px`
- Position: `X=0 / Y=530 / Z=0`
- Anchor/alignment: `CENTER_BOTTOM`
- Wrapping: `NO_WRAP`
- Maximum width: `1920 px`
- Outline: `5 px / quality 64 / blur 0 / smoothness 100`
- Opacity/zoom: `100% / 100%`
- Additional voice tail: `0.15 sec`

## Character values

- **霊夢**: text `#FF0000` / border decoration `#FFFFFF` / outline effect `#FF0000` / voice `m1_aq_f1` / `ACTIVE`
- **魔理沙**: text `#FFFF00` / border decoration `#000000` / outline effect `#FFFFFF` / voice `aq_marisa_default` / `ACTIVE`
- **アリス**: text `#FFFFFF` / border decoration `#0000FF` / outline effect `#FF004B` / voice `ymm_alice_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **こいし**: text `#4BFF87` / border decoration `#000000` / outline effect `#FFFFFF` / voice `ymm_koishi_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **さとり**: text `#FF00FF` / border decoration `#FFFFFF` / outline effect `#FF00FF` / voice `ymm_satori_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **フラン**: text `#FFFFFF` / border decoration `#FF0000` / outline effect `#FFD200` / voice `ymm_flandre_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **パチュリー**: text `#FFFFFF` / border decoration `#C400FF` / outline effect `#FFFFFF` / voice `ymm_patchouli_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **レミリア**: text `#FF3A44` / border decoration `#FFFFFF` / outline effect `#4A148C` / voice `ymm_remilia_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **咲夜**: text `#FFFFFF` / border decoration `#464646` / outline effect `#FFFFFF` / voice `aq_kp_sakuya_v21` / `ACTIVE`
- **慧音**: text `#77FFFF` / border decoration `#0600FF` / outline effect `#FFFFFF` / voice `ymm_keine_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **白澤慧音**: text `#BBFF63` / border decoration `#000000` / outline effect `#FFFFFF` / voice `ymm_hakutaku_keine_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **早苗**: text `#FFFFFF` / border decoration `#00AA20` / outline effect `#69F999` / voice `ymm_sanae_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **文**: text `#FBB02C` / border decoration `#000000` / outline effect `#FFFFFF` / voice `ymm_aya_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **妹紅**: text `#FFBEBE` / border decoration `#FF0027` / outline effect `#FFFFFF` / voice `ymm_mokou_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **妖夢**: text `#A4FF5B` / border decoration `#004700` / outline effect `#FFFFFF` / voice `ymm_youmu_aquestalk_v1_7` / `FUTURE_CANDIDATE`
- **チルノ**: text `#00FFFF` / border decoration `#000000` / outline effect `#FFFFFF` / voice `ymm_cirno_aquestalk_v1_7` / `FUTURE_CANDIDATE`

## Fixed assignments

- `PC1 / PL1 → 霊夢`
- `PC2 / PL2 → 魔理沙`
- `KP → 咲夜`
- `SYSTEM → no character / no voice / no portrait`
- The remaining 13 entries are `FUTURE_CANDIDATE` and have `auto_use=false`.

## Unresolved values

- Conversion from YMM `Speed/PlaybackRate/Volume` to the current renderer is intentionally unresolved for future-only characters.
- These reference profiles cannot be auto-used until an explicit renderer profile and license review are approved.
