# CORBITT V15 Negative Reference Decision

**Session:** `CORBITT_LONGRUN_ITERATION3_V15_HOME_001`  
**Disposition:** `IMMUTABLE_NEGATIVE_REFERENCE`  
**Stop reason:** `FULL_LONG_COMPLETION_CONTRACT_FAIL`  
**Same-session rerun:** `FORBIDDEN`  
**Next session hint:** `CORBITT_LONGRUN_ITERATION3_V16_HOME_001`

## Fresh identity

| Field | Value |
|---|---|
| Cycle start | 0 |
| resume_count | 0 |
| migration | null |
| preflight_tag | `v15-preflight-accepted` → `7709118` |
| Model | `qwen2.5:14b` |

## Outcome snapshot

| Field | Value |
|---|---|
| completed | false |
| phase | investigation |
| final_cycle / turn | 60 / 99 |
| final_location | corbitt_ground_floor |
| corbitt_defeated | false |
| combat_state | ENDED |
| basement_planks_examined | true |
| basement_planks_broken | true |
| has_corbitt_knife | false |
| post_combat_recovery_failure | 1 |
| validated_kill_route_id | none |
| SPECIAL_OBJECTIVE_COMPLETED | none |

## Raw freeze

| Field | Value |
|---|---|
| V15_RAW_FILES | 862 |
| V15_RAW_SHA256 | `c8fe8b7cda18bcc56f79dac00a1879d977872c01769aba089c25141ced5c2d9c` |
| Formal Normalizer / Auditor | not_run (stopped before freeze path in Night Guard; Raw frozen manually as negative reference) |

## Gates

```text
FORMAL_CORRECTNESS = FAIL / not_completed
SCENARIO_FIDELITY = FAIL
NATURAL_DECISION_QUALITY = FAIL (insufficient structured NDM evidence + high forced/S4 pressure; hard leaks=0 but quality gates unmet)
KNOWN_GOOD_PROMOTION = BLOCKED
VIDEO_REGENERATION = NOT_AUTHORIZED
```

## Notable failure mode

After basement planks were broken and Corbitt body / boss trigger was reached, combat ended without a validated kill route. The remainder of the Full-Long oscillated between `corbitt_exterior` and `corbitt_ground_floor` under sustained no-progress / S4 pressure (`SYSTEM_FORCED=35`, `max_stagnation=62`).

Control artifacts: `evaluation-control/CORBITT_LONGRUN_ITERATION3_V15_HOME_001/`.
