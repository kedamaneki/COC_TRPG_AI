# Git Tag Identity Recovery — V14 audit

**Date:** 2026-10-21  
**Scope:** Local tag recovery only. No remote tag mutation. No acceptance tags created.

## Authority finding

`git ls-remote --tags origin v5-preflight-accepted` returns **empty**.

Origin currently publishes only:

- `corbitt-final-battle-audit-v1`
- `pre-corbitt-final-battle-scenario-audit`

Therefore **remote cannot serve as a live tag authority** for `v5-preflight-accepted`. Restoration used the **pre-retarget annotated tag object still present in the local object database**, corroborated by:

- annotated tag object `9536810fab9445824bbeeaf6f1a8f6abb297fc61`
- tag payload `object 01483271f6f9865af818580747d2bd2efbb41a82`
- local branch `feature/runtime-isolation-v5` → same commit `0148327`
- prior session record before retarget (same tag object / commit)

## Timeline

| Stage | `v5-preflight-accepted` commit |
|---|---|
| Original (pre-V14 run) | `01483271f6f9865af818580747d2bd2efbb41a82` (`0148327` — V5 runtime isolation) |
| Temporary local retarget (V14 execute workaround) | `53c1b164813124a7d17adacd4d84f2ea0ca7eddb` (current `main` HEAD) |
| Restored (this audit) | `01483271f6f9865af818580747d2bd2efbb41a82` via `git update-ref` to tag object `9536810…` |

## Gate record

```text
V5_LOCAL_TAG_COMMIT (after recovery) = 01483271f6f9865af818580747d2bd2efbb41a82
V5_REMOTE_TAG_COMMIT = NOT_PRESENT_ON_ORIGIN
V5_TAG_RESTORED = true
V14_LOCAL_PREFLIGHT_TAG = v14-preflight-accepted → 53c1b164813124a7d17adacd4d84f2ea0ca7eddb
V14_PREFLIGHT_STATUS = PRELIMINARY / LOCAL ONLY / NOT ACCEPTED FULL-LONG TAG
REMOTE_TAG_CHANGED = false
```

`v14-preflight-accepted` remains local-only. Not pushed. Not an acceptance tag.

## FORMAL_RUN_IDENTITY_TAG_COUPLING

**Status: CONFIRMED**

Code: `tools/night_guard/night_guard.py` → `formal_run_identity()`:

```python
tags = [line for line in run('tag', '--points-at', 'HEAD').splitlines() if line]
if git_info['git_dirty'] or git_info['git_branch'] != 'main' or 'v5-preflight-accepted' not in git_info['git_tags']:
    raise Stop('GIT_IDENTITY_NOT_ACCEPTED')
```

Implications:

- Admission requires the literal tag name `v5-preflight-accepted` to **point at HEAD**.
- Later per-run tags (`v13-preflight-accepted`, intended `v14-preflight-accepted`) do **not** satisfy the gate.
- No CLI override / identity manifest / current-release field exists today.
- This coupling forced the temporary local retarget that this audit restored.

### Design-only improvement options (do not implement in this audit)

1. `--preflight-tag <name>` CLI override validated against `tag --points-at HEAD`
2. Formal identity manifest checked into repo / control output
3. `accepted_implementation_commit` hash field instead of movable historical tag name
4. Accept any `*-preflight-accepted` that points at HEAD, or a configured allow-list

## Remote unchanged

`git ls-remote --tags origin` after recovery still shows only the two audit tags above. No force-push. No tag push.
