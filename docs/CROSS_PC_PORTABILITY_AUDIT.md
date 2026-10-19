# Cross-PC Portability Audit

## Contract

Machine paths are supplied by environment variables or ignored `config/local_paths.json`. Active
Core/Video/runtime code is scanned by `tools/verify_portability.py`; historical receipts and old
reproduction scripts may retain paths as evidence and are not runtime configuration.

## Fresh clone procedure

```powershell
git clone https://github.com/kedamaneki/COC_TRPG_AI.git <new-directory>
cd <new-directory>
git checkout main
py -3.12 -m venv .venv-portability
.\.venv-portability\Scripts\python -m pip install -r requirements-portability.txt
.\.venv-portability\Scripts\python -m pip install -e video
```

Set the variables documented in `.env.example`, then run:

```powershell
python tools/verify_portability.py
python -m pytest core/src -q
python -m pytest video/tests -q
python -c "import sys,pytest,pathlib; r=pathlib.Path.cwd(); sys.path[:0]=[str(r),str(r/'tools'/'night_guard'),str(r/'tools'/'runtime_isolation'),str(r/'video'/'src'),str(r/'core'/'src')]; raise SystemExit(pytest.main(['tests','-q']))"
python tools/scan_video_assets.py "$env:VIDEO_ASSET_ROOT" --registry video/config/asset_registry.json --dry-run
```

The portability verifier checks V13 source count/hash, required asset hashes, native runtime paths,
the packaged Corbitt Scenario source, active runtime hard-codes, registry loading, event range
264..281, and the offset 271 roll without rendering or changing external files.

The Video suite recreates its small ignored WAV and existence-only preview fixtures at test startup.
Accepted videos and synthesized audio remain excluded from Git; the generated files are test data
only and are covered by `.gitignore`.

## Pre-push result

The canonical checkout passed:

- Core: 626 passed, 26 subtests passed
- Video Agent: 293 passed
- Auditor/night/runtime: 64 passed
- V13 source: 373 files; aggregate SHA-256
  `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d`
- Required external/repository assets: hash verified
- Active runtime absolute paths: 0
- Video pipeline dry-run: PASS; rendering was not executed
- Full asset scan: 32,158 unchanged, 0 new, 0 changed hash; one optional unapproved registry
  entry (`nc86017`) is absent and is not referenced by the accepted pipeline

The first GitHub Fresh Clone correctly exposed an ignored `.local` Corbitt Scenario dependency.
The canonical 16-file Scenario source is now packaged under `core/scenario_sources`, verified by
`manifests/CORBITT_SCENARIO_SOURCE.json`, and no ignored staging cache is required.

The same clone also exposed historical Video tests that depended on ignored generated media. The
suite now creates deterministic local fixtures at test startup, keeping generated MP4/WAV content
out of version control while preserving the full 293-test baseline.

The machine-readable checks are `docs/CROSS_PC_PORTABILITY_VERIFY.json` and
`docs/PRE_PUSH_AUDIT.json`. The final GitHub Fresh Clone repeats these checks against the updated
`main`; the annotated pre-audit tag remains an immutable checkpoint from before this follow-up fix.

## Final GitHub Fresh Clone result

- Source commit tested: `243ff228f6b9c4431b05793c325226cfbd7e7445`
- Clone root: `F:\制作物\その3\corbitt-trpg-system-portability-verified-20261020`
- Core: 626 passed, 26 subtests passed; 0 failed/error/skipped
- Video Agent: 293 passed; 0 failed/error/skipped
- Auditor/night/runtime: 64 passed; 0 failed/error/skipped
- Asset scan: 32,158 unchanged; 0 new; 0 changed hash; 1 optional unapproved missing
- V13 source: 373 files and expected aggregate SHA-256 matched
- Packaged Scenario: 16 files and aggregate SHA-256 matched
- Runtime tools and font: PASS
- Active runtime hard-coded paths: 0
- Video pipeline dry-run: PASS; no rendering performed
- Fresh Clone worktree after checks: clean

Machine-readable Fresh Clone receipt: `docs/CROSS_PC_PORTABILITY_FRESH_CLONE.json`.

`CROSS_PC_PORTABILITY_AUDIT=PASS`

`READY_FOR_SECOND_PC=true`
