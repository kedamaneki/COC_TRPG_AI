# V13 Video 001 V2.8 Replay Summary Bridge Report

## Scope

- Source session: `CORBITT_LONGRUN_ITERATION3_V13_HOME_001`
- Source range: raw event offsets `82..233`
- Immutable predecessors: V13 Raw and V1 through V2.7
- Derived video: `V13_VIDEO_001_BASEMENT_PLANKS_V2_8`
- Dialogue UI: V7 default Dialogue UI

## Entry Bridge

- Render mode: `SUMMARY_ENTRY_BRIDGE`
- Speaker: `KP`
- Reason class: `BEHAVIORALLY_SUPPORTED_TRANSITION`
- Evidence offsets: `144`, `146`
- Source transition: `corbitt_basement -> corbitt_ground_floor`
- Display text: `板の状態を確認しましたが、その場では突破せず、いったん地下室を離れて一階へ移ります。`
- Facts used: the planks were examined, they were not broken, and the party moved to the ground floor.
- Invented motivation: none

## Exit Bridge

- Render mode: `SUMMARY_EXIT_BRIDGE`
- Speaker: `KP`
- Reason class: `BEHAVIORALLY_SUPPORTED_TRANSITION`
- Evidence offsets: `149`, `175`, `231`
- Source transition at offset 231: `corbitt_ground_floor -> corbitt_basement`
- Display text: `一階と上階を調べたのち、再び地下室へ戻ります。`
- Facts used: ground-floor investigation, upper-floor investigation, and return to the basement.
- Invented motivation: none

## Replay Order

1. Full render through offset 145
2. Entry bridge for offset 146
3. Three summary blocks for offsets 147..230
4. Exit bridge for offset 231
5. Full render from offset 232

## Gates

- `LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED=true`
- `SUMMARY_ENTRY_CONTEXT_MISSING=0`
- `SUMMARY_EXIT_CONTEXT_MISSING=0`
- `UNGROUNDED_BRIDGE_FACT=0`
- `BRIDGE_INVENTED_REASON=0`
- `BRIDGE_LOCATION_MISMATCH=0`
- `UNEXPLAINED_SCENE_TRANSITION=0`
- `SUMMARY_TRACEABILITY=1.0`
- Existing Replay Summary counts: all `0`
- Technical QA: `PASS`
- Content QA: `PASS`
- Source artifacts unchanged: `true`

## Verification

- Focused Replay Summary and Dialogue UI fixtures: `10 passed`
- Full Video Agent suite: `276 passed`
- Representative entry and exit frames were inspected for KP identity, V7 Dialogue UI, two-line wrapping, clipping, and location transition wording.

## Status

- `VIDEO_V2_8_ACCEPTED_FOR_HUMAN_REVIEW=true`
- Human review: `PENDING`
- License review: `REQUIRED`
- Auto publish: prohibited
