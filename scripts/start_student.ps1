$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$ollamaPath = Join-Path $projectRoot '.runtime/ollama/ollama.exe'
if (-not (Test-Path -LiteralPath $ollamaPath)) { throw 'Ollama binary missing from .runtime/ollama' }
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot '.runtime/models'
$env:OLLAMA_CONTEXT_LENGTH = '16384'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_KEEP_ALIVE = '15m'
& $ollamaPath serve
exit $LASTEXITCODE
