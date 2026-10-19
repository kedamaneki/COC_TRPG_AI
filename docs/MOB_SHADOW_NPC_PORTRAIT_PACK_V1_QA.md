# Mob / Shadow NPC Portrait Pack v1 — QA

- File count: 12 / 12
- PNG RGBA transparency: PASS
- Opaque-edge clipping: 0 (all edge alpha values are 0–2 only; no visible silhouette clipping)
- Height range 1000–1600 px: PASS
- Duplicate pack asset IDs: 0
- Duplicate pack portrait IDs: 0
- Missing semantic tags: 0
- Registry references: PASS
- Unapproved automatic-use assets: 0
- Corbitt exclusivity metadata: PASS
- Existing accepted render replacement: NOT PERFORMED

## Regression

- Dedicated portrait-pack fixture: **6 passed**
- Full Video Agent suite: **282 passed / 0 failed / 0 errors / 0 skipped**
- The first full-suite attempt used the Windows sandbox temp directory and produced temp-write errors. The unchanged suite was rerun with an isolated repo-local temp root and passed completely.

## Historical artifact protection

- V13 Raw freeze file count: **373 / 373**
- V13 Raw freeze manifest comparison: **0 hash mismatches**
- V13 Raw aggregate SHA-256: `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d`
- V1–V2.8 render output root: **write operations 0**
- Video rerender: **NOT PERFORMED**
