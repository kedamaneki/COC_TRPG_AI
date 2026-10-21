# V14 Natural Reasoning — Counterfactual Analysis (C31–C42)

**Status:** SIMULATED_REASONING only  
**Not world fact. Not Raw. Not acceptance evidence.**  
**Source observation (immutable):** `CORBITT_LONGRUN_ITERATION3_V14_HOME_001`  
**Related audit:** `CORBITT_V14_CHAPEL_STALL_TRACE.md`, `CORBITT_V14_FIRST_PROGRESSION_DIVERGENCE.md`

```text
DISCLAIMER = SIMULATED_REASONING
V14_RAW_CHANGED = 0
```

## 1. Observed anchors (factual from Raw/checkpoints)

| Cycle | Fact |
|---|---|
| 31 | `search → wall_planks`; `basement_planks_examined=true`; `broken=false` |
| ~31–32 | `break → wall_planks` appears in stall `recent_failed_actions` |
| 32 | AUTONOMOUS `move → corbitt_ground_floor` while continuity still ranked `break wall_planks` #1 |
| 33 | SYSTEM_GUIDED chapel `search → white_symbol` |
| 34–35 | SYSTEM_GUIDED `break → rotting_floorboards` |
| 42 | S4 SYSTEM_FORCED `move → boston_globe` despite AVAILABLE `move → corbitt_basement` |

## 2. Simulated PL_REASONING_STATE after C31 failure

**SIMULATED** sketch (would be structured evidence, not CoT dump):

```json
{
  "known_facts": [
    "wall_planks_examined",
    "break_wall_planks_failed_once",
    "basement_still_accessible",
    "junk_searched"
  ],
  "unresolved_questions": [
    "What is beyond the planks?",
    "Was break failure method, skill, tool, or luck?"
  ],
  "current_goals": ["investigate_corbitt_anomaly"],
  "high_value_leads": [
    {"id": "lead_basement_planks", "status": "unresolved_high_value"}
  ],
  "failed_attempts": [
    {"action": "break", "target": "wall_planks", "class": "ATTEMPT_FAILED"}
  ],
  "confidence": 0.45
}
```

Natural **considered_actions** under V1 policy:

| Candidate | Class | Why-now |
|---|---|---|
| `push` / `force` planks | TEST_HYPOTHESIS | Method may differ from break |
| other PC retry | PROGRESS_GOAL | Insufficient skill / bad luck hypothesis |
| seek tool upstairs/city | RECOVER_RESOURCE | INSUFFICIENT_TOOL hypothesis |
| temporary leave | TRANSITION | Justified leave; lead retained |
| immediate re-break same way | LOW_VALUE_REPEAT | Penalized |

**Not preferred:** silent leave with no `leave_reason` while dropping the lead.

## 3. Counterfactual branches (SIMULATED)

### Branch A — Stay and alternate method (ideal self-recovery)

```text
C31 fail break
  → PL R1: classify ATTEMPT_FAILED
  → try push/force or other PC
  → either progress OR clearer TARGET_IMPOSSIBLE / need-tool
```

KP: S0 (meaningful alternate attempts).

### Branch B — Justified temporary leave (R2)

```text
leave_reason = seek_tool_or_info
lead_basement_planks retained = unresolved_high_value
```

Elsewhere: if **new** meaningful progress → remain S0 (R4).  
If empty chapel/city loops → S1 self-review → S2 reminder “planks still unbroken” → S3 nudge → only then S4 recover to basement set (not auto-push).

### Branch C — What V14 roughly did (observed) vs V1 expected KP

| Observed | V1 expected |
|---|---|
| Left with continuity still ranking basement break #1 | Require leave_reason; keep lead hot |
| Guided into chapel break sink | Treat chapel as side lead; do not outrank open basement high-value lead without justification |
| S4 forces `boston_globe` while `corbitt_basement` AVAILABLE | S4 selects **frontier-set recovery** including basement; forbids city preference when critical lead open |

### Branch D — Amended S4 path (SIMULATED_REASONING; post-amendment)

**Observed (old):** S4 → `boston_globe`.

**Simulated under amended model:**

```text
unresolved basement lead remains visible (party-known; not hidden-solution score)
  ↓
high-value frontier set (value_reasons = known lead + goal relevance + actions remain)
  ↓
move → corbitt_basement recovery binding
  ↓
S4 ends
  ↓
S-level → S0   (POST_S4_RESET; no persistent failsafe pressure)
  ↓
recovery_grace_window while meaningful attempts continue
  ↓
PL freely chooses push / other method / other PC / tool seek
  (S4 does NOT force push basement_planks)
```

Hidden “correct ending proximity” must **not** be why basement is valued — only visible unresolved lead + goals.

## 4. Simulated KP ladder for C32–C42 empty stretch

Assuming Branch B leave without tool success and chapel repetition:

| Phase | Level | Action |
|---|---|---|
| First empty repeats | S1 | Self-review: list known facts + unresolved planks |
| Still no return | S2 | Reminder: planks examined, not broken |
| Continues | S3 | Nudge unresolved basement lead |
| Still stuck | S4 | Recover to `{basement_planks, …}` via location binding |
| After recovery | **S0** | Freedom restored; grace window active |

If S3 nudge yields a meaningful turn earlier: **S3 → S0** (or S1 if stall signs remain).

**Forbidden simulated S4:** `force push basement_planks` as direct solution.

## 5. What this analysis is not

- Not a claim that V14 “should have” cleared under same seed without new code  
- Not a Raw patch or acceptance argument  
- Not evidence WP-A/B/C caused the stall (see remediation assessment)

## 6. Design takeaway

V14’s C31–C42 window is a **canonical motivating fixture** for:

- failure classification ≠ impossible  
- leave_reason + lead retention  
- INFORMATION_PROGRESS vs empty loops  
- S4 frontier-set recovery over city forced moves when critical leads remain open  
- **S4 → S0 reset** and **no hidden-solution frontier scoring**
