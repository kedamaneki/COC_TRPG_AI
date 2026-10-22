# CORBITT V16 Negative Reference Decision

**Session:** `CORBITT_LONGRUN_ITERATION3_V16_HOME_001`  
**Disposition:** `IMMUTABLE_NEGATIVE_REFERENCE`  
**Stop reason:** `FULL_LONG_COMPLETION_CONTRACT_FAIL`  
**Same-session rerun:** `FORBIDDEN`  
**FAILURE_AXIS:** `MULTI_AXIS`  
**Next session hint:** `CORBITT_LONGRUN_ITERATION3_V17_HOME_001` (not executed)

## Fresh identity

| Field | Value |
|---|---|
| Cycle start | 0 |
| resume_count | 0 |
| migration | null |
| preflight_tag | `v16-preflight-accepted` → `4917233` |
| implementation_commit | `491723333fe4975da3bc7a0f2a34f4d7ee882b49` |
| Model | `qwen2.5:14b` |
| OLLAMA | PASS |

## Outcome snapshot

| Field | Value |
|---|---|
| completed | false |
| scenario_goal_completed | false |
| phase | investigation |
| final_cycle / turn | 60 / 157 |
| final_location | corbitt_ground_floor |
| corbitt_defeated | false |
| combat_state | INACTIVE |
| basement / boss | false / false |
| validated_kill_route_id | none |
| SPECIAL_OBJECTIVE_COMPLETED | none |
| max_no_progress_streak | 170 |
| SYSTEM_FORCED | 4 |

## Raw freeze

| Field | Value |
|---|---|
| V16_RAW_FILES | 862 |
| V16_RAW_SHA256 | `ae254b70d595ca64dc24c24e0b23c481a56b0f88de95323da24ac8b338938b3a` |
| V16_RAW_PRE_AUDIT_HASH | `ae254b70d595ca64dc24c24e0b23c481a56b0f88de95323da24ac8b338938b3a` |
| V16_RAW_POST_AUDIT_HASH | `ae254b70d595ca64dc24c24e0b23c481a56b0f88de95323da24ac8b338938b3a` |
| V16_RAW_REHASH | PASS |
| Formal Normalizer / Auditor | not_run (Night Guard stopped on completion-contract fail; Raw frozen as negative reference) |
| Freeze manifest | `evaluation-control/CORBITT_LONGRUN_ITERATION3_V16_HOME_001/V16_RAW_FREEZE_MANIFEST.json` |

## 4-axis gates

```text
PRODUCTION_WIRING_INTEGRITY = FAIL
FORMAL_CORRECTNESS = FAIL
SCENARIO_FIDELITY = FAIL
NATURAL_DECISION_QUALITY = FAIL
KNOWN_GOOD_PROMOTION = BLOCKED
VIDEO_REGENERATION = NOT_AUTHORIZED
ACCEPTANCE_TAG = none
```

### AXIS A — Production Wiring Integrity (FAIL)

- `NATURAL_DECISION_RUNTIME_ACTIVE = true` (runtime started and remained active)
- `S_LEVEL_AUTHORITY = natural_decision_v1` only (no legacy S-level authority observed)
- `PL_REASONING_EVENT_COUNT = 192`
- `KP_PROGRESS_ASSESSMENT_COUNT = 3`
- `SELECTED_ACTION_WITH_NDM_REASONING_COUNT = 3`
- `SELECTED_ACTION_REASONING_ID_MISSING = 0`
- `NDM_DECISION_CAUSAL_COVERAGE = 0.0` (required 1.0)
- `LEGACY_DECISION_COMMIT_COUNT = 194` (required 0; equals `SAFE_LEGACY_PROGRESSION_COUNT`)
- `SAFE_LEGACY_PROGRESSION` fallback streak = 194 after early NDM-bound actions
- Fail-open to inactive NDM → legacy primary: not observed (NDM stayed active), but causal coverage collapse via SAFE_LEGACY dominates Axis A FAIL

