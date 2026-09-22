$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$trainingPython = Join-Path $projectRoot '.venv-train/Scripts/python.exe'
$statusPath = Join-Path $projectRoot '.runtime/training-bootstrap.json'
$lockPath = Join-Path $projectRoot '.runtime/training-bootstrap.lock'
$bootstrapLock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
function Write-TrainingStatus([string]$stage, [string]$message) {
    @{stage=$stage; message=$message; at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -Encoding utf8 ($statusPath+'.tmp')
    Move-Item -LiteralPath ($statusPath+'.tmp') -Destination $statusPath -Force
}
try {
    $wheel = Join-Path $projectRoot '.runtime/wheels/torch-2.10.0+cu128-cp310-cp310-win_amd64.whl'
    Write-TrainingStatus 'waiting_for_torch' 'Waiting for the verified official CUDA wheel.'
    while (-not (Test-Path -LiteralPath $wheel)) { Start-Sleep -Seconds 15 }
    Write-TrainingStatus 'installing_torch' 'Installing the verified local wheel and PyPI dependencies.'
    & $trainingPython -m pip install --index-url https://pypi.org/simple $wheel
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }
    Write-TrainingStatus 'installing_training_dependencies' 'Installing pinned training packages in the isolated venv.'
    & $trainingPython -m pip install --index-url https://pypi.org/simple -r requirements-training.txt -e .
    if ($LASTEXITCODE -ne 0) { throw 'Training dependencies installation failed.' }
    & $trainingPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Training dependency consistency check failed.' }
    & $trainingPython -m pip freeze | ForEach-Object { if ($_ -like '-e *') { '-e .' } else { $_ } } | Set-Content -Encoding utf8 requirements-training-lock.txt
    Write-TrainingStatus 'gpu_check' 'Checking CUDA NF4 forward and backward.'
    & $trainingPython scripts/check_training_gpu.py
    if ($LASTEXITCODE -ne 0) { throw 'GPU NF4 compatibility check failed.' }
    Write-TrainingStatus 'loss_tests' 'Checking completion likelihood and DPO preference gradients.'
    & $trainingPython -m pytest tests/test_training_math.py tests/test_supervision.py -q
    if ($LASTEXITCODE -ne 0) { throw 'Training loss/data tests failed.' }
    Write-TrainingStatus 'ready' 'Training packages and GPU/loss checks passed.'
} catch {
    Write-TrainingStatus 'failed' $_.Exception.Message
    throw
} finally {
    $bootstrapLock.Dispose()
}
