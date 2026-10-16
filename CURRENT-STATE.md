# Current State

Canonical production and runtime isolation acceptance are complete.

- RUNTIME_ISOLATION_V5 = PASS
- CORE_REGRESSION = 582 passed + 23 subtests passed
- VIDEO_REGRESSION = 208 passed
- AUDITOR_REGRESSION = 24 passed
- NIGHT_GUARD_AND_RUNTIME_BOUNDARY = 60 passed
- V3_READONLY = PASS (Raw 96/96, duplicate 0, traceability 1.0, segment coverage 1.0)
- V5_START_ALLOWED = true after main points at the accepted integration commit, the v5-preflight-accepted tag points at that commit, and git status is clean.
- VIDEO_SOURCE_ELIGIBLE = false

No formal V5 session had been created when this acceptance record was prepared.
