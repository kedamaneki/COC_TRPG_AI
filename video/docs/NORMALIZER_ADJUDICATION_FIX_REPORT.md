# Normalizer Adjudication Fix Report

## Result

Normalizerの判定証拠回復はPASS。M0/M1/M2/M3の既存テストは全件通過した。M3自体はCLOSEDにしない。

## Root Causes

- Unified Eventに判定値がない旧ログを、時刻近接だけで安全に統合できなかった。
- raw resultとLuck適用後のfinal resultを分離していなかった。
- SANの明示本文があっても構造値へ移せず、Presentation側が参照できなかった。

## Normalizer Changes

- `adjudication_id`が同じsource eventだけを統合する。
- source priorityを structured Unified、structured Session、legacy text parse の順とした。
- `resolution_mode`、target、roll、raw/final result、modifier、SAN tupleを保持する。
- source間の値が衝突した場合は `NORMALIZATION_SOURCE_CONTRADICTION` を出し、推測で選ばない。
- Legacy SAN/Luckは明示値を完全に読める場合だけparseし、provenanceを付与する。

## Legacy Compatibility

- 元の `normalized_session.json` と `edited_script.json` は不変。
- 再正規化結果は `normalized_session_v2.json` へ分離した。
- 壁板矛盾と存在しないナイフ戦闘は補完していない。

## SAN Result

旧: `san = null`

V2: `before 70 / target 70 / roll 40 / SUCCESS / loss 0 / after 70`

`normalization_source = LEGACY_TEXT_PARSE`、`derived_from_legacy_text = true` を保持する。

## Luck Result

旧: `roll 59 / target 50 / modifier null / final null`

V2: `raw FAILURE / Luck 9 / final REGULAR_SUCCESS / Luck 50 -> 41`

## New Session Audit

- `source_contradiction_count = 0`
- `normalization_gap_count = 0`
- `combat_without_termination_count = 0`
- `normalization_source_contradiction_count = 0`
- `rolled_check_incomplete_count = 0`
- `legacy_text_parse_count = 0`
- result: `PASS`

## Test Results

- Video Agent: 160 tests PASS
- M0 import/validation: PASS、16 events、traceability 1.0
- SAN、Luck、wall、knife、final special objectiveの監査: PASS

## Artifact Integrity

- original normalized SHA-256: `02C30843753501B5718E0D1D03320489F13AEB958EE8FCB6A5C625BB07FEDB1F`
- original edited script SHA-256: `79BFC1D59E732E219006D04A8AC62B0D845BA5253D1F9A8DE4AC8B461D3F47C0`

## Remaining Issues

- 決定論的受入セッションは長編自律プレイの代替ではない。
- M3は `PRESENTATION_NEEDS_ITERATION / ASSET_INPUT_REQUIRED / LICENSE_REVIEW_REQUIRED / HUMAN_REVIEW_REQUIRED` を維持する。
