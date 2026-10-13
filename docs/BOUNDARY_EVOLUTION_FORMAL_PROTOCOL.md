# Stage 2 冻结连续评测（运行中）

2026-10-13。正式工程规模协议已冻结，protocol `15bc371cf0011b0965ccffa98a22c95a6d12efb983780fdcebd78f3b012afdbb`。该批为 ENGINEERING_NOT_RESEARCH_POWERED，不是统计功效充足的研究实验。

预先固定 CPU：W1/W6/STRUCTURAL3 × 2 independent sequence seeds × 3 stages × 5 methods = **90 个计划运行**。STRUCTURAL3 是最多两个谓词无法完整表达的三因子 conjunction，只作预注册 CPU 域不足/结构诊断，不加 acquisition 算法。

真实 Agent：W1/W6 × 2 independent sequence seeds × 3 stages = **12 个阶段 / 4 个独立 world-sequence**。每阶段 3 日常请求 + 1 fault-only 日常请求，候选条件验证 6 primary + 2 stable，盲测 1 changed + 1 stable；同模型/程序/发现/Runtime 比较 NoAdapt 与 ExistingActive。ImprovedActive 未在开发消融入选，故不强制添加重复方法。阶段为 changed → unchanged → restore_original。日常公开回执触发，world/epoch/gold 不进入触发器或 learner；真实模型只读当前公共 Bundle。

真实 Agent gate 按 world-sequence 聚类。一个 sequence 的多个 task 只提供一个独立簇，不能用六个 task 假装六个样本；本工程样本不足时 INCONCLUSIVE。Boundary 准入和 Agent 准入分开，只有双层准入才能进入下一轮真实父链；CPU Boundary-only 父链单独报告。恢复旧规则失败、拒绝、未知、无触发和未激活全保留，不声称总体零遗忘或正向连续更新已成立。W6 的 primary validation 是公开固定服务子集；负例仍有 stable Guard 案例，若 primary 正/负覆盖不足，严格算术门应弃权，不放宽。

最大物理 Agent 臂 320；相同完整 task、fault、真实 policy、模型/Runtime、Boundary 的角色可共享实际证据。每方法逻辑费用和全局去重物理费用分开。预算继承 **1,851,663 tokens / 4789.28 秒**，本阶段 cap **17,700,000 tokens / 37,800 秒**；全局上限 **19,551,663 tokens / 42589.28 秒**，低于 20M / 12h 保守采集墙钟上限。GPU utilization hours 未实测，墙钟不改称实测 GPU 小时。资源耗尽/基础设施中断时按实际证据记 incomplete，不能按成绩增减 seed、换模型或重设预算。

完整精确源码副本预检 **497 passed / 1 skipped / 2 upstream warnings**；copied_sources_match 与 sources_unchanged_during_tests 均为 true。旧 A/B、Stage 1 冻结来源、历史资产和 main-v3 SHA 通过。首次预检因 Windows 临时路径过长而失败，原日志保留；第二次仅换短临时路径并加入源码复制一致性检查。控制器 smoke-r2 的 15 单元 / 153 实际探针 / 76 查询经独立 replay 通过。

启动命令（本批已执行，不能重复运行）：

```powershell
./scripts/run_boundary_formal.ps1 -Run results/skill-evolution/v1.3/formal-P11-v1
```

脚本自动并行 CPU/真实 Agent，采集完成后依次运行独立 CPU 与 Agent 审计并生成正式报告。失败保留日志、checkpoint 和批准费用，不自动重放中断臂。无训练、生产部署或服务指针切换。

[只读预览](http://127.0.0.1:8093/skill-evolution)；[冻结协议](../results/skill-evolution/v1.3/formal-P11-v1/protocol.json)；[运行状态](../results/skill-evolution/v1.3/formal-P11-v1/workflow-status.json)；[精确预检](../results/skill-evolution/v1.2/development/preflight-20261013-P11-r2/preflight.json)。最终 CPU / Agent 结果与审计尚未全部完成，不能提前宣称研究收益或 v1 正向持续适应交付。

## 当前续跑入口

首次 Agent 流在真实无效 Action 的独立审计路径中断。原数据/费用和失败结果保留；现用 [审计器扩展与精确续跑](BOUNDARY_EVOLUTION_AUDITOR_CONTINUATION.md)，协议和模型不变。最终 Agent 结果在 `agent/continuation-v2/`，原 `agent/report.json` 是首次 partial，不能将其误读为当前终止状态。CPU 90/90 完成，正在独立审计；后台自动串联后续 Agent、v2 全量审计和正式报告。
