param([ValidateSet('Base','SFT','DPO')][string]$Stage='SFT')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$plan=Get-Content configs/training-runs.json -Raw | ConvertFrom-Json
$pipeline=Get-Content .runtime/training-pipeline.json -Raw | ConvertFrom-Json
if ($pipeline.stage -ne 'completed') { throw 'Complete the serial GPU evaluation before deploying another GPU service.' }
$finish=Get-Content .runtime/research-finish.json -Raw | ConvertFrom-Json
if ($finish.stage -ne 'completed') { throw 'The predeclared stability evaluation and report are not complete.' }
& (Join-Path $projectRoot '.venv/Scripts/python.exe') -m scripts.package_project --check-only
if ($LASTEXITCODE -ne 0) { throw 'Release evidence audit failed; inspect results/release-readiness.json.' }
$expectedModel='Qwen3-4B-NF4-'+$Stage
$expectedHash=$null
if ($Stage -ne 'Base') {
    $adapterResult=Get-Content (Join-Path $plan.root ($Stage.ToLower()+'/result.json')) -Raw | ConvertFrom-Json
    $expectedHash=$adapterResult.adapter_hash
}
function Stop-OwnedWeb {
    $pidFile=Join-Path $projectRoot '.runtime/project-web.pid'
    if (-not (Test-Path -LiteralPath $pidFile)) { throw 'Existing workbench has no owned PID record; inspect its owner.' }
    $webOwnerId=[int](Get-Content -LiteralPath $pidFile)
    $webOwner=Get-CimInstance Win32_Process -Filter "ProcessId=$webOwnerId"
    if (-not $webOwner) { return }
    if ($webOwner.CommandLine -notmatch 'uvicorn\s+skillforge\.api:app') { throw 'PID no longer belongs to the workbench.' }
    $webChildren=Get-CimInstance Win32_Process -Filter "ParentProcessId=$webOwnerId AND Name='python.exe'"
    foreach ($child in $webChildren) {
        if ($child.CommandLine -notmatch 'uvicorn\s+skillforge\.api:app') { throw 'Unexpected Python child; inspect before stopping.' }
    }
    foreach ($child in $webChildren) { Stop-Process -Id $child.ProcessId -ErrorAction Stop }
    Stop-Process -Id $webOwnerId -ErrorAction SilentlyContinue
}
$studentHealth=$null
try { $studentHealth=Invoke-RestMethod 'http://127.0.0.1:8002/health' -TimeoutSec 3 } catch { }
if ($studentHealth) {
    if ($studentHealth.model -ne $expectedModel -or $studentHealth.settings.adapter_sha256 -ne $expectedHash) {
        throw 'Port 8002 already serves a different model; inspect its owner before replacing it.'
    }
} else {
    if (Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8002 is occupied by an unverified service.' }
    $env:SKILLFORGE_HF_LABEL=$Stage
    $env:SKILLFORGE_HF_CONFIG=Join-Path $projectRoot $plan.config
    $env:SKILLFORGE_HF_ADAPTER=Join-Path $projectRoot ($plan.root+'/'+$Stage.ToLower()+'/adapter')
    $studentProcess=Start-Process -FilePath (Join-Path $projectRoot '.venv-train/Scripts/python.exe') -ArgumentList '-m','uvicorn','skillforge.hf_server:app','--host','127.0.0.1','--port','8002','--workers','1' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime/trained-student.stdout.log') -RedirectStandardError (Join-Path $projectRoot '.runtime/trained-student.stderr.log') -PassThru
    $studentProcess.Id | Set-Content .runtime/trained-student.pid
    for ($attempt=0; $attempt -lt 240; $attempt++) {
        try { $studentHealth=Invoke-RestMethod 'http://127.0.0.1:8002/health' -TimeoutSec 2; break } catch { }
        if ($studentProcess.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $studentHealth -or $studentHealth.model -ne $expectedModel -or $studentHealth.settings.adapter_sha256 -ne $expectedHash) { throw 'Trained Student startup or identity verification failed; inspect its logs.' }
}
# Clear conflicting process-local overrides; the checked-in profile defines the deployment.
Remove-Item Env:SKILLFORGE_MODEL_URL -ErrorAction SilentlyContinue
Remove-Item Env:SKILLFORGE_MODEL_NAME -ErrorAction SilentlyContinue
$profile='configs/model.hf-'+$Stage.ToLower()+'.json'
$env:SKILLFORGE_MODEL_CONFIG=Join-Path $projectRoot $profile
$webHealth=$null
try { $webHealth=Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 3 } catch { }
if ($webHealth -and $webHealth.model -ne $expectedModel) {
    $historyOffset=0
    do {
        $running=Invoke-RestMethod ("http://127.0.0.1:8080/api/v1/runs?limit=100&offset=$historyOffset") -TimeoutSec 3
        if (@($running.runs | Where-Object { $_.status -in @('running','queued') }).Count -gt 0) { throw 'Workbench still has live jobs; preserve them before switching models.' }
        $historyOffset+=100
    } while ($running.runs.Count -eq 100)
    Stop-OwnedWeb
}
& (Join-Path $PSScriptRoot 'start_project.ps1') -DashboardOnly
$webHealth=Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 5
if ($webHealth.model -ne $expectedModel -or -not $webHealth.worker_alive) { throw 'Workbench is not bound to the selected trained Student.' }
$selectionDescription='Explicit manual stage; no automatic choice from test scores'
$selectionPath=Join-Path $plan.evaluation_root 'deployment-selection.json'
if (Test-Path -LiteralPath $selectionPath) {
    $selected=Get-Content -LiteralPath $selectionPath -Raw | ConvertFrom-Json
    if ($selected.label -eq $Stage) { $selectionDescription='Audited validation-only policy; policy SHA256 '+$selected.policy_sha256 }
}
$deployment=@{stage=$Stage;model=$expectedModel;profile=$profile;adapter_sha256=$expectedHash;at=(Get-Date -Format o);selection=$selectionDescription;end_to_end_verified=$false}
$deployment | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'configs/deployment.local.json' -Encoding UTF8
$deployment | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'results/workbench-acceptance/trained-deployment.json' -Encoding UTF8
Write-Output 'Trained Student deployed: http://127.0.0.1:8080 ; real end-to-end acceptance still required.'
