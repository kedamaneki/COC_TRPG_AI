# PL Reasoning Model V1

**Parent:** `TRPG_NATURAL_DECISION_MODEL_V1`  
**Scope:** Per-PL cognitive state and decision policy (design only)

## 1. PL vs PC

| Entity | Role |
|---|---|
| **PC** | In-world character (fear, curiosity, self-preservation) |
| **PL** | Out-of-character decision maker (puzzle solving, table strategy) |

Conflict is allowed and recorded, e.g.:

- PL intent: investigate basement (high-value lead)
- PC preference: avoid entering (low `risk_tolerance`)

Resolution policy (design): PL may override PC preference with an explicit `character_tension` note; Action Executor still enforces world legality. Personality **weights** choices; it never hard-bans categories.

## 2. `PL_REASONING_STATE`

Minimum fields (per `actor_id` / PL):

| Field | Type (conceptual) | Notes |
|---|---|---|
| `known_facts` | Fact[] | Observed / learned only |
| `unresolved_questions` | Question[] | Explicit open mysteries |
| `current_goals` | Goal[] | What to achieve |
| `current_intent` | Intent | Near-term focus |
| `recent_attempts` | Attempt[] | What was tried |
| `recent_outcomes` | Outcome[] | What happened |
| `failed_attempts` | FailedAttempt[] | Classified failures |
| `hypotheses` | Hypothesis[] | Non-facts |
| `high_value_leads` | Lead[] | Promising clues toward goals |
| `low_value_leads` | Lead[] | Weak / exhausted clues |
| `reasons_to_stay` | Reason[] | Why remain here |
| `reasons_to_leave` | Reason[] | Why leave |
| `risk_assessment` | RiskSummary | Local / route / combat / SAN |
| `resource_concerns` | ResourceNote[] | HP, SAN, ammo, time, tools |
| `other_pcs_suggestions` | ForeignProposal[] | Heard proposals |
| `confidence` | 0..1 | Decision confidence |

Structured reasoning **summaries** are stored; full LLM chain-of-thought is **not**.

## 3. Known Facts

Each fact:

| Field | Meaning |
|---|---|
| `fact_id` | Stable id |
| `source_event_id` | Observing event |
| `observed_by` | Actor who learned it |
| `learned_at` | Cycle/turn/offset |
| `confidence` | Epistemic certainty |
| `freshness` | Recency / salience weight |
| `source_type` | observation / testimony / document / deduction_from_known |

**Rule:** PL DecisionPolicy may only cite `known_facts` (+ marked hypotheses). Citing unknown world truth → `REASONING_KNOWLEDGE_LEAK` (fail-closed).

### Memory salience (not deletion)

Tags for retrieval priority: `recent`, `important`, `emotionally_salient`, `goal_related`, `repeated`, `forgotten`.

- “Forgotten” lowers **reference priority** in reasoning prompts
- Core knowledge store / Raw are **never** deleted

## 4. Unresolved Questions

Examples:

- What is beyond the basement planks?
- Can the planks be broken another way?
- What is the dagger for?
- Is this NPC trustworthy?

Each question links optionally to `lead_ids` / `hypothesis_ids`.

## 5. Goals vs Leads

| Concept | Definition | Example |
|---|---|---|
| **Goal** | Desired achievement | Identify cause of Corbitt house anomaly |
| **Lead** | Possible path toward a goal | basement, planks, chapel, documents |

Leads have status: `open` | `high_value` | `low_value` | `exhausted` | `deferred`.

Leaving a location with open `high_value` leads requires a recorded `leave_reason` (does **not** forbid leaving).

## 6. Hypotheses

Kinds (must not be mixed):

| Kind | Meaning |
|---|---|
| `FACT` | Known observation |
| `HYPOTHESIS` | Tentative explanation |
| `SPECULATION` | Weak / playful guess |

Updates after outcomes: `support` | `contradict` | `unchanged` | `unknown`.

