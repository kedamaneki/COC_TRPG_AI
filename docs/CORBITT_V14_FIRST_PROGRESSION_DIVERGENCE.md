# CORBITT V14 — First Meaningful Progression Divergence

**Baseline (success):** `CORBITT_LONGRUN_ITERATION3_V13_HOME_001`  
**Negative reference:** `CORBITT_LONGRUN_ITERATION3_V14_HOME_001`  
**Method:** checkpoint `state.json` flags/locations + `director_v2` continuity/stall + `last_pl_action` (read-only)

## Milestone order (compressed)

| Milestone | V13 | V14 |
|---|---|---|
| Corbitt exterior | C3 / T5 | C9 / T14 |
| House entered | C7 / T11 | C19 / T30 |
| Ground floor | C8 / T15 | C20 / T34 |
| Basement accessible | C9 / T19 | C26 / T53 |
| **Basement first arrival** | **C10 / T23** | **C31 / T75** |
| Upper floor | C16 / T46 | C21 / T36 (**before basement**) |
| Planks examined | C14 (flag) / basement search C13 | C31 search `wall_planks` |
| Planks broken | **C21** | **never** |
| Chapel | never | C33 / T83 → dominates to C60 |
| Boss / clear | C25 | never |

## Last equivalent state

Around **basement_accessible=true**, both runs have entered the house and unlocked the basement door.

- V13: C9 ground floor → immediately enters basement C10
- V14: C26 ground floor → still spends cycles on ground/upper exhaust, enters basement only at C31

## First milestone-order divergence

**V14 Cycle 21 / Turn 36 — `corbitt_upper_floor` while basement not yet visited.**

V13’s successful order is basement-first (C10), upper later (C16).  
V14 inverts that order. This is the first structural milestone reorder, but it is **not yet fatal** (basement is still reached later).

## First causal / failure-relevant divergence (primary)

**V14 Cycle 32 — leave `corbitt_basement` after a failed `break wall_planks`, without completing the plank frontier.**

Evidence at end of C31→C32 window:

1. C31: `search wall_planks` (AUTONOMOUS) → `basement_planks_examined=true`, `basement_planks_broken=false`
2. Mid-cycle actions recorded in C32 `director_v2.stall.recent_actions` include **`break wall_planks` in `recent_failed_actions`**
3. C32 last action: `move → corbitt_ground_floor` (AUTONOMOUS)
4. Yet C32 `candidate_continuity_scores` still ranks **`break wall_planks` #1 (score 180, local_frontier=true)** ahead of push/force/break `basement_planks`
5. C33: path `ground → exterior → neighborhood → chapel`; `SYSTEM_GUIDED search white_symbol`
6. After C33, continuity scores are **chapel-local** (`rotting_floorboards` / `white_symbol`); basement break frontier is abandoned
7. **No later `move → corbitt_basement` succeeds**; `visit_corbitt_basement` stays 1 through C60

### V13 behavior in the comparable plank window

- Multiple basement visits (C10, C13, C21–C24)
- `basement_planks_broken` becomes true by **C21** while location remains basement-family
- Remains in basement through combat/dagger guidance → room2 clear at C25

### Candidate difference (saved evidence only)

| Point | V14 candidates / continuity | Outcome |
|---|---|---|
| C30 ground EXHAUSTED | continuity #1 `move→corbitt_basement` (score 5) | Enters basement C31 |
| C32 after failed break | continuity #1 `break→wall_planks` (180) | **Ignored; left location** |
| C42 neighborhood S4 | `candidate_next_actions` includes **AVAILABLE** `move→corbitt_basement` | S4 forces `move→boston_globe` instead |

## State differences that matter

- V14 `basement_planks_broken` remains false forever
- V14 `chapel_investigated=true` (C38) while critical basement frontier incomplete
- V14 `location_objective_status=EXHAUSTED` on 20/60 checkpoints vs V13 5/25
- V14 max `maximum_no_progress` = **34** vs V13 **7**
- V14 `forced_action_count` final **22** / guided **60** vs V13 **4** / **25**

## Likely causal significance

```text
FIRST_MEANINGFUL_PROGRESSION_DIVERGENCE =
  primary_causal: V14 cycle=32 turn≈75+ (basement exit after failed break wall_planks)
  first_milestone_reorder: V14 cycle=21 (upper before basement)

Classification mix:
  - LLM_PATH_VARIANCE (left basement despite #1 continuity break)
  - PREEXISTING_PROGRESSION_INSTABILITY / CONTINUITY_SCORING_REGRESSION
    (high-ranked local frontier not retained across location change)
  - PROGRESSION_RECOVERY_FAILURE at S4 (C42 basement candidate present, city forced)
  - SCENARIO_FRONTIER_GAP (chapel rotting_floorboards sink with conflicting in_basement guard)
```

Not explained by “LLM said something different” alone: after C32 the **system recovery path** fails to re-bind the still-open basement plank frontier.
