# Local Frontier Continuity + Replay Summary Layer v1

## Result

- `LOCAL_FRONTIER_CONTINUITY_GAP`: fixed for future runs.
- `REPLAY_SUMMARY_LAYER`: implemented.
- V13 accepted Raw: unchanged.
- V2.7 preview: rendered as a separate derived artifact.
- Human review: pending.

## Core / Progression

Candidate availability remains the authority for whether an action is legal. A separate
continuity score now ranks already-valid candidates. Local unresolved executable
frontiers, current-goal routes, declared intended state effects, and recent context are
rewarded. Low-value movement, revisiting a recent destination, and location loops are
penalized. Blocked, wrong-location, and exhausted information candidates are removed
before the display/execution limit is applied.

`expected_state_effect` describes the state change an action is intended to pursue. It
does not promise success or alter dice/adjudication results.

## Replay Summary

Replay events are classified as `FULL_RENDER`, `SUMMARY_RENDER`, or `OMIT`. Omitted
repetitive blocked checks remain covered by a summary block and retain source event
provenance. A full-render gap containing gameplay without summary coverage fails as
`UNEXPLAINED_GAMEPLAY_GAP`.

V13 offsets 147 through 231 are represented by three KP factual summaries:

1. Ground-floor re-exploration: offsets 147-171.
2. Upper-floor exploration: offsets 172-223.
3. Movement between floors and return to the basement: offsets 224-231.

No narrator speaker was introduced. Each claim is tied to exact raw offsets and source
event IDs.

## Gates

- `SUMMARY_TRACEABILITY = 1.0`
- `UNGROUNDED_SUMMARY_FACT = 0`
- `SUMMARY_CAUSAL_ORDER_MISMATCH = 0`
- `SUMMARY_LOCATION_MISMATCH = 0`
- `SUMMARY_DROPPED_MAJOR_STATE_CHANGE = 0`
- `SUMMARY_INVENTED_REASON = 0`
- `UNEXPLAINED_GAMEPLAY_GAP = 0`
- Technical QA: PASS
- Content QA: PASS

## Regression

- Core: `626 passed, 26 subtests passed`.
- Video Agent: `271 passed` from an ASCII-path staging copy of the same source. This
  avoids the known OpenCV Windows Unicode-path limitation without changing production
  files.
- Focused progression and replay-summary fixtures: PASS.

## Artifact

`V13_VIDEO_001_BASEMENT_PLANKS_V2_7_PREVIEW.mp4` is accepted for human review only.
Auto-publish remains prohibited and license review remains required.
