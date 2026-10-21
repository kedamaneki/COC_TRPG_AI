# TRPG Natural Decision — Evaluation Plan V1

**Parent:** `TRPG_NATURAL_DECISION_MODEL_V1`  
**Status:** COMPLETE (design)

## 1. Three evaluation layers

| Layer | Name | Question |
|---|---|---|
| **1** | Rule correctness | Legality, dice integrity, knowledge boundary, no truth mutation |
| **2** | Progression robustness | Stall recovery, frontier retention, completion without illegal force |
| **3** | Human-likeness | Explainable, non-robotic, low premature railroad |

Layers are scored **separately**. A run can pass L1 and fail L3.

## 2. Human-likeness metrics (definitions)

| Metric | Direction | Definition (design) |
|---|---|---|
| `UNEXPLAINED_ACTION_RATE` | ↓ | Selected actions lacking structured `selection_reason` / supporting knowledge |
| `REPETITIVE_ACTION_RATE` | ↓ | Same action+target after exhaustion / without new info |
| `UNRESOLVED_LEAD_ABANDON_RATE` | ↓ | Leave high-value lead without `leave_reason` or later return plan |
| `PREMATURE_S4_RATE` | ↓ | S4 while exploring valid alternatives / information_progress present |
| `FORCED_SOLUTION_RATE` | ↓ | Forced actions that directly solve critical puzzle / victory |
| `MEANINGFUL_PROGRESS_RATE` | ↑ | Fraction of cycles with meaningful progress (incl. information_progress) |
| `SELF_RECOVERY_RATE` | ↑ | Stall exits via PL/group reasoning before S3+ |
| `HINT_DEPENDENCY_RATE` | ↓ | Progress that only occurs immediately after KP hint/force |

### Related operational counters

- `forced_action_count`, `forced_solution_count`, `hint_count`, `frontier_recovery_count`, `player_choice_preserved`
- `UNNECESSARY_S4` (subset of S4 where softer tier would suffice)
- S4 **count is not a goal to zero**; unnecessary/premature S4 is

### Amendment metrics

| Metric | Direction | Definition |
|---|---|---|
| `S_LEVEL_RESET_SUCCESS_RATE` | ↑ | Meaningful progress events that correctly reset S→S0 |
| `POST_S4_FREEDOM_RATE` | ↑ | S4 recoveries followed by S0 (no lingering failsafe pressure) |
| `HIDDEN_SOLUTION_FRONTIER_RATE` | =0 | Frontiers valued only via hidden solution signals |
| `SAFE_FALLBACK_RATE` | track | Reasoning failures that entered `SAFE_LEGACY_PROGRESSION` |
| `FALLBACK_GUARD_VIOLATION_RATE` | =0 | Fallback selections that violated retained guards |
| `REPEATED_FALLBACK_STREAK` | ↓ / capped | Consecutive fallbacks; must not grow unbounded |

## 3. Ideal tendencies

```text
UNEXPLAINED_ACTION_RATE ↓
REPETITIVE_ACTION_RATE ↓
PREMATURE_S4_RATE ↓
FORCED_SOLUTION_RATE ↓
HIDDEN_SOLUTION_FRONTIER_RATE = 0
FALLBACK_GUARD_VIOLATION_RATE = 0

SELF_RECOVERY_RATE ↑
MEANINGFUL_PROGRESS_RATE ↑
S_LEVEL_RESET_SUCCESS_RATE ↑
POST_S4_FREEDOM_RATE ↑
```
## 4. Replay comparison (future)

Compare (read-only):

- human table notes / transcripts (pattern extraction only — **no copy of a specific streamer’s style**)
- V13 successful Full-Long  
- V14 negative reference  
- post-model Fresh Full-Long  

### Human pattern observations to extract

- turns stayed after failure  
- when leave happens  
- when return to old lead  
- consultation frequency  
- time-to-hint  
- retry frequency  

**Copy learning prohibited** — generalize patterns only.

## 5. Pass gates for short controlled validation (future)

Suggested (tunable after Human Review):

| Gate | Draft |
|---|---|
| L1 knowledge leaks | 0 |
| L1 ungrounded KP hints | 0 |
| L1 forced solutions | 0 |
| L3 unexplained actions | below threshold |
| L3 premature S4 | below threshold |
| Fixtures R1–R10 / G / K | all PASS |

## 6. Reporting

Each validation run emits a metrics JSON + narrative summary.  
Does not rewrite Raw. Metrics are derived artifacts.
