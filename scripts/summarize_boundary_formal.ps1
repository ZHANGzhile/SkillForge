param([string]$Run = 'results/skill-evolution/v1.3/formal-P11-v1', [string]$AgentReportName = 'agent/report.json', [string]$AgentAuditName = 'agent/independent-audit.json')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$studyRoot = (Resolve-Path -LiteralPath (Join-Path $repoRoot $Run)).Path
function Read-Artifact([string]$name) { return Get-Content -LiteralPath (Join-Path $studyRoot $name) -Raw -Encoding UTF8 | ConvertFrom-Json }
$p=Read-Artifact 'protocol.json'; $cpu=Read-Artifact 'cpu/report.json'; $agent=Read-Artifact $AgentReportName
$ca=Read-Artifact 'cpu/independent-audit.json'; $aa=Read-Artifact $AgentAuditName
if (-not $ca.passed -or -not $aa.passed -or $ca.report_hash -ne $cpu.hash -or $aa.report_hash -ne $agent.hash) { throw 'Matching independent audits required for report generation' }
$lines = [Collections.Generic.List[string]]::new()
$lines.Add('# Stage 2 连续 Boundary / Agent 工程规模正式报告')
$lines.Add('')
$lines.Add("Agent 最终证据：``$AgentReportName``；最终审计：``$AgentAuditName``。")
if ($AgentReportName -ne 'agent/report.json') {
    $lines.Add('原 agent/report.json 保留为首次审计中断报告。版本化审计扩展重放模型真实无效 Action，仍计 model_error / EOC 失败及实际 tokens。恢复复用十个已完成物理臂，未重新推理或写入，未改模型、Runtime、算法、任务、门槛或预算；continuation-v2/manifest.json 绑定新审计源码、原费用和全部旧文件。')
}

