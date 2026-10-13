param([string]$Run = 'results/skill-evolution/v1.3/formal-P11-v1')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$studyRoot = (Resolve-Path -LiteralPath (Join-Path $repoRoot $Run)).Path
if (-not $studyRoot.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar)) { throw 'Study must remain inside this checkout' }
$pythonCpu = Join-Path $repoRoot '.venv/Scripts/python.exe'
$pythonGpu = Join-Path $repoRoot '.venv-train/Scripts/python.exe'
$logRoot = Join-Path $studyRoot 'workflow-logs'
New-Item -ItemType Directory -Path $logRoot -ErrorAction Stop | Out-Null
$statusPath = Join-Path $studyRoot 'workflow-status.json'
function Save-WorkflowStatus([string]$state, [string]$detail) {
    $value = [ordered]@{ state=$state; detail=$detail; utc=[DateTime]::UtcNow.ToString('o'); protocol_hash=$script:protocolHash; cpu_pid=$script:cpuPid; agent_pid=$script:agentPid }
    $temporaryStatus = $statusPath + '.tmp'
    [IO.File]::WriteAllText($temporaryStatus, ($value | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    if ([IO.File]::Exists($statusPath)) { [IO.File]::Replace($temporaryStatus,$statusPath,$statusPath + '.previous') }
    else { [IO.File]::Move($temporaryStatus,$statusPath) }
}
function Start-StudyProcess([string]$python, [string[]]$arguments, [string]$name) {
    return Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot ($name + '.stdout.log')) -RedirectStandardError (Join-Path $logRoot ($name + '.stderr.log'))
}
$protocol = Get-Content -LiteralPath (Join-Path $studyRoot 'protocol.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$script:protocolHash = $protocol.hash
$script:cpuPid = $null; $script:agentPid = $null
try {
    $cpu = Start-StudyProcess $pythonCpu @('-m','scripts.run_boundary_evolution','cpu','--run',$Run) 'cpu'
    $script:cpuPid = $cpu.Id
    $agent = Start-StudyProcess $pythonGpu @('-m','scripts.run_boundary_evolution','agent','--run',$Run) 'agent'
    $script:agentPid = $agent.Id
    Save-WorkflowStatus 'RUNNING' 'CPU and fixed-model Agent run concurrently; independent audits and report follow automatically.'
    Write-Output "Started CPU $($cpu.Id), Agent $($agent.Id) for protocol $($protocol.hash)"
    while (-not ($cpu.HasExited -and $agent.HasExited)) {
        Start-Sleep -Seconds 5
        $cpu.Refresh(); $agent.Refresh()
    }
    $cpu.WaitForExit(); $agent.WaitForExit()
    if ($cpu.ExitCode -ne 0 -or $agent.ExitCode -ne 0) { throw "Worker failed: CPU=$($cpu.ExitCode), Agent=$($agent.ExitCode); retain all evidence and approved fees." }
    $cpuReport = Get-Content -LiteralPath (Join-Path $studyRoot 'cpu/report.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $agentReport = Get-Content -LiteralPath (Join-Path $studyRoot 'agent/report.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $cpuReport.complete -or -not $agentReport.complete) { throw 'Incomplete study; no automatic rerun or budget reset.' }
    Save-WorkflowStatus 'AUDITING' 'Collection complete; full raw-evidence replay is running without new inference.'
    foreach ($entry in @(@('scripts.audit_boundary_trial_cpu','audit-cpu'), @('scripts.audit_boundary_trial_agent','audit-agent'))) {
        $audit = Start-StudyProcess $pythonCpu @('-m',$entry[0],'--run',$Run) $entry[1]
        $audit.WaitForExit()
        if ($audit.ExitCode -ne 0) { throw "Independent audit failed: $($entry[0]); inspect saved logs." }
    }
    & (Join-Path $PSScriptRoot 'summarize_boundary_formal.ps1') -Run $Run
    Save-WorkflowStatus 'AUDITED_COMPLETE' 'CPU and Agent independent replay passed; derived report saved; no production deployment.'
    Write-Output 'Formal engineering study and independent audits complete.'
} catch {
    Save-WorkflowStatus 'FAILED_OR_INCOMPLETE' $_.Exception.Message
    Write-Error $_
    exit 1
}
