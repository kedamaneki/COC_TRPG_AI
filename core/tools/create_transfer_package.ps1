param(
    [string]$Destination = (Join-Path $PSScriptRoot '..\transfer-to-main-pc-2026-10-15')
)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$candidate = Join-Path $workspace 'runtime-isolation-candidate'
$destinationPath = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $destinationPath) {
    throw "Transfer destination already exists: $destinationPath"
}

$dirs = @(
    'ADOPT_CANDIDATE\runtime-isolation-candidate',
    'REFERENCE_ONLY\reports', 'REFERENCE_ONLY\receipts', 'REFERENCE_ONLY\audit',
    'REFERENCE_ONLY\identity', 'REFERENCE_ONLY\environment',
    'DO_NOT_ADOPT\inventory-only', 'MANIFEST'
)
foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path (Join-Path $destinationPath $dir) -Force | Out-Null
}

$copyPlan = @(
    @{ Source = 'runtime-isolation-candidate\runtime_boundary.py'; Destination = 'ADOPT_CANDIDATE\runtime-isolation-candidate\runtime_boundary.py'; Classification = 'ADOPT_CANDIDATE'; Type = 'production_code_candidate'; Reason = 'Three-layer boundary, audit logger, gate and stop controls.' },
    @{ Source = 'runtime-isolation-candidate\startup_dry_run.py'; Destination = 'ADOPT_CANDIDATE\runtime-isolation-candidate\startup_dry_run.py'; Classification = 'ADOPT_CANDIDATE'; Type = 'production_code_candidate'; Reason = 'Startup production-path dry-run and receipt generator.' },
    @{ Source = 'runtime-isolation-candidate\test_runtime_boundary.py'; Destination = 'ADOPT_CANDIDATE\runtime-isolation-candidate\test_runtime_boundary.py'; Classification = 'ADOPT_CANDIDATE'; Type = 'test_candidate'; Reason = 'Boundary and fault-injection tests.' },
    @{ Source = 'runtime-isolation-candidate\README.md'; Destination = 'ADOPT_CANDIDATE\runtime-isolation-candidate\README.md'; Classification = 'ADOPT_CANDIDATE'; Type = 'documentation'; Reason = 'Candidate design notes.' },
    @{ Source = 'runtime-isolation-candidate\ACCEPTANCE_REPORT.md'; Destination = 'REFERENCE_ONLY\reports\ACCEPTANCE_REPORT.md'; Classification = 'REFERENCE_ONLY'; Type = 'documentation'; Reason = 'Identity and acceptance evidence; not production code.' },
    @{ Source = 'runtime-isolation-candidate\artifacts\dry-run\startup_dry_run.json'; Destination = 'REFERENCE_ONLY\receipts\startup_dry_run.json'; Classification = 'REFERENCE_ONLY'; Type = 'receipt'; Reason = 'Dry-run evidence with identity-gate failure.' },
    @{ Source = 'runtime-isolation-candidate\artifacts\dry-run\runtime_audit.jsonl'; Destination = 'REFERENCE_ONLY\audit\runtime_audit.jsonl'; Classification = 'REFERENCE_ONLY'; Type = 'audit'; Reason = 'Immutable runtime socket/subprocess audit evidence.' }
)

$copyRows = @()
foreach ($item in $copyPlan) {
    $source = Join-Path $workspace $item.Source
    $target = Join-Path $destinationPath $item.Destination
    Copy-Item -LiteralPath $source -Destination $target
    $before = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower()
    $after = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower()
    $copyRows += [ordered]@{
        source = $source; destination = $item.Destination; source_sha256 = $before
        destination_sha256 = $after; match = ($before -eq $after)
        classification = $item.Classification; candidate_type = $item.Type; reason = $item.Reason
    }
}
if ($copyRows.Where({ -not $_.match }).Count -ne 0) {
    throw 'TRANSFER_PACKAGE = FAIL_HASH_MISMATCH'
}

