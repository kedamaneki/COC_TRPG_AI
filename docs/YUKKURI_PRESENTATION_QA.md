# Yukkuri Presentation QA

## Gate result

`YUKKURI_PRESENTATION_REGISTRY_QA = PASS`

## Gates

- Registry files present and parseable: PASS
- 16 requested characters present: PASS
- Common subtitle settings match runtime: PASS
- Exact text/border/outline colors retained: PASS
- PC1/PL1, PC2/PL2, KP, SYSTEM resolution: PASS
- SYSTEM character/voice/portrait all null: PASS
- Future candidate auto-use: 0
- Active portrait path/hash verification: PASS
- Missing asset behavior: FAIL_CLOSED
- New asset registration: DETECTED / NOT_APPROVED / LICENSE_REVIEW_REQUIRED
- Changed hash requires new unapproved revision: PASS
- Duplicate content detection: PASS
- Video Agent regression: 221 passed

## Historical immutability

- `video_001_basement_planks`: 65 files / current aggregate `0245d76dafe43858b046dd52a5a5904d4dc237aafa68ca7da9f619b6530ed79d` / access=READ_ONLY / writes=0
- `video_001_basement_planks_v2`: 20 files / current aggregate `9af5c59515a61fea42da08d574a05f4932d145c1858f29bed2d132c23db074b5` / access=READ_ONLY / writes=0
- `video_001_basement_planks_v2_1`: 14 files / current aggregate `bd0136f0241687e02738fb422d865ab20131a4c44e311208f33292c1ec8a0d16` / access=READ_ONLY / writes=0
- V13 Accepted Raw aggregate remains referenced as `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d`.

No video was re-rendered. V13 Accepted source and V1/V2/V2.1 artifacts were read only.
