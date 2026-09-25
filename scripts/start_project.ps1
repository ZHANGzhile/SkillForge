param([switch]$DashboardOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$gpuReserved=$false
if (Test-Path -LiteralPath '.runtime/training-pipeline.json') {
    $trainingState=Get-Content .runtime/training-pipeline.json -Raw | ConvertFrom-Json
    $nowSeconds=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $gpuReserved=($trainingState.stage -notin @('completed','failed') -and ($nowSeconds-$trainingState.at) -lt 120)
}
if (-not $DashboardOnly -and -not $gpuReserved -and (Test-Path -LiteralPath 'configs/deployment.local.json')) {
    $deployment=Get-Content configs/deployment.local.json -Raw | ConvertFrom-Json
    if ($deployment.recovery) {
        & (Join-Path $PSScriptRoot 'deploy_trained_project.ps1') -Stage $deployment.stage -Recovery
    } else {
        & (Join-Path $PSScriptRoot 'deploy_trained_project.ps1') -Stage $deployment.stage
    }
    return
}
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot '.runtime/models'
$env:OLLAMA_CONTEXT_LENGTH = '16384'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_KEEP_ALIVE = '15m'
if (-not $DashboardOnly -and -not $gpuReserved) {
try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 } catch {
    Start-Process -FilePath (Join-Path $projectRoot '.runtime/ollama/ollama.exe') -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime/project-model.stdout.log') -RedirectStandardError (Join-Path $projectRoot '.runtime/project-model.stderr.log') | Out-Null
}
}
$webReady = $false
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 3
    $webReady = $health.worker_alive -eq $true
} catch { }
if (-not $webReady) {
    $webProcess = Start-Process -FilePath (Join-Path $projectRoot '.venv/Scripts/python.exe') -ArgumentList '-m','uvicorn','skillforge.api:app','--host','127.0.0.1','--port','8080' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime/project-web.stdout.log') -RedirectStandardError (Join-Path $projectRoot '.runtime/project-web.stderr.log') -PassThru
    $webProcess.Id | Set-Content .runtime/project-web.pid
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 2
            if ($health.worker_alive) { $webReady = $true; break }
        } catch { }
        if ($webProcess.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
}
if (-not $webReady) { throw 'Workbench did not start. Inspect .runtime/project-web.stderr.log; run one API worker only.' }
Write-Output 'SkillForge Workbench: http://127.0.0.1:8080'