$lines.Add('')
$lines.Add('此报告从已完成且独立审计通过的固定协议生成。工程规模：真实 Agent 为 2 worlds × 2 independent sequence seeds × 3 stages；CPU 另含预声明的三谓词结构外推规则。不是研究功效充足的统计显著性实验。')
$lines.Add('')
$lines.Add('规则阶段为改变、不变、恢复原规则。模型 main-v3、程序、搜索/加载、Runtime 和门槛固定；没有 SFT/DPO/RL、全局服务切换或生产部署。新 acquisition 在开发消融中未入选，没有添加 ImprovedActive 冒充新方法。')
$lines.Add('')
$lines.Add('| CPU 方法 | 计划单元 | budget 内原始收敛率 | RMQ cap=20 |')
$lines.Add('|---|---:|---:|---:|')
foreach ($m in $p.cpu_methods) {
    $metric=$cpu.methods.$m
    $lines.Add("| $m | $($metric.runs) | $([Math]::Round($metric.convergence_rate_within_budget,4)) | $([Math]::Round($metric.restricted_mean_queries_to_convergence,4)) |")
}
$lines.Add('')
$lines.Add('以上收敛指标以全部冻结阶段为分母，含未触发/无需更新阶段，不等于条件探索效率；逐运行的 trigger、原始 posterior、候选与有效 fallback、FA/FB、UNKNOWN、stable 退步均在 CPU 原始报告。CPU Boundary-only 父链不能当作真实 Agent 激活链。')
$lines.Add('')
$lines.Add('| 真实 Agent test 方法 | 逻辑 task 臂 | EOC | 自主 / Runtime 辅助 | 尝试 / 实际违规 | 逻辑 tokens |')
$lines.Add('|---|---:|---:|---:|---:|---:|')
foreach ($method in $p.agent_methods) {
    $rows=@($agent.logical_arms | Where-Object { $_.partition -eq 'test' -and $_.role -eq $method })
    $eoc=@($rows | Where-Object eoc).Count; $aut=@($rows | Where-Object autonomous_eoc).Count; $ass=@($rows | Where-Object runtime_assisted_eoc).Count
    $attempt=($rows | Measure-Object -Property attempted_violations -Sum).Sum; $actual=($rows | Measure-Object -Property actual_violations -Sum).Sum
    $logicalTokens=($rows | Measure-Object -Property tokens -Sum).Sum
    $lines.Add("| $method | $($rows.Count) | $eoc | $aut / $ass | $attempt / $actual | $logicalTokens |")
}
$belief=@($agent.stages | Where-Object belief_converged).Count; $boundary=@($agent.stages | Where-Object boundary_admitted).Count
$admitted=@($agent.stages | Where-Object agent_admitted).Count; $activated=@($agent.stages | Where-Object isolated_activated).Count
$lines.Add('')
$lines.Add("固定分母真实 Agent 漏斗：$($agent.stages.Count) planned stages → $belief Belief Converged → $boundary Boundary Admitted → $admitted Agent Admitted → $activated Activated。候选拒绝、不确定、未触发均保留在分母。")
$lines.Add('')
$lines.Add('Agent 准入按 world-sequence 聚类：同一 sequence 内的六个 task 只提供一个独立簇，不能伪造六个独立胜场。本工程样本不足时为 INCONCLUSIVE；不声称总体零遗忘、显著提升或已完成正向连续自进化。Boundary 正确和完整 Agent 正确分别判断；refuse/escalate 错误不改标为 Boundary 学习错误。')
$lines.Add('')
$lines.Add('| World-sequence | Test 配对 EOC 差（Existing − NoAdapt） | 完成阶段 |')
$lines.Add('|---|---:|---:|')
foreach ($world in $p.agent_worlds) {
    foreach ($seed in $p.sequence_seeds) {
        $prefix="agent/$world/$seed/"
        $rows=@($agent.logical_arms | Where-Object { $_.partition -eq 'test' -and $_.folder.StartsWith($prefix) })
        $old=@($rows | Where-Object { $_.role -eq 'NoAdapt' -and $_.eoc }).Count
        $new=@($rows | Where-Object { $_.role -eq 'ExistingActive' -and $_.eoc }).Count
        $n=@($agent.stages | Where-Object { $_.key.StartsWith("$world/$seed/") }).Count
        $lines.Add("| $world / $seed | $($new-$old) | $n / 3 |")
    }
}
$totalWall=$p.prior_wall_seconds+$agent.collection_wall_seconds
$lines.Add('')
$lines.Add("物理实际费用：$($agent.physical_statuses.Count) 个模型任务臂，新增 $($agent.charged_tokens) tokens；继承开发累计 $($agent.shared_total_tokens) tokens / $([Math]::Round($totalWall,2)) 秒采集墙钟。CPU 探针 $($cpu.physical_probes)，工具调用 $($cpu.physical_tool_calls)，CPU 墙钟 $([Math]::Round($cpu.cpu_wall_seconds,2)) 秒。GPU utilization hours 未实测，采集墙钟不改称 GPU 小时。")
$lines.Add('')
$lines.Add('相同 task、模型、Runtime、Boundary、真实环境和故障的臂按预注册规则共享物理运行；逻辑每方法费用单列，全局实际费用去重。重放审计没有新增推理 tokens。真正激活仅指隔离评测版本，部署为 false。')
$lines.Add('')
$lines.Add("Protocol: ``$($p.hash)``")
$lines.Add("CPU report / audit: ``$($cpu.hash)`` / ``$($ca.hash)``")
$lines.Add("Agent report / audit: ``$($agent.hash)`` / ``$($aa.hash)``")
$lines.Add('')
$lines.Add('复现命令：`python -m scripts.audit_boundary_trial_cpu --run <run>`；`python -m scripts.audit_boundary_trial_agent --run <run>`。原始结果在 `cpu/report.json` / `agent/report.json`，逐阶段决定在 `agent/<world>/<seed>/<stage>/decision-before-test.json`，模型/工具/SQLite/checkpoint 在 `agent/physical/`。')
$text=($lines -join "`n")+"`n"
[IO.File]::WriteAllText((Join-Path $studyRoot 'REPORT.md'),$text,[Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $repoRoot 'docs/BOUNDARY_EVOLUTION_FORMAL_ENGINEERING.md'),$text,[Text.UTF8Encoding]::new($false))
Write-Output 'Derived report saved from independently audited results.'