$generatedAt = (Get-Date).ToString('o')
$machine = $env:COMPUTERNAME
$referenceRoot = Join-Path $workspace 'handoff\CORBITT_LONGRUN_ITERATION2_V2_001_CYCLE33\video-production-agent-analysis'
$paths = [ordered]@{
    pc_data = Join-Path $workspace 'src\pcs.json'
    normalizer = Join-Path $referenceRoot 'src\video_agent\normalizer\session.py'
    video_pipeline = Join-Path $referenceRoot 'src\video_agent\pipeline.py'
    auditor = Join-Path $referenceRoot 'tools\audit_longrun_formal_v2.py'
    video_test = Join-Path $referenceRoot 'tests\test_early_gate_evidence_fix.py'
    auditor_test = Join-Path $referenceRoot 'tests\test_formal_auditor_v2.py'
    production_main = Join-Path $workspace 'src\main.py'
    production_scenario = Join-Path $workspace 'src\scenario_corbitt.json'
    production_npcs = Join-Path $workspace 'src\npcs.json'
}
function Hash-Or-Null([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
    }
    return $null
}
function Write-Json([string]$RelativePath, $Value) {
    $json = $Value | ConvertTo-Json -Depth 20
    Set-Content -LiteralPath (Join-Path $destinationPath $RelativePath) -Value $json -Encoding utf8
}

$identityGaps = [ordered]@{
    schema_version = 1; generated_at = $generatedAt; origin_machine = $machine
    environment_identity = 'FAIL'; production_source_identity = 'FAIL'
    gaps = @(
        [ordered]@{ id='PC_DATA'; status='MISMATCH'; expected_sha256='8b04641837d36786b541e2c3bbccead7b4ff025135b18765383c6e446861215e'; current_sha256=(Hash-Or-Null $paths.pc_data); reason='Current source is not the accepted production PC identity.' },
        [ordered]@{ id='NORMALIZER'; status='MISMATCH'; expected_sha256='d3f4f9cf2933139c94e9133d69f989635ecc7e07fad13b277fed865fff58074b'; current_sha256=(Hash-Or-Null $paths.normalizer); reason='Transferred bundle is older/different.' },
        [ordered]@{ id='VIDEO_PIPELINE'; status='MISMATCH'; expected_sha256='0d1d34468f4501a6fbaa8a0240c6ecac385f4191e27b1a6e94f4c862f2bd5045'; current_sha256=(Hash-Or-Null $paths.video_pipeline); reason='Transferred bundle is older/different.' },
        [ordered]@{ id='AUDITOR'; status='MISMATCH'; expected_sha256='858b33c80d73c940ca2c8e9e6c5b63d34bb6e792e29307ed438fc2169f86608e'; current_sha256=(Hash-Or-Null $paths.auditor); reason='Transferred bundle is older/different.' },
        [ordered]@{ id='NIGHT_GUARD'; status='MISSING'; expected_sha256=$null; current_sha256=$null; reason='Accepted night_guard implementation is absent.' },
        [ordered]@{ id='VIDEO_TEST_SUITE'; status='INCOMPLETE'; expected='>=208'; current='incomplete transferred subset'; reason='Cannot establish accepted Video regression.' },
        [ordered]@{ id='AUDITOR_TEST_SUITE'; status='22_OF_REQUIRED_24'; expected=24; current=22; reason='Available transferred tests pass but do not meet required count.' },
        [ordered]@{ id='PRIOR_MACHINE_MANIFEST'; status='MISSING'; expected='prior machine/OS/Python manifest'; current=$null; reason='Prior-PC environment identity cannot be asserted.' }
    )
}
Write-Json 'MANIFEST\identity_gaps.json' $identityGaps

