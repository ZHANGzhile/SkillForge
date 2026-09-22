param([ValidateSet('Base','SFT','DPO')][string]$Stage='SFT')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:SKILLFORGE_HF_LABEL=$Stage
$trainingPlan=Get-Content configs/training-runs.json -Raw | ConvertFrom-Json
$env:SKILLFORGE_HF_CONFIG=Join-Path $projectRoot $trainingPlan.config
$env:SKILLFORGE_HF_ADAPTER=Join-Path $projectRoot ($trainingPlan.root+'/'+$Stage.ToLower()+'/adapter')
if ($Stage -ne 'Base' -and -not (Test-Path -LiteralPath (Join-Path $env:SKILLFORGE_HF_ADAPTER 'adapter_model.safetensors'))) { throw 'Requested trained adapter is not available yet.' }
& (Join-Path $projectRoot '.venv-train/Scripts/python.exe') -m uvicorn skillforge.hf_server:app --host 127.0.0.1 --port 8002 --workers 1
