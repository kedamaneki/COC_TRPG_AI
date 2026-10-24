# V18 Goal Convergence Model

**GOAL_CONVERGENCE_MODEL = COMPLETE**

## Purpose

Give the runtime a **Goal Convergence Signal** without railroading. NDM stays; KP/S-level gain better inputs.

## Goal Convergence Tracker (per active goal)

```text
goal_id
last_goal_directed_progress_cycle
goal_no_progress_streak          # alias of GOAL_CONVERGENCE_STALL for this goal
active_lead_count
active_frontier_count
unresolved_blockers[]
recent_attempts[]                # frontier_id / action / result summaries
```

Party-level aggregate: max / sum of goal_no_progress_streak across visible active goals.

## Escalation (soft, ordered)

Thresholds are configuration, not hard-coded Corbitt values. On rising `goal_no_progress_streak`:

```text
G0 normal exploration
G1 goal self-review        (“今の目的は何だった？”)
G2 unresolved lead reminder (known leads only)
G3 frontier persistence nudge (return_condition / deferred set)
G4 recovery toward valid frontier *set* (not a single correct action)
```

G-levels are **conceptual inputs** to existing S0–S4 / KP intervention selection — a new parallel level system is optional, not required.

## KP Intervention redesign (goal stall path)

Distinguish:

| Situation | KP stance |
|---|---|
| Activity stall | classic idle / repeat interventions |
| Goal convergence stall | self-review → lead reorder → frontier set reminder |

Order on goal stall (aligned with S1–S4 *spirit*, not forced mapping):

```text
S1: clarify current explicit goal
S2: organize known unresolved leads
S3: remind important deferred/executable frontiers
S4: recover to a valid frontier *set*
```

**Never** name the single correct action / hidden solution.

## Local Optimum detection

```text
PROGRESSION_LOCAL_OPTIMUM when sustained:
  meaningful_progress high
  goal_directed_progress low
  location_revisit_rate high
  frontier_switch_rate high
```

Response: same soft ladder (self-review → lead re-rank → persistence), **not** immediate S4.

Evidence uses only observed rates — no hidden solution.

## Scoring auxiliary axes (not one-shot weight fix)

Keep existing axes: goal_relevance, information_gain, continuity, novelty, risk, cost, character_fit.

Add **auxiliary** (non-absolute) pressures:

```text
goal_stall_pressure
frontier_persistence
unresolved_blocker_value
return_value
```

These bias candidate ranking softly. They must **not** implement:

- absolute forced solution
- mandatory top frontier
- hidden-solution bonus

## Anti-railroading

Goal stall growth never implies “must select author path.” Leave, defer, and lateral exploration remain legal while trackers continue.
