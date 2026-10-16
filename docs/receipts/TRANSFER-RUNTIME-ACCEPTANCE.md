# V5 conditional-start acceptance report

Generated: 2026-10-15 (Asia/Tokyo)

This comparison uses `evaluation-v2/CORBITT_LONGRUN_ITERATION3_V3_HOME_001/run_identity.json`
as the latest locally available accepted production identity. The prior PC's
machine/OS/Python manifest and the accepted `night_guard` implementation are
not present on this PC, so those identities cannot be asserted.

```text
MACHINE_IDENTITY = 403-01 / Windows 11 Pro 10.0.26200 build 26200 x64

ENVIRONMENT_IDENTITY = FAIL
Reason: prior-PC machine/OS/Python manifest unavailable; current Core/Video Python is 3.14.3.

PRODUCTION_SOURCE_IDENTITY = FAIL
Core listed implementation files = PASS
Prompt (main.py identity) = PASS
Scenario = PASS
NPC = PASS
PC = FAIL
Normalizer = FAIL
Video pipeline = FAIL
Auditor = FAIL
night_guard = FAIL (accepted implementation absent)

PRODUCTION_CORE = PASS (582 passed, 23 subtests passed, 0 fail/error/skip)
PRODUCTION_VIDEO = FAIL (required >=208; available transferred suite is incomplete)
PRODUCTION_AUDITOR = FAIL (22 available transferred tests passed; required >=24)

RUNTIME_BOUNDARY = PASS (isolated candidate, 11 fault/boundary tests passed)
STARTUP_DRY_RUN = FAIL (INPUT_IDENTITY mismatch; no formal session created)
STREAMLIT_IMPORT = PASS
PLATFORM_SYSTEM_QUERY = PASS
CORE_CONSTRUCTOR = PASS
OLLAMA_HEALTH = PASS
OLLAMA_GENERATION_PROBE = PASS (deterministic response: OK)

FAULT_INJECTION = PASS
OLD_RUN_WRITE_PROTECTION = PASS
NETWORK_RESTRICTION = PASS
PAID_API_BLOCK = PASS

UNATTENDED_ADAPTERS_CONNECTED = FAIL
UNATTENDED_LOOP_ENABLED = false
V5_START_ALLOWED = false

SESSION_ID = CORBITT_LONGRUN_ITERATION3_V5_HOME_001 (reserved, not created)
FULL_LONG_STARTED = false
EARLY_GATE = NOT_REACHED
FULL_LONG_RAW_RUN = NOT_STARTED_IDENTITY_GATE_FAILED
FULL_LONG_AUTONOMOUS_REEVALUATION = NEEDS_ENVIRONMENT_RECONCILIATION
VIDEO_SOURCE_ELIGIBLE = false
```

## Identity evidence

| Component | Accepted SHA-256 | Current/local SHA-256 | Result |
|---|---|---|---|
| Core `main.py` / prompt | `8cf1403ec36a9bf8f931429c4a3e172d2ecb5361decc08d28c96c480fc7393c6` | same | PASS |
| Scenario | `b6f0559ffca677b57bc3a69c16991bb24c483d30256cb6dfd30fc938ebd84ed7` | same | PASS |
| PC | `8b04641837d36786b541e2c3bbccead7b4ff025135b18765383c6e446861215e` | `f47bb03ff6406c228dd7c88f94c597d6e28785b47c6e0afe1322b7596c31c3dd` | FAIL |
| NPC | `3c795e6098f97ae8e6240b9ed2412428ab332c91c30a1cb45b846d2f4628377c` | same | PASS |
| Normalizer | `d3f4f9cf2933139c94e9133d69f989635ecc7e07fad13b277fed865fff58074b` | `a33ac9bc8d6b18d8465abb145c35e39a0c8eabdcc2674570b30dc771d4fa9b30` | FAIL |
| Video pipeline | `0d1d34468f4501a6fbaa8a0240c6ecac385f4191e27b1a6e94f4c862f2bd5045` | `598d3aa56cb9513f699240146b09add6574a98f7e7f3df1e33a2571d0b69ae54` | FAIL |
| Auditor v2 | `858b33c80d73c940ca2c8e9e6c5b63d34bb6e792e29307ed438fc2169f86608e` | `bd5444dcd67f9e90c12f2723e7f307efce96456d1802ee345ed05c1ab46bb90e` | FAIL |

The local transferred Video bundle also lacks
`tests/test_simple_move_bijection.py`, so the accepted Simple Move patch and
its fixture cannot be established from this copy. A hash search across all
projects under `F:\制作物` found no copy of the accepted Normalizer, Video
pipeline, or Auditor identities.

## Ollama identity

Ollama endpoint is fixed to `127.0.0.1:11434` inside the candidate dry-run.
The installed model is `qwen2.5:14b`, family `qwen2`, size `14.8B`,
quantization `Q4_K_M`, digest
`7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6`.
The accepted V3 record contains the same name/family/size/quantization but no
digest, so all comparable model fields pass.

## Dry-run and audit

The dry-run traversed Python, Streamlit import, all Core imports, configuration,
Scenario/PC/NPC loading, identity validation, Core construction, local Ollama
health and generation, run identity construction, output preflight, session
pre-boundary, and Cycle 0 pre-boundary. It used only a temporary
`DRY_RUN_TEMP_SESSION_*` directory and removed it afterward.

No child process was created during the production-path dry-run. The audit log
contains six allowed socket operations, all to `127.0.0.1:11434`, and zero
subprocess records. Unknown children are denied and are never auto-added.

Fault injection verified safe stop for regression/identity failure, unknown
subprocess, external network, paid API configuration, old-Run write, model
mismatch, implementation drift, and an injected runtime exception.

V4 and V5 session directories are absent. No V4 ID was reused and no V5 Raw
Run, checkpoint, migration, resume, or replacement Run was created.
