# V18 Progression Convergence Fix Design V1

**Status:** `READY_FOR_HUMAN_REVIEW`  
**DESIGN_APPROVED_FOR_IMPLEMENTATION = false**  
**IMPLEMENTATION_STARTED = false**  
**CODE_CHANGED = 0**  
**V18_READY = false**  
**DESIGN_DOCS_COMMITTED = false**

## 0. Formal premises (from V17 audit @ `89e0d33`)

```text
PRIMARY_ROOT_CAUSE =
MEANINGFUL_PROGRESS_INFLATION + GOAL_CONVERGENCE_SIGNAL_GAP

NDM_RUNTIME = PASS
NDM_SAFETY = PASS
NDM_DECISION_POLICY_PROBLEM = partial
SCENARIO_FRONTIER_GAP = false

FIRST_CONVERGENCE_DIVERGENCE =
C9 / leave_basement_without_plank_resolution

MEANINGFUL_PROGRESS_RATE = 0.9950
GOAL_DIRECTED_PROGRESS_RATE = 0.1000
LATERAL_EXPLORATION_PROGRESS_RATE = 0.7000
MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK = 35
FRONTIER_SWITCH_RATE = 0.7627
FRONTIER_PERSISTENCE = 1.3043
LOCATION_REVISIT_RATE = 0.7619
GROUND_FLOOR_VISIT_COUNT = 37
PROGRESSION_LOCAL_OPTIMUM = true

SECONDARY =
FRONTIER_PRIORITIZATION_GAP
FRONTIER_TO_ACTION_GAP
ACTION_TO_STATE_EFFECT_GAP
STALL_CLASSIFICATION_GAP
GOAL_TO_LEAD_GAP
LEAD_TO_FRONTIER_GAP
```

V17 showed: NDM commits and safety worked; continuous “meaningful” lateral progress hid goal non-convergence after leaving an unresolved critical frontier at C9.

## 1. Design principles

```text
MEANINGFUL_PROGRESS ≠ GOAL_DIRECTED_PROGRESS
Goal convergence ≠ 正解ルート強制
Exploration freedom remains first-class
```

**In scope:** progress semantics, dual stall, goal→lead→frontier→action→state-effect contracts, frontier persistence, ignore/local-optimum signals, KP inputs, metrics/tests/precheck.

**Out of scope (this design):** NDM personality/style redesign; knowledge-boundary rewrite; hidden-solution scoring; Corbitt-specific hard force paths; mandatory top-frontier selection; V18 implementation/smoke/Full-Long.

## 2. Architecture overview

```text
Progress Semantics v2
        ↓
Dual Stall (ACTIVITY vs GOAL_CONVERGENCE)
        ↓
Goal Convergence Tracker + soft escalation inputs to KP/S-level
        ↓
Goal → Lead → Frontier → Action Candidate
        ↓
Expected State Effect → Observed State Effect
        ↓
Frontier Persistence / Ignore Guard / Local Optimum Detector
```

NDM core decision loop remains; it **consumes** richer progression signals rather than being replaced.

## 3. Document map

| Doc | Content |
|---|---|
| `V18_PROGRESS_SEMANTICS_V2.md` | Progress classes + event schema |
| `V18_STALL_CLASSIFICATION_V2.md` | Dual stall model |
| `V18_GOAL_CONVERGENCE_MODEL.md` | Tracker, escalation, KP inputs |
| `V18_GOAL_LEAD_FRONTIER_CONTRACT.md` | Chain contract + drop reasons |
| `V18_FRONTIER_PERSISTENCE_MODEL.md` | DEFERRED, return pressure, ignore guard |
| `V18_ACTION_STATE_EFFECT_CONTRACT.md` | Expected/observed effects |
| `V18_PROGRESSION_CONVERGENCE_TEST_PLAN.md` | PS/GC/FP/FI/FA/SE/LO/RR fixtures |
| `V18_PRECHECK_GATES.md` | Smoke + gates |
| `V18_PROGRESSION_CONVERGENCE_FIX_DESIGN_V1.json` | Machine-readable summary |

## 4. Runtime schema migration (design judgment)

```text
RUNTIME_SCHEMA_MIGRATION_REQUIRED = true
```

New/extended runtime fields (progress_class, dual stall counters, frontier persistence, effect traces) are additive. Historical Raw/checkpoints are **never** rewritten; old sessions remain readable via adapters/defaults.

## 5. NDM algorithm change scope

| May change | Must not change |
|---|---|
| Progress classification inputs | Personality / PL style |
| Goal-convergence / persistence / stall signals into KP | Knowledge boundary |
| Trace contracts | Group deliberation core |
| Soft scoring **auxiliary axes** (stall pressure, persistence) — not one-shot weight hacks alone | Hidden solution policy; S-level *meaning* |

```text
NDM_CORE_ALGORITHM_REDESIGN = false
```

## 6. Anti-railroading (design gates)

```text
HIDDEN_SOLUTION_USED = 0
FORCED_CORRECT_FRONTIER_PATH = 0
MANDATORY_TOP_FRONTIER_SELECTION = false
DIRECT_SOLUTION_S4_PATH = 0
CORBITT_SPECIFIC_FORCE_PATH = 0
```

Leave/defer/explore elsewhere remains legal. Convergence pressure is reminder/re-rank, never forced correct action.

## 7. Human-likeness guarantee

After convergence hardening, the party may still: pause a thread, take side paths, fail and try another method, temporarily prioritize another explicit goal. Only silent drop of known unresolved important frontiers and “meaningful resets all stall” are closed.

## 8. Design QA checklist

```text
MEANINGFUL_EQUALS_GOAL_DIRECTED_PATH = 0
LATERAL_PROGRESS_FULL_GOAL_STALL_RESET_PATH = 0
GOAL_WITHOUT_LEAD_TRACE_PATH = 0
LEAD_WITHOUT_FRONTIER_TRACE_PATH = 0
FRONTIER_WITHOUT_ACTION_REASON_PATH = 0
ACTION_WITHOUT_STATE_EFFECT_TRACE_PATH = 0
CRITICAL_FRONTIER_SILENT_DROP_PATH = 0
MANDATORY_TOP_FRONTIER_PATH = 0
HIDDEN_SOLUTION_SCORING_PATH = 0
CORBITT_SPECIFIC_FORCE_PATH = 0
IMPLEMENTATION_STARTED = false
CODE_CHANGED = 0
```

## 9. Recommended next step

```text
RECOMMENDED_NEXT_STEP = Human Review
```

After approval only: implementation → smoke `CORBITT_PROGRESSION_CONVERGENCE_SMOKE_V18PRE_001` → precheck → (later) Fresh Full-Long session ID TBD. Do **not** start those in this task.
