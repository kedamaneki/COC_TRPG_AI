# V6 Progression Stagnation Analysis

## Status and evidence boundary

- Session: `CORBITT_LONGRUN_ITERATION3_V6_HOME_001`
- Disposition: `INCOMPLETE_MAX_CYCLES` (60 cycles / 79 turns)
- Raw policy: frozen; no resume, backfill, checkpoint regeneration, or max-cycle extension
- Final location: `chapel_of_contemplation`
- Final counters: evaluation `no_progress_count=113`; director consecutive streak `90`
- Formal acceptance and video eligibility remain false.
- Reproducible cycle detail and all 12 interventions are in the external receipt `V6_PROGRESSION_TIMELINE.json`. Its before/after SHA-256 check confirms the three principal Raw files were unchanged.

## Progress timeline conclusion

The timeline distinguishes progress as `FACT`, `ACCESS`, `GOAL`, and `COMBAT`. V6 produced fact and access progress through cycle 15. It produced no goal-completion or combat progress. The final meaningful event was the forced successful investigation of `skeletons_in_robes` during cycle 15.

- `LAST_MEANINGFUL_PROGRESS_CYCLE = 15`
- `FIRST_SUSTAINED_STAGNATION_CYCLE = 15`

Cycle 15 ended with a three-action no-progress streak (`S2`). Cycle 16 reached `S4` with six consecutive non-progress actions. From cycle 16 through cycle 60, the location remained `chapel_of_contemplation`, the action phase remained `TRANSITION`, the location objective remained `EXHAUSTED`, and the director exposed zero candidate actions. By cycles 30, 45, and 60 the consecutive streak was 39, 54, and 90 respectively.

Meaningful milestones were:

| Cycle | Progress |
|---:|---|
| 3 | FACT: `knott_memo`, `knott_letter` |
| 4 | ACCESS/FACT: neighborhood and Corbitt exterior reached; Dolly information acquired |
| 5 | FACT: `front_door`, `exterior_windows` |
| 7 | FACT/ACCESS: exterior view completed and chapel reached |
| 8 | FACT: `white_symbol`, `chapel_secret_cellar` |
| 9 | FACT: `rotting_floorboards` examined and cellar entered |
| 12 | FACT: `shelf_with_records` |
| 15 | FACT: `skeletons_in_robes`; no later progress |

## Unmet-goal dependency graph

```text
terminal: defeat corbitt_body
  requires FACT corbitt_body_encountered=true
  requires ACCESS location=corbitt_basement_room2
    requires ACCESS leave chapel basement
      reachable event: climb / rotting_floorboards
      effect: chapel_cellar_entered=false
      then exit: chapel -> the_neighborhood
    requires ACCESS reach Corbitt house and basement
    requires FACT basement_planks_broken=true
  then GOAL action break|force|attack|use|push|kick / corbitt_body
```

Classification at the frozen V6 state:

- `leave chapel basement`: **REACHABLE**, but hidden by selection/candidate generation.
- `chapel -> the_neighborhood`: **BLOCKED_BY_MISSING_ACCESS** until the climb-out event clears the scoped basement state.
- `location=corbitt_basement_room2`: **BLOCKED_BY_MISSING_ACCESS** downstream of the chapel exit and basement route gates.
- `corbitt_body_encountered=true`: **BLOCKED_BY_MISSING_ACCESS** because its producer is at the final basement location.
- final `corbitt_body` action: **BLOCKED_BY_MISSING_FACT** and **BLOCKED_BY_MISSING_ACCESS**.

The dependency graph was not intrinsically dead. Its reachable frontier was omitted, which made it appear dead to the director.

## Candidate, ranking, and selection trace

The frozen state has:

- canonical `in_basement=false`
- persistent `chapel_cellar_entered=true`
- scoped chapel `in_basement=true`
- `rotting_floorboards` already investigated

The scenario contains an explicit, currently applicable event:

`chapel_of_contemplation__rotting_floorboards__climb_out_success`

It accepts `climb/break/force/push`, requires scoped `in_basement=true`, and clears that state. `ActionAvailability` can validate this explicit event even though the object's coarse guard says `!in_basement`.

Candidate generation ran earlier and required the coarse target status to be exactly `INVESTIGATED`. The same scoped state made `rotting_floorboards` appear `UNAVAILABLE`, so the explicit event was discarded before availability checking. With no available exit and no event candidate:

- ranking received an empty list;
- selection had nothing to choose;
- `SYSTEM_GUIDED` and `SYSTEM_FORCED` could not rewrite to a progress action;
- S4 continued returning the PL's non-progress actions until max cycles.

