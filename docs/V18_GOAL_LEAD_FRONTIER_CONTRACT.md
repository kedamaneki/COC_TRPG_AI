# V18 Goal → Lead → Frontier → Action → State Effect Contract

**GOAL_LEAD_FRONTIER_CONTRACT = COMPLETE**  
**FRONTIER_TO_ACTION_CONTRACT = COMPLETE** (this doc + ASE doc)

## Formal chain

```text
Goal
 ↓
Lead
 ↓
Frontier
 ↓
Action Candidate
 ↓
Expected State Effect
 ↓
Observed State Effect
```

Silent breaks are forbidden: each hop must either link or record an explicit reason.

## Goal

```text
goal_id
statement
status              # ACTIVE | DEFERRED | RESOLVED | ABANDONED | SUPERSEDED
priority_class
source
visible_to_party    # must be true for GD classification
```

V17 failure mode: single vague goal with empty requirements → no discriminative GD signal. Contract requires visible goals to expose leads or declare `GOAL_WITHOUT_LEAD` reason.

## Lead

```text
lead_id
goal_ids[]
source_fact_ids[]
status              # NEW | ACTIVE | DEFERRED | RESOLVED | EXHAUSTED | INVALIDATED
unresolved          # bool
```

`GOAL_TO_LEAD_GAP`: active visible goal with zero leads and no `GOAL_WITHOUT_LEAD_REASON` is a contract violation for progression health (not a Raw rewrite).

## Frontier

```text
frontier_id
goal_ids[]
lead_ids[]
location
available_actions[]
expected_state_effects[]
reachable
executable
persistence_*       # see persistence model
```

`LEAD_TO_FRONTIER_GAP`: unresolved active lead with zero frontiers and no `LEAD_WITHOUT_FRONTIER_REASON` is a contract gap.

## Action Candidate

```text
candidate_id
frontier_id
action
target
required_location
expected_state_effect
```

### Frontier → Action availability reasons

When frontier exists but candidates = 0, **must** set one of:

```text
NO_ACTION_GENERATED
ACTION_BLOCKED
ACTION_EXHAUSTED
LOCATION_MISMATCH
TOOL_REQUIRED
INFO_REQUIRED
```

Silent drop of the frontier is forbidden (`FRONTIER_WITHOUT_ACTION_REASON_PATH = 0`).

## Traceability requirements

| Break | Required artifact |
|---|---|
| Goal without lead | `GOAL_WITHOUT_LEAD_REASON` |
| Lead without frontier | `LEAD_WITHOUT_FRONTIER_REASON` |
| Frontier without action | availability reason enum |
| Action without effect trace | `ACTION_WITHOUT_STATE_EFFECT_TRACE` finding candidate |

## Auditor finding candidates (design only)

```text
GOAL_LEAD_TRACE_BROKEN
LEAD_FRONTIER_TRACE_BROKEN
FRONTIER_ACTION_TRACE_BROKEN
ACTION_STATE_EFFECT_TRACE_BROKEN
CRITICAL_FRONTIER_SILENTLY_DROPPED
```

Not implemented in this task.

## Scenario independence

All IDs and links are generic. No `if target == basement_planks` force path. Corbitt vignette is test data only.
