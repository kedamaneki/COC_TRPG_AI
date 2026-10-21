# CORBITT V14 — Progression Failure Root Cause Tree

**Stop reason:** `FULL_LONG_COMPLETION_CONTRACT_FAIL`  
**Final:** C60 / T143 / `chapel_of_contemplation` / `completed=false`  
**Basement reached:** true once (C31) · **Planks broken:** false · **Boss:** false

## Root cause tree (evidence-linked)

```text
Early path variance (city-heavy; upper before basement)
        ↓
Basement finally reached (C31); wall_planks examined
        ↓
break wall_planks attempted and FAILED (recorded in stall.recent_failed_actions by C32)
        ↓
AUTONOMOUS leave basement → ground floor
  DESPITE continuity_score #1 still break wall_planks (180, local_frontier)
        ↓
Move chain to chapel (C33); SYSTEM_GUIDED attaches to chapel local frontiers
        ↓
Chapel rotting_floorboards / white_symbol consume guided attention
  (side progress: chapel_investigated; critical plank frontier forgotten)
        ↓
Location objective EXHAUSTED + wait loops
        ↓
S4 forced recovery (C42) sees move→corbitt_basement AVAILABLE
  but forces move→boston_globe (s3_candidate_ignored)
        ↓
City/neighborhood revisit thrash (no second basement visit)
        ↓
Return to chapel dead-end candidates
  (floorboards event requires in_basement==true while guard/conflict disagree)
        ↓
Cycle 60 max-cycles → FULL_LONG_COMPLETION_CONTRACT_FAIL
```

## PRIMARY_ROOT_CAUSE

**PROGRESSION_RECOVERY_FAILURE after incomplete basement plank frontier**

Specifically: after `basement_planks_examined=true` and a failed `break wall_planks`, the runtime did not keep the actor on (or forcibly return to) the still-ranked local break frontier; subsequent guidance/S4 recovery preferred chapel/city sinks.

## SECONDARY_ROOT_CAUSES

1. **LLM_PATH_VARIANCE** — autonomous exit from basement while break remained top-ranked  
2. **CONTINUITY_SCORING / LOCATION BINDING GAP** — high local_frontier scores do not survive / rebind after location change  
3. **SCENARIO_FRONTIER_GAP** — chapel `rotting_floorboards` presents an attractive break frontier that is not on the Corbitt kill path and carries conflicting `in_basement` conditions  
4. **PREEXISTING_PROGRESSION_INSTABILITY** — V14 max no-progress 34 vs V13’s 7; large guided/forced counts without critical-path completion  
5. **S4 SELECTION MISS** — C42 candidates included `corbitt_basement`; forced action chose `boston_globe`

## Failure class

```text
V14_FAILURE_CLASS =
  PROGRESSION_STALL_AFTER_PARTIAL_BASEMENT_PROGRESS
  + RECOVERY_MISS_ON_OPEN_CRITICAL_FRONTIER
  + CHAPEL_SIDE_FRONTIER_SINK
```

Multi-label tags from the audit taxonomy:

- `PREEXISTING_PROGRESSION_INSTABILITY`
- `LLM_PATH_VARIANCE`
- `CONTINUITY_SCORING_REGRESSION` (behavioral; not implying a specific unproven commit bisect)
- `SCENARIO_FRONTIER_GAP`
- `UNKNOWN` components remain around why the in-basement break failed mechanically (dice/availability detail not fully reconstructed from checkpoint alone)

## Quantitative comparison

| Metric | V13 | V14 |
|---|---|---|
| Total cycles | 25 | 60 |
| Basement first arrival | C10 / T23 | C31 / T75 |
| Basement visits (checkpoint locs) | 6+ (basement + room2) | 1 |
| Planks broken | true (by C21) | false |
| Max no-progress (evaluator maximum_no_progress) | 7 | 34 |
| Location revisit extras (visits−1 summed) | 19 | 48 |
| Unique locations | 6 | 12 |
| Final forced / guided counts | 4 / 25 | 22 / 60 |
| Chapel | none | 14 checkpoint visits |
| Clear / boss | yes | no |

## S4_BEHAVIOR summary

- S4 **was reached** (explicit on forced actions; e.g. C16, C42).  
- S4 **did not recover** the critical basement plank/boss route when a direct `move→corbitt_basement` candidate was available (C42).  
- Therefore: `S4_RECOVERY = FAIL` (not NOT_REACHED).

## What this is not

- Not a Formal Normalizer/Auditor defect (not reached; incomplete run).  
- Not evidence that WP-A/B/C combat remediation blocked exploration (boss never entered; no kill-route / BossCombatPolicy activation observed).  
- Not solved by “LLM picked differently” without addressing recovery binding to open critical frontiers.