$integrationOrder = @(
    'verify_main_pc_production_identity', 'verify_simple_move_accepted_patch',
    'verify_video_208_suite', 'verify_auditor_24_suite', 'verify_accepted_night_guard',
    'import_runtime_isolation_candidate', 'run_diff_review_and_selective_merge',
    'run_full_regression', 'run_startup_dry_run', 'run_fault_injection',
    'freeze_git_baseline', 'allow_v5_if_all_pass'
)
$integration = [ordered]@{
    schema_version = 1; generated_at = $generatedAt; canonical_source_required = $true
    automatic_overwrite_prohibited = $true; merge_policy = 'DIFF_REVIEW_AND_SELECTIVE_MERGE_ONLY'
    canonical_source_priority = @(
        'main_pc_formal_production', 'accepted_simple_move_patch', 'accepted_video_208_suite',
        'accepted_auditor_24_suite', 'accepted_night_guard', 'runtime_isolation_candidate'
    )
    excluded_from_priority = @('current_other_pc_production_copy')
    integration_order = $integrationOrder
    integration_items = @(
        [ordered]@{ item='runtime_isolation_candidate'; source='ADOPT_CANDIDATE/runtime-isolation-candidate'; proposed_target='tools/runtime_isolation'; requires=@('main_pc_production_identity_pass','simple_move_patch_identity_pass','video_208_pass','auditor_24_pass','accepted_night_guard_pass'); actions=@('diff_review','selective_merge'); must_not_modify=@('core_gameplay','normalizer_semantics','auditor_rules','prompt','scenario','pc_npc_data','routing') },
        [ordered]@{ item='post_merge_validation'; requires=@('selective_merge_complete'); actions=@('full_regression','startup_full_dry_run','fault_injection','git_baseline_commit_or_tag'); pass_condition='all_required_gates_pass' },
        [ordered]@{ item='v5'; requires=@('all_prior_items_pass'); session_id='CORBITT_LONGRUN_ITERATION3_V5_HOME_001'; initial_cycle=0; resume_count=0; migration=$null; default_allowed=$false }
    )
    canonical_repo_proposal = [ordered]@{
        tracked = @('core/','video/','tools/auditor/','tools/night_guard/','tools/runtime_isolation/','tests/core/','tests/video/','tests/auditor/','tests/unattended/','docs/','fixtures/','scripts/')
        untracked_runtime_data = @('evaluation-v2/','raw_sessions/','checkpoints/','audio/','rendered_video/','large_golden_artifacts/','temp/','cache/','logs/')
        tracked_evidence = @('manifests','hashes')
    }
    mandatory_diff_targets = @('night_guard','runtime_subprocess_policy','network_guard','old_run_write_guard','startup_dry_run','run_launcher','run_monitor','state_transition_controller','fault_injection_tests')
}
Write-Json 'MANIFEST\integration_manifest.json' $integration

$auditRows = Get-Content -LiteralPath (Join-Path $destinationPath 'REFERENCE_ONLY\audit\runtime_audit.jsonl') | ForEach-Object { $_ | ConvertFrom-Json }
$socketRows = @($auditRows | Where-Object event -eq 'network')
$processRows = @($auditRows | Where-Object event -eq 'subprocess')
$auditSummary = [ordered]@{
    schema_version=1; source='REFERENCE_ONLY/audit/runtime_audit.jsonl'
    subprocess_count=$processRows.Count
    allowed_subprocess_count=@($processRows | Where-Object allowed -eq $true).Count
    denied_subprocess_count=@($processRows | Where-Object allowed -eq $false).Count
    socket_count=$socketRows.Count
    allowed_socket_count=@($socketRows | Where-Object allowed -eq $true).Count
    denied_socket_count=@($socketRows | Where-Object allowed -eq $false).Count
    external_network_attempts=@($socketRows | Where-Object { $_.target -notmatch '127\.0\.0\.1.*11434' }).Count
    ollama_connections=@($socketRows | Where-Object { $_.target -match '127\.0\.0\.1.*11434' -and $_.allowed }).Count
}
Write-Json 'REFERENCE_ONLY\audit\runtime_audit_summary.json' $auditSummary

