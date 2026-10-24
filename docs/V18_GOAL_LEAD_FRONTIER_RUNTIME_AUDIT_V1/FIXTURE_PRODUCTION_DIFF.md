# Controlled Fixture vs Production Difference

Sources:
- Controlled: `core/src/test_v18_progression_convergence.py`, `scripts/ndm_progression_smoke_v18pre.py`
- Production: `CORBITT_LONGRUN_ITERATION3_V18_HOME_001` checkpoints + NDM telemetry

| Component | Controlled Fixture | Production | Status |
|---|---|---|---|
| Scenario input | Synthetic C8/C9 / smoke IDs | Full Corbitt run | different by design |
| Goal input | Explicit `visible_goal_ids` / `goal_ids` on events | Director `current_goal` text only; no `goal_id` | **FAIL production** |
| Goal creation (convergence) | Via tick with real IDs | Synthetic `default_goal` only | **FAIL production** |
| Lead creation | Implicit via fixture IDs / Lead upsert in NDM unit tests | **No production upsert** | **FAIL production** |
| Frontier creation | `upsert_frontier(...)` in fixture/smoke | **Never called** | **FAIL production** |
| ID binding into decide/tick | Explicit lists | Empty `high_value_leads` ×3 | **FAIL production** |
| Action selection | N/A or local | NDM 173 commits including basement-related | production selects actions |
| Trace emission | Fixture asserts DEFERRED/return pressure | Persistence=0; no G/L/F on events | **FAIL production** |
| Progress classification | GD when IDs linked | All lateral | expected given inputs |
| Metric aggregation | Non-null metrics v2 | Non-null but GD=0 / Persistence=0 | aggregation OK, inputs empty |

## First divergence

**Fixture-only injection** of Goal/Lead/Frontier objects and IDs.

Production Path after V18 modules landed:

- Modules exist and are imported by `runtime.decide` (`tick_progression_cycle`)
- **No adapter** populates LeadTracker / FrontierPersistenceStore from Known Facts or director goal
- Smoke/tests bypass this by constructing objects directly

This is a **Missing integration adapter**, not a Fixture-only false positive of the classifier itself.
