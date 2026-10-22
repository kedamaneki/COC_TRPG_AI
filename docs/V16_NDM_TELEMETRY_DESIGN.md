# V16 Natural Decision Telemetry Design

**Parent:** `V16_PREIMPLEMENTATION_FIX_DESIGN_V1`  
**Closes:** V15 null Full-Long NDM metrics (`TELEMETRY_INCOMPLETE`)  
**CODE_CHANGED:** 0 (design only)

---

## 1. Problem restatement

V15 `V15_NATURAL_DECISION_METRICS.json` had:

| Metric | V15 |
|---|---|
| UNEXPLAINED_ACTION_RATE | null |
| UNRESOLVED_LEAD_ABANDON_RATE | null |
| SELF_RECOVERY_RATE | null |
| MEANINGFUL_PROGRESS_RATE | null |

Cause: NDM evidence not emitted to Raw; production pipeline unwired; aggregator fail-closed.

V16 Full-Long **must** make these four rates **non-null** (computable from Raw).

---

## 2. Emit contract (Raw)

### 2.1 Channel

Prefer **unified event log** entries (append-only) so Night Guard / Formal Auditor share one Raw root.

Optional companion: `ndm_evidence.jsonl` under session Raw, listed in freeze manifest — must not replace UEL for the four rates.

### 2.2 Event types (design)

| event_type | When | Required fields |
|---|---|---|
| `PL_REASONING_COMPLETED` | Each successful PL reasoning cycle | `reasoning_id`, `actor_id`, `decision_source=natural_decision_v1`, `selection_reason`, `selected_action`, `selected_target`, `lead_ids`, `hypothesis_ids`, `considered_actions_count`, `unexplained=false` |
| `ACTION_COMMITTED` (or executor UEL row) | Action applied to world | Same `reasoning_id`, `decision_source`, `selected_action`, `selected_target` — **causal bind** to reasoning event |
| `PL_REASONING_UNEXPLAINED` | Selection without reason (should be rare; usually blocked) | `reasoning_id`, `actor_id`, `unexplained=true` |
| `PL_REASONING_FALLBACK` | SAFE_LEGACY_PROGRESSION step | `reasoning_id?`, `fallback_mode=SAFE_LEGACY_PROGRESSION` |
| `LEAD_STATUS_CHANGED` | Lead lifecycle transition | `lead_id`, `from_status`, `to_status`, `leave_reason?` |
| `KP_PROGRESS_ASSESSMENT` | Each KP assessment | `assessment_id`, `meaningful_progress`, `progress_kinds[]`, `merely_repeating`, `s_level_before`, `s_level_after`, `s_level_authority` |
| `NDM_INTERVENTION_DECISION` | S-level decision | `s_level`, `reason`, `recovery_grace_remaining`, `s_level_authority=natural_decision_v1` |
| `NDM_RUNTIME_HEARTBEAT` | At least once per cycle | `NATURAL_DECISION_RUNTIME_ACTIVE`, `legacy_stall_detector_primary`, `pl_reasoning_event_count_cum`, `kp_assessment_event_count_cum` |

### 2.3 Authority fields on every NDM intervention / heartbeat

```text
s_level_authority = "natural_decision_v1"
legacy_stall_detector_primary = false
NATURAL_DECISION_RUNTIME_ACTIVE = true
```

---

## 3. Metric definitions (Full-Long aggregator)

Aggregator inputs: Raw only. No V15 backfill.

| Metric | Definition (V16) |
|---|---|
| `UNEXPLAINED_ACTION_RATE` | `# PL_REASONING_UNEXPLAINED / # (PL_REASONING_COMPLETED + UNEXPLAINED)` — missing reason after executor-bound selection also counts unexplained if emit path marks it |
| `UNRESOLVED_LEAD_ABANDON_RATE` | `# LEAD_STATUS_CHANGED to abandoned-without-reason / # unresolved-lead departures` — “abandon” = leave high-value unresolved lead without `leave_reason` / INVALIDATED without justification |
| `SELF_RECOVERY_RATE` | `# cycles where meaningful_progress true AND s_level decreases or stays ≤ prior without SYSTEM_FORCED / # stall-risk cycles` — align with eval plan “recovery before S4”; emit `self_recovery=true` on KP assessment when applicable |
| `MEANINGFUL_PROGRESS_RATE` | `# KP_PROGRESS_ASSESSMENT with meaningful_progress / # KP_PROGRESS_ASSESSMENT` using `MEANINGFUL_PROGRESS_KINDS` |

Hard gates remain separate: `KNOWLEDGE_LEAK=0`, `DIRECT_SOLUTION_S4=0`, etc.

### 3.1 Null policy

```text
IF NATURAL_DECISION_RUNTIME_ACTIVE != true OR pl_reasoning_events == 0
  → metrics may be null AND run FAIL precheck / quality gate
ELSE
  → four rates MUST be numeric (may be 0.0)
```

Null after active NDM run = **TELEMETRY_CONTRACT_FAIL** (blocking).

---

## 4. Control artifact

Post-run (and smoke):

`evaluation-control/<session>/V16_NATURAL_DECISION_METRICS.json` (or version-agnostic `NATURAL_DECISION_METRICS.json` with `schema_version`)

Must include the four rates as numbers when runtime active, plus:

```json
{
  "NATURAL_DECISION_RUNTIME_ACTIVE": true,
  "PL_REASONING_EVENT_COUNT": 12,
  "KP_PROGRESS_ASSESSMENT_COUNT": 12,
  "S_LEVEL_AUTHORITY": "natural_decision_v1",
  "LEGACY_STALL_DETECTOR_PRIMARY": false
}
```

---

## 5. Compatibility

- Additive events only; historical Raw unchanged  
- Formal Auditor may ignore unknown types until schema bump  
- V15 negative reference metrics stay null — do not rewrite  

---

## 6. Acceptance for this WP (design-level)

| Gate | Requirement |
|---|---|
| Four rates defined | Yes |
| Raw emit types listed | Yes |
| Null-after-active = fail | Yes |
| Runtime evidence fields | Yes |
