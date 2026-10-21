# KP Intervention Model V1

**Parent:** `TRPG_NATURAL_DECISION_MODEL_V1`  
**Scope:** Keeper-side assessment and S0–S4 redesign (design only)

## 1. Role of KP Reasoning

KP compares:

- **Scenario / world truth** (authorized)
- **Party-visible understanding** (from speech, choices, shared reasoning summaries)

KP does **not** read hidden PL private thoughts unless the table explicitly shares a reasoning summary.

KP does **not** invent facts, change dice, or guarantee success.

## 2. `KP_REASONING_STATE`

| Field | Meaning |
|---|---|
| `party_understanding` | What the party appears to know / believe |
| `party_misunderstandings` | Detected wrong beliefs (grounded only) |
| `unresolved_leads` | Open high-value leads from party + scenario |
| `available_meaningful_frontiers` | Legal, progress-bearing frontiers |
| `exhausted_frontiers` | Tried / depleted |
| `current_progress_trend` | improving / flat / degrading |
| `recent_repetition` | Same target/method/location loops |
| `intervention_history` | Prior S-levels and types |
| `current_hint_level` | Active intervention tier |

## 3. Per-cycle internal questions

1. Are players making **meaningful** progress?  
2. Are they pursuing a **valid alternative**?  
3. Exploring vs merely repeating?  
4. Do they remember important unresolved leads?  
5. Rule/fact misunderstanding?  
6. Would a human KP intervene **yet**?  
7. Least intrusive useful intervention?

## 4. Meaningful progress

Counts as progress (any one):

- new fact  
- new location  
- hypothesis resolution  
- world state change  
- new viable lead  
- major risk discovery  
- resource acquisition  
- objective advancement  

**INFORMATION_PROGRESS** alone can justify non-intervention even without state mutation.

## 5. Exploring vs stalled

| Pattern | Treatment |
|---|---|
| New reasonable hypotheses / methods each turn | Soft stall; prefer S0–S1 |
| Same investigated target + same failed method + same location round-trip | Hard stall; escalate |

## 6. S0–S4 semantics (redesign)

| Level | Name | KP behavior |
|---|---|---|
| **S0** | `NONE` | Full freedom |
| **S1** | `PLAYER_SELF_REVIEW` | Force PL metacognition / self-summary of known facts, unresolved leads, recent failures. **No KP hint content** |
| **S2** | `INFORMATION_REMINDER` | Re-present **already known** observations only (e.g. “the basement planks are still unbroken”). **No new information** |
| **S3** | `SOFT_GUIDANCE` | Indirect attention return to unresolved leads. **No direct answer** |
| **S4** | `FAILSAFE_RECOVERY` | Only if still stuck: recover to `UNRESOLVED_HIGH_VALUE_FRONTIER_SET` |

### Hint types (S2–S3)

| Type | Content |
|---|---|
| `REMINDER` | Known fact restatement |
| `REFRAME` | Reorganize known facts |
| `NUDGE` | Point attention at unresolved lead |

**ANSWER** (direct solution statement) is forbidden in interventions.  
Source-authorized NPC advice remains a separate channel.

## 6.1 De-escalation / reset contract (REQUIRED_AMENDMENT_1)

Escalation alone is incomplete. **De-escalation is mandatory contract.**

### Meaningful progress → reset to S0

If any of the following occurs:

- new validated fact  
- new meaningful location  
- hypothesis resolved  
- new viable lead  
- critical state change  
- objective advancement  

then **principle**:

```text
S-level → S0
stall counter → reset or strong reduction
```

### Reasonable exploration suspends escalation

While the party is testing **new rational hypotheses / methods**:

```text
S-level increase = suspended
```

Even without world-state mutation, presence of `INFORMATION_PROGRESS` or `HYPOTHESIS_PROGRESS` must **not** immediately raise to S2/S3.

### After successful S3

If an S3 nudge is followed by a meaningful action turn:

```text
S3 → S0   (preferred)
S3 → S1   (allowed only if strong stall signs remain)
```

### After S4 recovery

Once S4 has returned the party to a free-choice point on the frontier set:

```text
S4 → S0
```

S4 pressure **must not persist**. S4 restores agency; it does not solve the problem and does not keep the table under failsafe.

### `recovery_grace_window`

After an S4 recovery to a frontier set, immediate re-escalation to S4 on the **same** frontier within a short empty loop is forbidden.

