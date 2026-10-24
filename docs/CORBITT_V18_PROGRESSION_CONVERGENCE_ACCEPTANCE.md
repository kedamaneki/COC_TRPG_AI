# Corbitt V18 Progression Convergence (Axis F) — FAIL

**Session:** `CORBITT_LONGRUN_ITERATION3_V18_HOME_001`  
**PROGRESSION_CONVERGENCE = FAIL**

## Measured

| Metric | Value |
|---|---|
| MEANINGFUL_PROGRESS_RATE | 0.994 |
| GOAL_DIRECTED_PROGRESS_RATE | 0.0 |
| LATERAL_EXPLORATION_PROGRESS_RATE | 0.994 |
| MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK | 173 |
| FRONTIER_SWITCH_RATE | 0.665 |
| FRONTIER_PERSISTENCE | 0 |
| LOCATION_REVISIT_RATE | 0.808 |
| GOAL_RELEVANT_ACTION_RATE | 0.0 |
| PROGRESSION_LOCAL_OPTIMUM_COUNT | 1 |
| CRITICAL_FRONTIER_SILENT_DROP_COUNT | 0 |
| LATERAL_PROGRESS_GOAL_STALL_RESET_COUNT | 0 |
| HIDDEN_SOLUTION_SIGNAL | 0 |
| CORBITT_SPECIFIC_FORCE_PATH | 0 |
| MANDATORY_TOP_FRONTIER_SELECTION | false |
| MEANINGFUL_PROGRESS_INFLATION | true |

## Interpretation

- Dual-stall **did not** reset goal convergence on lateral NEW_LOCATION-style progress (desired).
- Goal-directed channel never fired in production (`GD=0`), so convergence pressure never converted into basement/planks resolution.
- Frontier persistence store remained empty (`FRONTIER_PERSISTENCE=0`) — production lead→frontier upsert path did not populate deferred planks frontier.
- Anti-railroading hard counters stayed clean; failure is under-convergence / local optimum, not forced solution.
