# V18 Progression Convergence Test Plan

**DETERMINISTIC_FIXTURES = DEFINED**  
**PRODUCTION_SMOKE_DESIGN = COMPLETE** (this + Precheck Gates)

## Progress semantics

### PS1
`NEW_LOCATION` with no active lead/blocker link  
→ Meaningful=yes, Goal-directed=no

### PS2
Known blocker removed (visible lead/blocker)  
→ Meaningful=yes, Goal-directed=yes

### PS3
Lateral meaningful progress  
→ ACTIVITY_STALL reset  
→ GOAL_CONVERGENCE_STALL continues/increments

## Goal convergence

### GC1
No goal-directed progress for N cycles  
→ self-review signal / G1-class input raised (no forced action)

### GC2
Goal-directed progress occurs  
→ goal convergence stall reset

## Frontier persistence

### FP1
Important frontier temporary leave  
→ status=DEFERRED + reason_to_leave + return_condition retained

### FP2
leave_reason / return_condition resolved  
→ frontier re-enters evaluation (not mandatory select)

## Frontier ignore

### FI1
Critical/important frontier ignored consecutively without valid why_not_selected  
→ FRONTIER_IGNORE_STREAK↑ → reminder path

## Frontier → action

### FA1
Frontier exists, action candidates=0  
→ explicit blocked reason enum (not silent drop)

## State effect

### SE1
expected effect achieved  
→ observed classification EXPECTED_EFFECT_ACHIEVED + progress linkage

### SE2
repeated NO_EFFECT same method  
→ method reconsideration / ACTION_EXHAUSTED-style reason

## Local optimum

### LO1
meaningful high + goal-directed low + revisit high (+ optional high switch rate)  
→ PROGRESSION_LOCAL_OPTIMUM detected  
→ soft self-review path, not immediate S4

## V17 counterfactual vignette

### RR1 — C8/C9 basement leave
Setup (generic IDs in fixture; Corbitt names only as scenario data):

1. Arrive location with important unresolved frontier F* (executable).
2. Leave location next cycle without resolving F*.

Expect:

```text
leave allowed
F* status = DEFERRED
reason_to_leave stored
return_condition stored
GOAL_CONVERGENCE_STALL continues
later return pressure may rise
no mandatory re-select of F*
no hidden-solution scoring
```

**V13 path copy forbidden** — fixture does not assert V13 cycle numbers as success criteria.

## Production smoke (pre-formal)

Session example (not formal V18 Full-Long ID):

```text
CORBITT_PROGRESSION_CONVERGENCE_SMOKE_V18PRE_001
```

Must demonstrate:

- Meaningful vs Goal-directed separately measurable
- Lateral progress does not clear goal stall
- Important frontier DEFERRED retention
- why_not_selected / ignore streak recorded
- action→state effect trace present
- local optimum detector can fire in synthetic stress

## Fixture hygiene

- Deterministic seeds
- No network / paid API
- No Raw historical rewrite
- No Corbitt-only force branches in production code under test