Thus the necessary action was **not in the candidate set**. It was not merely ranked too low, and the PL did not ignore an available climb-out recommendation.

## SYSTEM intervention audit

All 10 `SYSTEM_GUIDED` and 2 `SYSTEM_FORCED` actions were traced to their committed event and cycle.

| Cycle | Origin | Selected action | Result |
|---:|---|---|---|
| 3 | GUIDED | search `knott_memo` | progress +2 |
| 3 | GUIDED | search `knott_letter` | progress +2 |
| 5 | GUIDED | search `front_door` | progress +2 |
| 5 | GUIDED | search `exterior_windows` | progress +2 |
| 7 | FORCED | search `corbitt_house_exterior_view` | progress +2 |
| 7 | GUIDED | move `chapel_of_contemplation` | progress +1 |
| 8 | GUIDED | search `white_symbol` | progress +2 |
| 8 | GUIDED | search `chapel_secret_cellar` | progress +2 |
| 9 | GUIDED | search `rotting_floorboards` | progress +2 |
| 12 | GUIDED | search `shelf_with_records` | progress +2 |
| 14 | GUIDED | search `skeletons_in_robes` | no progress |
| 15 | FORCED | search `skeletons_in_robes` | progress +2 |

Nine of ten guided actions and both forced actions produced progress. Most guided labels describe autonomous actions that already matched the top candidate; their source action was retained rather than rewritten. The cycle-14 skeleton action was the only guided no-progress result, and the forced retry at cycle 15 succeeded. The intervention machinery worked while candidates existed. It became powerless only after candidate generation returned an empty list.

## Root cause classification

`ROOT_CAUSE = MULTIPLE_CAUSES`

Primary components:

1. `PROGRESSION_STATE_MISREAD`: coarse object availability was treated as authoritative even when an explicit event was applicable under the scoped state.
2. `GOAL_CANDIDATE_MISSING`: the climb-out event was removed before availability validation.
3. `GOAL_DEPENDENCY_DEADLOCK`: omission of the only reachable frontier made all downstream goal requirements appear blocked.
4. `STAGNATION_RECOVERY_TOO_WEAK`: S2-S4 could only select from existing candidates and did not fail closed when an exhausted transition state had none.

Secondary symptom: `GUIDANCE_INEFFECTIVE` after cycle 15 because the guidance list was empty. `GOAL_RANKING_FAILURE`, `EXHAUSTED_TARGET_RESELECTION`, and `LOCATION_LOOP` are not the initiating cause.

## Fix

The production change is limited to `ProgressionPolicy._event_state_change_candidates`:

- retain the normal `INVESTIGATED` path;
- when coarse status is unavailable, accept an explicit event only if the target has prior investigation evidence, all explicit event conditions are satisfied, and the event has a pending state/location/phase effect;
- mark it `reachable_frontier_event_override`;
- preserve the scenario event's first declared action verb for this override.

This is scenario-data-driven and contains no Corbitt-specific target or location ID. It does not weaken final availability validation.

The V6 fixture reproduces the pre-fix empty candidate list. Post-fix it selects `climb / rotting_floorboards`; executing the existing scenario event clears `chapel_cellar_entered` exactly as the ScenarioManager contract already specifies and makes the neighborhood exit available.

## Counterfactual expectation

At the frozen cycle-15/60 state, the new policy chooses the reachable climb-out frontier instead of an empty list. After its existing event effect, the next frontier is the normal move to `the_neighborhood`. This addresses the observed deadlock without increasing max cycles or altering scenario facts, prompts, characters, evidence, normalization, auditing, dice, segments, identities, runtime isolation, or Simple Move behavior.

The read-only counterfactual was repeated at cycles 15, 16, 30, 45, and 60. All five states selected the same valid explicit-event frontier.

## Regression verification

- Core: 591 passed (required baseline at least 588), 0 failed/error/skipped
- Video Agent: 208 passed, 0 failed/error/skipped
- Formal Auditor group: 24 passed, 0 failed/error/skipped
- night_guard/runtime isolation: 60 passed, 0 failed/error/skipped
- Core Formal Evidence plus progression group: 39 passed
- Video Formal Evidence, Early Gate, and Simple Move cross-audit: 25 passed
- V6 frozen Raw inventory: 862 files; aggregate SHA-256 `ea762258eaedc0da0af4c4dcd6b4c44868a701bcf13ab855e9027e2627e33d30`
