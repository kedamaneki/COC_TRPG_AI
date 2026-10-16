# Replay Editing Contract v0.1

`normalized_session.json` is the sole truth source. An editor may change presentation and remove log-format redundancy, but it must not change facts, rolls, outcomes, attribution, character decisions, or causal order.

Every one of the 678 normalized events receives exactly one `Content Decision`: `KEEP`, `COMPRESS`, or `CUT`. Every retained script line carries at least one normalized or source-log event ID. A compressed line carries every merged source ID.

Editing is represented on three independent axes:

- Content: `KEEP`, `COMPRESS`, `CUT`
- Presentation: `VOICED`, `SUBTITLE_ONLY`, `OVERLAY_ONLY`, `SILENT_VISUAL`, `NONE`
- Text: `VERBATIM`, `TRIM_REDUNDANCY`, `LIGHT_NORMALIZE`, `COMPRESSED`, `NONE`

The deterministic editor may remove an exact speaker/log prefix, isolate system processing from PC speech, cut internal AI/development telemetry, and collapse exact near-duplicate lines. It may not invent dialogue or emotional narration. Any provider failure falls back to `KEEP / VOICED / VERBATIM`.

`HARD_PROTECTED` events cannot be cut. `SOFT_PROTECTED` events may be compressed but their meaning must remain. Dependency sources remain visible whenever their dependent event remains visible.

Provider output must conform to the decision schema and reference supported source IDs. Unsupported or schema-invalid output is discarded. The current M2 implementation uses the local deterministic provider and performs no external LLM/API call.
