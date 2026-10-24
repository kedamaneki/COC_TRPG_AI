# V18 Progression Convergence Precheck Gates

**V18_PRECHECK_GATES = COMPLETE**  
**V18_READY remains false until implementation + gates PASS + Human Review of results.**

## Formal gates (minimum)

```text
PROGRESS_CLASS_SEPARATION = PASS
GOAL_CONVERGENCE_STALL = PASS
GOAL_TO_LEAD_TRACE = PASS
LEAD_TO_FRONTIER_TRACE = PASS
FRONTIER_TO_ACTION_TRACE = PASS
ACTION_TO_STATE_EFFECT_TRACE = PASS
FRONTIER_PERSISTENCE = PASS
CRITICAL_FRONTIER_SILENT_DROP = 0
LATERAL_PROGRESS_GOAL_STALL_RESET = 0
PROGRESSION_LOCAL_OPTIMUM_DETECTION = PASS
HIDDEN_SOLUTION_SIGNAL = 0
CORBITT_SPECIFIC_FORCE_PATH = 0
MANDATORY_TOP_FRONTIER_SELECTION = false
DIRECT_SOLUTION_S4_PATH = 0
```

## Gate meanings

| Gate | Pass criterion |
|---|---|
| PROGRESS_CLASS_SEPARATION | Meaningful / GD / Lateral / Terminal measurable independently |
| GOAL_CONVERGENCE_STALL | Dual stall unit + PS3 behavior |
| *_TRACE | Contract reason or link present; silent break = fail |
| FRONTIER_PERSISTENCE | FP1/FP2 |
| CRITICAL_FRONTIER_SILENT_DROP | 0 silent drops of important unresolved frontiers |
| LATERAL_PROGRESS_GOAL_STALL_RESET | 0 cases where lateral-only progress clears goal stall |
| LOCAL_OPTIMUM_DETECTION | LO1 |
| HIDDEN_SOLUTION_SIGNAL | 0 scoring/paths using hidden solution |
| CORBITT_SPECIFIC_FORCE_PATH | 0 production hard-codes forcing Corbitt targets |

## Metrics v2 (acceptance dashboards)

```text
MEANINGFUL_PROGRESS_RATE
GOAL_DIRECTED_PROGRESS_RATE
LATERAL_EXPLORATION_PROGRESS_RATE
MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK
FRONTIER_SWITCH_RATE
FRONTIER_PERSISTENCE
CRITICAL_FRONTIER_IGNORE_RATE
LOCATION_REVISIT_RATE
GOAL_RELEVANT_ACTION_RATE
PROGRESSION_LOCAL_OPTIMUM_COUNT
```

**Do not** accept/reject Full-Long on Meaningful rate alone.

## Smoke identity

```text
CORBITT_PROGRESSION_CONVERGENCE_SMOKE_V18PRE_001
```

Formal Full-Long session ID is **not** reserved by this design doc alone.

## Precheck order (future)

1. Deterministic fixture suite (PS/GC/FP/FI/FA/SE/LO/RR)  
2. Smoke session above  
3. Historical Raw rehash (unchanged)  
4. Only then consider Fresh Full-Long under a new session ID  

This design task does **not** run those steps.
