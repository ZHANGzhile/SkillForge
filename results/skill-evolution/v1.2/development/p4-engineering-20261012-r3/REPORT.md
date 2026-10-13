# P4 只读程序治理与验证工程报告

2026-10-12。真实 P2/P3 保持 NO_USEFUL_CANDIDATE；本批没有生成、注册、激活或部署新 Skill。

| 检查 | 结果 |
|---|---|
| 去重 | 规范化 DSL 相同识别重复；调用重排标潜在重复 |
| 修订治理 | metadata/program/boundary 分离，精确父版本，第一阶段禁止改 Boundary |
| RevisionMemory | 只收来源已登记的 learn/dev，拒绝正式反馈，每父最多两次尝试 |
| 独立动态验证 | 8 例行为符合预期；4 完成、2 预期拒绝、2 故障安全退出 |
| 数据库与义务 | 全部无变化、无 pending、无非预期违规 |
| 工程程序准入 | INCONCLUSIVE，不能进入 VERIFIED |
| 统计检查 | 六来源组合成收益通过；单来源 100 任务仍弃权 |
| 成本防伪 | 双方失败不计正收益；成本未知或配对缺失弃权 |
| 保留真实父目录 | 是；真实候选 0 |
| 新模型调用 / tokens | 0 / 0 |

最终工程运行 19 次验证调用 +19 次准入重放，独立事后审计再执行 19 次，共 57 次 scripted CPU 工具调用；不进入 learner。错误顾客探针的一次原始权限违规尝试保留，属于预声明工程注入，没有冒充真实模型行为。八例行为通过不等于八例业务 EOC。

程序准入、统计门、Agent 准入和激活分开。当前正式程序 API 没有真实候选实测，统计门还没有真实 Agent 轨迹审计接入，ISOLATED_ACTIVE 没有执行入口。所有正式成功/研究/激活标志保持未通过。

详细实现、统计单位、源码归档、范围与后续见 [P4 阶段说明](../../../../../docs/SKILL_EVOLUTION_P4_GOVERNANCE.md)。前两版工程结果保留，最终解释以 r3 的成本 protocol-v2 为准。

最终完整独立回归 **390 passed / 1 skipped**，两个上游弃用警告；冻结 A/B 源码、历史保护清单和固定 main-v3 adapter 核验通过。本批未启动 GPU。

- [机器报告](report.json)
- [验证协议](protocol.json)
- [完整程序证据](program-validation.json)
- [准入回执](program-admission.json)
- [独立审计](evidence-audits/954f75226dace9a479693059c21241492a1ac7738517c9a5625408dc12aded2f.json)
- [修订 sidecar](governance-revision.json)
- [生命周期](lifecycle/000002.json)
- [RevisionMemory](revision-memory/000000.json)
- [合成分组统计](synthetic-paired-gate.json)
- [单组小样本弃权](synthetic-small-sample.json)
- [源码快照索引](source-index.json)
