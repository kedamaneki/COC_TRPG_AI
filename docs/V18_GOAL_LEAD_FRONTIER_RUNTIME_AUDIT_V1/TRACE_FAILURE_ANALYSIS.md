# Trace Failure Analysis

Canonical chain:

```text
Goal → Lead → Frontier → Action → Expected Effect → Observed Effect
```

| Boundary | Result | Notes |
|---|---|---|
| T1 Goal → Lead | **FAIL** | No production Lead creation; director goal lacks `goal_id` |
| T2 Lead → Frontier | **NOT_REACHED** | No leads to expand |
| T3 Frontier → Action | **FAIL** | Frontier store empty; selected actions have no `frontier_id` |
| T4 Action → Expected Effect | **FAIL** | Not recorded on ACTION_SELECTED / candidates in telemetry |
| T5 Expected → Observed | **FAIL / NOT_OBSERVABLE** | No expected effect on commit trail |

## First break

**T1 / Lead population + Goal ID contract** is the first hard production break.

Downstream empty frontiers, missing action bindings, Lateral-only classification, Persistence=0, and Goal-directed=0 are **symptoms**.

## Code path (static)

1. `ndm_integration.enrich_pc_action_with_ndm` → `NaturalDecisionRuntime.decide`
2. `decide` syncs `st.high_value_leads` from `LeadTracker.unresolved_high_value_frontier_set()` (**empty**)
3. `tick_progression_cycle(..., visible_goal_ids=high_value_leads, unresolved_lead_ids=high_value_leads, known_frontier_ids=high_value_leads)` — three roles collapsed onto empty list
4. No call to `upsert_frontier` / `LeadTracker.upsert` on this path
5. `emit_progress_from_director_delta` sets `goal_id` from `director_v2.goal.goal_id` (absent; only `current_goal` text)

## Classifier consequence

With no goal/lead/frontier IDs on events and empty visible sets:

```text
MEANINGFUL_PROGRESS = true (kinds match)
GOAL_DIRECTED_PROGRESS = false
LATERAL_EXPLORATION_PROGRESS = true
```

Reproduced read-only on final progress_events buffer (`AUDIT_SUMMARY.json` → `classifier_reeval_empty_context`).
