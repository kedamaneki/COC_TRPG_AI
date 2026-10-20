# CORBITT Final Battle — V14 Acceptance Decision

**Date:** 2026-10-20  
**Baseline design:** `6ede213` / remediation commits through Phase 5  
**Session (intended):** `CORBITT_LONGRUN_ITERATION3_V14_HOME_001`

## Phase 6 regression (pre-V14)

| Gate | Result | Notes |
|---|---|---|
| Core unit tests | **PASS** `646` (≥626) | Includes WP-A/B/C + V14 fixtures |
| Video agent tests | **PASS** `292` collected-green; `9` voice-runtime ERROR (env) | Voice fixtures need `VOICE_RUNTIME_PATH`; not introduced by remediation |
| Auditor fidelity + formal | **PASS** (formal auditor + V14 pack tests) | `--fidelity-pack none` preserves V8–V13 |
| Night/unattended (subset) | **PASS** `47` (2 process-boundary fail without sitecustomize on path) | Expected when isolation sitecustomize not injected |
| `ACTIVE_RUNTIME_HARDCODE` | **0 / PASS** | `tools/verify_portability.py` scan |
| V13 immutability rehash | **PASS** `373` files, aggregate `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d` | External source + control roots |

## Implementation shipped (Phases 1–5)

- WP-C: `CombatResolutionGuard` fail-closed combat NO_ROLL  
- WP-A: Route A armor/HP0 + Route B dagger; break→attack remap; defeat auto-clear removed  
- WP-B: `BossCombatPolicy` (dagger / Dominate / body activation / normal attack)  
- Normalizer forwards kill-route / activation / armor fields (no invention)  
- Auditor V14 fidelity pack (gated; historical default unchanged)  
- Fixtures A–H, N1–N4, P1–P6  

## Phase 7 — V14 Fresh Full-Long

Night Guard now accepts `--session-id` (default unchanged). Launch path:

```text
python tools/night_guard/night_guard.py execute \
  --session-id CORBITT_LONGRUN_ITERATION3_V14_HOME_001 \
  --output <fresh_output_dir>
```

Constraints:

- Fresh: Cycle0, `resume_count=0`, `migration=null`  
- **Never resume V13** (V13 added to `OLD_RUN_NAMES` write-protect list)  
- Instant fail if `break corbitt_body → NO_ROLL → clear` recurs  

## Phase 8 — Acceptance decision (current)

| Gate family | Status |
|---|---|
| Formal correctness (V14 run) | **PENDING** — Full-Long not yet executed in this implementation pass |
| Scenario fidelity FB-01..14 | **PENDING** — requires V14 Raw + `--fidelity-pack corbitt_v14` audit |
| `KNOWN_GOOD_PROMOTION` | **BLOCKED** |
| V13 | Remains `FORMAL_ACCEPTANCE=PRESERVED` / `SCENARIO_FIDELITY=FAIL` |
| Video 002 remake | **Not authorized** until V14 Formal+Fidelity PASS |

### Decision

```text
KNOWN_GOOD_PROMOTION = BLOCKED
REASON = V14_FRESH_FULL_LONG_NOT_YET_RUN
BLOCKER_OBSERVED = Night Guard dry-run could not obtain LOCAL_OLLAMA model identity
                   (HTTP 404 on /api/show name=qwen2.5:14b)
NEXT = Ensure local Ollama qwen2.5:14b is available, then:
       python tools/night_guard/night_guard.py execute \
         --session-id CORBITT_LONGRUN_ITERATION3_V14_HOME_001 \
         --output <fresh_output_dir>
       then apply docs/CORBITT_FINAL_BATTLE_V14_ACCEPTANCE_GATES.md FB-01..14
       with Formal Auditor --fidelity-pack corbitt_v14
```

Code remediation Phases 1–6 are complete and pushed. `--session-id` override is live.
Acceptance tag must wait for a live V14 Fresh Full-Long result with Formal+Fidelity PASS.
