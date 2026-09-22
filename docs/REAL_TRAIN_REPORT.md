# 真实训练轨迹与Skill冻结报告

日期：2026-09-10。模型Qwen3 4B，RTX 5070，ollama_qwen3_raw适配，temperature=0，seed=42，输出512 token，16K上下文。本阶段未训练权重。

## 完成的改动

新增v1/v2/v3决策提示版本；配置和每条新轨迹记录提示原文、版本、SHA-256。v1保留原始行为；v2补充状态读取、业务边界、执行后验证；v3强化历史优先但实测退步，不激活。

公开policy明确order.status与shipment.status，说明退款不依赖物流状态、缺失观察需先读取；底层业务eligibility与门槛不变。所有动作仍由真实模型生成，未用规则替换模型决策。

## 结果及适用范围

最初同一组5个train诊断案例：v1为1/5，v2为2/5，v3为0/5。目录分别为`results/local-student/9354139e-ad4f-4a02-b140-06d8dfe41c37`、`ff188a48-35ea-4f7e-8f85-65473e81fa8b`、`43576b2e-8e3a-4135-aaa7-1841ccb87fa8`。这是提示开发数据，不能作为独立泛化评测。

选择v2并澄清公开policy后，完整69个train任务获得40/69符合Expected Outcome（57.97%），13/69有违规尝试（18.84%），实际违规0。结局符合且无违规尝试为33/69（47.83%）。平均7.48次模型调用、20844.5总token、5.25秒/任务。与最初五例的任务构成不同，不可把20%到57.97%直接解释为提升幅度。

| 领域 | 预期结局符合 / 总数 |
|---|---|
| 地址修改 | 19/27 |
| 取消订单 | 6/15 |
| 退款 | 9/18 |
| 组合流程 | 3/3 |
| 物流调查 | 3/3 |
| 工单 | 0/3 |

仍有漏验证7次、步数耗尽8次、提前stop4次、模型/运行错误2次；错误类别可重叠。正确拒绝和转人工由Expected Outcome检查，未一律视为成功。7个结局合格案例仍有违规尝试。

原始69条来源：`results/real-v2-sources/6b00119e-5990-48a5-b7ff-fe8c8cd50c1d/source_trajectories.jsonl`。完整benchmark子目录：`7b6f63e9-b26e-4dac-96cb-d7895bd7de48`。`collection.json`确认69个任务绑定train manifest，engineering_sources=false。

## 三类Skill证据与冻结

本轮69条加上此前v2五例的完整真实轨迹，组成74条、69个独立train任务。五条历史轨迹完整保留，不挑选单个有利动作。两次公开policy的表述不同，语义和底层业务policy v1.1相同；来源与文件哈希保存在`results/real-v2-combined/sources.json`。未混入scripted记录或validation/test来源。

| 领域 | 合格有序执行证据 | 业务失败反例 | validation契约检查 |
|---|---|---|---|
| 地址修改 | 4 | 5 | 27/27 |
| 取消订单 | 3 | 1 | 15/15 |
| 退款 | 3 | 1 | 18/18 |

边界显式引用successful trajectories、failed trajectories和business policy。来源审计及编译就绪报告：`results/real-v2-combined-readiness.json`。编译阈值和有序read/mutation/verification检查未放宽。

冻结文件：`results/real-v2-frozen/frozen.json`，3个VERIFIED Skill，engineering_only=false，hash=`3bec0fcd3b4d72c571450d3ccdb56815957212bcffd5e93ab002e96d784b4769`。独立Naive Skill一并生成。`decision_config.json`保存当前提示、公开policy和代码哈希。

上述validation是确定性Gate/Executor契约准入和后置条件检查，不是模型端到端成功率，也不是Decision-level模型选择成绩。

## 验证与下一步

46项pytest通过，保留2项已知上游弃用警告。新source审计脚本已对69条及74条真实来源实际执行。

下一阶段固定当前配置执行真实B0–B3及无Gate消融，输出Full System与Decision-level双评测；本轮未读取test结果调提示。完整对照前不开展SFT/DPO正式训练。

```powershell
.\.venv\Scripts\python -m skillforge.cli compare --dataset data/experiment-v1 --bundle results/real-v2-frozen/frozen.json --output results/real-v2-comparisons --ablation
```
