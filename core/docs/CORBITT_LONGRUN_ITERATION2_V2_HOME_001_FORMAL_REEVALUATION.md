# CORBITT_LONGRUN_ITERATION2_V2_HOME_001 Formal Re-evaluation

## Final decision

- FULL_LONG_RAW_RUN = COMPLETED_UNAUDITED
- FULL_LONG_AUTONOMOUS_REEVALUATION_V2_HOME = NEEDS_ITERATION
- VIDEO_SOURCE_ELIGIBLE = false
- Normalizer = PASS
- Auditor v2 = NEEDS_ITERATION
- CRITICAL = 61
- MAJOR = 64

Raw Runは完走したが、Formal gateは不合格である。自動修正・自動再Runは行っていない。

## Resume and migration

- Resume: CHECKPOINT_CYCLE_000039
- Resume count: 1
- Migration: SPECIAL_OBJECTIVE_COMBAT_CONTRACT_FIX_V1
- Preflight / Migration / Continuity: PASS
- duplicate / missing(full Raw) / double execution / double commit: 0 / 0 / 0 / 0

Migration boundary:
- Segment 1: Cycle 1-39 / pre-fix Core
- Migration: SPECIAL_OBJECTIVE_COMBAT_CONTRACT_FIX_V1
- Segment 2: Cycle 40-46 / post-fix compatible Core
- pre-fix source: 0becb4ace78706764bf5a99d98d9520b0359f1d5a4feb9efe79f5e0e846f7723
- post-fix source: 3de5164d6ec3a1b576487d48474d9a96e7f6dcbb616c042d83e7e8d45eed1514
- protected source: 0a169103531f54137f430b59abd8242c626ed47716c510e13b256762a3a37124

## Raw Run result

- completed / phase: true / clear
- Cycle / Turn: 46 / 111
- final checkpoint: CHECKPOINT_CYCLE_000046
- corbitt_defeated: true
- combat state: INACTIVE
- human intervention: 0
- LLM calls: 279 / 279 SUCCESS
- errors / retries / fallbacks / SECONDARY: 0 / 0 / 0 / 0
- completed Raw hash verification: 24 / 24 PASS

## Special objective contract

COMBAT_ACTION_RESOLVED -> SPECIAL_OBJECTIVE_COMPLETED -> COMBAT_ENDING -> COMBAT_ENDED

- adjudication ID: adj_fb2dfaaa593140dba7b4a00e2ffebf49
- CORBITT_BODY_DESTROYED state mutation: exactly once
- world fact retained: CORBITT_BODY_DESTROYED
- separate CORBITT_BODY_DESTROYED combat event: 0

## Segment artifact note

Runnerのsegment_merge判定はPASS、duplicate removalは0である。ただし停止時にCycle 1-39のsegment成果物がcommitされていなかったため、最終merged/events.jsonlはresume event 1件とCycle 40-46のRaw event 57件だけを含む。Full unified-event-log.jsonは424件を欠落なく保持しており、Formal NormalizerはFull Raw logを使用した。segment coverage上は先頭367 Raw eventが未収録である。

## Formal Normalizer

- validation: PASS
- normalized/source events: 977 / 977
- dropped events: 0
- traceability: 1.0
- legacy text parse: 0
- special objective provenance: retained
- NORMALIZATION_SOURCE_CONTRADICTION: 3

矛盾はDice target 32 vs 65、Knife final result HIT_ATTACKER vs REGULAR_SUCCESS、special objective final result SPECIAL_OBJECTIVE_COMPLETED vs REGULAR_SUCCESSである。

## Auditor v2

- SHA-256: 8499ba51693e6b0f52dc94c2a19b4ef2243c9b819d2d66d0c789ce8bafd3f902
- Formal status: NEEDS_ITERATION
- CRITICAL / MAJOR / findings: 61 / 64 / 125
- traceability: 1.0
- ROLL_CONTRACT_INCOMPLETE: 122
- NORMALIZATION_SOURCE_CONTRADICTION: 3

SOURCE_CONTRADICTION、NORMALIZATION_GAP、COMBAT_WITHOUT_TERMINATION、およびIteration 2のSAN/Object/Narrative 5分類はすべて0だった。

## Legacy Comparison

- corbitt_clear_001: completed、CRITICAL 2、MAJOR 4、combat termination gap 1、壁矛盾あり。
- CORBITT_LONGRUN_POST_ADJUDICATION_FIX_001: completed、CRITICAL 4、MAJOR 5、combat termination gap 0、Normalizer contradiction 22、rolled check incomplete 9。
- HOME_001: completed、combat termination gap 0、Normalizer contradiction 3。ただしAuditor v2のROLL/NO_ROLL検査で122件がblocking。
- 学校Run ITERATION2_V2_001: Cycle 33 / Turn 93、PAUSED_FOR_PC_HANDOFF、NOT_COMPARABLE_FINAL。

Auditor世代と厳格さが異なるため絶対件数は単純比較できない。Gameplay完走、戦闘lifecycle、SAN/Object系、source contradictionは改善したが、判定証拠契約はFormal公開基準を満たしていない。

## Next required work

Raw Run原本は変更しない。次の修正対象は、上流Logging/NormalizerのROLLにおけるtarget・roll・raw/final result、NO_ROLLにおけるreason/final outcomeの一貫した構造化、および3件のsource contradictionである。修正後は新Sessionで再評価する。