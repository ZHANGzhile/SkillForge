# Stage 2 正式 CPU Boundary 结果（真实 Agent 仍在运行）

2026-10-13。冻结工程规模协议 `15bc371cf0011b0965ccffa98a22c95a6d12efb983780fdcebd78f3b012afdbb`。W1/W6/STRUCTURAL3 × 2 independent sequence seeds × changed/unchanged/restore_original × 5 methods，共 **90/90** 完成并通过独立审计。

| 方法 | 冻结阶段单元 | budget 内原始收敛率 | RMQ cap=20 | effective FA / FB（嵌套案例合计） | stable 新退步 | CPU Boundary-only 更新 |
|---|---:|---:|---:|---:|---:|---:|
| no_adapt | 18 | 0.0000 | 20.0000 | 41 / 13 | 0 | 0 |
| passive | 18 | 0.0000 | 20.0000 | 41 / 13 | 0 | 0 |
| random | 18 | 0.0000 | 20.0000 | 41 / 13 | 0 | 0 |
| OriginalActive | 18 | 0.4444 | 14.2222 | 13 / 19 | 0 | 4 |
| ExistingActiveV2 | 18 | 0.2778 | 16.4444 | 13 / 19 | 0 | 4 |

收敛率/RMQ 按全部冻结阶段输出，包括未触发/不需要更新的阶段；这不是条件探索样本的纯算法效率比较。case 错误合计用于有限集合安全验收，不把数千 task 当独立样本。CPU 独立单位为 6 个 world-sequence，阶段与任务嵌套；不做统计显著性结论。候选与 effective、raw belief 与 Boundary gate、域不足/UNKNOWN/无法区分/预算停止均在逐运行原始数据里，不把未通过验证的候选当有效规则。

CPU Boundary-only 父链不等于真实 Agent 生效父链。独立 Agent admission/activation 仍由真实模型的完整 EOC、安全、stable 和 world-sequence 聚类决定。恢复原规则时保留旧限制的错误也完整记录；没有因该结果继续调 acquisition/H0 门槛。STRUCTURAL3 为预声明的三个条件 conjunction、超出 max-two-predicate 域的 CPU 结构诊断；不代表真实 Agent 结构泛化。

实际沙箱探针 **3,058**，实际工具调用 **25,022**，各方法逻辑探索 **416**；CPU 采集墙钟 **1304.48 秒**。同任务配对方法缓存实际回执，逻辑方法查询仍分别计费。零模型 calls/tokens，零训练/生产部署。

独立审计重放全部 source/entity 所有权、public trigger、实际保存返回值的 DSL/postcondition、Bayes/EIG/RPC、候选、分层算术与父链，已通过；**291.05 秒**，新增工具/模型调用 0。它是保存回执的完整逻辑重放，不伪称重新采集模型或业务工具。

report `479335d4cd64c99f0d3bbe282ca6475a7f21cfd957d5389d3c96088877c4f14c`；audit `e88791b66b0d6507409a76fa49097f5699acd5fac601b7d0ebc43c200d9ed156`。

[原始 CPU 结果](../results/skill-evolution/v1.3/formal-P11-v1/cpu/report.json)、[独立审计](../results/skill-evolution/v1.3/formal-P11-v1/cpu/independent-audit.json)、[真实 Agent 续跑状态](../results/skill-evolution/v1.3/formal-P11-v1/workflow-status.json)。最终真实 Agent 和两阶段总报告尚未完成，不提前宣称 end-to-end 自进化收益。
