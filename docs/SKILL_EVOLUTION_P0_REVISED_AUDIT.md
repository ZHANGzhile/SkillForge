# 新版两阶段方案 P0 审计（2026-10-12）

依据：`TWO_PHASE_EVOLUTION_SPEC_REVISED_2026-10-12.md`。本报告先于新版 P1 修改落盘；不是正式 protocol，也不证明研究收益。

## 资产与历史证据

- HEAD：`ecceeb317bbe967b30b36c58df5031c6e7bfbdce`；新增两阶段代码、文档、结果尚未提交，不等同于 GitHub main 已更新。
- 机器可读审计：`results/skill-evolution/v1.2/development/p0-revised-20261012-verified/preflight.json`。
- 正式 A 的 86 个源文件、正式 B 的 100 个源文件哈希全部一致。
- 历史基线 10,699 个文件中，仅两份 README 与早期基线不同，且均与已发布 ecceeb3 完全一致；此差异明确保留。
- 固定 main-v3 adapter SHA256：`f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b`。
- 本次 P0 没有重新执行 GPU 推理；上次完整工程回归是 298 passed / 1 skipped，新修改后必须重新验证。
- 首次沙箱审计因 Windows 硬链接写入被拒而未生成报告；使用获准的本地文件操作完成上述独立输出，未覆盖失败目录。

## 已有实现和新版差距

| 项目 | 已有证据 | 新版缺口 / 实施约束 |
|---|---|---|
| 公开隔离 | worker 只接收公开任务、目录与工具 RPC | 机会标签、离线分母、验证结果不得进入 worker |
| 全库检索 | 无 family 预筛选、确定性词法搜索、精确版本加载 | 加入公开 observation/tool 摘要及独立排名审计；保留历史 v1 重放 |
| 选择链 | 已保存上下文、搜索、加载、Skill 调用和 Receipt | 增加逐步 selection_trace、可见集合哈希、错误分类；不能从 family 推出机会 |
| 机会分母 | 旧报告的任务 family 相关性只是诊断 | 在固定独立 DB fork 实际执行并用独立目标验证；保留 UNKNOWN 与不可支持状态 |
| 同状态因果检查 | 已有 SQLite/runtime/RNG 快照恢复 | 两臂共享快照、前缀、模型、规则及预算，仅改变 Skill 可见性；自然轨迹差异不能代替 |
| 程序沉淀 | 旧固定 compiler 及静态库 | P2/P3 尚未实现；不能把现有三个程序换名计成学习 |
| 版本治理 | 内容寻址、依赖与加载冲突检查 | revision_kind、语义去重、RevisionMemory、配对准入和正式数据曝光记录仍待后续 |
| 持久控制器 | 单任务 checkpoint、未知提交及成本保留 | 尚无完整跨阶段 run/resume；不宣称整个控制器可恢复 |
| 模型比较 | main-v3 两次真实 smoke | 更强模型没有已验证可用配置，不伪造比较，不启动训练 |

## 已有 smoke 的结论边界

两批均是 dev：v1 为 4/6 EOC、v2 为 6/6 EOC；提示和 seed 同时改变，不能当配对增益。累计 233,471 tokens、834.2175 秒，属于原开发 smoke 的 500,000-token / 1,800-second 预算。两个源组及关联实体保持 dev；不能转为 learn 或独立正式 holdout。旧证据和原始失败保留，新增报告不能回写原始实验。

## 新流程可表达性审计

现有 `get_shipment/get_order/get_order_items/create_ticket` 可提供直线流程的工具基础；DSL 上限仍为 12 个 call/assert/finish 节点，无 branch。

现有 EOC 对工单主要检查 escalation ticket 数量，不能独立证明“物流调查结论或工单证据内容正确”。因此暂不创建工单 Skill 来凑新增数量。进入 P2 前，应先版本化定义公开工作流 schema、必要证据和独立 EOC，再采集 learn 轨迹。此环境定义必须先于候选生成，且有实例、来源组和组合结构的独立划分。

## 分阶段出口

1. 本次 P0：保留新版原文、资产审计、差距与数据/预算限制。
2. 新版 P1：独立机会评估、公开检索审计、逐步选择漏斗、同快照分叉；先 CPU 工程对照，再固定权重真实 smoke。脚本模拟与模型证据分开。
3. P2/P3：独立任务目标 → learn 归一化 / Opportunity → 轨迹依赖编译 → 候选静态/动态验证，允许无机会。
4. P4/P5：配对准入、版本记忆、三轮父链、No-History 和四类迁移，冻结 B/C 相同检索后端。
5. 冻结第一阶段后实施 P6–P11；先只读审计原 active/active_v2，再选择最小开发改动。

工程可运行、真实 Agent 使用、研究增量、隔离激活、部署分别记账。本次审计不启动 SFT/DPO/RL、不发布或部署。
