# V18 Stall Classification v2 (Dual Stall)

**DUAL_STALL_MODEL = DEFINED**  
**STALL_CLASSIFICATION_V2 = COMPLETE**

## Problem (V17)

Single stall notion was dominated by Meaningful Progress resets → Goal drought invisible while `no_progress_streak` / KP disagreed.

## Two stalls

### ACTIVITY_STALL

Party is not doing anything meaningful.

- Increment when cycle has no Meaningful Progress.
- Reset when Meaningful Progress occurs (including Lateral).

### GOAL_CONVERGENCE_STALL

Party may be busy, but not advancing currently visible Goal/Lead/blocker set.

- Increment when cycle has **no** Goal-Directed Progress.
- Reset only on Goal-Directed (or Terminal) Progress.
- **Lateral Meaningful Progress does not reset** this stall.

## Canonical matrix

| Meaningful | Goal-Directed | ACTIVITY_STALL | GOAL_CONVERGENCE_STALL |
|---|---|---|---|
| no | no | increment | increment |
| yes (lateral) | no | reset | **increment** |
| yes | yes | reset | reset |
| terminal | yes | reset | reset |

This is the **center** of V17 recurrence prevention:

```text
Meaningful = yes AND Goal-directed = no
→ ACTIVITY_STALL = reset
→ GOAL_CONVERGENCE_STALL = continue/increment
```

## Tracker fields (minimum)

```text
activity_stall_streak
goal_convergence_stall_streak
max_activity_stall_streak
max_goal_convergence_stall_streak
last_meaningful_progress_cycle
last_goal_directed_progress_cycle
```

## Interaction with existing S-levels

Do **not** redefine S0–S4 meanings. Dual stall feeds KP assessment as separate inputs:

- activity stall → classic “doing nothing” interventions
- goal-convergence stall → goal self-review / lead reminder / frontier persistence nudge path (see Goal Convergence Model)

Immediate S4 on goal stall alone is **forbidden**.

## Metrics

```text
MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK  # = max goal_convergence_stall_streak
ACTIVITY_STALL vs GOAL rates for acceptance dashboards
```
