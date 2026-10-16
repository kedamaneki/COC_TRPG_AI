# Runtime isolation candidate

This is an isolated candidate. It does not alter production Core, Normalizer,
Video pipeline, Auditor, prompts, Scenario, or PC/NPC data.

The boundary has three layers:

1. Trusted Runtime: exact executable allowlist plus an explicit purpose for each child process.
2. Restricted Repair Environment: no subprocess, shell, network, package/model operations, or writes outside this candidate.
3. Network Boundary: only local Ollama at `127.0.0.1:11434` (`localhost` and `::1` normalize to that endpoint).

Unknown children are denied and only logged. They are never added to the allowlist.
The dry-run uses a `DRY_RUN_TEMP_SESSION_*` directory and stops before a formal
session is created.
