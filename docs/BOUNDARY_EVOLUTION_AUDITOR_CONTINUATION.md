# 正式 Agent 审计器修复与精确续跑

2026-10-13。原协议 `15bc371cf0011b0965ccffa98a22c95a6d12efb983780fdcebd78f3b012afdbb` 不变。CPU **90/90** 已完成，独立审计进行中。真实 Agent 首次采集 10 个物理臂后，被审计器不支持的失败路径中断；不是因为结果不好重新选样本。

实际模型在 fault-only 案例输出 `{"type":"terminal","name":"","arguments":{}}`，不符合冻结 Action schema。原 Runtime 正确记为 `ValidationError / model_error / outcome error`，该臂 EOC=false，最后一次请求实际 3,905 tokens，整臂 **14,852 tokens**。旧审计器把所有 failed generation 都拒绝重放，导致 checkpoint 费用差异。原部分报告 `135c20a939192653808bcf74094893ed527df707f85884ca67c9b080c7d4908d` 保留，不覆盖或改成完成。

新增版本化 `audit_boundary_stage2_arm_v2.py` 仅支持实际已知 usage 的 Action parse failure：把原始无效 JSON 再送入相同 Action schema，仍然抛出相同 ValidationError、仍计 EOC 失败及实际 tokens。未知生成/传输错误仍保守拒绝，不构造合法动作。两个回归测试通过，事后替换合法动作不能通过审计。

恢复前 **10 个原始臂 / 281 checkpoints / 259,057 tokens** 全部重放一致，冻结源码逐项 SHA 零差异。续跑从保存的真实日常回执、probe/learner RPC、父链和费用重建，仅运行缺失任务；完成的模型臂与写入不重放。旧原始文件逐字节 hash 纳入 continuation manifest，结束再次校验；总 tokens 不重复收费，阶段上限不重置，累计墙钟包含首次 **639.97 秒**。

审计扩展 manifest `c3db1e692c918e307a6ff72c4cfbf95651dd23dfec66ae90eeb546c892e84c12`，扩展源码事先归档到 continuation-v2/source-snapshot。模型、原 Runtime、Belief/EIG、探针/假设、门槛、task/seed、程序和原预算均未改变。新增文件是审计/恢复扩展，不把 frozen source index 改写成另一个版本。原 Windows 工作流状态替换的空 backup 参数也已修正，避免子任务结束后状态写入失败；不涉及 Agent 行为。

当前后台命令：

```powershell
./scripts/continue_boundary_formal.ps1 -Run results/skill-evolution/v1.3/formal-P11-v1
```

CPU 90 运行不重跑，只做独立审计；真实 Agent 继续剩余任务，结束后自动执行 v2 全量独立审计和报告。最终 Agent 结果写 **agent/continuation-v2/report.json**，审计写 **agent/continuation-v2/independent-audit.json**；原 agent/report.json 始终为首次中断记录。只读 API 对当前结果选择续跑版本，另保留原报告链接。

[续跑 manifest](../results/skill-evolution/v1.3/formal-P11-v1/agent/continuation-v2/manifest.json)、[原部分报告](../results/skill-evolution/v1.3/formal-P11-v1/agent/report.json)、[实时工作流](../results/skill-evolution/v1.3/formal-P11-v1/workflow-status.json)、[只读页面](http://127.0.0.1:8093/skill-evolution)。最终真实 Agent 和全批独立审计尚未完成；不提前声称 formal complete、Agent admitted 或连续适应收益。
