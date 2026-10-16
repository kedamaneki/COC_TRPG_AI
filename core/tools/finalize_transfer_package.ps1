param([string]$Package = (Join-Path $PSScriptRoot '..\transfer-to-main-pc-2026-10-15'))
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $Package).Path
$machine = $env:COMPUTERNAME
$generatedAt = (Get-Date).ToString('o')
$classificationPath = Join-Path $root 'MANIFEST\source_classification.json'
$old = Get-Content -LiteralPath $classificationPath | ConvertFrom-Json
$externalRejected = @($old.entries | Where-Object classification -eq 'DO_NOT_ADOPT')
$receipt = Get-Content -LiteralPath (Join-Path $root 'REFERENCE_ONLY\receipts\copy_hash_receipt.json') | ConvertFrom-Json
$copiedByDestination = @{}
foreach ($item in $receipt.files) { $copiedByDestination[$item.destination.Replace('\','/')] = $item }

$entries = @()
Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $_.Name -notin @('source_classification.json','file_hashes.json','CHECKSUMS.sha256')
} | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($root, $_.FullName).Replace('\','/')
    $copied = $copiedByDestination[$relative]
    if ($copied) {
        $classification = $copied.classification
        $candidateType = $copied.candidate_type
        $reason = $copied.reason
        $origin = $copied.source
        $modified = $false
    } else {
        $classification = 'REFERENCE_ONLY'
        $candidateType = if ($relative -like 'MANIFEST/*') { 'manifest' } elseif ($relative -like '*.md') { 'documentation' } else { 'receipt' }
        $reason = 'Generated transfer metadata or evidence; not direct production code.'
        $origin = 'GENERATED_THIS_TASK'
        $modified = $true
    }
    $entries += [ordered]@{
        path=$relative; classification=$classification; candidate_type=$candidateType
        reason=$reason; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()
        origin_machine=$machine; origin_path=$origin; modified_in_this_task=$modified
    }
}
foreach ($entry in $externalRejected) {
    $entries += [ordered]@{
        path=$entry.path; classification='DO_NOT_ADOPT'; candidate_type=$entry.candidate_type
        reason=$entry.reason; sha256=$entry.sha256; origin_machine=$entry.origin_machine
        origin_path=$entry.origin_path; modified_in_this_task=$false
    }
}
@{ schema_version=1; generated_at=$generatedAt; scope_note='All package files except self-referential source_classification.json, file_hashes.json, and CHECKSUMS.sha256, plus all rejected origin inventory.'; entries=$entries } |
    ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $classificationPath -Encoding utf8

$hashRows = @()
Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $_.Name -notin @('file_hashes.json','CHECKSUMS.sha256')
} | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($root, $_.FullName).Replace('\','/')
    $hashRows += [ordered]@{ path=$relative; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(); size=$_.Length }
}
@{ schema_version=1; generated_at=$generatedAt; excludes=@('MANIFEST/file_hashes.json','CHECKSUMS.sha256'); files=$hashRows } |
    ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $root 'MANIFEST\file_hashes.json') -Encoding utf8

$lines = @()
Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object Name -ne 'CHECKSUMS.sha256' | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($root, $_.FullName).Replace('\','/')
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()
    $lines += "$hash  $relative"
}
Set-Content -LiteralPath (Join-Path $root 'CHECKSUMS.sha256') -Value $lines -Encoding ascii
