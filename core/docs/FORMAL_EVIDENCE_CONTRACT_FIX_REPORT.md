# Formal Evidence Contract / Normalizer / Segment Fix Report

## 判定

- `FORMAL_EVIDENCE_CONTRACT_FIX = PASS`
- `NORMALIZER_CONTRADICTION_FIX = PASS`
- `SEGMENT_ARTIFACT_COMPLETENESS_FIX = PASS`
- `NEXT_FULL_LONG_ALLOWED = true`
- `VIDEO_SOURCE_ELIGIBLE = false`
- HOME_001 Formal status: `NEEDS_ITERATION`

次の正式Full Longを開始していない。次回は新Session ID、Cycle 0、`resume_count=0`、migrationなしで開始する。`CORBITT_LONGRUN_ITERATION2_V2_HOME_001` は再開しない。

## HOME_001原本保全

`CORBITT_LONGRUN_ITERATION2_V2_HOME_001_COMPLETED_RAW_HASHES.json` の24ファイルを再照合し、SHA-256不一致は0だった。Raw Run、checkpoint、Session Log、Unified Logは変更していない。NormalizerとAuditorは `video-production-agent/formal-analysis/.../normalizer-evidence-contract-staging` と `auditor-evidence-contract-staging` にのみ出力した。

## 122 findingsの分類

元Formal監査の122 findingsは、111個のunique evidence subject、62個の明示adjudication IDだった。finding数と判定数は同一ではない。

- ROLL: 61 findings / 61 unique subject
- NO_ROLL: 61 findings / 50 unique subject
- raw: 73 findings
- normalized Unified: 42 findings
- normalized Session: 7 findings
- investigation: 32 findings
- combat: 21 findings
- special: 2 findings
- Luck: 1 finding
- other: 66 findings

修復可能性による相互排他的分類:

- Normalizer mappingで解消可能: 20 findings
- Raw source evidence不足: 79 findings
- semantic ambiguity: 23 findings

semantic ambiguityの23件は、12個の戦闘開始、ラウンド開始、行動選択、終了等のlifecycle/selection eventがRawとNormalizedの双方でNO_ROLL判定として監査されたもの。今後は判定確定eventだけがevidence envelopeを持つ。Raw source evidence不足79件（ROLL 41、実際のNO_ROLL move 38）は値を推測していない。詳細は `HOME_001_ROLL_NO_ROLL_FINDING_CLASSIFICATION.json` に保存した。

## Formal Evidence Contract

共通contractを `AdjudicationEvidence.py` に集約した。

ROLLは `adjudication_id / resolution_mode / skill_or_stat / base_target / final_target / target_value / roll / raw_result / final_result / modifier` を持つ。modifierなしも `{type: NONE}` として明示する。NO_ROLLは `adjudication_id / resolution_mode / resolution_reason / final_result` を持つ。

明示的resolutionを持つ新producerは、欠落時にcommit前で例外終了する。旧テスト用のtransient resultとmode省略のhistorical callerは互換タグを持てるが、Investigation/Combatのcommit境界では正式contractを満たさない限り受理しない。

## 3 contradiction fixes

1. targetは `base_target` と `final_target` を分離し、Normalizerは`final_target`を正式targetとして使う。
2. combatは `roll_result` と `effect_result` を分離し、`HIT_ATTACKER`を成功度として扱わない。
3. special objectiveは `objective_outcome` に `SPECIAL_OBJECTIVE_COMPLETED` を保持し、ROLL成功度と混ぜない。

Normalizerのsource priorityは structured Unified Event、structured Session、legacy text parseの順。ROLL相とNO_ROLL相を別phaseとしてmergeする。同じsource tier内の矛盾検出は維持し、known-bad fixtureで検出を確認した。

HOME_001のread-only staging再解析結果:

- `NORMALIZATION_SOURCE_CONTRADICTION = 0`
- traceability = `1.0`
- `ROLL_CONTRACT_INCOMPLETE = 113`
- Formal status = `NEEDS_ITERATION`

113件は旧Rawの欠落を残した結果であり、推測補完していない。

## Segment artifact

各cycleでcheckpointを公開する前に、同cycleのevent deltaを一時directoryへ書き、checksum、manifest、`COMPLETE`を作成してからatomic renameする。segment commit失敗時はcheckpointへ進まない。

resume時にpre-resume event coverageが不足していれば、checkpoint payload内のRaw Eventだけから隔離artifactを復元し、`RECONSTRUCTED_FROM_RAW`を付ける。merge gateは `missing=0 / duplicate=0 / coverage=1.0` を必須とする。

crash→resume fixtureではpre-resume 2件とpost/recovered 2件を100% mergeし、missing 0、duplicate 0、coverage 1.0を確認した。

## Tests

- Core全回帰: `570 passed, 23 subtests passed`
- Video Agent全回帰: `186 passed`
- Formal Auditor v2 fixtures: `19 passed`
- Contract/segment重点fixture: `84 passed, 4 subtests passed`（既存重点テストを含む）
- deterministic acceptance: `ROLL_CONTRACT_INCOMPLETE=0`, `NORMALIZATION_SOURCE_CONTRADICTION=0`, traceability `1.0`

決定論artifactは `evaluation-v2/formal_evidence_contract_deterministic_001/formal_evidence_contract_acceptance.json`。

## 次回Run条件

- HOME_001をresumeしない
- 新Session ID
- Cycle 0
- `resume_count=0`
- migrationなし
- Full Long開始前に同じunit / deterministic / routing / input identity gateを再確認
- 完走後まで `VIDEO_SOURCE_ELIGIBLE=false`

