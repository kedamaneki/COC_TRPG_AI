# Git Checkpoint Report

Checkpoint purpose: preserve the production state immediately before the Corbitt final-battle
source-versus-adaptation audit.

- Remote: `https://github.com/kedamaneki/COC_TRPG_AI.git`
- Branch: `main`
- Commit message: `checkpoint: video pipeline before Corbitt scenario audit`
- Annotated tag: `pre-corbitt-final-battle-scenario-audit`
- Force push: prohibited
- V13 Raw and historical video artifacts: external/read-only; never staged

Pre-push audit result:

- 619 candidate files / 69,237,036 bytes
- files larger than 50 MiB: 0
- video/audio/archive/executable candidates: 0
- recognized secret findings: 0
- missing candidate files: 0

The remote contains an older unrelated history. It is retained through a non-force merge parent;
the canonical production tree remains authoritative. The final SHA and remote verification are
reported after push and GitHub Fresh Clone validation.

The requested annotated tag preserves the exact pre-audit checkpoint. A first Fresh Clone exposed
one portability defect after the tag was published: the Corbitt Scenario builder depended on an
ignored local staging cache. The same 16 source files were copied into the repository with an
aggregate SHA-256 contract, and the fix is delivered as a follow-up commit on `main` without moving
or replacing the checkpoint tag.
