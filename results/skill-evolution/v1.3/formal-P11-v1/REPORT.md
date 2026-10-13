# Stage 2 连续 Boundary / Agent 工程规模正式报告

Agent 最终证据：`agent/continuation-v2/report.json`；最终审计：`agent/continuation-v2/independent-audit.json`。
原 agent/report.json 保留为首次审计中断报告。版本化审计扩展重放模型真实无效 Action，仍计 model_error / EOC 失败及实际 tokens。恢复复用十个已完成物理臂，未重新推理或写入，未改模型、Runtime、算法、任务、门槛或预算；continuation-v2/manifest.json 绑定新审计源码、原费用和全部旧文件。

此报告从已完成且独立审计通过的固定协议生成。工程规模：真实 Agent 为 2 worlds × 2 independent sequence seeds × 3 stages；CPU 另含预声明的三谓词结构外推规则。不是研究功效充足的统计显著性实验。

规则阶段为改变、不变、恢复原规则。模型 main-v3、程序、搜索/加载、Runtime 和门槛固定；没有 SFT/DPO/RL、全局服务切换或生产部署。新 acquisition 在开发消融中未入选，没有添加 ImprovedActive 冒充新方法。

| CPU 方法 | 计划单元 | budget 内原始收敛率 | RMQ cap=20 |
|---|---:|---:|---:|
| no_adapt | 18 | 0 | 20 |
| passive | 18 | 0 | 20 |
| random | 18 | 0 | 20 |
| OriginalActive | 18 | 0.4444 | 14.2222 |
| ExistingActiveV2 | 18 | 0.2778 | 16.4444 |

以上收敛指标以全部冻结阶段为分母，含未触发/无需更新阶段，不等于条件探索效率；逐运行的 trigger、原始 posterior、候选与有效 fallback、FA/FB、UNKNOWN、stable 退步均在 CPU 原始报告。CPU Boundary-only 父链不能当作真实 Agent 激活链。

| 真实 Agent test 方法 | 逻辑 task 臂 | EOC | 自主 / Runtime 辅助 | 尝试 / 实际违规 | 逻辑 tokens |
|---|---:|---:|---:|---:|---:|
| NoAdapt | 24 | 11 | 4 / 7 | 2 / 0 | 788558 |
| ExistingActive | 24 | 11 | 4 / 7 | 2 / 0 | 788558 |

固定分母真实 Agent 漏斗：12 planned stages → 0 Belief Converged → 0 Boundary Admitted → 0 Agent Admitted → 0 Activated。候选拒绝、不确定、未触发均保留在分母。

Agent 准入按 world-sequence 聚类：同一 sequence 内的六个 task 只提供一个独立簇，不能伪造六个独立胜场。本工程样本不足时为 INCONCLUSIVE；不声称总体零遗忘、显著提升或已完成正向连续自进化。Boundary 正确和完整 Agent 正确分别判断；refuse/escalate 错误不改标为 Boundary 学习错误。

| World-sequence | Test 配对 EOC 差（Existing − NoAdapt） | 完成阶段 |
|---|---:|---:|
| W1 / 2026101301 | 0 | 3 / 3 |
| W1 / 2026101302 | 0 | 3 / 3 |
| W6 / 2026101301 | 0 | 3 / 3 |
| W6 / 2026101302 | 0 | 3 / 3 |

物理实际费用：72 个模型任务臂，新增 2210126 tokens；继承开发累计 4061789 tokens / 11423.01 秒采集墙钟。CPU 探针 3058，工具调用 25022，CPU 墙钟 1304.48 秒。GPU utilization hours 未实测，采集墙钟不改称 GPU 小时。

相同 task、模型、Runtime、Boundary、真实环境和故障的臂按预注册规则共享物理运行；逻辑每方法费用单列，全局实际费用去重。重放审计没有新增推理 tokens。真正激活仅指隔离评测版本，部署为 false。

Protocol: `15bc371cf0011b0965ccffa98a22c95a6d12efb983780fdcebd78f3b012afdbb`
CPU report / audit: `479335d4cd64c99f0d3bbe282ca6475a7f21cfd957d5389d3c96088877c4f14c` / `e88791b66b0d6507409a76fa49097f5699acd5fac601b7d0ebc43c200d9ed156`
Agent report / audit: `e7f9a3488b473ee6bda6144fb1351f814fb007eb52f0c134fa18bcc812646302` / `46eb4460926235a56d5534a0a035b137d0dd6802ee136a08681a61896d9f6915`

复现命令：`python -m scripts.audit_boundary_trial_cpu --run <run>`；`python -m scripts.audit_boundary_trial_agent_v2 --run <run>`。最终原始结果在 `cpu/report.json` / `agent/continuation-v2/report.json`；`agent/report.json` 保留首次中断记录。逐阶段决定在 `agent/<world>/<seed>/<stage>/decision-before-test.json`，模型/工具/SQLite/checkpoint 在 `agent/physical/`。
