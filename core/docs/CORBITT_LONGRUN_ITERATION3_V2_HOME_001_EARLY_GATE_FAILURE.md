# CORBITT_LONGRUN_ITERATION3_V2_HOME_001 Early Gate Result

- FULL_LONG_RAW_RUN: **STOPPED_EARLY_UNAUDITED**
- EARLY_GATE: **FAIL**
- FULL_LONG_AUTONOMOUS_REEVALUATION: **NEEDS_ITERATION**
- NEXT_FULL_LONG_ALLOWED: **false**
- VIDEO_SOURCE_ELIGIBLE: **false**
- Cycle / Turn: **5 / 8**
- resume_count: **0**
- migration: **none**

## Gate results

- ROLL_CONTRACT_INCOMPLETE: **0**
- NORMALIZATION_SOURCE_CONTRADICTION: **0**
- lifecycle_misclassification: **9 findings / 5 unique adjudications**
- traceability: **1.0**
- dropped_events: **0**
- legacy_text_parse: **0**
- segment missing / duplicate / unexpected: **0 / 0 / 0**
- segment coverage: **1.0** (39 / 39)
- event_id missing / raw offset missing: **0 / 0**
- Normalizer validation: **PASS**
- Input Identity: **PASS** (Scenario EXACT / PC DERIVED_DECLARED / NPC EXACT)
- LLM calls: **38 successful / 0 failed**
- runtime error: **0**

## Blocking finding

Five movement actions in the Unified source have no explicit event_type but carry selected_action=move and resolution_mode=NO_ROLL. The Normalizer maps them to LOCATION_CHANGE while preserving NO_ROLL. Four matching Session Log rows produce a total of nine normalized lifecycle findings. This violates the required rule that LOCATION_CHANGE and other lifecycle events must not be treated as ROLL/NO_ROLL adjudications.

The four config_fallback markers are SINGLE_PC routing metadata for Judge requests resolving to PRIMARY. All four calls succeeded on PRIMARY; actual runtime fallback count is zero.

## Stop policy

The same process stopped at the Cycle 5 gate through EARLY_GATE_ABORT.json. No code fix, resume, or replacement Run was performed. Formal Auditor PASS/FAIL was not issued because the Run is incomplete.
