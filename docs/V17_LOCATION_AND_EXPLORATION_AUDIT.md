# V17 Location and Exploration Audit

## Cycle location distribution (checkpoint end-of-cycle)

From 60 checkpoints:

| location | cycle count (approx share) |
|---|---|
| corbitt_ground_floor | **37** (~61.7%) |
| corbitt_upper_floor | significant mid/late |
| corbitt_basement | sparse (visits without plank resolve) |
| corbitt_exterior / introduction | early only |

```text
GROUND_FLOOR_CYCLE_COUNT = 37
GROUND_FLOOR_RETURN_COUNT = 8
GROUND_FLOOR_CYCLE_SHARE ≈ 0.6167
UNIQUE_LOCATION_COUNT = 5
LOCATION_VISIT_TRANSITIONS = 21
LOCATION_REVISIT_RATE = 0.7619
```
（定義: `1 - UNIQUE_LOCATION_COUNT / LOCATION_VISIT_TRANSITIONS`。checkpoint連続でlocationが変わるたび1 visit。）

## Ground-floor concentration

Final location=`corbitt_ground_floor`. On GF the party repeatedly:

- `search/storage_room1_cupboard` (35 commits overall)
- `search/basement_door` (29) **after door already unlocked**
- `search/living_room_clutter` (14)
- `search/hidden_passage` (12)
- `move/corbitt_ground_floor` (37)

These yield enough `NEW_LOCATION` / object-state progress events to keep KP meaningful flags true, while basement plank resolution does not advance.

## Local optimum

```text
PROGRESSION_LOCAL_OPTIMUM = true
```

Pattern observed:

```text
small novelty / re-search progress
  → KP meaningful_progress=true (stall reset at intervention layer)
  → no S4 / no convergence nudge
  → another small GF progress
  → unresolved planks lead never forced back to center
```

Director `no_progress_streak` still climbs (to 61 by C60), proving **two progress notions disagree**:

| Layer | Signal |
|---|---|
| StallDetector streak | rises (goal-ish stagnation) |
| KP meaningful progress | almost always true |
| S-level / intervention | stays low |

```text
STALL_CLASSIFICATION_GAP = true
```

## Why S4 did not fire

Not because the run “had no problems,” but because meaningful-progress classification continuously denied “need intervention.” Premature/unnecessary S4 counters are 0 for the wrong reason: **missing escalation**, not healthy convergence.

## V13 contrast (characteristics only)

V13 also revisits GF/upper, but after basement access it **returns and finishes plank flags** by C14/C21 and clears at C25. Breadth without convergence pressure is the V17 pathology—not breadth itself.
