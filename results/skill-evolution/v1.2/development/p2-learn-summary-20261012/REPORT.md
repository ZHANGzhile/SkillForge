# P2 learn / P3 TraceCompiler 开发报告

2026-10-12，固定 main-v3，无新增训练。本批交付真实经验采集、独立审计、保守机会筛选和直线只读 TraceCompiler 初版。没有新 Skill 准入、正式研究收益、隔离激活或部署。

| 项目 | 结果 |
|---|---|
| learn 轨迹 / 独立来源组 | 6 / 6 |
| 独立 EOC | 6/6 |
| 无 Runtime 执行干预成功 / 辅助成功 | 6 / 0 |
| 违规尝试 / 实际 policy violation / 实际 workflow violation | 0 / 0 / 0 |
| 模型决策 / 模型来源工具调用 | 21 / 15 |
| 增量成本 | 68,906 tokens / 178.10 秒运行墙钟 |
| 共享累计成本 | 537,296 tokens / 1,904.82 秒 |
| Opportunity / 候选 | 0 / 0 |
| 筛选 / 编译状态 | NO_USEFUL_OPPORTUNITY / NO_USEFUL_CANDIDATE |

摘要工作流与调查资料工作流各有三组独立来源，均形成稳定的真实参数化读取序列。旧三个静态 Skill 不覆盖这些只读目标；22 次静态覆盖工具检查属于独立 scripted 工程证据，不教给 learner。

摘要自然执行每例三次决策，调查资料每例四次决策。search/load/execute/stop 的候选路径估计四次决策，节省分别为 -1 与 0，未达到预先登记的至少一次节省门槛。流程新颖性、三个来源和有效目标都不能代替增量效益。没有降低门槛、增加无意义调用或用剩余预算追正结果。

六个实体来自两个共享任务模板，不是六个独立任务结构；没有正式 heldout、显著性或跨结构泛化证据。成本估计不替代真实候选 Agent 的 tokens/时延/安全配对评测。

TraceCompiler 工程测试证明调用顺序来自轨迹，节点绑定/出处可追踪，伪造来源、heldout 混入、事件错配和虚构效益会拒绝，候选保持 CANDIDATE。真实数据不满足 Opportunity，因此未生成任何候选。这条零更新结果与六条业务成功可以同时成立。

最终源码副本回归 **360 passed / 1 skipped**，两个上游弃用警告；A/B 冻结源码及 adapter 哈希通过。初次预检的 dev5 审计兼容失败保留，修复后通过。采集 Worker 和 GPU 租约均已释放。

完整实现范围、预算登记与限制见 [P2/P3 阶段说明](../../../../../docs/SKILL_EVOLUTION_P2_LEARN.md)。下一步是 P4 工程治理与验证约束；真实候选准入须等待满足原门槛的新证据，不以 scripted 测试替代。

- [机器摘要](summary.json)
- [原始采集报告](../p2-learn-main-v3-20261012/report.json)
- [采集注册与源码身份](../p2-learn-main-v3-20261012/registration.json)
- [独立证据审计](../p2-learn-main-v3-20261012/evidence-audits/574eb527c912c069dd6b23992b5eaba27cffb14d85e23b159147d6003a7d3bba.json)
- [机会筛选](../p2-learn-main-v3-20261012/opportunity-screens/b576d9654e457aa79c66f7e5c8403096cc02e6a02d26695d13ed9879a0c5734e.json)
- [编译结果](../p3-trace-screen-20261012/report.json)
- [编译绑定](../p3-trace-screen-20261012/binding.json)
- [最终预检](../preflight-20261012-P2-P3-final/preflight.json)
