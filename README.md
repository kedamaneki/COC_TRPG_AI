# Corbitt TRPG System

Canonical repository for the accepted AI Cthulhu TRPG Core, Video Production Agent,
Formal Auditor, and guarded unattended runtime tooling.

The repository was established from copied, SHA-256 verified main-PC production.
Historical Raw Runs and generated media remain external or ignored and are recorded in
`manifests/EXTERNAL-ARTIFACTS.json`.

## Setup on another PC

1. Clone the repository and check out the required checkpoint tag.
2. Create Python 3.11+ environment and install `requirements-portability.txt`, then install `video` editable.
3. Copy `config/local_paths.example.json` to ignored `config/local_paths.json`, or set the variables from `.env.example` in the shell.
4. Attach or copy the V13 source and the asset tree. Drive letters do not need to match; set `CORBITT_V13_SOURCE_ROOT`, `CORBITT_V13_CONTROL_ROOT`, and `VIDEO_ASSET_ROOT`. The canonical Corbitt Scenario source is packaged in the repository; use `CORBITT_SCENARIO_SOURCE_ROOT` only for an explicitly verified override.
5. Install FFmpeg/FFprobe, AquesTalk runtime, the C# compiler used by the bridge, and Noto Sans JP. Point the corresponding variables at them.
6. Run `python tools/verify_portability.py`; it verifies the 373-file V13 freeze, packaged Scenario source, required asset hashes, active runtime paths, registries, and a no-render pipeline dry run.
7. Run the Core and Video test suites documented in `docs/CROSS_PC_PORTABILITY_AUDIT.md`.

External files are never copied into Git by these steps. See `docs/EXTERNAL_SOURCE_MANIFEST.md`,
`docs/EXTERNAL_ASSET_MANIFEST.md`, and `docs/RUNTIME_DEPENDENCY_MANIFEST.md`.
