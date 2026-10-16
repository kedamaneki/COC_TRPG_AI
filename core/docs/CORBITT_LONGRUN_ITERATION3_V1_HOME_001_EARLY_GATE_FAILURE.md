# CORBITT_LONGRUN_ITERATION3_V1_HOME_001 Early Gate Failure

## 判定

- FULL_LONG_RAW_RUN = STOPPED_EARLY_UNAUDITED
- EARLY_GATE = FAIL
- FULL_LONG_AUTONOMOUS_REEVALUATION = NEEDS_ITERATION
- VIDEO_SOURCE_ELIGIBLE = false
- NEXT_FULL_LONG_ALLOWED = false
- 自動修正・自動再Runは実施していない。

## 到達点

Cycle 0から新規開始し、CHECKPOINT_CYCLE_000005、Cycle 5 / Turn 7で意図どおり監査待機した。esume_count=0、migrationなし。PL/KP/JUDGEはすべてPRIMARYで、37 LLM callはSUCCESS、retry/fallback/remote callは0だった。

## Preflight

Core 570件＋23 subtests、Video Agent 186件は0 FAIL。Ollamaはqwen2.5:14b / qwen2 / 14.8B / Q4_K_M。入力identityはPASS。HOME_001は24/24 hash一致。

## Early Gate結果

- Raw Unified event: 40
- Raw側の明示ROLL: 6。Core validator error: 0
- Normalized event: 92
- Normalizer validation: PASS
- Source traceability: 1.0
- ROLL_CONTRACT_INCOMPLETE: 6
- Combat lifecycle誤分類: 0
- Segment: 5、missing 40、duplicate 0、coverage 0.0

## 根本原因

1. Segmentはcheckpointより先にatomic commitされているが、event_id付与がcheckpoint serialization時に行われる。したがってsegment内の行にevent_idがなく、checkpoint Raw stream 40件と一致しない。
2. dice_used=true のUnified summary 3件をNormalizerがROLLへ推定するが、summary側にはadjudication_idがない。
3. Social check 2件はSession Log本文にtarget/roll/resultがあるがadjudication_idがない。
4. moveのLOCATION_CHANGE 1件はNO_ROLLへ正規化されるが、structured resolution reasonがない。

## 未実行

Run未完走のため、Formal Auditor v2による正式判定、Legacy Comparison、最終Formal gateは実行していない。Early gate用Normalizerは隔離stagingにのみ出力した。
