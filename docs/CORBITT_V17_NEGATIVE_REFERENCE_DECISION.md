# CORBITT V17 Negative Reference Decision

**Session:** `CORBITT_LONGRUN_ITERATION3_V17_HOME_001`  
**Disposition:** `IMMUTABLE_NEGATIVE_REFERENCE`  
**Stop reason:** `FULL_LONG_COMPLETION_CONTRACT_FAIL`  
**Same-session rerun:** `FORBIDDEN`  
**FAILURE_AXIS:** `MULTI_AXIS` (`FORMAL` + `SCENARIO_FIDELITY`)  
**Next session hint:** `CORBITT_LONGRUN_ITERATION3_V18_HOME_001` (not executed)

## Fresh identity

| Field | Value |
|---|---|
| Cycle start | 0 |
| resume_count | 0 |
| migration | null |
| preflight_tag | `v17-preflight-accepted` → `66d7aed` |
| implementation_commit | `66d7aede5511f9e129dfa7c03b84e9002be3ae2a` |
| Model | `qwen2.5:14b` |
| OLLAMA | PASS |
| RecentAction schema_version | 1 |

## Outcome snapshot

| Field | Value |
|---|---|
| completed | false |
| scenario_goal_completed | false |
| phase | investigation |
| final_cycle / turn | 60 / 179 |
| final_location | corbitt_ground_floor |
| corbitt_defeated | false |
| combat_state | INACTIVE |
| basement / boss | false / false |
| validated_kill_route_id | none |
| SPECIAL_OBJECTIVE_COMPLETED | none |
| max_no_progress_streak | 169 |
| SYSTEM_FORCED | 5 |

## Raw freeze

| Field | Value |
|---|---|
| V17_RAW_FILES | 862 |
| V17_RAW_SHA256 | `ca7f5627007ec8e0452a6c6de11c4f2d893c28ccc2ab355557065cf0bfcacb9c` |
| V17_RAW_PRE_AUDIT_HASH | `ca7f5627007ec8e0452a6c6de11c4f2d893c28ccc2ab355557065cf0bfcacb9c` |
| V17_RAW_POST_AUDIT_HASH | `ca7f5627007ec8e0452a6c6de11c4f2d893c28ccc2ab355557065cf0bfcacb9c` |
| V17_RAW_REHASH | PASS |
| Formal Normalizer / Auditor | not_run (Night Guard stopped on completion-contract fail; Raw frozen as negative reference) |
| Freeze manifest | `evaluation-control/CORBITT_LONGRUN_ITERATION3_V17_HOME_001/V17_RAW_FREEZE_MANIFEST.json` |

## 5-axis gates

```text
PRODUCTION_WIRING_INTEGRITY = PASS
RUNTIME_CONTRACT_INTEGRITY = PASS
FORMAL_CORRECTNESS = FAIL
SCENARIO_FIDELITY = FAIL
NATURAL_DECISION_QUALITY = PASS
KNOWN_GOOD_PROMOTION = BLOCKED
VIDEO_REGENERATION = NOT_AUTHORIZED
ACCEPTANCE_TAG = none
```

### AXIS A — Production Wiring Integrity (PASS)

- `NATURAL_DECISION_RUNTIME_ACTIVE = true`
- `NDM_DECISION_COMMIT_COUNT = 202`
- `SAFE_LEGACY_DECISION_COMMIT_COUNT = 0`
- `UNSAFE_LEGACY_DECISION_COMMIT_COUNT = 0`
- `REASONING_FALLBACK_COUNT = 0`
- `NDM_DECISION_CAUSAL_COVERAGE = 1.0`
- All `ACTION_SELECTED` decision_source = `natural_decision_v1` with `reasoning_id` present (202/202)
- S-level authority observed = `natural_decision_v1` only
- Contrast vs V16: V16 had SAFE_LEGACY×194 and coverage 0.0; V17 closes that wiring failure mode

### AXIS B — Runtime Contract Integrity (PASS)

- `RECENT_ACTION_SCHEMA_MISMATCH_COUNT = 0`
- `LIST_GET_ATTRIBUTE_ERROR_COUNT = 0` (no `'list' object has no attribute 'get'`)
- `RUNTIME_CONTRACT_VIOLATION_COUNT = 0`
- `SAFE_FALLBACK_FAILURE_COUNT = 0`
- `SAFE_FALLBACK_RECURSION_COUNT = 0`
- RecentAction `schema_version = 1` on producer path

### AXIS C — Formal Correctness (FAIL)

