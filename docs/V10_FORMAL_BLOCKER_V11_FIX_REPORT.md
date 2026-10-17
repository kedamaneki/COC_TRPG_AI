# V10 Formal Blocker Root Cause and V11 Producer Fix

## Disposition

- Frozen source: `CORBITT_LONGRUN_ITERATION3_V10_HOME_001`
- V10 remains rejected and is not eligible for video use.
- Resume, backfill, Raw editing, same-session rerun, and re-elevation were not performed.
- Before and after the work, all 542 frozen files match `V10_RAW_FREEZE_MANIFEST.json` byte-for-byte.
- The aggregate reconstructed from the manifest's LF-joined ordered rows remains
  `4e2b8ae41bb08686ba7c5b2b89836841e25994f96a7a89aa5e2e0ee63b679e3c`.

## Historical Acceptance

The current Normalizer and Formal Auditor were run against V10 in a new control-side
output directory. The historical result was reproduced exactly:

- 8 CRITICAL
- 4 MAJOR
- `ROLL_CONTRACT_INCOMPLETE = 8`
- `LIFECYCLE_MISCLASSIFIED_AS_NO_ROLL = 3`
- `NORMALIZATION_SOURCE_CONTRADICTION = 1`
- traceability `1.0`

The producer fixes do not reinterpret or clean the frozen V10 evidence.

## Group A — Session ROLL Evidence Gaps

| Session source | Producer path | FIRST_MISSING_BOUNDARY |
|---|---|---|
| `session_log:000160` | Luck decline followed by Push decision | `step_luck_decision()` called `append_system_log_entry()` without the authoritative result, actor, or adjudication tuple. |
| `session_log:000217` | Automatic SAN resolution | `step_system_resolve_san()` omitted actor, target, and `adjudication=san_result` at Session commit. |
| `session_log:000265` | Push decline | `resolve_push_decline()` rebuilt a result without inheriting the original failed ROLL evidence. |
| `session_log:000299` | Push decline | Same boundary as `000265`. |
| `session_log:000428` | Luck decline followed by Push decision | Same boundary as `000160`. |
| `session_log:000430` | Push decline | Same boundary as `000265`. |
| `session_log:000440` | Push decline | Same boundary as `000265`. |
| `session_log:000445` | Push decline | Same boundary as `000265`. |

The dice execution and authoritative result existed upstream. The defect class is
`ROLL_EVIDENCE_PROPAGATION_GAP`, with two Session-commit omissions and one
pending-decision inheritance omission.

### Fix

- Pending Push state now carries the complete original adjudication envelope.
- Push decline validates and reuses that envelope; it never rerolls or reconstructs values.
- Luck and Push decision logging uses the common result logging path.
- SAN uses the PC as both authoritative actor and SAN target and commits the complete tuple.
- Any Session text containing a recognized ROLL marker without authoritative adjudication now fails closed.
- A committed Session ROLL validates `adjudication_id`, actor, target, canonical skill,
  target value, roll, raw result, final result, and modifier.

## Group B — Combat Lifecycle Contamination

### Session rows

`session_log:000517` and `session_log:000524` combined an adjudication log and a
`【戦闘開始】` or `【戦闘終了】` display block in one Session record. The first
contamination boundary was `_append_result_log_with_knowledge()`, which committed the
combined text with one ROLL/NO_ROLL metadata envelope. The Normalizer correctly gave
the explicit lifecycle marker its lifecycle type, exposing the contamination.

### Unified row

`evt_000387_9131c7e6bc6bd2f31371` was emitted by
`_apply_combat_payload_effects()`. That producer passed the special-objective
`adjudication_id` and resolution fields directly into `COMBAT_ENDING/COMBAT_ENDED`.
Although the serializer removed `resolution_mode`, it retained the adjudication ID;
the Normalizer then merged the Session NO_ROLL tuple into the lifecycle record.

### Fix

- Combined Session output is split before commit into an adjudication row and a pure
  lifecycle display row.
- The display row carries only `cause_adjudication_id` as its causal relation.
- `COMBAT_STARTED`, `COMBAT_ENDING`, and `COMBAT_ENDED` reject resolution fields.
- Unified lifecycle producers now use `cause_adjudication_id`; resolution evidence
  remains on `COMBAT_ACTION_RESOLVED` or `SPECIAL_OBJECTIVE_COMPLETED`.

## Group C — Canonical Dice Identifier

For adjudication `adj_49328bee910a432cb6f0017e07873f2b`, the authoritative
investigation evidence is:

- proposed identifier: `目星`
- KP-selected identifier: `STR`
- actual Dice Engine target: `STR 55`
- roll: `38`
- result: `REGULAR_SUCCESS`

`INVESTIGATION_ROLLED` and `INVESTIGATION_SUCCEEDED` correctly store `STR`.
The first contradictory boundary was `ProgressDirectorV2.record_unified_turn()`: its
summary `skill` field came from the original PL action (`目星`), while the same summary
also inherited authoritative `skill_or_stat=STR`.

The summary producer now sets `skill` and `canonical_identifier` from the authoritative
adjudication envelope for ROLL events and preserves the proposal separately as
`requested_roll_identifier`. Normalizer contradiction detection is unchanged.

## Dedicated Acceptance Fixtures

- Missing Session actor/target or an absent adjudication envelope fails closed.
- Push decline preserves the original target, roll, raw result, actor, target, and ID.
- Combat lifecycle rejects resolution metadata and retains only cause relation.
- Combined roll plus combat display becomes two Session records.
- A proposed `目星` / selected `STR` investigation summary remains canonically `STR`.
- Formal Normalizer/Auditor fixture results:
  - Session ROLL gap `0`
  - combat lifecycle contamination `0`
  - dice identity contradiction `0`

## Regression Results

- Core: `607 passed + 26 subtests passed`
- Video Agent: `213 passed`
- Formal Auditor / Normalizer / Evidence focused suite: `32 passed`
- night_guard / runtime isolation: `60 passed`
- All runs completed with 0 fail, 0 error, and 0 skip.
- Existing V5/V6/V7/V8/V9, Simple Move, Special Objective, SAN, Luck, Push,
  Segment, EventIdentity, and Formal Evidence fixtures are included in the passing suites.

## Gate

- `V10_HISTORICAL_12_BLOCKERS_REPRODUCED = PASS`
- `SESSION_ROLL_EVIDENCE_FIX = PASS`
- `COMBAT_LIFECYCLE_PURITY_FIX = PASS`
- `DICE_CANONICAL_IDENTIFIER_FIX = PASS`
- `V10_RAW_INTEGRITY = PASS`
- `VIDEO_SOURCE_ELIGIBLE = false` for V10
