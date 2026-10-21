# TRPG Reasoning Knowledge Boundary V1

**Parent:** `TRPG_NATURAL_DECISION_MODEL_V1`  
**Status:** COMPLETE (design)

## 1. Separation of truths

| Store | Contents | Writable by reasoning? |
|---|---|---|
| World / Core truth | Scenario state, hidden flags, solutions | **No** |
| PL belief | Known facts, hypotheses, speculation | Yes (belief only) |
| KP assessment | Party understanding vs truth | Assessment only |
| Raw / Evidence | Immutable run logs | Append structured reasoning evidence only (future impl); never rewrite historical Raw |

```text
PL belief ≠ world truth
```

Always stored separately.

## 2. What PL may receive (LLM / policy inputs)

Allowed:

- observable session state (location, visible objects as rules define)
- PL `known_facts`
- structured reasoning summaries
- legal available actions (from Action Availability)
- PC personality / PL style profiles
- other PLs’ **spoken** proposals

Forbidden:

- hidden scenario solutions / route IDs
- future state
- unobserved NPC private motives
- private world truth not yet observed by that PL
- correct-answer keys for S4
- hidden-solution frontier scores (`is_correct_path`, `distance_to_solution`, `required_for_ending`, `secret_priority`, `author_priority`)

## 3. PL hallucination / leak guard

If PL reasoning references a fact_id / entity not in that PL’s known set:

```text
REASONING_KNOWLEDGE_LEAK → FAIL (candidate rejected)
```

Design QA: `PL_HIDDEN_KNOWLEDGE_PATH = 0`

## 4. What KP may use for hints

A KP hint must ground in at least one of:

1. source / scenario-authorized public fact  
2. known party observation (already in Raw / known_facts of someone)  
3. validated scenario fact already revealed  

Otherwise:

```text
UNGROUNDED_KP_HINT → FAIL
```

Design QA: `KP_UNGROUNDED_HINT_PATH = 0`

## 4.1 High-value frontier knowledge gate

Frontier promotion into `UNRESOLVED_HIGH_VALUE_FRONTIER_SET` must not use hidden-solution scoring.

```text
HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK = 0
HIDDEN_CORRECT_PATH_SIGNAL = 0
```

Value reasons must cite party-visible / known leads and goals. See `KP_INTERVENTION_MODEL_V1.md` §7.1.

## 5. Mutation boundary

| Actor | May propose action? | May mutate state? |
|---|---|---|
| PL Reasoning | Yes | No |
| Group Deliberation | Yes | No |
| KP Intervention | Yes (recovery binding / self-review prompts) | No direct world mutation |
| Action Executor | N/A | **Yes** (only legal effects) |
| Progression safety | May force/bind candidates per policy | Only via Executor |

Design QA:

- `WORLD_TRUTH_MUTATION_BY_REASONING = 0`
- `PROGRESSION_BYPASS = 0` (Executor still validates)

## 6. Thought log policy

Do **not** persist full chain-of-thought. Persist structured summaries only (intent, supports, alternatives, selected, reason, confidence).

## 7. Determinism stance

Same state need not yield identical prose.  
Same state **should** yield a stable **acceptable action set** under the policy (allow-list stability), with personality weighting inside that set.
