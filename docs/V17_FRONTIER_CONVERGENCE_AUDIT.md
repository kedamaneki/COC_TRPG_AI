# V17 Frontier Convergence Audit

## Verdict

```text
FRONTIER_CONVERGENCE_QUALITY = FAIL
FRONTIER_SWITCH_RATE ≈ 0.7627
FRONTIER_PERSISTENCE ≈ 1.3043
CRITICAL_TOP_CANDIDATE_IGNORED = 17 / 17
```

## High-value / continuity set

`director_v2.candidate_continuity_scores` typically hold 3-ish entries with components like `declared_state_effect` + `new_local_information`. Many non-critical targets share **score 55**, so ranking is flat.

Examples:

- C8 basement: top=`basement_planks` (55) — **not selected** as resolving action; leave next cycle.
- Mid/late GF: top often `storage_room1_cupboard` (55–65) while `move/corbitt_basement` appears with **negative** scores (−15) and is still sometimes the only converging option — yet selection prefers door/cupboard.

## Over-broad / switching

- Switch rate ~0.76 ⇒ selected (action,target) changes most cycles.
- Persistence ~1.3 ⇒ almost no multi-cycle stickiness on the same frontier.
- DEFERRED reactivation: cupboard / basement_door / hidden_passage rotate for dozens of cycles after door unlock — classic oscillation, not deepening.

## Goal relevance weight

Explicit goal is constant `悪霊の家` with empty requirements → **goal_relevance cannot win** because everything “fits.” Continuity scoring is dominated by local information / declared state-effect proxies, i.e. novelty-adjacent signals.

KP-facing `available_meaningful_frontiers` is always `[]`, so NDM/KP cannot prefer “high-value unresolved frontier set” at assessment layer even when continuity candidates exist.

## Novelty bias

Observed preference order in mass counts:

1. revisit GF / cupboard / clutter  
2. re-search already-unlocked basement_door  
3. occasional planks / basement move  

Known unresolved lead (planks after C8) loses to novelty/local loops.

## Chain gaps

| Gap | Result |
|---|---|
| SCENARIO_FRONTIER_GAP | **false** — planks/basement candidates exist |
| GOAL_TO_LEAD_GAP | **true** — KP leads always empty |
| LEAD_TO_FRONTIER_GAP | **true** — KP frontiers always empty |
| FRONTIER_TO_ACTION_GAP | **true** — critical top ignored 17/17 |
| ACTION_TO_STATE_EFFECT_GAP | **true** — `search/basement_planks` ×10 without examined/broken; V13 progressed via `wall_planks` path |

## NDM policy note

NDM **does** commit causally (202/202 `natural_decision_v1`). Failure is not “NDM off,” but selection among flattened frontiers without convergence pressure. Treat as **partial** NDM_DECISION_POLICY_PROBLEM inside MULTI_COMPONENT — do not start with weight-only hacks or hidden-solution scoring.
