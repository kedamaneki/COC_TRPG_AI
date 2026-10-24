# V18 Progress Semantics v2

**MEANINGFUL_GOAL_DIRECTED_SEPARATION = DEFINED**

## Principle

```text
MEANINGFUL_PROGRESS ≠ GOAL_DIRECTED_PROGRESS
```

Acceptance must **not** judge health by `MEANINGFUL_PROGRESS_RATE` alone (V17 lesson: 0.995 with non-convergence).

## Progress classes

| Class | Meaning | Resets ACTIVITY_STALL? | Resets GOAL_CONVERGENCE_STALL? |
|---|---|---|---|
| `MEANINGFUL_PROGRESS` | Any valued investigation activity | yes (if present) | **no** by itself |
| `GOAL_DIRECTED_PROGRESS` | Advances currently visible Goal/Lead/blocker/frontier | yes | **yes** |
| `LATERAL_EXPLORATION_PROGRESS` | Valuable side exploration not advancing current GD set | yes | **no** (continue/increment) |
| `TERMINAL_PROGRESS` | Goal resolve / major blocker clear / boss / validated kill / scenario clear | yes | yes |

A single cycle may emit multiple classes (e.g. NEW_LOCATION that is also GD). Classification is multi-label via `progress_types` + derived `progress_class` set.

## Meaningful Progress

Examples: new fact, new location, new hypothesis, resource gain, NPC interaction, object state change with observable effect.

Rule: `meaningful = true` **must not** fully clear Goal Convergence Stall.

## Goal-Directed Progress (legal visibility only)

**Allowed evidence:**

- current explicit goal_ids
- known unresolved lead_ids
- known blockers
- known frontier_ids
- observed_state_effect tied to those

**Forbidden evidence:**

- “near ending”
- author solution
- future required events
- hidden objectives / hidden solution scoring

## Lateral Exploration Progress

Examples: new room with no link to active GD set; minor adjacent mystery; information that does not move current blockers.

Value: preserve human-like exploration. Effect on stalls: activity reset only; goal-convergence stall continues.

## Terminal Progress

Distinct class for scenario-critical completions (defeat, clear, validated kill route commit, etc.). Does not imply those IDs are known a priori as “correct path” during play—only that observed terminal contracts fired.

## Progress Event schema v2

```text
progress_event_id
schema_version = 2
progress_class          # primary class for indexing; may also list
progress_classes[]      # multi-label
progress_types[]        # NEW_FACT | NEW_LOCATION | ...
goal_ids[]
lead_ids[]
frontier_ids[]
source_event_ids[]
observed_state_effect   # structured or null
expected_state_effect_ref  # optional link to candidate
cycle
turn
actor_id
```

Backward compatible: v1 events without `progress_classes` map to Meaningful-only via adapter; Goal-Directed defaults false unless classifiers prove GD from visible links.

## Mapping from V17 types (informative)

| V17 progress_type | Default v2 tendency |
|---|---|
| NEW_LOCATION | Meaningful + often Lateral |
| NEW_FACT / OBJECT_STATE_CHANGE | Meaningful; GD only if linked to active lead/blocker |
| OBJECTIVE_ADVANCEMENT | Meaningful + Goal-Directed when goal/lead attached |
| RESOURCE_GAIN / RISK_DISCOVERY | Meaningful; GD iff linked |

No Corbitt-specific type hacks.
