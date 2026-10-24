# V17 Scenario Progression Convergence Audit V1

**Status:** `V17_SCENARIO_PROGRESSION_CONVERGENCE_AUDIT_V1 = PASS`  
**Session:** `CORBITT_LONGRUN_ITERATION3_V17_HOME_001`  
**Compare:** `CORBITT_LONGRUN_ITERATION3_V13_HOME_001` (Known-Good, read-only)  
**CODE_CHANGED = 0** · **V17_RAW_CHANGED = 0** · **AUDIT_DOCS_COMMITTED = false** · **V18_READY = false**

## Premise

V17 achieved NDM wiring / runtime contract / NDM quality PASS (`NDM_DECISION_COMMIT_COUNT=202`, coverage=1.0, SAFE/UNSAFE legacy=0, meaningful rate≈0.995) but failed scenario completion at C60 on `corbitt_ground_floor` without final battle.

Central question: why did continuous “meaningful progress” + healthy NDM commits fail to converge on the scenario goal?

## Immutable preflight

| Artifact | Result |
|---|---|
| Git | `main` @ `56ab45d` present; working tree clean at audit start |
| V17 Raw | 862 / `ca7f5627007ec8e0452a6c6de11c4f2d893c28ccc2ab355557065cf0bfcacb9c` = PASS |
| V13 Raw | 373 / `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d` = PASS |

## Executive answer

Meaningful progress is **inflated** by `NEW_LOCATION` / `OBJECT_STATE_CHANGE` / `NEW_FACT`, while **goal/lead/frontier signals are empty** (`KP unresolved_leads=[]` and `available_meaningful_frontiers=[]` for all 202 assessments). After **first basement arrival at C8**, the party **left at C9** without resolving planks; thereafter ground-floor cupboard / basement_door / hidden_passage oscillation produced local novelty that kept KP `meaningful_progress_this_cycle=true` / trend=`advancing`, so **no convergence pressure / no S4**, despite director `no_progress_streak` rising.

```text
FIRST_CONVERGENCE_DIVERGENCE =
C9 / leave_basement_without_plank_resolution
```

## 5-track summary

| Track | Verdict |
|---|---|
| A Goal/Lead/Frontier timeline | Goal stuck at `悪霊の家` with empty requirements; KP leads/frontiers empty; action oscillation documented |
| B V13 convergence | V13 basement C10 → planks examined C14 → broken C21 → clear C25 |
| C Meaningful vs Goal-directed | GOAL_DIRECTED_RATE≈0.10 vs MEANINGFUL≈0.995; inflation=true; max GD drought=35 |
| D Frontier convergence | FAIL; critical top candidate ignored 17/17; switch rate≈0.76 |
| E Exploration / local optimum | ground_floor 37/60 cycles; local optimum=true |
| F Scenario structure | SCENARIO_FRONTIER_GAP=false (candidates exist); GOAL→LEAD→FRONTIER chain broken; ACTION→STATE_EFFECT gap on planks |

## Primary / secondary causes

**PRIMARY_ROOT_CAUSE** = Meaningful-progress inflation + goal-convergence signal gap (empty lead/frontier telemetry) allowing lateral exploration to reset stall/intervention while unresolved basement-plank lead is abandoned after C8.

**SECONDARY** = frontier prioritization gap; action→state-effect gap on repeated `basement_planks` search; stall classification gap; goal→lead / lead→frontier gaps.

**V17_FAILURE_INTERPRETATION** = `MEANINGFUL_PROGRESS_INFLATION` + `GOAL_CONVERGENCE_SIGNAL_GAP` + `FRONTIER_PRIORITIZATION_GAP` + `STALL_CLASSIFICATION_GAP` + `MULTI_COMPONENT`

**V18_FIX_SCOPE** = `MULTI_COMPONENT_FIX` (progress semantics + goal-convergence layer + frontier priority; not NDM scoring weight tweaks alone; no hidden-solution scoring)

## Responsibility separation

| Class | Proven? |
|---|---|
| NDM_DECISION_POLICY_PROBLEM | partial (selects among weak equal scores; not sole root) |
| PROGRESS_CLASSIFICATION_PROBLEM | **true** |
| FRONTIER_GENERATION_PROBLEM | false for basement/planks candidates; true for KP-facing frontier list |
| SCENARIO_ADAPTATION_PROBLEM | partial (`ACTION_TO_STATE_EFFECT` on planks search) |
| STALL_ESCALATION_PROBLEM | **true** |

## Human TRPG reading

Exploration freedom was high; many side searches are plausible. Unnatural part is **long ground-floor revisit loops** (cupboard×35, basement_door×29) after an unlocked basement with unresolved planks visible in continuity candidates — a human table would usually re-focus or get a soft KP nudge well before C60. Immediate S4 / railroad is **not** recommended.

## Audit QA

```text
FIRST_CONVERGENCE_DIVERGENCE_UNRESOLVED = 0
MEANINGFUL_PROGRESS_CLASSIFICATION_UNRESOLVED = 0
GOAL_DIRECTED_PROGRESS_CLASSIFICATION_UNRESOLVED = 0
FRONTIER_CONVERGENCE_CAUSE_UNRESOLVED = 0
SCENARIO_FRONTIER_COMPLETENESS_UNRESOLVED = 0
V13_V17_COMPARISON_UNRESOLVED = 0
HIDDEN_SOLUTION_USED_FOR_ANALYSIS = 0
CODE_CHANGED = 0
V17_RAW_CHANGED = 0
```

## Artifacts

- `docs/V17_GOAL_LEAD_FRONTIER_TIMELINE.md`
- `docs/V13_V17_CONVERGENCE_COMPARISON.md`
- `docs/V17_MEANINGFUL_VS_GOAL_DIRECTED_PROGRESS.md`
- `docs/V17_FRONTIER_CONVERGENCE_AUDIT.md`
- `docs/V17_LOCATION_AND_EXPLORATION_AUDIT.md`
- `docs/V17_PROGRESSION_ROOT_CAUSE_TREE.md`
- `docs/V17_PROGRESSION_CONVERGENCE_METRICS.json`

## Recommended next step

```text
RECOMMENDED_NEXT_STEP =
V18_PROGRESSION_CONVERGENCE_FIX_DESIGN_REQUIRED
```

Do **not** start V18 Full-Long. Design should separate Meaningful / Goal-Directed / Exploration Value, add convergence pressure without hidden-solution scoring, and repair lead/frontier signal plumbing + plank state-effect path.
