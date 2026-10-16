# SPECIAL_OBJECTIVE_COMPLETED Combat Contract Fix Report

## Final Status

- `SPECIAL_OBJECTIVE_COMBAT_CONTRACT_FIX = PASS`
- `HOME_001_RESUME_ALLOWED = true`
- `VIDEO_SOURCE_ELIGIBLE = false`
- Production Run auto-resume: **NOT EXECUTED**
- Production `CORBITT_LONGRUN_ITERATION2_V2_HOME_001`: `CHECKPOINT_CYCLE_000039` のまま固定

## Root Cause

`main._apply_combat_payload_effects()` は、シナリオ特殊目標の成功時に次の順序でUnified Combat Eventを生成する設計だった。

`COMBAT_ACTION_RESOLVED → SPECIAL_OBJECTIVE_COMPLETED → COMBAT_ENDING → COMBAT_ENDED`

しかし `CombatProgression.append_combat_event()` の許可集合に `SPECIAL_OBJECTIVE_COMPLETED` がなく、Cycle 40でunknown event保護が正しく例外を送出した。producerとconsumerの契約更新漏れであり、unknown event保護自体の問題ではない。

さらにproducerには、`world_fact.fact = CORBITT_BODY_DESTROYED` を保持した `SPECIAL_OBJECTIVE_COMPLETED` の直後に、コービット固有名をイベント型にした `CORBITT_BODY_DESTROYED` を二重送信する処理があった。これは汎用Combat Event型ではなく特殊目標のworld factであるため、別イベント型としては送らず、`SPECIAL_OBJECTIVE_COMPLETED.world_fact` に保持する契約へ統一した。

## Contract Decision

`SPECIAL_OBJECTIVE_COMPLETED` は正式なCombat Eventとする。

理由:

- 戦闘中の合法なSPECIAL行動に対応する。
- `COMBAT_ACTION_RESOLVED` と `COMBAT_ENDING` の間に発生する。
- 同じ `combat_id`、`transaction_id`、`adjudication_id` で戦闘終了因果を接続する。
- Formal Auditor v2が `SPECIAL_OBJECTIVE_COMPLETED` / `CORBITT_BODY_DESTROYED` を最終目標証拠として扱う既存設計と一致する。

payload必須契約:

- 非空 `combat_id`
- 非空 `adjudication_id`
- `target`
- `world_fact.event == SPECIAL_OBJECTIVE_COMPLETED`
- 非空 `world_fact.fact`
- `world_fact.target == target`

同一 `combat_id + adjudication_id + target` の再投入は無処理とし、unknown eventは従来どおり `ValueError` で拒否する。

## Code Changes

- `src/CombatProgression.py`
  - `SPECIAL_OBJECTIVE_COMPLETED` を正式登録。
  - event固有payload validationを追加。
  - event固有idempotency keyを追加。
- `src/main.py`
  - `transaction_id`、`adjudication_id`、`cause_event_ids`、`state_before/state_after`、`world_fact`を特殊目標イベントへ保持。
  - `COMBAT_ACTION_RESOLVED` と特殊目標イベントのfinal resultを `SPECIAL_OBJECTIVE_COMPLETED` に統一。
  - 冗長な `CORBITT_BODY_DESTROYED` event type送信を除去し、world factとして保持。
- `src/EvaluationCheckpoint.py`
  - 原本チェックポイントを変更せず修正後コードで再開するため、厳密な互換migration `SPECIAL_OBJECTIVE_COMBAT_CONTRACT_FIX_V1` を追加。
  - 旧source hash、修正後protected source hash、旧/新prompt hashを固定照合する。
- `src/run_investigation_evaluation.py`
  - 上記migrationを明示CLI選択肢へ追加。

## Dedicated Tests

`test_combat_progression_fix.py` に追加・確認:

- valid special objective
- invalid payload rejection
- idempotency
- state mutation exactly once
- combat termination exactly once
- unknown event rejection
- adjudication / transaction / provenance preservation

`test_evaluation_checkpoint.py` に追加:

- 正式migrationの完全一致PASS
- 想定外prompt変更の拒否
- 想定外gameplay source変更の拒否

結果:

- Dedicated combat tests: `30/30 PASS`
- Combat + checkpoint focused tests: `47/47 PASS`
- Full Core unit/regression: `566/566 PASS`, `0 FAIL`
- Iteration 2 deterministic acceptance: `PASS`
- Iteration 2全8指標: `0`

## Cycle 40 Isolated Reproduction

Production checkpointの原本は使わず、`CHECKPOINT_CYCLE_000039` の隔離コピーを作成した。

実モデルによる1-cycle再開では、モデルが再選択した行動が特殊目標経路に入らなかったため、同じ隔離checkpoint stateを起点に、実ScenarioManager、GameStateManager、CombatProgression、commit_system_resolutionを使う最小決定論的継続を実行した。

確認結果:

- `SPECIAL_OBJECTIVE_COMPLETED accepted = true`
- `runtime exception = 0`
- `state mutation exactly once = true`
- `adjudication_id retained = true`
- `Session append = PASS`
- `Unified append = PASS`
- `duplicate event ids = 0`
- `double commit = 0`
- `combat terminated = true`

イベント順序:

`COMBAT_STARTED → COMBAT_ACTION_SELECTED → COMBAT_ACTION_RESOLVED → SPECIAL_OBJECTIVE_COMPLETED → COMBAT_ENDING → COMBAT_ENDED`

## Formal Normalizer

隔離決定論的継続のみを別入力としてFormal Normalizerへ投入した。

- validation: `PASS`
- source traceability: `1.0`
- dropped events: `0`
- special objective normalized count: `1`
- special objective `source_event_ids`: `combat_event_000371`
- special objective `adjudication_id`: `adj_cycle40_special_objective_repro`
- special objective world fact: `CORBITT_BODY_DESTROYED`
- このadjudicationに対するnormalization contradiction: `0`

Auditor v2は未完走fixtureへFormal PASS/FAILを付けない要件に従い、実行していない。

## Integrity

- HOME production Run: `484/484` files SHA-256一致、差分0
- School Run: `421/421` files SHA-256一致、差分0
- Production Raw Run / checkpoint原本の変更: `0`

## Resume Gate

production `CHECKPOINT_CYCLE_000039` と修正後コードの互換性をread-only評価した。

- validation: `PASS`
- reasons: `[]`
- required migration: `SPECIAL_OBJECTIVE_COMBAT_CONTRACT_FIX_V1`
- 許可対象: `CombatProgression.py`, `main.py` の確定修正のみ

正式resume時は通常の固定構成に加え、次を明示する必要がある。

`--compatible-migration SPECIAL_OBJECTIVE_COMBAT_CONTRACT_FIX_V1`

今回、自動resumeは行っていない。

## Evidence

- `evaluation-v2/CORBITT_HOME_001_CYCLE40_CONTRACT_REPRO/deterministic_contract_continuation/contract_result.json`
- `evaluation-v2/CORBITT_HOME_001_CYCLE40_CONTRACT_REPRO/normalized_contract_continuation/validation_report.json`
- `evaluation-v2/CORBITT_HOME_001_CYCLE40_CONTRACT_REPRO/normalized_contract_continuation/provenance_report.json`
- `evaluation-v2/CORBITT_HOME_001_CYCLE40_CONTRACT_REPRO/resume_compatibility.json`
- `evaluation-v2/CORBITT_HOME_001_CYCLE40_CONTRACT_REPRO/integrity_verification.json`
