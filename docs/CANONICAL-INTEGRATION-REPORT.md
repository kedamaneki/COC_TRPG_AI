# Canonical Integration Report

## Canonical baseline

The canonical repository was created by copying accepted main-PC production and verifying every copy with SHA-256. Existing production and historical Raw Runs were not moved, deleted, overwritten, resumed, or backfilled.

Baseline commit: 755ddb3c4eac5dbb9880e4f064887892ff9aacce
Tag: pre-runtime-isolation-v5

## Accepted production

- Core: 582 passed, 23 subtests passed
- Video Agent: 208 passed
- Formal Auditor gate: 24 passed
- Original night_guard suite: 49 passed
- Core, Scenario, PC/NPC, prompt, Normalizer, Video pipeline, Auditor, Segment, EventIdentity and Simple Move hashes match the accepted main-PC identities.

## Runtime isolation selective merge

transfer-to-main-pc-2026-10-15/CHECKSUMS.sha256 verified 20/20. Only ADOPT_CANDIDATE runtime boundary, startup dry-run, its 11-test fixture, and README were adopted. The accepted main-PC sitecustomize.py supplies the network and old-Run process boundary. DO_NOT_ADOPT production and incomplete test suites were not integrated.

The startup adapter was reconciled for Python 3.12 by admitting only the exact Windows command interpreter for the named standard-library platform.system ver probe. Unknown commands and all other shell calls remain denied. The candidate's other-PC PC hash was replaced with the accepted main-PC PC hash; the mismatched PC data itself was not adopted.

Protected production diff after selective merge: empty.

## Startup acceptance

The production-path dry-run passed Python, Streamlit, platform.system, Core imports, configuration, Scenario/PC/NPC identity, Core construction, local Ollama health and deterministic generation, run identity, Session preflight and Cycle 0 pre-boundary. It created only DRY_RUN_TEMP_SESSION data and reported persistent_session_created=false.

Model identity: qwen2.5:14b, family qwen2, size 14.8B, quantization Q4_K_M, digest 7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6. Only 127.0.0.1:11434 was allowed.

## Post-integration acceptance

- Core: 582 passed, 23 subtests passed, 0 fail/error/skip
- Video Agent: 208 passed, 0 fail/error/skip
- Formal Auditor: 24 passed, 0 fail/error/skip
- night_guard + runtime boundary: 60 passed (49 + 11), 0 fail/error/skip
- startup dry-run: PASS
- night_guard adapter dry-run: PASS
- old-Run content hashes unchanged: PASS
- carried runtime fault/boundary suite: 11/11 PASS
- V3 read-only reanalysis: Raw 96/96, duplicate 0, traceability 1.0, segment missing/duplicate/unexpected 0/0/0, coverage 1.0

## Git and run identity

The runtime integration is committed on feature/runtime-isolation-v5, then fast-forwarded to main and tagged v5-preflight-accepted. Formal runs are rejected unless the current branch is main, that tag points at HEAD, and the worktree is clean. run_identity.json records commit, branch, tags, dirty state, accepted component hashes, model identity, routing, Cycle 0, resume_count=0, and migration=null.

## Decision

- RUNTIME_ISOLATION_V5 = PASS
- V5_START_ALLOWED = true once the Git merge/tag/clean activation condition is met
- VIDEO_SOURCE_ELIGIBLE = false
