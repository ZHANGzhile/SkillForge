$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot '.runtime/models'
$env:OLLAMA_CONTEXT_LENGTH = '16384'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_KEEP_ALIVE = '15m'
try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 } catch {
    Start-Process -FilePath (Join-Path $projectRoot '.runtime/ollama/ollama.exe') -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime/demo-model.stdout.log') -RedirectStandardError (Join-Path $projectRoot '.runtime/demo-model.stderr.log') | Out-Null
}
try { $null = Invoke-WebRequest 'http://127.0.0.1:8080/skill-demo' -UseBasicParsing -TimeoutSec 3 } catch {
    $webProcess = Start-Process -FilePath (Join-Path $projectRoot '.venv/Scripts/python.exe') -ArgumentList '-m','uvicorn','skillforge.api:app','--host','127.0.0.1','--port','8080' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.runtime/demo-web.stdout.log') -RedirectStandardError (Join-Path $projectRoot '.runtime/demo-web.stderr.log') -PassThru
    $webProcess.Id | Set-Content .runtime/demo-web.pid
}
$webReady = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try { $null = Invoke-WebRequest 'http://127.0.0.1:8080/skill-demo' -UseBasicParsing -TimeoutSec 2; $webReady = $true; break } catch { Start-Sleep -Milliseconds 250 }
}
if (-not $webReady) { throw 'Demo website did not start. See .runtime/demo-web.stderr.log' }
Write-Output 'SkillForge: http://127.0.0.1:8080/skill-demo'
