# V18 Goal / Lead / Frontier Runtime Audit V1

**TASK_ID:** `V18_GOAL_LEAD_FRONTIER_RUNTIME_AUDIT_V1`  
**AUDIT_STATUS:** PASS  
**SOURCE_RUN:** `CORBITT_LONGRUN_ITERATION3_V18_HOME_001`  
**HISTORICAL_INTEGRITY:** PASS (862 / `796150da1389a10fdd5bcfa7d0a4fcd131c7326f5354ae6c7dcdb6eebb7ff241`)  
**CODE_CHANGES:** 0 · **V18_RERUN:** NOT_EXECUTED · **V19_IMPLEMENTATION:** NOT_EXECUTED · **V19_READY:** false

## Executive Summary

| Field | Result |
|---|---|
| PRIMARY_ROOT_CAUSE | **MULTI_COMPONENT** with confirmed core = **LEAD_RUNTIME_POPULATION_GAP** + **FRONTIER_RUNTIME_POPULATION_GAP** + **GOAL_CONTEXT_BINDING_GAP** |
| ROOT_CAUSE_CONFIDENCE | **CONFIRMED** (static call-graph + cycle checkpoints + 173 commits) |
| PRODUCTION_WIRING_STATUS | NDM decide path active (173 commits, coverage 1.0) — **PASS for decision wiring** |
| GOAL_POPULATION_STATUS | Scenario director `current_goal` text exists; Convergence tracker only holds synthetic `default_goal`; no durable Goal IDs on events |
| LEAD_POPULATION_STATUS | **EMPTY** — `LeadTracker.upsert` has **zero production call sites** |
| FRONTIER_POPULATION_STATUS | **EMPTY all 60 cycles** — `upsert_frontier` has **zero production call sites** |
| ACTION_BINDING_STATUS | **0/173** commits carry goal/lead/frontier/effect IDs |
| TRACE_EMISSION_STATUS | Progress events emitted (NEW_LOCATION/NEW_FACT/…) but **without** goal/lead/frontier IDs |
| CLASSIFIER_STATUS | Behaves as designed: missing links → Meaningful+Lateral, GD=0 |
| AGGREGATION_STATUS | Largely faithful to classifier inputs (not the primary bug) |
| V19_READY | false |

### Answer to the audit question

> 本番で Goal/Lead/Frontier を作れなかったのか / 作れても意思決定に渡せなかったのか / 記録・分類だけ壊れていたのか？

**作れなかった（Lead/Frontier 永続オブジェクト）＋ Goal ID 契約が未配線。**  
意思決定自体は NDM で成立し、地下室関連アクション候補も選ばれているが、Goal→Lead→Frontier オブジェクト生成と ID バインディングが production に未接続のため、Metric 上は GD=0 / Persistence=0 / Trace FAIL になる。Classifier/Aggregation の単独故障ではない。

## Layer evidence model

| Layer | Finding |
|---|---|
| 1 Scenario facts | house entered; basement not reached; many `search basement_door` / `move corbitt_basement` / `push basement_door` actions selected |
| 2 Runtime internal | `LeadTracker` empty; frontier store empty; synthetic `default_goal` only in progression_convergence |
| 3 Persisted | ACTION_SELECTED ×173 without G/L/F/effect fields; progress_events without G/L/F IDs |
| 4 Derived metrics | GD=0, Lateral≈Meaningful, Persistence=0 — consistent with Layers 2–3 |

## First broken boundary

```text
Goal ID contract (director.current_goal text ≠ goal_id)
  → Lead creation NEVER invoked in production   ← FIRST HARD BREAK
  → Frontier upsert NEVER invoked               ← immediate cascade
  → Action commit has no frontier_id
  → Expected/Observed effect not on commit
  → Classifier sees no GD links → Lateral
```

T1 = FAIL (population)  
T2 = NOT_REACHED (no leads)  
T3–T5 = FAIL as downstream / NOT_REACHED for real chain

## Phase findings (condensed)

### Goal
- Director goal blob present (`current_goal` = 「悪霊の家」 by house exterior).
- `goal_id` field absent → `emit_progress_from_director_delta` writes empty `goal_id`.
- `tick_progression_cycle` invents `default_goal` when `visible_goal_ids` empty (`progression_convergence.py`).

### Lead
- Static scan: `leads.upsert` / `Lead(` upsert only under `test_*.py`.
- Runtime syncs `st.high_value_leads` from empty `LeadTracker.unresolved_high_value_frontier_set()`.

### Frontier
- `FRONTIER_PERSISTENCE=0` = **P1 SUPPORTED/CONFIRMED** (never created in store).
- P2–P5 rejected as primary (nothing to bind/resolve/transfer/aggregate).

### 173 NDM commits
- Unique ACTION_SELECTED = 173 = telemetry commit count.
- DECISIONS_WITH_GOAL/LEAD/FRONTIER/EFFECT = **0**.
- All binding_class = `MULTIPLE_MISSING_LINKS`.
- Decision source all `natural_decision_v1`.

### Classifier
- Re-eval with empty context on last progress buffer: Meaningful=true, GD=false, Lateral=true.
- Matches production rates. **Not** the first break.

### Fixture vs Production
| Component | Controlled Fixture / Smoke | Production Full-Long |
|---|---|---|
| Scenario input | synthetic | real |
| Goal/Lead/Frontier objects | **manually upserted / IDs injected** | **not created** |
| tick_progression_cycle | called with explicit IDs | called with empty `high_value_leads` thrice |
| Trace/persistence | PASS in fixture | Persistence=0 |

**First divergence:** Fixture-only injection of Goal/Lead/Frontier; production lacks population adapter from Known Facts / director goal → LeadTracker / FrontierPersistenceStore.

## Hypothesis candidates (G1–G8 / A–I)

| ID | Verdict |
|---|---|
| A Goal object missing | **PARTIAL** — narrative goal exists; ID’d Goal Convergence object = synthetic only |
| B Lead not generated | **CONFIRMED** |
| C Frontier not generated | **CONFIRMED** (cascade + no upsert) |
| D Frontier not bound to action | Downstream of C |
| E Trace missing only | **REJECTED as sole cause** — objects themselves absent |
| F Classifier misclassify | **REJECTED as primary** — correct given missing links |
| G Aggregation bug | **REJECTED as primary** |
| H Multiple | **CONFIRMED** (Lead+Frontier+Goal-ID binding) |
| I No goal-related actions selected | **REJECTED** — basement-related actions selected repeatedly |

## Unresolved

- Exact per-cycle PL Known Facts graph not fully reconstructed (schema scattered; flags often NOT_IN_STATE in checkpoints).
- Why `move corbitt_basement` did not yield `in_basement=true` (action success / door lock) — separate from population gap; needs scenario-effect audit if V19 cares about physical progress.
- Formal Normalizer/Auditor NOT_RUN (pre-audit block) — not treated as audit failure.

## Artifacts

- `RUNTIME_POPULATION.csv`
- `DECISION_BINDING.csv`
- `PROGRESS_EVENTS_SAMPLES.csv`
- `AUDIT_SUMMARY.json`
- `EVIDENCE_MATRIX.md`
- `FIXTURE_PRODUCTION_DIFF.md`
- `TRACE_FAILURE_ANALYSIS.md`
- `V19_RECOMMENDATION.md`
