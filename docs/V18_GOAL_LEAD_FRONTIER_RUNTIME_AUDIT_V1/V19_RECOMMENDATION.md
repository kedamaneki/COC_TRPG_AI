# V19 Recommendation (design only — NOT implemented)

**V19_IMPLEMENTATION_READY = false**  
**V19_ALLOWED = false** under this audit task.

## Constraints (retain)

```text
No hidden solution
No mandatory top frontier
No scenario-specific forced route
No artificial success injection
No forced objective completion
```

## MUST_FIX

1. **Production Lead population adapter**  
   From party-visible Known Facts / unresolved observations, upsert Lead objects into `LeadTracker` on the live NDM path (not tests only).

2. **Production Frontier population + persistence upsert**  
   Derive frontiers from active leads with reachability/executable/expected_effect fields; call `upsert_frontier` / defer on leave.

3. **Goal ID contract**  
   Ensure director/runtime exposes stable `goal_id` (not only display `current_goal` text) and forward into progress events + progression tick `visible_goal_ids`.

4. **Stop collapsing three roles onto `high_value_leads`**  
   Pass distinct goal_ids / lead_ids / frontier_ids into `tick_progression_cycle` and KP assessment.

5. **Action commit / telemetry binding**  
   Persist `goal_ids`, `lead_ids`, `frontier_id`, `expected_state_effect` on selected action / ACTION_SELECTED (observed effect after execution).

## SHOULD_FIX

- Production smoke that asserts non-empty Lead/Frontier stores after N cycles **without** fixture injection.
- Trace-break findings emission when chain empty despite active director goal.
- Remove or clearly mark synthetic `default_goal` so metrics do not imply a real goal object.

## OPTIONAL

- Richer Known-Facts → Lead heuristics documentation.
- Auditor findings for GOAL_LEAD_TRACE_BROKEN once Formal runs again.

## NOT_RECOMMENDED

- Hardcoding basement / planks / Corbitt house as mandatory frontiers.
- Forcing top frontier selection or S4 direct solution.
- Treating classifier Lateral fallback as the bug to “patch” without fixing population/binding.

## Suggested next task (owner approval required)

```text
V19_GOAL_LEAD_FRONTIER_RUNTIME_WIRING_DESIGN_V1
```

Docs-only design; no Full-Long until design approved and preflight gates redefine population+binding contracts.
