# Full Video Agent 186 Regression Result

## Decision

- FULL_VIDEO_AGENT_CHECKOUT = COMPLETE
- FULL_VIDEO_AGENT_186_REGRESSION = PASS
- NEXT_FULL_LONG_ALLOWED = true
- VIDEO_SOURCE_ELIGIBLE = false
- 次Full Longは開始していない。

## Full regression

- Video Agent collection: 189 tests（旧baseline 186 + Early Gate 3）
- Video Agent: 189 passed / 0 failed
- Core: 579 passed / 23 subtests passed / 0 failed
- Core evidence/checkpoint focus: 29 passed
- Video evidence/normalizer/auditor focus: 33 passed
- Special Objective / unknown event protection: 5 passed
- Auditor / Early Gate focus: 22 passed

## Required acceptance values

- ROLL_CONTRACT_INCOMPLETE_fixture = 0
- NORMALIZATION_SOURCE_CONTRADICTION_fixture = 0
- lifecycle_misclassification = 0
- 	raceability = 1.0
- dropped_events = 0
- legacy_text_parse = 0
- segment missing = 0
- segment duplicate = 0
- segment unexpected = 0
- segment coverage = 1.0

Auditor contract fixtureはvalid ROLL/NO_ROLLを0 findingsで受理し、invalid ROLL/NO_ROLLを各1 findingで拒否した。SPECIAL_OBJECTIVE_COMPLETED認識とunknown combat event拒否も維持している。

## Implementation identity

- Formal Evidence: $(System.Collections.Specialized.OrderedDictionary.formal_evidence) — 学校版と一致
- Checkpoint/Segment: $(System.Collections.Specialized.OrderedDictionary.checkpoint_segment) — 学校版と一致
- Auditor v2: $(System.Collections.Specialized.OrderedDictionary.auditor) — 学校版と一致
- Normalizer: $(System.Collections.Specialized.OrderedDictionary.normalizer) — 学校版hashとは意図的に不一致

Normalizer差分は、完全checkout側のase_target/final_target、oll_result/effect_result/objective_outcome、structured source priority、adjudication phase propagationを保持したため。学校修正のdice_used=true単独昇格禁止とlifecycle除外は反映済み。明示的な旧ログ本文だけは既存186回帰互換としてparse可能にしている。

## Frozen runs

- CORBITT_LONGRUN_ITERATION2_V2_HOME_001: 24/24 hash一致
- CORBITT_LONGRUN_ITERATION3_V1_HOME_001: 100/100 hash一致
- 学校Run: resumeなし、出力先使用なし

次Full Longは新Session ID、Cycle 0、esume_count=0、migrationなし、Early Gateありで別途開始する。