### AXIS B — Formal Correctness (FAIL)

- `RUN_TERMINATED = true` (Night Guard exit 2 / `FULL_LONG_COMPLETION_CONTRACT_FAIL`)
- `SCENARIO_COMPLETED = false` → Formal acceptance blocked by contract
- Completion atomicity: `corbitt_defeated=false`, `scenario_goal_completed=false` → FAIL
- Formal Normalizer / Auditor: not executed on incomplete Full-Long (same disposition as V15 negative freeze)

### AXIS C — Scenario Fidelity (FAIL)

- Final battle not reached (`trigger_corbitt_boss_battle=false`, `in_basement=false`)
- Kill route: none (neither `ROUTE_A_HP0` nor `ROUTE_B_DAGGER`)
- Combat termination full chain: absent
- `IMPLICIT_COMBAT_NO_ROLL_KILL = 0` (no combat)
- FB-01..14: not ALL_PASS (final-battle / kill / chain gates fail)
- Pack reference: `corbitt_v14` applicable but fidelity FAIL

### AXIS D — Natural Decision Quality (FAIL)

Hard safety (observed 0):

- `KNOWLEDGE_LEAK = 0`
- `HIDDEN_SOLUTION_FRONTIER = 0`
- `DIRECT_SOLUTION_S4 = 0`
- `FALLBACK_GUARD_VIOLATION = 0`

Telemetry (numeric):

| Metric | Value |
|---|---|
| UNEXPLAINED_ACTION_RATE | 0.0 |
| REPETITIVE_ACTION_RATE | 0.0 |
| UNRESOLVED_LEAD_ABANDON_RATE | 0.0 |
| PREMATURE_S4_RATE | 0.0 |
| FORCED_SOLUTION_RATE | 0.0202 |
| SELF_RECOVERY_RATE | 0.0 |
| MEANINGFUL_PROGRESS_RATE | 0.0 |
| HINT_DEPENDENCY_RATE | 0.0 |
| UNNECESSARY_S4 | 0 |
| S_LEVEL_RESET_SUCCESS_RATE | 1.0 |
| POST_S4_FREEDOM_RATE | 1.0 |
| SAFE_FALLBACK_RATE | 0.496 |
| NDM_DECISION_CAUSAL_COVERAGE | 0.0 |

Quality FAIL drivers: coverage 0.0, extreme SAFE_LEGACY dependency (`fallback_streak=194`), meaningful progress 0, KP/S-level path effectively stalled at S0/NONE after 3 assessments, high no-progress (170) without successful reorientation evidence.

## Notable failure mode

NDM production path activated and bound the first few actions (`ACTION_SELECTED`×3 with `reasoning_id` / `decision_source=natural_decision_v1`). Thereafter the run almost exclusively used `PL_REASONING_FALLBACK` / `SAFE_LEGACY_PROGRESSION` (194). The party entered `corbitt_ground_floor` and investigated several rooms but never unlocked basement access or reached Corbitt final battle before max cycles (60). Night Guard therefore refused Full-Long completion contract.

Control artifacts: `evaluation-control/CORBITT_LONGRUN_ITERATION3_V16_HOME_001/`.  
Raw artifacts: `evaluation-v2/CORBITT_LONGRUN_ITERATION3_V16_HOME_001/`.

## Historical immutability

| Version | Files | Aggregate SHA-256 | Rehash |
|---|---|---|---|
| V13 | 373 | `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d` | PASS |
| V14 | 862 | `d71f4a51416cf696d88061c79a6b7fc409392a2ca92d43555967317000a551fe` | PASS |
| V15 | 862 | `c8fe8b7cda18bcc56f79dac00a1879d977872c01769aba089c25141ced5c2d9c` | PASS |

`V13_RAW_CHANGED = 0` / `V14_RAW_CHANGED = 0` / `V15_RAW_CHANGED = 0` / `HISTORICAL_ARTIFACTS_CHANGED = 0`
