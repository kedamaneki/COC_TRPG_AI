# Group Decision Model V1

**Parent:** `TRPG_NATURAL_DECISION_MODEL_V1`  
**Scope:** Multi-PL deliberation (design only)

## 1. Purpose

When multiple PLs act, decisions are not “whoever the orchestrator picks.” The table models:

```text
each PL proposal
  → share reasons
  → dissent / counterproposal
  → agree / split / defer
  → choose executor
  → Action Executor
```

Conformity-only behavior is forbidden as the sole path.

## 2. Proposal schema

```json
{
  "proposal_id": "prop_…",
  "proposer": "pc_01",
  "action": {"action": "push", "target": "wall_planks"},
  "reason": "break failed; try force method",
  "confidence": 0.55,
  "risk": "medium",
  "supporting_known_fact_ids": ["fact_31"],
  "lead_ids": ["lead_basement_planks"]
}
```

## 3. Response types

| Response | Meaning |
|---|---|
| `agree` | Support proposal |
| `disagree` | Oppose with reason |
| `counterproposal` | Offer alternate action + reason |
| `defer` | Yield decision to another PL / wait |

Blind `agree` without reason is allowed as a **weak** social move but scores low on explainability if overused (`HINT_DEPENDENCY` / social-only patterns tracked in eval).

## 4. Deliberation outcomes

| Outcome | Result |
|---|---|
| `consensus` | One action; executor may be proposer or designated |
| `split` | Party may split tasks (role division) if scenario allows concurrent intents |
| `deadlock` | Escalate to metacognition (S1) before KP content hints |
| `executor_assigned` | Who performs the action |

## 5. Role division (optional)

Examples: scout / researcher / social face / muscle.  
Recorded as `role_plan` in group evidence; does not bypass legality.

## 6. Knowledge boundary in groups

- PLs may only share facts they know
- Hearing another PL’s testimony creates a **new known fact** of type `testimony` with source = that PL’s statement event — not automatic world truth
- KP still cannot inject unobserved truths into the huddle

## 7. Group evidence

```json
{
  "deliberation_id": "del_…",
  "proposals": ["prop_a", "prop_b"],
  "responses": [
    {"from": "pc_02", "to": "prop_a", "type": "disagree", "reason": "too risky without tool"}
  ],
  "outcome": "counterproposal_selected",
  "selected_proposal_id": "prop_b",
  "executor_id": "pc_01"
}
```

## 8. Fixtures

| ID | Scenario |
|---|---|
| G1 | Divergent proposals |
| G2 | One PL blocks dangerous action |
| G3 | Consensus formation |
| G4 | Role division |
