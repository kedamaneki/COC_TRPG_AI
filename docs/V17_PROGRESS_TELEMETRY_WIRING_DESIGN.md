# V17 Progress Telemetry Wiring Design

**Track D**  
**Status:** COMPLETE  
**NDM_ALGORITHM_CHANGE_PLANNED:** false (wiring only; KP kinds may map existing ProgressDirector signals)

## V16 problem mix (formal)

| Observation | Class |
|---|---|
| MEANINGFUL_PROGRESS_RATE = 0 / SELF_RECOVERY_RATE = 0 | reported |
| UEL `progress_delta > 0` on 28 turns; many true flags | world progress existed |
| `enrich_pc_action_with_ndm` never passed `progress_events` | RAW_INSTRUMENTATION_GAP |
| Metric only counts NDM KP assess path | AGGREGATION_GAP |
| 194 SAFE_LEGACY commits | NDM_NOT_CONTROLLING_ACTIONS |

V17 wires producers so Full-Long rates are **always numeric** (never null). Null ⇒ `NATURAL_DECISION_QUALITY = BLOCKED`.

## Meaningful progress Raw event

```text
ProgressEvent {
  progress_event_id: str
  progress_type: enum
  progress_class: "MEANINGFUL" | "NON_MEANINGFUL" | "UNKNOWN"
  source_event_id: str | null
  actor_id: str
  cycle: int
  turn: int
  goal_id: str | null
  lead_id: str | null
  schema_version: 1
}
```

### progress_type enum

| progress_type | Maps from (examples) |
|---|---|
| NEW_FACT | new investigation fact / knowledge flag |
| NEW_LOCATION | location change to previously unvisited |
| HYPOTHESIS_RESOLVED | hypothesis tracker resolution |
| NEW_VIABLE_LEAD | lead upsert high-value open |
| OBJECT_STATE_CHANGE | object_states / item acquisition |
| OBJECTIVE_ADVANCEMENT | requirement / goal step completed |
| RISK_DISCOVERY | major risk signal |
| RESOURCE_GAIN | useful resource acquisition |

Align with existing `MEANINGFUL_PROGRESS_KINDS` via a stable mapping table in implementation (no PL/KP scoring rewrite).

## Production wiring points

1. **ProgressDirectorV2 / ProgressTrackerV2** — when `progress_delta > 0` or requirement flags change, emit one or more `ProgressEvent` into a session buffer (e.g. `director_v2.progress_events` ring + NDM telemetry mirror).  
2. **ndm_integration.enrich_pc_action_with_ndm** — pass `progress_events=list(buffer[-N:])` into `rt.decide(...)`.  
3. **NaturalDecisionRuntime** — continue using `assess_party_progress(..., progress_events=...)`; increment `meaningful_progress_count` when assessment says so **and/or** when a MEANINGFUL ProgressEvent was consumed this decide (document single source of truth in impl: prefer assessment result fed by wired events).  

Design QA: `PROGRESS_EVENT_UNWIRED_PATH = 0` for production enrich path.

## Self-recovery Raw evidence

Self recovery is detectable iff all are present / linkable:

```text
stall_detected: bool                         # from stall signals / no_progress
self_review_event_id: str                    # PL self-review / S1-class evidence id
kp_intervention_before_recovery: false       # no KP escalate before recovery action
meaningful_action_event_id: str              # action event after self-review
progress_event_id: str                       # subsequent ProgressEvent
```

Emit `SELF_RECOVERY_RECORDED` (or equivalent telemetry event) when the chain closes.  
`self_recovery_count` increments only on recorded chains (not on SAFE_LEGACY).

## Full-Long non-null metric contract

Always emit numeric rates (0.0 allowed):

- UNEXPLAINED_ACTION_RATE  
- UNRESOLVED_LEAD_ABANDON_RATE  
- SELF_RECOVERY_RATE  
- MEANINGFUL_PROGRESS_RATE  
- (+ existing NDM rates)

If any required rate is null/missing at Full-Long acceptance aggregation:

`NATURAL_DECISION_QUALITY = BLOCKED`.

Design QA: `FULL_LONG_METRIC_NULL_PATH = 0`.
