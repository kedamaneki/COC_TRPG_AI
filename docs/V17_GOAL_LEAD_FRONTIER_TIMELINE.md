# V17 Goal / Lead / Frontier Timeline

**Source:** read-only checkpoints + NDM telemetry of `CORBITT_LONGRUN_ITERATION3_V17_HOME_001`  
**Raw unchanged.**

## Goal state (C0–C60)

| Field | Observation |
|---|---|
| `current_goal` | From C2 onward constant: `悪霊の家` |
| `remaining_requirements` | Always `[]` |
| `completed_requirements` | Always `[]` |
| `subgoals` | Always `[]` |
| Goal create/activate/resolve/abandon events | **Not observed** as structured lifecycle events |

Interpretation: the explicit goal object does not provide a decomposable goal stack. Almost any house exploration can claim relevance to `悪霊の家`, so goal relevance cannot discriminate lateral vs converging actions.

## Lead lifecycle (KP-facing)

Across **202** `KP_PROGRESS_ASSESSED` events:

| Field | Count non-empty |
|---|---|
| `unresolved_leads` | **0 / 202** |
| `available_meaningful_frontiers` | **0 / 202** |
| `exhausted_frontiers` | 0 / 202 |
| `meaningful_progress_this_cycle=true` | 201 / 202 |
| `current_progress_trend=advancing` | 201 / 202 |

Therefore NEW→ACTIVE→RESOLVED lead transitions are **not reconstructible from KP assessments** (signal gap). Visually inferred leads from flags/actions:

| Lead (observed) | First evidence | Status at C60 |
|---|---|---|
| Enter house / ground floor | C5–C7 | RESOLVED (entered) |
| Unlock basement door | ≤C8 (`basement_door_unlocked=true`) | RESOLVED |
| Basement access | C8 loc=`corbitt_basement`, `basement_accessible=true` | RESOLVED (access) |
| Basement planks | C8 top continuity cand=`basement_planks`; searched ×10 later | **ACTIVE unresolved** (`examined=false`, `broken=false`) |
| Corbitt body / boss | never | never activated |
| Magic dagger / knife ownership | `has_corbitt_knife=false` | never |

## Frontier timeline (continuity candidates + selected actions)

Continuity candidates **do** include basement-critical targets. Example at first basement arrival (C8):

- top cand: `search/basement_planks` score 55  
- selected last action recorded: `search/scattered_junk`  
- next cycle C9: location=`corbitt_ground_floor`, top cand becomes `storage_room1_cupboard`

Critical top-candidate present in **17** cycles; selected action matched top critical cand in **0 / 17**.

### Selected-action mass (202 commits)

| action\|target | count |
|---|---|
| move\|corbitt_ground_floor | 37 |
| search\|storage_room1_cupboard | 35 |
| search\|basement_door | 29 |
| search\|living_room_clutter | 14 |
| search\|hidden_passage | 12 |
| search\|basement_planks | 10 |
| search\|kitchen_breaker_box | 9 |
| move\|corbitt_basement | 5 |

## Compact cycle table (key window + late samples)

| C | location | last action/target | planks ex/br | bsmt_acc | streak | top cand |
|---|---|---|---|---|---|---|
| 7 | corbitt_ground_floor | search/basement_door | F/F | F→ | 1 | push/basement_door (170, local) |
| 8 | **corbitt_basement** | search/scattered_junk | F/F | T | 1 | **search/basement_planks (55)** |
| 9 | corbitt_ground_floor | search/hidden_passage | F/F | T | 4 | search/storage_room1_cupboard |
| 10–15 | upper / ground | bedroom/bath loops | F/F | T | 0–5 | spare_bedroom / move GF |
| 17–21 | basement↔GF | cupboard / door / junk / planks | F/F | T | 13–21 | cupboard or planks |
| 29–35 | ground_floor | basement_door / cupboard | F/F | T | 50–66 | cupboard |
| 45–59 | ground_floor | basement_door inspect/search | F/F | T | 4–57 | move/basement often **score −15** |
| 60 | ground_floor | move/ground_floor | F/F | T | 61 | move/ground_floor |

Full compact timeline: `docs/V17_PROGRESSION_CONVERGENCE_METRICS.json` → `timeline_v17_compact`.

## Important frontier first/last

| Frontier | first generated (cand) | first selected | last selected | resolved? |
|---|---|---|---|---|
| basement_planks | ≤C8 | yes (×10 searches across run) | late mid-run | **No** (flags never flip) |
| move corbitt_basement | intermittent | ×5 | late | access only; no plank resolve |
| storage_room1_cupboard | ≤C9 | dominant | through late run | N/A (lateral) |
| basement_door (post-unlock) | early | ×29 | late | door already unlocked — non-converging |

## S-level

NDM S-level authority=`natural_decision_v1`. Observed transitions remain at S0 family; `PREMATURE_S4=0`, `UNNECESSARY_S4=0`. KP `current_hint_level` stays low because meaningful progress keeps resetting intervention necessity.