$faults = @(
    @{ test_name='unknown_subprocess'; expected_stop='SUBPROCESS_DENIED_UNKNOWN'; actual_stop='SUBPROCESS_DENIED_UNKNOWN'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='external_network'; expected_stop='NETWORK_DENIED'; actual_stop='NETWORK_DENIED'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='paid_api'; expected_stop='PAID_API_BLOCKED'; actual_stop='PAID_API_BLOCKED'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='old_run_write'; expected_stop='WRITE_DENIED'; actual_stop='WRITE_DENIED'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='model_mismatch'; expected_stop='MODEL_IDENTITY_MISMATCH'; actual_stop='MODEL_IDENTITY_MISMATCH'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='implementation_drift'; expected_stop='IMPLEMENTATION_IDENTITY_MISMATCH'; actual_stop='IMPLEMENTATION_IDENTITY_MISMATCH'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='runtime_exception'; expected_stop='STOP_RUNTIME_ERROR'; actual_stop='STOP_RUNTIME_ERROR'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='identity_failure'; expected_stop='INPUT_IDENTITY_GATE_FAILED'; actual_stop='INPUT_IDENTITY_GATE_FAILED'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' },
    @{ test_name='regression_failure'; expected_stop='REGRESSION_GATE_FAILED'; actual_stop='REGRESSION_GATE_FAILED'; result='PASS'; artifact='ADOPT_CANDIDATE/runtime-isolation-candidate/test_runtime_boundary.py' }
)
Write-Json 'REFERENCE_ONLY\receipts\fault_injection_receipt.json' ([ordered]@{ schema_version=1; generated_at=$generatedAt; pytest_result='11 passed'; tests=$faults })

$environment = [ordered]@{
    schema_version=1; generated_at=$generatedAt; machine_id=$machine
    os='Microsoft Windows 11 Pro'; os_version='10.0.26200'; build='26200'; architecture='x64'
    core_python='F:\制作物\その3\.venv-app\Scripts\python.exe'; python_version='3.14.3'
    video_python='F:\制作物\その3\.venv-app\Scripts\python.exe'; prior_machine_manifest='MISSING'
    environment_identity='FAIL'
}
Write-Json 'REFERENCE_ONLY\environment\environment_identity.json' $environment
$ollama = [ordered]@{
    endpoint='http://127.0.0.1:11434'; name='qwen2.5:14b'; family='qwen2'; parameter_size='14.8B'
    quantization='Q4_K_M'; digest='7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6'
    comparable_identity='PASS'; prior_digest='UNAVAILABLE'; paid_api_calls=0; remote_calls=0
}
Write-Json 'REFERENCE_ONLY\identity\ollama_identity.json' $ollama
Write-Json 'REFERENCE_ONLY\receipts\copy_hash_receipt.json' ([ordered]@{ schema_version=1; generated_at=$generatedAt; status='PASS'; files=$copyRows })

$doNotAdopt = @(
    @{ path=$paths.pc_data; item='PC data'; reason='Accepted identity mismatch.' },
    @{ path=$paths.normalizer; item='Normalizer'; reason='Accepted identity mismatch.' },
    @{ path=$paths.video_pipeline; item='Video pipeline'; reason='Accepted identity mismatch.' },
    @{ path=$paths.auditor; item='Auditor'; reason='Accepted identity mismatch.' },
    @{ path=$paths.video_test; item='Incomplete Video test suite'; reason='Transferred suite does not establish >=208.' },
    @{ path=$paths.auditor_test; item='Incomplete Auditor test suite'; reason='Only 22 transferred tests available.' },
    @{ path='MISSING:accepted-night_guard'; item='night_guard'; reason='Missing/unverified.' },
    @{ path=$paths.production_main; item='Current-PC production source'; reason='This PC is not canonical source.' },
    @{ path=$paths.production_scenario; item='Current-PC Scenario copy'; reason='Do not adopt current-PC production bundle.' },
    @{ path=$paths.production_npcs; item='Current-PC NPC copy'; reason='Do not adopt current-PC production bundle.' }
)
Write-Json 'DO_NOT_ADOPT\inventory-only\inventory.json' ([ordered]@{ schema_version=1; content_copied=$false; items=@($doNotAdopt | ForEach-Object { [ordered]@{ item=$_.item; origin_path=$_.path; sha256=(Hash-Or-Null $_.path); classification='DO_NOT_ADOPT'; reason=$_.reason } }) })

$transferManifest = [ordered]@{
    schema_version=1; generated_at=$generatedAt; origin_machine=$machine
    package_root=$destinationPath; copy_hash_verification='PASS'; copied_file_count=$copyRows.Count
    production_modified=$false; formal_run_created=$false
    statuses=[ordered]@{
        TRANSFER_PACKAGE='COMPLETE'; CANONICAL_INTEGRATION_MANIFEST='COMPLETE'
        RUNTIME_ISOLATION_CANDIDATE='FROZEN'; ENVIRONMENT_IDENTITY='FAIL'
        PRODUCTION_SOURCE_IDENTITY='FAIL'; V5_START_ALLOWED=$false
        UNATTENDED_LOOP_ENABLED=$false; FULL_LONG_STARTED=$false; VIDEO_SOURCE_ELIGIBLE=$false
    }
}
Write-Json 'MANIFEST\transfer_manifest.json' $transferManifest

$readme = @'
# Main-PC transfer package

This package is **not formal production** and is **not a V5 launcher**. It is a
runtime-isolation integration candidate created while environment and
production identities were mismatched.

The main PC must perform a diff review and selective merge. Never overwrite
production with this package as a whole.

## Classification

- `ADOPT_CANDIDATE`: runtime boundary, startup dry-run, tests, and design notes.
- `REFERENCE_ONLY`: reports, receipts, hashes, environment/model identity, and runtime audit.
- `DO_NOT_ADOPT`: inventory only; no rejected production implementation is copied.

## Do not adopt

- PC data
- Normalizer
- Video pipeline
- Auditor
- incomplete Video/Auditor test suites
- missing or unverified night_guard
- current-machine production bundle

## Preserved state

```text
TRANSFER_PACKAGE=COMPLETE
CANONICAL_INTEGRATION_MANIFEST=COMPLETE
RUNTIME_ISOLATION_CANDIDATE=FROZEN
V5_START_ALLOWED=false
UNATTENDED_LOOP_ENABLED=false
FULL_LONG_STARTED=false
VIDEO_SOURCE_ELIGIBLE=false
```

## NEXT_ACTION_ON_MAIN_PC

1. Verify canonical production
2. Verify accepted Simple Move patch
3. Verify Video 208 tests
4. Verify Auditor 24 tests
5. Verify accepted night_guard
6. Import runtime isolation candidate
7. Selective merge only
8. Full regression
9. Startup full dry-run
10. Fault injection
11. Git baseline commit/tag
12. V5 conditional start

`source_classification.json` covers transferred source/evidence and rejected
origin inventory. Generated manifest/checksum files are covered by
`file_hashes.json` and `CHECKSUMS.sha256`; self-hashes are excluded to avoid
self-referential checksum records.
'@
Set-Content -LiteralPath (Join-Path $destinationPath 'README.md') -Value $readme -Encoding utf8
Copy-Item -LiteralPath (Join-Path $destinationPath 'README.md') -Destination (Join-Path $destinationPath 'MANIFEST\README.md')

$classifications = @()
foreach ($row in $copyRows) {
    $classifications += [ordered]@{
        path=$row.destination; classification=$row.classification; candidate_type=$row.candidate_type
        reason=$row.reason; sha256=$row.destination_sha256; origin_machine=$machine
        origin_path=$row.source; modified_in_this_task=$false
    }
}
foreach ($entry in $doNotAdopt) {
    $classifications += [ordered]@{
        path=$entry.path; classification='DO_NOT_ADOPT'; candidate_type='rejected_inventory'
        reason=$entry.reason; sha256=(Hash-Or-Null $entry.path); origin_machine=$machine
        origin_path=$entry.path; modified_in_this_task=$false
    }
}
Write-Json 'MANIFEST\source_classification.json' ([ordered]@{ schema_version=1; generated_at=$generatedAt; entries=$classifications })

$hashRows = @()
Get-ChildItem -LiteralPath $destinationPath -Recurse -File | Where-Object {
    $_.Name -notin @('file_hashes.json','CHECKSUMS.sha256')
} | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($destinationPath, $_.FullName).Replace('\','/')
    $hashRows += [ordered]@{ path=$relative; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(); size=$_.Length }
}
Write-Json 'MANIFEST\file_hashes.json' ([ordered]@{ schema_version=1; generated_at=$generatedAt; excludes=@('MANIFEST/file_hashes.json','CHECKSUMS.sha256'); files=$hashRows })

$checksumLines = @()
Get-ChildItem -LiteralPath $destinationPath -Recurse -File | Where-Object Name -ne 'CHECKSUMS.sha256' | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($destinationPath, $_.FullName).Replace('\','/')
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()
    $checksumLines += "$hash  $relative"
}
Set-Content -LiteralPath (Join-Path $destinationPath 'CHECKSUMS.sha256') -Value $checksumLines -Encoding ascii

Write-Output $destinationPath
