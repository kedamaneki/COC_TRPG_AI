# TRPG Natural Decision Model V1

**Status:** PASS + AMENDMENT PASS — `DESIGN_APPROVED_FOR_IMPLEMENTATION = true`  
**Version:** V1 (amended: S-level de-escalation, no hidden-solution frontier value, SAFE_LEGACY_PROGRESSION)  
**Implementation:** not started (`IMPLEMENTATION_STARTED = false`, `CODE_CHANGED = 0`)  
**QA:** see `TRPG_NATURAL_DECISION_MODEL_V1_AMENDMENT_QA.md`

## 0. Purpose

Replace the implicit equation

```text
available action → score → select → stall → S0–S4
```

with an explicit human-TRPG decision stack:

```text
World facts (Core)
  → PC-known facts
  → PL understanding / hypotheses / intent
  → PL decision (+ group deliberation)
  → KP progress assessment
  → least-intrusive intervention
  → existing Progression / S0–S4 safety layer
```

**Goal of “human-like”:** not full brain simulation, but decisions that are **explainable** from known information, recent experience, current goals, unresolved leads, risk, alternatives, personality, and consultation.

### Definition

```text
NATURAL_TRPG_DECISION =
  known facts
  + recent experience
  + current purpose
  + unresolved matters
  + risk
  + alternatives
  + PC/PL personality
  + consultation with others
→ selecting an action that can be justified from those inputs
```

## 1. Absolute principles

| Layer | Authority |
|---|---|
| Core / Raw / Scenario | Decides world truth |
| PL Reasoning | Thinks only from known information |
| KP Reasoning | Compares scenario truth vs party understanding |
| LLM | Thinking aid, phrasing, candidate structuring |
| Progression | Stall safety net — not primary “correct next action” picker |

Reasoning **never** mutates world state. It only proposes actions. **Action Executor** determines legality and applies effects.

## 2. Hard prohibitions

- PL learns unobserved information
- PL reads scenario internal state / correct-route IDs
- KP fabricates outcomes or alters dice
- KP guarantees success
- PL reasoning alone mutates state
- KP hint alone mutates state

## 3. Architecture overview

```text
┌─────────────────────────────────────────────┐
│ Observable Runtime (session, location, etc.) │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│ Knowledge Boundary Filter                   │
│  (PL-visible facts only / KP-grounded facts)│
└──────────────────────┬──────────────────────┘
                       ▼
┌──────────────┐   ┌──────────────────────────┐
│ PLReasoning  │←→│ GroupDeliberation         │
│  (per PL)    │   │  proposals / dissent     │
└──────┬───────┘   └────────────┬─────────────┘
       │                        │
       ▼                        ▼
┌─────────────────────────────────────────────┐
│ Candidate Enrichment                        │
│  action + reason + purpose + support + …    │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│ Existing Progression / Availability / Exec  │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│ KPProgressAssessment → KPInterventionPolicy │
│  S0–S4 (redesigned semantics)               │
└─────────────────────────────────────────────┘
```

### Recommended modules (design names only)

- `PLReasoningState`
- `PLDecisionPolicy`
- `HypothesisTracker`
- `LeadTracker`
- `GroupDeliberation`
- `KPProgressAssessment`
- `KPInterventionPolicy`
- `FrontierRecoveryPolicy`
- `ReasoningEvidence`

## 4. Why-now requirement

Every selectable candidate MUST carry:

| Field | Meaning |
|---|---|
| `action` | Proposed legal action skeleton |
| `reason` | Why this PL would do it **now** |
| `expected_purpose` | What they hope to learn/achieve |
| `supporting_knowledge` | `known_fact_ids` / hypothesis ids |
| `uncertainty` | Confidence / unknowns |
| `alternative_considered` | At least one rejected option + why |

Missing `reason` → candidate is **not** eligible for PL selection (`UNEXPLAINED_ACTION` path closed at design QA).

## 5. Document map

| Doc | Content |
|---|---|
| `PL_REASONING_MODEL_V1.md` | PL state, facts, goals/leads, hypotheses, failure, stay/leave, personality |
| `KP_INTERVENTION_MODEL_V1.md` | KP state, meaningful progress, S0–S4, frontier-set recovery, anti-railroad |
| `GROUP_DECISION_MODEL_V1.md` | Multi-PL proposals, dissent, consensus, roles |
| `TRPG_REASONING_KNOWLEDGE_BOUNDARY.md` | Leak / ungrounded-hint guards |
| `TRPG_REASONING_PROGRESSION_INTEGRATION.md` | How this sits atop existing Progression |
| `TRPG_NATURAL_DECISION_TEST_PLAN.md` | R1–R10, G1–G4, K1–K5 fixtures |
| `TRPG_NATURAL_DECISION_EVALUATION_PLAN.md` | 3-layer eval + human-likeness metrics |
| `V14_NATURAL_REASONING_COUNTERFACTUAL_ANALYSIS.md` | Simulated C31–C42 analysis (not Raw fact) |
| `TRPG_NATURAL_DECISION_MODEL_V1_AMENDMENT_QA.md` | Human Review amendment QA + approval gates |

## 6. Design QA checklist

| Gate | Target |
|---|---|
| `PL_HIDDEN_KNOWLEDGE_PATH` | 0 |
| `KP_UNGROUNDED_HINT_PATH` | 0 |
| `DIRECT_SOLUTION_S4_PATH` | 0 |
| `UNEXPLAINED_ACTION_PATH` | 0 |
| `PL_KP_ROLE_CONFUSION` | 0 |
| `WORLD_TRUTH_MUTATION_BY_REASONING` | 0 |
| `PROGRESSION_BYPASS` | 0 |
| `S_LEVEL_DEESCALATION_UNDEFINED` | 0 |
| `POST_S4_PRESSURE_PERSISTENCE_PATH` | 0 |
| `HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK` | 0 |
| `HIDDEN_CORRECT_PATH_SIGNAL` | 0 |
| `UNSAFE_LEGACY_FALLBACK_PATH` | 0 |
| `FALLBACK_GUARD_UNDEFINED` | 0 |

## 7. Historical compatibility

- V8–V14 Raw / Accepted / negative references: **immutable**
- Model applies only to **future runs** after implementation approval
- Fallback if reasoning fails: `SAFE_LEGACY_PROGRESSION` + `REASONING_MODEL_FALLBACK` evidence (guards retained)

## 8. Rollout

```text
Human Review + Amendment PASS
  → DESIGN_APPROVED_FOR_IMPLEMENTATION = true
  → (next task, not this phase) Implementation
  → Fixtures
  → Short controlled validation
  → Fresh Full-Long (new session ID; never V14 resume)
```

## 9. Success criteria

```text
TRPG_NATURAL_DECISION_MODEL_V1 = PASS
TRPG_NATURAL_DECISION_MODEL_V1_AMENDMENT = PASS
DESIGN_APPROVED_FOR_IMPLEMENTATION = true
IMPLEMENTATION_STARTED = false
CODE_CHANGED = 0
```