## 7. Failure interpretation

Never collapse all failure to “impossible.”

| Class | Meaning |
|---|---|
| `METHOD_FAILED` | This method seems wrong |
| `ATTEMPT_FAILED` | This try failed; method may still work |
| `INSUFFICIENT_SKILL` | Skill/check may be too low |
| `INSUFFICIENT_TOOL` | Need tool/aid |
| `INSUFFICIENT_INFORMATION` | Need more info first |
| `BAD_LUCK` | Dice / chance |
| `TARGET_IMPOSSIBLE` | Evidence suggests impossible |
| `UNKNOWN_REASON` | Cannot classify yet |

### Retry / alternate evaluation

Before abandoning:

- prior failure class
- another PC?
- another skill?
- another tool?
- Push available?
- risk increase?
- new information since last try?

## 8. Stay / Leave

Before location transition, compare `reasons_to_stay` vs `reasons_to_leave`.

- Unfinished high-value lead ⇒ require explicit `leave_reason`
- Leaving is **allowed** (humans leave)
- Abandon without reason increments `UNRESOLVED_LEAD_ABANDON` metric risk

## 9. Action meaning classes

`INVESTIGATE` · `TEST_HYPOTHESIS` · `PROGRESS_GOAL` · `RECOVER_RESOURCE` · `AVOID_RISK` · `HELP_OTHER_PC` · `REVISIT_WITH_NEW_INFO` · `SOCIAL` · `ROLEPLAY` · `TRANSITION` · `LOW_VALUE_REPEAT`

## 10. Multi-axis value (not a single score)

Axes (weights applied by policy + personality):

| Axis | Intent |
|---|---|---|
| `goal_relevance` | Advances current goals |
| `information_gain` | New info / falsifies hypothesis |
| `continuity` | Follows active lead |
| `novelty` | Avoids empty repetition |
| `risk` | Danger cost |
| `cost` | Time / resources |
| `reversibility` | Can undo / leave |
| `social_value` | Party / NPC relations |
| `character_fit` | PC personality fit |
| `recent_failure_penalty` | Same failed method |
| `repeat_penalty` | Same exhausted target |

### INFORMATION_PROGRESS

Progress includes non-state advances: new fact, hypothesis resolution, risk discovery — not only Progression “state delta.”

## 11. Personality models

### PC profile (in-world)

`risk_tolerance`, `curiosity`, `caution`, `sociality`, `persistence`, `skepticism`, `impulsiveness`, `self_preservation`  
(numeric or qualitative profile — weights only, not hard locks)

### PL style (table)

`EXPLORER` · `PROBLEM_SOLVER` · `ROLEPLAYER` · `CAUTIOUS` · `AGGRESSIVE` · `COMPLETIONIST` · `IMPROVISER`  
(composable)

## 12. Metacognition (feeds S1)

Self-check prompts:

- Am I repeating?
- Did I overlook an unresolved lead?
- What failed last time and why might it have?

## 13. Decision evidence schema

Per selected action:

```json
{
  "reasoning_id": "plr_…",
  "actor_id": "pc_01",
  "known_fact_ids": ["fact_31", "fact_42"],
  "goal_ids": ["goal_anomaly"],
  "lead_ids": ["lead_basement_planks"],
  "considered_actions": [
    {"action": "break", "target": "wall_planks", "rejected_because": "just_failed"},
    {"action": "push", "target": "wall_planks", "rejected_because": null}
  ],
  "selected_action": {"action": "leave_temporarily", "target": "corbitt_ground_floor"},
  "selection_reason": "seek tool / alternate method after attempt failed",
  "confidence": 0.61,
  "failure_class_if_any": "ATTEMPT_FAILED",
  "leave_reason": "seek better approach; keep lead open",
  "character_tension": null
}
```

## 14. Fixture anchors (see test plan)

- R1 failure → alternate method
- R2 failure → justified leave + lead retained
- R10 unknown fact citation → BLOCK
