param([string]$Run = 'results/skill-evolution/v1.3/formal-P11-v1')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$studyRoot = (Resolve-Path -LiteralPath (Join-Path $repoRoot $Run)).Path
if (-not $studyRoot.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar)) { throw 'Study outside checkout' }
$logRoot = Join-Path $studyRoot 'workflow-continuation-v2-logs'
New-Item -ItemType Directory -Path $logRoot -ErrorAction Stop | Out-Null
$p = Get-Content -LiteralPath (Join-Path $studyRoot 'protocol.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$statusPath = Join-Path $studyRoot 'workflow-status.json'
function Save-ContinuationStatus([string]$state,[string]$detail) {
    $v=[ordered]@{state=$state;detail=$detail;protocol_hash=$p.hash;utc=[DateTime]::UtcNow.ToString('o');agent_pid=$script:agentPid;cpu_audit_pid=$script:auditPid;continuation='auditor-only-v2'}
    [IO.File]::WriteAllText($statusPath+'.tmp',($v|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    [IO.File]::Replace($statusPath+'.tmp',$statusPath,$statusPath+'.previous')
}
function Start-ContinuationWorker([string]$python,[string[]]$arguments,[string]$name) {
    return Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot ($name+'.stdout.log')) -RedirectStandardError (Join-Path $logRoot ($name+'.stderr.log'))
}
$pythonCpu=Join-Path $repoRoot '.venv/Scripts/python.exe';$pythonGpu=Join-Path $repoRoot '.venv-train/Scripts/python.exe'
$script:agentPid=$null;$script:auditPid=$null
try {
    $cpuReport=Get-Content -LiteralPath (Join-Path $studyRoot 'cpu/report.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $cpuReport.complete) { throw 'CPU collection must complete; do not restart it' }
    $audit=Start-ContinuationWorker $pythonCpu @('-m','scripts.audit_boundary_trial_cpu','--run',$Run) 'audit-cpu'
    $script:auditPid=$audit.Id
    $agent=Start-ContinuationWorker $pythonGpu @('-m','scripts.continue_boundary_trial_agent','--run',$Run) 'agent'
    $script:agentPid=$agent.Id
    Save-ContinuationStatus 'RUNNING' 'Auditor-only continuation: reuse exact completed arms/fees and continue missing tasks; CPU full audit runs in parallel.'
    Write-Output "Continuation Agent $($agent.Id), CPU audit $($audit.Id); protocol unchanged $($p.hash)"
    while (-not ($agent.HasExited -and $audit.HasExited)) { Start-Sleep -Seconds 5; $agent.Refresh(); $audit.Refresh() }
    $agent.WaitForExit();$audit.WaitForExit()
    if ($agent.ExitCode -ne 0 -or $audit.ExitCode -ne 0) { throw "Continuation worker failed: Agent=$($agent.ExitCode), CPU audit=$($audit.ExitCode)" }
    $result=Get-Content -LiteralPath (Join-Path $studyRoot 'agent/continuation-v2/report.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $result.complete) { throw 'Continuation incomplete; retain original and continuation reports without automatic replay' }
    Save-ContinuationStatus 'AUDITING' 'Full real Agent raw-evidence replay with versioned invalid-Action audit support.'
    $finalAudit=Start-ContinuationWorker $pythonCpu @('-m','scripts.audit_boundary_trial_agent_v2','--run',$Run) 'audit-agent'
    $finalAudit.WaitForExit()
    if ($finalAudit.ExitCode -ne 0) { throw 'Final independent Agent continuation audit failed' }
    & (Join-Path $PSScriptRoot 'summarize_boundary_formal.ps1') -Run $Run -AgentReportName 'agent/continuation-v2/report.json' -AgentAuditName 'agent/continuation-v2/independent-audit.json'
    Save-ContinuationStatus 'AUDITED_COMPLETE' 'Frozen study plus auditor-only continuation independently audited; derived report saved.'
} catch { Save-ContinuationStatus 'FAILED_OR_INCOMPLETE' $_.Exception.Message; Write-Error $_; exit 1 }
