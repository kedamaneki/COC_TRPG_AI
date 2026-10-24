# V18 Frontier Persistence Model

**FRONTIER_PERSISTENCE_MODEL = COMPLETE**  
**CRITICAL_FRONTIER_IGNORE_POLICY = DEFINED**

## V17 problem

```text
FRONTIER_SWITCH_RATE = 0.7627
FRONTIER_PERSISTENCE = 1.3043
critical top ignored = 17 / 17
```

Important unresolved frontiers evaporated from decision focus without DEFERRED memory or why_not_selected.

## Persistence state (per frontier)

```text
persistence_score
attempt_count
last_attempt_result
unresolved_importance
reason_to_leave
reason_to_return
return_condition
status                 # ACTIVE | DEFERRED | EXHAUSTED | INVALIDATED | RESOLVED
```

## Important unresolved frontier

Retain in memory when **all** hold:

- known unresolved
- goal relevant (visible goal/lead link)
- still executable **or** can become executable
- not exhausted

Do **not** silently remove from candidate consideration set.

## Temporary leave (allowed)

Leaving is legal human play. On leave:

```text
status = DEFERRED
reason_to_leave = <observed>
return_condition = <predicate on state / tools / info / risk>
```

## Return pressure (soft)

Re-evaluate deferred frontiers when any of:

- `reason_to_leave` resolved
- competing frontier value falls
- `GOAL_CONVERGENCE_STALL` rises
- `return_condition` satisfied

Pressure increases ranking / KP reminder — **never** forces selection.

## Persistence ≠ railroading

Forbidden:

```text
MANDATORY_TOP_FRONTIER_SELECTION
same frontier always chosen
ban other exploration
fix correct frontier
```

## Critical Frontier Ignore Guard

### why_not_selected

If a high-value / important unresolved frontier is not selected, record `why_not_selected` from an allowed set, e.g.:

```text
risk_too_high
tool_missing
location_unavailable
other_explicit_goal_prioritized
party_disagreement
resource_recovery
new_evidence
method_exhausted
```

### FRONTIER_IGNORE_STREAK

Increment when important frontier is ignored **without** a valid why_not_selected (or with empty reason).

### Escalation

```text
PL self-review
 → unresolved frontier reminder (known set only)
```

No correct-action injection.

### Metric

```text
CRITICAL_FRONTIER_IGNORE_RATE
CRITICAL_FRONTIER_SILENT_DROP = 0  (gate)
```

## V17 C8/C9 vignette expectation (design)

Leave basement at C9: **allowed**.  
Plank-related frontier: **DEFERRED** with reason_to_leave + return_condition.  
Goal convergence stall: **continues**.  
Later: return pressure may rise — still without mandatory select.
