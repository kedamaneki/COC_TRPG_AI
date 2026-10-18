# V12 Basement Planks Stagnation / V13 Preflight Report

## Raw custody

- Session: `CORBITT_LONGRUN_ITERATION3_V12_HOME_001`
- Frozen status: `PROGRESSION_STAGNATION_UNRESOLVED`
- Files verified before and after work: `645 / 645`
- Missing / extra / changed files: `0 / 0 / 0`
- Aggregate SHA-256: `f3cda1a73c387e497a4d35b712ef93d31cdaa447325592d48b16eadea3f2ae59`
- The Raw session, checkpoints, segments, logs, and state were not edited or regenerated.

## Historical reproduction

The frozen Cycle 45 / Turn 136 state was reproduced read-only:

- location: `corbitt_basement`
- `basement_planks_examined=true`
- `basement_planks_broken=false`
- declared frontier verbs: `break`, `force`, `push`
- `no_progress_streak=20`
- intervention: `S4`
- terminal reason: `PROGRESSION_STAGNATION_UNRESOLVED`

## Cycle 41 onward trace

1. `search basement_planks` succeeded (`STR 55`, roll `26`) and marked the planks examined.
2. `break wall_planks` by `pc_02` failed (`99` vs `40`).
3. `break wall_planks` by `pc_01` failed (`52` vs `55`).
4. S4 bound `push basement_planks`; the opposed attempt failed (`94` vs `55`, opponent `8`).
5. Recovery then selected location transitions rather than another legal plank route: basement → ground floor → upper floor → ground floor → basement.

| Route | Reachable observations | Candidate/selection | Adjudication | Result | State/progress |
|---|---:|---:|---:|---|---|
| break | 2 | 2 | 2 | 2 failures | no mutation / no progress |
| force | declared reachable | 0 | 0 | not attempted | no mutation / no progress |
| push | 1 | 1 | 1 | 1 failure | no mutation / no progress |

## First divergence and root cause

`FIRST_DIVERGENCE_BOUNDARY` is candidate regeneration immediately after the legal S4 push failure. The scenario event exposed three legal verbs, but candidate construction retained only one route. The global `s4_override_used` flag then prevented S4 from binding a different route, so selection fell back to already explored movement.

Classification: `MULTIPLE_CAUSES`

- `FRONTIER_DETECTED_BUT_NOT_CANDIDATE`
- `RECOVERY_RECOMMENDED_BUT_NOT_EXECUTED`

The rolls themselves failed legally. There was no success without state mutation, and the first S4 push was bound into the execution path.

## Changes

- Scenario event frontiers now preserve every distinct legal action route.
- Each frontier records `reachable`, `executable`, `blocked_reason`, `adjudication_route`, and `expected_state_effect`.
- Availability checks stamp executable and blocked candidates explicitly.
- S4 binds one known executable candidate into the real proposal and execution pipeline.
- S4 route history prevents repeating the same action/context and allows the next legal route after failure.
- Invoking the executor marks `adjudication_started`; it does not force success or alter dice.
- Exhausting all executable routes emits `REACHABLE_FRONTIER_EXHAUSTED` instead of claiming that an executable frontier remains.

No Scenario fact, PC/NPC data, prompt, Dice, Evidence Contract, Normalizer, Auditor, Segment, EventIdentity, Simple Move, or runtime-isolation semantics were changed.

## Deterministic fixtures

The V12 fixture covers:

- frozen historical state
- separate `break`, `force`, and `push` routes
- S4 binding and route rotation
- legal S4 failure without forced success
- all-frontier-blocked termination
- successful state mutation recognized as meaningful progress

## Regression results

- Core: `621 passed + 26 subtests passed`
- Focused progression suite: `62 passed`
- Video Agent: `214 passed`
- Formal/Auditor focused suites: `52 passed`
- night/runtime: `49 + 11 = 60 passed`
- Fail / error / skip: `0 / 0 / 0`

## Gate result

- `V12_HISTORICAL_STAGNATION_REPRODUCED=PASS`
- `REACHABLE_FRONTIER_EXECUTABILITY_FIX=PASS`
- `S4_EXECUTION_BINDING_FIX=PASS`
- `V12_RAW_IMMUTABLE=PASS`
- `V13_PREFLIGHT=PASS`