Design: prefer a **grace window** keyed to ongoing **meaningful attempts** (not a rigid fixed turn count alone). While meaningful attempts continue on the recovered frontier set, S-level increase toward S4 is suppressed. Empty repetition after grace expires may escalate again via the normal ladder.

Design QA:

- `S_LEVEL_DEESCALATION_UNDEFINED = 0`
- `POST_S4_PRESSURE_PERSISTENCE_PATH = 0`
- `POST_S4_RESET = S0`

## 7. Frontier-set recovery (S4)

S4 does **not** mean “execute the correct winning action.”

```text
UNRESOLVED_HIGH_VALUE_FRONTIER_SET
  → required location(s)
  → recovery binding (e.g. move to location / re-open choice set)
  → STOP
  → S-level → S0
```

Example binding allowed: `move → corbitt_basement`  
Example binding **forbidden** as S4 default: `push → basement_planks` (that solves the puzzle)

Principles:

- Prefer a **set** of open frontiers when multiple exist (preserve player choice — R9)
- Do not auto-complete victory / special objective / kill route
- Anti-railroad gate: `DIRECT_SOLUTION_S4_PATH = 0`

## 7.1 HIGH_VALUE_FRONTIER without hidden solution value (REQUIRED_AMENDMENT_2)

`UNRESOLVED_HIGH_VALUE_FRONTIER` value is computed **only** from information the party/KP may legally use for *guidance grounding*:

**Allowed value inputs**

- known unresolved lead  
- current goal relevance  
- source-backed observed clue  
- recent observation  
- unresolved (party-visible) state  
- new action possibility  
- information gain potential  
- risk relevance  
- party-stated interest  

**Forbidden value inputs**

- hidden scenario solution  
- future required event  
- author-intended correct route  
- unobserved objective state  
- secret success probability  
- final-answer proximity  

**Forbidden signals (never passed into Reasoning/Progression)**

`is_correct_path` · `distance_to_solution` · `required_for_ending` · `secret_priority` · `author_priority`

KP may *know* scenario truth, but must **not** recover “because it is the correct path.” Recovery grounding is:

> the party can recognize it as unresolved, it relates to current goals, and meaningful actions remain.

### Frontier evidence (minimum)

```json
{
  "frontier_id": "basement_planks",
  "known_fact_ids": ["fact_planks_examined", "fact_break_failed"],
  "goal_ids": ["goal_anomaly"],
  "lead_ids": ["lead_basement_planks"],
  "value_reasons": ["known_unresolved_lead", "goal_relevance", "available_actions_remain"],
  "visible_to_party": true,
  "unresolved": true,
  "available_action_count": 3
}
```

### Hidden Knowledge Gate

```text
HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK = 0
HIDDEN_CORRECT_PATH_SIGNAL = 0
```

If `value_reasons` are supported **only** by hidden scenario truth, the frontier **cannot** be promoted into the S4 recovery set.

## 8. Anti-railroading metrics (design)

Track:

- `forced_action_count`
- `forced_solution_count` (must stay 0 for S4 policy)
- `hint_count`
- `frontier_recovery_count`
- `player_choice_preserved`

S4 count is **not** the success metric; `UNNECESSARY_S4` / `PREMATURE_S4` are.

## 9. KP intervention evidence

```json
{
  "intervention_id": "kpi_…",
  "stall_reason": "repetitive_exhausted_target",
  "party_state_summary": "planks examined, break failed, party left for chapel",
  "intervention_level": "S3",
  "intervention_type": "NUDGE",
  "facts_referenced": ["fact_wall_planks_examined", "fact_break_failed"],
  "frontiers_considered": ["basement_planks", "chapel_floorboards"],
  "selected_frontier_set": ["basement_planks"]
}
```

Ungrounded hint (no source fact / known observation / validated scenario fact) → `UNGROUNDED_KP_HINT` fail.

## 10. Expected V14-shaped behavior (design intent, not Raw rewrite)

Given `basement_planks_examined=true`, `broken=false`, break failed:

1. S0–S1: PL considers push / other PC / tool / temporary leave with lead retained  
2. If leave without return and no new meaningful progress → S2 reminder of unbroken planks  
3. Continued empty loops → S3 nudge to unresolved basement lead  
4. Full stall → S4 recover to basement frontier **set**, not auto-break

## 11. Fixtures

See `TRPG_NATURAL_DECISION_TEST_PLAN.md` K1–K5, R5–R9.
