# CORBITT_LONGRUN_ITERATION2_V2_001 Resume Preflight

- checked_at: 2026-10-13 (Asia/Tokyo)
- resume_from: CHECKPOINT_CYCLE_000033
- requested_cycle_turn: Cycle 33 / Turn 93
- decision: **BLOCKED_INFRA**
- FULL_LONG_RAW_RUN: **BLOCKED_INFRA**
- VIDEO_SOURCE_ELIGIBLE: **false**

## 判定

PC2の固定SECONDARY endpoint `http://172.22.25.121:11434` が到達不能です。HTTP `/api/version` は接続失敗、TCP 11434は失敗、pingも失敗しました。

`SECONDARY_FAILURE_POLICY=FAIL_CLOSED` を維持し、PRIMARYへのfallbackは行っていません。Raw Runは再開しておらず、Cycle 33 / Turn 93、`resume_count=0` のままです。

## PC / Model / Routing

- PRIMARY reachable: PASS
- PRIMARY model identity: PASS
  - model: qwen2.5:14b
  - family / architecture: qwen2
  - parameters: 14.8B (14,770,033,664)
  - quantization: Q4_K_M
  - format: gguf
- SECONDARY reachable: **FAIL**
- SECONDARY model identity: NOT_VERIFIED（到達不能）
- PL routing: PRIMARY / PC1
- KP routing: PRIMARY / PC1
- JUDGE routing: SECONDARY / PC2
- FAIL_CLOSED: ENABLED
- execution profile: SCHOOL_DUAL_PC

## Run / Checkpoint Identity

- handoff manifest 421 files: PASS
- missing files: 0
- SHA-256 mismatches: 0
- length mismatches: 0
- checkpoint ID: CHECKPOINT_CYCLE_000033
- checkpoint readable: PASS
- COMPLETE marker: PASS
- checkpoint cycle / turn: 33 / 93
- session ID: CORBITT_LONGRUN_ITERATION2_V2_001
- event log offset: 350
- input_manifest run_input_identity: PASS
- Core main.py hash: MATCH
- runner hash: MATCH
- Scenario hash: MATCH
- PC hash: MATCH
- NPC hash: MATCH
- resume_handoff next_resume_count: 1
- current raw status resume_count: 0

## Append Destinations

同一Session配下を指すことを確認しました。

- session-log.json
- unified-event-log.json
- checkpoints/
- segments/
- llm_call_metrics.jsonl
- llm_performance_summary.json

ただし、再開していないためappend実動作は未検証です。

## Continuity / Execution

- RESUME_PREFLIGHT: **FAIL**
- CONTINUITY: NOT_RUN
- duplicate_events: 0（既存状態）
- missing_events: 0（既存状態）
- double_execution: NOT_RUN
- segment_merge: NOT_RUN
- resume_count: 0（未再開。要求値1は次回再開時）
- session/unified append: NOT_RUN
- human_intervention: 0
- LLM calls: 224（既存Run）
- errors: 0
- retries: 0
- fallbacks: 0
- final checkpoint: CHECKPOINT_CYCLE_000033

## Raw Run Preservation

Session/Unified Log、checkpoint、Raw Run成果物は変更していません。Normalizer、Formal Auditor v2、Legacy Comparison、Formal gateも実行していません。

