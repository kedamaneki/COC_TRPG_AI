# V13 Video Acceptance Context

## Source status

- `SOURCE_ACCEPTED=true`
- `VIDEO_SOURCE_ELIGIBLE=true`
- `RAW_HASH_VERIFIED=true`
- `INPUT_IDENTITY_PASS=true`
- `FORMAL_AUDITOR_PASS=true`
- `LEGACY_COMPARISON_PASS=true`
- `traceability=1.0`
- `segment_coverage=1.0`
- `dropped_events=0`

The source session is `CORBITT_LONGRUN_ITERATION3_V13_HOME_001`, accepted as `CORBITT_KNOWN_GOOD_BASELINE_V13`. The Raw root and formal outputs are read-only evidence. Derived media must be written under `F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001` or another separate root.

## Truth hierarchy

1. Raw Session Archive and Unified Event Log
2. Formal Normalizer output
3. Video-side derived representation
4. Script and narrative rendering

The Video Agent may change presentation only. It must not fill missing events, generate missing rolls, invent dialogue, swap actors, change locations or outcomes, or add SAN/combat/Special Objective/ending facts. `FACT`, `PRESENTATION`, and `INFERENCE` must remain distinct; inference may never be displayed as fact.

## Rendering entry gate

The Video Agent must verify the handoff manifest, accepted evidence hash, source index, actor mapping, segment coverage, and raw event order before generating media. Source-hash mismatch, unresolved actor identity, coverage below `1.0`, or non-monotonic event order is fail-closed. Auto-publish is prohibited. Human Review is mandatory.
