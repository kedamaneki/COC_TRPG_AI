# Cross-PC Portability Audit

## Contract

Machine paths are supplied by environment variables or ignored `config/local_paths.json`. Active
Core/Video/runtime code is scanned by `tools/verify_portability.py`; historical receipts and old
reproduction scripts may retain paths as evidence and are not runtime configuration.

## Fresh clone procedure

```powershell
git clone https://github.com/kedamaneki/COC_TRPG_AI.git <new-directory>
cd <new-directory>
git checkout pre-corbitt-final-battle-scenario-audit
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
active runtime hard-codes, registry loading, event range 264..281, and the offset 271 roll without
rendering or changing external files.

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

The machine-readable checks are `docs/CROSS_PC_PORTABILITY_VERIFY.json` and
`docs/PRE_PUSH_AUDIT.json`. GitHub Fresh Clone repeats these checks against the pushed tag.
