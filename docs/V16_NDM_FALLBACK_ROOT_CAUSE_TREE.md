# V16 NDM Fallback Root Cause Tree

## Tree (evidence-backed)

```text
StallDetectorV2.update stores recent_actions as [action, target] lists
        │
        ▼
ndm_integration.enrich_pc_action_with_ndm passes stall.recent_actions unchanged
        │
        ▼
NaturalDecisionPipeline / NaturalDecisionRuntime call assess_party_progress
        │
        ▼
assess_party_progress does a.get("action") on list entries
        │
        ▼
AttributeError: 'list' object has no attribute 'get'
        │
        ├─(early, streak≤5)─► pipeline SAFE_LEGACY select also .get on lists
        │                         │
        │                         ▼
        │                   AttributeError propagates out of run_cycle
        │                         │
        │                         ▼
        │                   runtime._fallback_select (no recent_actions)
        │                         │
        │                         ▼
        │                   PL_REASONING_FALLBACK ×5 (PURE)
        │
        └─(streak>5)─► FallbackUnboundedError → mode=FAIL_CLOSED
                          selected_action=None, reasoning_evidence present
                                │
                                ▼
                   runtime.decide does not handle FAIL_CLOSED
                                │
                                ▼
                   emits PL_REASONING_COMPLETED (action/target null)
                                │
                                ▼
                   runtime assess_party_progress AttributeError again
                                │
                                ▼
                   _fallback_select → PL_REASONING_FALLBACK ×189
                                │
                                ▼
                   LEGACY_DECISION_COMMIT_COUNT / SAFE_LEGACY_PROGRESSION_COUNT = 194
                                │
                                ▼
                   NDM_DECISION_CAUSAL_COVERAGE → 0.0
                   SELECTED_ACTION_WITH_NDM_REASONING_COUNT stays 3
                                │
                                ▼
                   NDM stops steering Full-Long
                                │
                                ▼
                   progression continues only via legacy/safe fallback actions
                                │
                                ▼
                   basement/final battle not reached by cycle 60
                                │
                                ▼
                   FULL_LONG_COMPLETION_CONTRACT_FAIL
                   (V16 IMMUTABLE_NEGATIVE_REFERENCE)
```

## Parallel telemetry branch

```text
enrich_pc_action_with_ndm never passes progress_events
        │
        ▼
KP meaningful_progress_this_cycle stays false even when UEL progress_delta>0
        │
        ▼
MEANINGFUL_PROGRESS_RATE = 0.0  (instrumentation / aggregation gap)
SELF_RECOVERY_RATE = 0.0       (NDM recovery chain absent)
```

## PRIMARY_ROOT_CAUSE

`RECENT_ACTIONS_SCHEMA_MISMATCH` — StallDetector list tuples vs NDM dict `.get` contract.

## SECONDARY_ROOT_CAUSES

1. `FAIL_CLOSED` ignored by `NaturalDecisionRuntime.decide`  
2. SAFE_LEGACY path re-consumes incompatible `recent_actions` (double fault)  
3. Exception→SAFE_LEGACY policy too eager for schema bugs  
4. `progress_events` not wired from production enrich hook  
5. SAFE_LEGACY counted inside `LEGACY_DECISION_COMMIT_COUNT`

## NDM_COMMIT_FAILURE_STAGE (identified)

Dominant: **post-PL, at KP assess** (`DROP_AFTER_REASONING` ×189; `DROP_AFTER_DECISION` ×5).

## MEANINGFUL_PROGRESS_ZERO_CAUSE (identified)

`RAW_INSTRUMENTATION_GAP + AGGREGATION_GAP + NDM_NOT_CONTROLLING_ACTIONS`

## V17_FIX_SCOPE

`MULTI_COMPONENT_FIX` — normalize recent_actions schema at boundary; handle FAIL_CLOSED; stop treating AttributeError as SAFE_LEGACY; optional progress_events bridge; clarify LEGACY vs SAFE_LEGACY counters.

**V17_READY = false** until design exists.
