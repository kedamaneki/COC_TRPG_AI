# TRPG Reasoning ↔ Progression Integration V1

**Parent:** `TRPG_NATURAL_DECISION_MODEL_V1`  
**Status:** COMPLETE (design)  
**Constraint:** Existing Progression is **not** deleted.

## 1. Target pipeline

```text
Reasoning Layer (PL / Group / KP assessment prep)
        ↓
Candidate Filter / Enrichment
  (add why-now, failure class, lead links, reject unexplained)
        ↓
Existing Progression / Availability / Continuity
  (legalize, score safety, stall signals)
        ↓
Action Executor
        ↓
KP Intervention Policy (S0–S4 redesigned)
        ↓
Safety Recovery (FrontierRecoveryPolicy) when needed
```

## 2. Role shift for Progression

| Era | Progression role |
|---|---|
| Current (pre-model) | Often primary “next action” driver via scores / S-force |
| With Natural Decision V1 | **Supervisor**: detect unhealthy stall; preserve legal frontiers; failsafe recovery |

Progression must **not** be the only source of “why.”

## 3. Enrichment contract

Incoming legal candidates from availability are enriched:

```text
legal_candidate
  + reason
  + expected_purpose
  + supporting_knowledge
  + uncertainty
  + alternative_considered
  + meaning_class
  + multi_axis_values
```

Candidates lacking `reason` are dropped from PL selection (`UNEXPLAINED_ACTION_PATH` closed).

## 4. Stall signals shared with KP

Progression continues to emit mechanical signals (no-progress streak, attempt exhausted, location loops).  
KP maps them through “exploring vs stuck”:

- new methods / information_progress → dampen escalation  
- pure repetition → escalate S1→S2→S3→S4

## 5. S4 integration

`FrontierRecoveryPolicy` consumes:

- Progression exhausted/reachable frontier data  
- KP `unresolved_leads` / high-value frontier set  
- PL retained leads (`deferred` high-value)

Outputs **recovery bindings** (typically location return / reopen choice set), not solution actions.

Anti-railroad: no direct victory / kill / plank-solve force as default S4.

## 6. Fallback — `SAFE_LEGACY_PROGRESSION` (REQUIRED_AMENDMENT_3)

If reasoning module errors / fails closed:

```text
REASONING_MODEL_FALLBACK
  → SAFE_LEGACY_PROGRESSION
  → record fallback evidence
```

**Not** an unrestricted “old Progression does whatever it wants.”

### Guards that MUST remain active in SAFE_LEGACY_PROGRESSION

- hidden knowledge prohibition  
- attempt exhausted filtering  
- location legality  
- `required_location` enforcement  
- recent repetition penalty  
- unresolved lead preservation  
- implicit forced-solution prohibition  
- invalid action exclusion  
- already-resolved objective suppression  

### Explicitly forbidden under fallback

- direct force of the correct/solution action  
- hidden objective references  
- re-selecting attempt-exhausted actions  
- illegal location actions  
- unconditional S4  
- automatic victory-critical action execution  

### Fallback evidence

```json
{
  "event": "REASONING_MODEL_FALLBACK",
  "failure_reason": "…",
  "fallback_mode": "SAFE_LEGACY_PROGRESSION",
  "guards_active": [
    "hidden_knowledge_prohibition",
    "attempt_exhausted_filtering",
    "location_legality",
    "required_location",
    "recent_repetition_penalty",
    "unresolved_lead_preservation",
    "no_forced_solution",
    "invalid_action_exclusion",
    "resolved_objective_suppression"
  ],
  "candidate_count_before": 12,
  "candidate_count_after": 5,
  "selected_action": {"action": "move", "target": "corbitt_ground_floor"},
  "fallback_streak": 1
}
```

### `fallback_streak`

Consecutive reasoning failures increment `fallback_streak`. Design must **not** allow infinite silent fallback: after a configured threshold, fail-closed or emit an explicit warning / hard stop for operator review.

Design QA:

- `UNSAFE_LEGACY_FALLBACK_PATH = 0`
- `FALLBACK_GUARD_UNDEFINED = 0`

## 7. Compatibility

- Historical runs V8–V14 unchanged  
- Feature flag / session generation gate for future runs only  
- Night Guard / Formal gates remain authoritative for Raw integrity  

## 8. Non-goals for V1 integration

- Rewriting CombatResolutionGuard / kill routes as “reasoning”  
- Replacing Action Availability  
- Auto-committing design into V15 without Human Review
