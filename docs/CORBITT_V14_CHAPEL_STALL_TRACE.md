# CORBITT V14 — Chapel Stall Trace

Session: `CORBITT_LONGRUN_ITERATION3_V14_HOME_001`  
Chapel first arrival: **Cycle 33 / Turn 83**  
Final: **Cycle 60 / Turn 143** still `chapel_of_contemplation` (also revisited after city loop)

## Causal sequence (C31 → C60)

### A. Last useful basement progress (pre-chapel)

| Cycle | Location | Origin | Action | Notes |
|---|---|---|---|---|
| 31 | `corbitt_basement` | AUTONOMOUS | `search → wall_planks` | `basement_planks_examined=true`; junk already searched |
| 32 | `corbitt_ground_floor` | AUTONOMOUS | `move → corbitt_ground_floor` | `break wall_planks` appears in stall `recent_failed_actions`; continuity still ranks break #1 |

**LAST_POSITIVE_PROGRESS (critical path):** C31 examine `wall_planks` / junk.  
**LAST_POSITIVE_PROGRESS (any flag):** C38 `chapel_investigated=true` (side content, not kill-path).

### B. Entry into chapel sink

| Cycle | Location | Origin | Action | Classification |
|---|---|---|---|---|
| 33 | `chapel_of_contemplation` | SYSTEM_GUIDED | `search → white_symbol` | GUIDED_BUT_NONPROGRESS (relative to basement plank frontier) |
| 34–35 | chapel | SYSTEM_GUIDED | `break → rotting_floorboards` | REDUNDANT / FAILED local frontier |
| 36–41 | chapel | AUTONOMOUS | mostly `wait` | LOCATION_LOOP / NONPROGRESS |
| 38 | chapel | (flag) | `chapel_investigated=true` | USEFUL for chapel side-objective only |

Route into chapel (from C33 stall `recent_locations`):  
`corbitt_basement → corbitt_ground_floor → corbitt_exterior → the_neighborhood → chapel_of_contemplation`

### C. S4 recovery that misses basement

| Cycle | Location | Origin | Action | Evidence |
|---|---|---|---|---|
| 42 | `the_neighborhood` | SYSTEM_FORCED | `move → boston_globe` | `intervention_level=S4`, reason `s3_candidate_ignored` |

At the same decision, `_director_goal_before.candidate_next_actions` included **executable** options:

- `move → boston_globe`
- `move → central_library`
- **`move → corbitt_basement`** (AVAILABLE, reachable, expected_state_effect change_location)

S4 selected city (`boston_globe`), not the open basement return.

### D. City / neighborhood thrash

| Cycles | Pattern | Classification |
|---|---|---|
| 42–55 | neighborhood / boston_globe / hall_of_records / courts loops; waits; forced hall moves | LOCATION_LOOP / FORCED_BUT_NONPROGRESS |
| 55 | `search → reference_room_clipping_files` | REDUNDANT (already investigated earlier) |

`visit_*` counters by end (from C60 director state): basement **1**, chapel **4**, neighborhood **15**, boston_globe **10**, exterior **9**.

### E. Return to chapel dead-end (C56–60)

| Cycle | Action | Issue |
|---|---|---|
| 56 | SYSTEM_GUIDED `break → rotting_floorboards` | Repeats exhausted chapel frontier |
| 57–60 | AUTONOMOUS `wait` | LOCATION_LOOP; streak grows to 5 |
| 60 candidates | `climb/break/force → rotting_floorboards` | `scenario_runtime_conflict=true`: event requires `flags.in_basement == true` while runtime_guard is `requires_flag:!in_basement`; `expected_state_effect` would set `in_basement=false` though flag already false |
| 60 attempted move | player intent `move → corbitt_exterior` | validation `move_not_executable` → settled as `wait` |

## Chapel objective / frontier status

- `location_objective_status` oscillates ACTIVE/EXHAUSTED while stuck on chapel/city
- Local targets `white_symbol` / `rotting_floorboards` become EXHAUSTED
- Guided recovery keeps re-proposing **chapel break/climb**, not **basement plank break**
- `BLOCKED_ATTEMPT_EXHAUSTED` cache size grows (~33 → 40); many entries are stale ground-floor `basement_door` exhaustions

## S-level behavior in this window

| Signal | Observation |
|---|---|
| Checkpoint `session_state.intervention_level` | almost always stored as `standard` (not a reliable S-tier readout) |
| `director_v2.stall.intervention_level` | S0–S2 observed around C30–34 |
| Explicit S4 on action | C42 (and earlier C16 city) with `SYSTEM_FORCED` |
| S4 basement recovery | **FAIL** — basement candidate present, not selected |

## Why chapel blocked basement completion

1. Failed basement `break wall_planks` did not escalate into a bound forced break in-basement.
2. Location left while continuity still prioritized basement break.
3. Chapel presented a high-scoring **local** break frontier (`rotting_floorboards`) that **consumes guided/forced attention**.
4. Later S4 recovery prefers already-visited city locations over returning to the incomplete basement plank frontier.
5. Chapel scenario event for floorboards is internally conflicted on `in_basement`, producing nonproductive candidates until Cycle 60 timeout.

## Action classification after last critical progress (C31+)

| Class | Examples |
|---|---|
| USEFUL | C31 plank examine; C38 chapel_investigated (side only) |
| REDUNDANT | repeated city searches; re-break floorboards |
| BLOCKED / ATTEMPT_EXHAUSTED | growing blocked cache; failed break wall_planks |
| LOCATION_LOOP | chapel waits; neighborhood revisits |
| GUIDED_BUT_NONPROGRESS | C33–35 chapel guided search/break vs basement need |
| FORCED_BUT_NONPROGRESS | C42 S4 → boston_globe despite basement candidate |
