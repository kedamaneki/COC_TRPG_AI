# Corbitt V18 — Immutable Negative Reference

**Session:** `CORBITT_LONGRUN_ITERATION3_V18_HOME_001`  
**V18_FULL_LONG_ACCEPTANCE = BLOCKED**  
**V18_STATUS = IMMUTABLE_NEGATIVE_REFERENCE**  
**KNOWN_GOOD_PROMOTION = BLOCKED**  
**V18_SAME_SESSION_RERUN = FORBIDDEN**  
**VIDEO_REGENERATION = NOT_AUTHORIZED**  
**NEXT_SESSION_HINT = CORBITT_LONGRUN_ITERATION3_V19_HOME_001** (not started)

## Identity

| Field | Value |
|---|---|
| preflight_tag | `v18-preflight-accepted` → `9d6adf6` |
| git_commit | `9d6adf60f8545b7d4dc3b8e7603ac6eb09c1f8f9` |
| Fresh | cycle=0, resume_count=0, migration=null |
| Model | qwen2.5:14b |
| Stop | `FULL_LONG_COMPLETION_CONTRACT_FAIL` |

## Raw freeze

| Field | Value |
|---|---|
| V18_RAW_FILES | 862 |
| V18_RAW_SHA256 | `796150da1389a10fdd5bcfa7d0a4fcd131c7326f5354ae6c7dcdb6eebb7ff241` |
| PRE_AUDIT == POST_AUDIT | PASS |
| Manifest | `evaluation-control/.../V18_RAW_FREEZE_MANIFEST.json` |

## 6-axis

| Axis | Result |
|---|---|
| A PRODUCTION_WIRING_INTEGRITY | **PASS** |
| B RUNTIME_CONTRACT_INTEGRITY | **PASS** |
| C FORMAL_CORRECTNESS | **FAIL** (scenario incomplete; Formal Normalizer/Auditor NOT_RUN on night_guard stop path) |
| D SCENARIO_FIDELITY | **FAIL** (final battle not reached; basement never entered) |
| E NATURAL_DECISION_QUALITY | **FAIL** (long-horizon incomplete; system_guided=73) |
| F PROGRESSION_CONVERGENCE | **FAIL** |

**FAILURE_AXIS_CLASS = MULTI_AXIS**

## Axis A/B evidence (PASS)

- `NATURAL_DECISION_RUNTIME_ACTIVE = true`
- `NDM_DECISION_COMMIT_COUNT = 173`
- `SAFE_LEGACY = 0`, `UNSAFE_LEGACY = 0`
- `NDM_DECISION_CAUSAL_COVERAGE = 1.0`
- `RUNTIME_CONTRACT_VIOLATION_COUNT = 0`
- `SAFE_FALLBACK_FAILURE/RECURSION = 0`
- `RECENT_ACTION_SCHEMA_MISMATCH = 0`

## Axis F primary blockers

| Metric | V18 | V17 ref |
|---|---|---|
| GOAL_DIRECTED_PROGRESS_RATE | **0.0** | 0.10 |
| LATERAL_EXPLORATION_PROGRESS_RATE | 0.994 | 0.70 |
| MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK | **173** | 35 |
| FRONTIER_PERSISTENCE | **0** | 1.30 |
| LOCATION_REVISIT_RATE | 0.808 | 0.762 |
| PROGRESSION_LOCAL_OPTIMUM_COUNT | 1 | true |
| MEANINGFUL_PROGRESS_INFLATION | **true** | — |
| CRITICAL_FRONTIER_SILENT_DROP | 0 | — |
| HIDDEN_SOLUTION_SIGNAL | 0 | — |
| CORBITT_SPECIFIC_FORCE_PATH | 0 | — |
| MANDATORY_TOP_FRONTIER_SELECTION | false | — |
| LATERAL_PROGRESS_GOAL_STALL_RESET_COUNT | 0 (stall continued) | — |

Semantics separation **instrumentation** worked (Meaningful ≠ counted as GD), but production Goal/Lead/Frontier **wiring into progression store** left `FRONTIER_PERSISTENCE=0` and never produced Goal-directed progress. Dual stall correctly stayed in `LOCAL_OPTIMUM` / high goal-convergence streak without clearing on lateral moves — yet that did not recover basement / final battle.

## Scenario outcome

- cycles=60, turns=117, location=`corbitt_ground_floor`
- house entered; basement door never unlocked; planks never examined/broken
- `corbitt_defeated=false`, combat INACTIVE, no kill route

## Policy

Do not resume, regenerate segments, overwrite Raw, retarget historical tags, or rerun this session.  
Video regeneration remains unauthorized until a later session earns Known-Good.