- `RUN_TERMINATED = true` (Night Guard exit 2 / `FULL_LONG_COMPLETION_CONTRACT_FAIL`)
- `SCENARIO_COMPLETED = false` → Formal acceptance blocked by contract
- Completion atomicity: `corbitt_defeated=false`, `scenario_goal_completed=false` → FAIL
- Formal Normalizer / Auditor: not executed on incomplete Full-Long (same disposition as V15/V16 negative freeze)
- `TRACEABILITY` / `DROPPED_EVENTS` / Auditor CRITICAL/BLOCKING: NOT_RUN

### AXIS D — Scenario Fidelity (FAIL)

- Final battle not reached (`trigger_corbitt_boss_battle=false`, `in_basement=false`, `corbitt_body_encountered=false`)
- Kill route: none (neither `ROUTE_A_HP0` nor `ROUTE_B_DAGGER`)
- Combat termination full chain: absent
- `IMPLICIT_COMBAT_NO_ROLL_KILL = 0` (no combat)
- FB-01..14: not ALL_PASS (final-battle / kill / chain gates fail)
- Pack reference: `corbitt_v14` applicable but fidelity FAIL

### AXIS E — Natural Decision Quality (PASS)

Hard safety (observed 0):

- `KNOWLEDGE_LEAK = 0`
- `HIDDEN_SOLUTION_FRONTIER = 0`
- `DIRECT_SOLUTION_S4 = 0`
- `FALLBACK_GUARD_VIOLATION = 0`
- `UNSAFE_LEGACY_DECISION_COMMIT_COUNT = 0`

Full-Long rates (non-null):

| Metric | Value |
|---|---|
| UNEXPLAINED_ACTION_RATE | 0.0 |
| REPETITIVE_ACTION_RATE | 0.0594 |
| UNRESOLVED_LEAD_ABANDON_RATE | 0.0 |
| PREMATURE_S4_RATE | 0.0 |
| FORCED_SOLUTION_RATE | 0.0263 |
| SELF_RECOVERY_RATE | 0.0 |
| MEANINGFUL_PROGRESS_RATE | 0.9950 |
| HINT_DEPENDENCY_RATE | 0.0 |
| UNNECESSARY_S4 | 0 |
| S_LEVEL_RESET_SUCCESS_RATE | 1.0 |
| POST_S4_FREEDOM_RATE | 1.0 |
| SAFE_FALLBACK_RATE | 0.0 |
| NDM_DECISION_CAUSAL_COVERAGE | 1.0 |
| PROGRESS_EVENT_COUNT | 5663 |

Notes:

- `SELF_RECOVERY_RATE = 0` despite `max_no_progress_streak = 169` is recorded; not treated as automatic Axis E FAIL per acceptance text (distinguish absent recovery opportunity vs failed recovery). Pathological SAFE_LEGACY dominance is absent (rate 0).
- Meaningful progress count / progress_event wiring is non-zero and consistent with an active NDM session; scenario non-completion is scored under Axis C/D, not as Axis E null-telemetry BLOCK.

## Historical immutability (post-audit rehash)

| Run | files | SHA256 | Result |
|---|---|---|---|
| V13 | 373 | `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d` | PASS |
| V14 | 862 | `d71f4a51416cf696d88061c79a6b7fc409392a2ca92d43555967317000a551fe` | PASS |
| V15 | 862 | `c8fe8b7cda18bcc56f79dac00a1879d977872c01769aba089c25141ced5c2d9c` | PASS |
| V16 | 862 | `ae254b70d595ca64dc24c24e0b23c481a56b0f88de95323da24ac8b338938b3a` | PASS |

`V13_RAW_CHANGED=0` … `V16_RAW_CHANGED=0`, `HISTORICAL_ARTIFACTS_CHANGED=0`.

## Video

```text
VIDEO_AGENT_REGRESSION = ENVIRONMENT_ONLY  (cv2 missing; preflight separated)
VIDEO_REGENERATION = NOT_AUTHORIZED
```

## Policy

- V17 Raw is immutable negative reference; do not resume, regenerate segments, overwrite Normalizer/Auditor onto Raw, or retarget historical tags.
- `v17-full-long-accepted` tag is **forbidden**.
- Next formal Fresh session candidate: `CORBITT_LONGRUN_ITERATION3_V18_HOME_001` (not started here).

## Evidence locations

Control artifacts: `evaluation-control/CORBITT_LONGRUN_ITERATION3_V17_HOME_001/`.  
Raw artifacts: `evaluation-v2/CORBITT_LONGRUN_ITERATION3_V17_HOME_001/`.  
Axis extraction: `V17_AXIS_EXTRACTION.json`, `V17_ACCEPTANCE_DECISION.json`, `V17_RAW_FREEZE_MANIFEST.json`.
