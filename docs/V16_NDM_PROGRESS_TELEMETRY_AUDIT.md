# V16 Meaningful Progress / Self Recovery Telemetry Audit

## Reported zeros

| Metric | Acceptance value |
|---|---|
| MEANINGFUL_PROGRESS_RATE | 0.0 |
| SELF_RECOVERY_RATE | 0.0 |
| meaningful_progress_count (telemetry scalar) | 0 |
| self_recovery_count (telemetry scalar) | 0 |
| KP_PROGRESS_ASSESSMENT_COUNT | 3 |

## Producer path (code)

NDM increments `meaningful_progress_count` only inside `NaturalDecisionRuntime.decide` after successful `assess_party_progress`, when `assessment.meaningful_progress_this_cycle` is true.

That flag is true only if `progress_events` contains a `kind` in `MEANINGFUL_PROGRESS_KINDS`.

`enrich_pc_action_with_ndm` **never passes** `progress_events` into `rt.decide(...)` → always default `()`.

Self-recovery increments only when KP assessment sets `testing_valid_hypothesis` or `exploring_valid_alternative` (also requires hypothesis/alternative inputs that production decide path does not supply).

## Raw reality check (not zero world-progress)

UEL turn records include `progress_delta`:

| progress_delta | turns |
|---:|---:|
| 0 | 170 |
| 1 | 8 |
| 2 | 20 |

**28 turns with progress_delta > 0** exist. Final flags include 27 `true` investigation/state flags (house entered, living room, diaries, etc.).

So world progress happened; **NDM meaningful-progress metric did not observe it**.

## Zero-cause classification

### MEANINGFUL_PROGRESS_RATE = 0.0

| Class | Applies |
|---|---|
| TRUE_ZERO | **no** (world progress exists) |
| RAW_INSTRUMENTATION_GAP | **yes** — `progress_events` not wired; KP assess almost never runs after fallback storm |
| AGGREGATION_GAP | **yes** — metric only counts NDM KP assess path |
| DEFINITION_TOO_STRICT | **partial** — kinds gate is narrow vs ProgressDirector `progress_delta` |
| NDM_NOT_CONTROLLING_ACTIONS | **yes** — 194/197 commits are SAFE_LEGACY |

`MEANINGFUL_PROGRESS_RATE_ZERO_CAUSE = RAW_INSTRUMENTATION_GAP + AGGREGATION_GAP + NDM_NOT_CONTROLLING_ACTIONS`

### SELF_RECOVERY_RATE = 0.0

No Raw chain of `stall → PL self-review → pre-KP recovery` under NDM authority after the early window. KP intervention events are only 3× `NONE` at S0.

| Class | Applies |
|---|---|
| TRUE_ZERO | **yes** for NDM-defined self-recovery chain |
| RAW_INSTRUMENTATION_GAP | **yes** |
| NDM_NOT_CONTROLLING_ACTIONS | **yes** |

`SELF_RECOVERY_RATE_ZERO_CAUSE = TRUE_ZERO (NDM-defined chain absent) + RAW_INSTRUMENTATION_GAP + NDM_NOT_CONTROLLING_ACTIONS`

## Actor / category notes

NDM successes (3): pc_01/pc_02 mix on search/move.  
Fallback population: both PCs represented; action category on COMPLETED intent often `other` because action fields null.

## SAFE fallback evaluation

| | |
|---|---|
| SAFE_FALLBACK_SAFETY | PASS |
| SAFE_FALLBACK_AVAILABILITY | FAIL |
