# V16 NDM Intent vs Legacy Executed Action Diff

## Data limits (explicit)

`PL_REASONING_FALLBACK` events store only:

- `fallback_mode`, `decision_source`, `decision_transaction_id`, `failure_reason`

They do **not** store `legacy_selected_action`.  
For 189 `COMPLETED_THEN_FALLBACK` rows, COMPLETED often has `selected_action=null` / `selected_target=null` (FAIL_CLOSED), while `selection_reason` text may still exist.

Therefore many per-fallback diffs are `UNKNOWN` by Raw honesty rules (no invented legacy action).

## What can be said with evidence

### Early NDM successes (n=3)

Bound NDM actions (from telemetry ACTION_SELECTED):

1. `search` / `knott_letter`  
2. `move` / `central_library`  
3. `search` / `newspaper_archives`  

These are coherent with early UEL progression (introduction → library).

### After fallback dominance

- NDM ceases to publish bound ACTION_SELECTED.  
- UEL still shows 198 turn records with concrete `selected_action`/`target` under normal evaluation execution (AUTONOMOUS / SYSTEM_GUIDED / SYSTEM_FORCED).  
- Those post-dominance actions are **not NDM-causally bound** (`decision_source` path = safe_legacy_progression for the 194 fallback commits).

### Intent residue on 189 COMPLETED_THEN_FALLBACK

COMPLETED events retain `actor_id` + `selection_reason` strings (PL did choose among candidates inside pipeline before KP assess crashed), but **lose action/target fields** when `FAIL_CLOSED` returns without `selected_action`.

Diff class for those rows: **UNKNOWN** (cannot pair null NDM action to a specific legacy action from the fallback event). Qualitatively: **NDM decision payload truncated → legacy `_fallback_select` replaces commit**.

## Location-focused reading

| Area | NDM steering | Observed run |
|---|---|---|
| introduction / library / neighborhood | brief NDM success then loss of bind | entered / visited |
| corbitt_exterior | fallback-dominated | long dwell / revisits |
| corbitt_ground_floor | fallback-dominated | entered; living room etc. investigated |
| basement / boss | never reached | no NDM-guided push to planks/boss |

## Diff counters (Raw-strict)

| class | count |
|---|---:|
| UNKNOWN | 194 |
| SAME_ACTION / others | 0 (not assertable from fallback records) |

**NDM_VS_LEGACY_ACTION_DIFFERENCE_RATE = 1.0** if defined as “share of fallback commits lacking proven SAME_ACTION evidence”; **not** a measured semantic divergence rate.

## Fallback dominance vs progression failure

`FALLBACK_DOMINANCE_CAUSED_PROGRESSION_FAILURE = partial`

- **true aspects:** NDM stopped steering after cycle~2; causal coverage 0; long no-progress; no final battle.  
- **false-as-sole-cause:** legacy path still produced real state progress (house entry, 27 true flags, 28 UEL turns with `progress_delta>0`).  
- Final battle miss is **joint**: fallback dominance + legacy progression limits / exploration inefficiency under max cycles.
