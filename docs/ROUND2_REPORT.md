# 第二轮交付：隔离实验与 Skill 对照

日期：2026-09-09

## 本轮结果

已完成从版本化数据集、训练轨迹采集、来源审计、地址/取消 Skill 编译、validation 验证、冻结到 B0–B3 对照的可执行流程。最终全套测试为 36 passed、2 条上游弃用 warning；追加的源码哈希对照测试也通过。

真实 Student 的接口预检仍失败（ConnectError / WinError 10061）。以下所有数字来自 scripted-engineering-only，验证的是工程正确性，不能证明模型能力或算法收益。

## 数据和产物

- 数据：216 个合成任务，train=69、validation=69、test=78。
- 训练来源：90 条工程轨迹，含69次正常策略执行和21次明确标注的刻意失败执行；不含 test 轨迹。
- Skill：地址修改、取消订单两个主方法 Skill；另有独立 success-only Naive Skill。
- 数据清单：`data/experiment-v1/manifest.json`。
- 冻结包：`results/frozen-experiment-v1/frozen.json`。
- 最终结果：`results/experiment-comparisons/680408b2-3c0a-45fa-8bfe-a71aa6ce7c04/comparison.json`，同目录有 CSV 和完整逐任务记录。

## 工程对照

相同78个测试任务，每组重复3次。五组共1,170次执行全部符合各自 Expected Outcome Contract。

| 配置 | 工程任务成功 | 平均工具调用 | 平均策略决策次数 | 真实 LLM 调用 |
|---|---:|---:|---:|---:|
| B0 | 234/234 | 4.308 | 4.769 | 0 |
| B1 Raw Memory | 234/234 | 4.308 | 4.769 | 0 |
| B2 Naive Skill | 234/234 | 4.615 | 4.615 | 0 |
| B3 Verified Skill | 234/234 | 5.038 | 3.038 | 0 |
| B3-no-gate | 234/234 | 4.692 | 4.615 | 0 |

B3 包含 Gate 补查与内部步骤，因此工具调用多于 B0。这些成本没有隐藏。脚本策略不通过语言推理使用 Raw Memory，B1 数字只是检索/注入路径的工程检查。所有组均无实际违规写入，但权限不匹配任务存在被工具拒绝的读取尝试；报告保留尝试违规率。

固定候选决策探针与系统评测分开保存。D类故障任务和权限不足的状态准备任务显式跳过并计数，不把准备失败算成决策成功。

## 发现与修复

首次隔离对照 B3 为75/78。Gate 的读取错误被吞掉，重试耗尽后模型重新发起读取，绕过了既定错误处理路径。修复包括：

1. Gate 异常进入模型可见 gate_observations。
2. 同任务同调用的耗尽预算不能通过更换 step 重置。
3. 相同 mutation payload 在 Skill/primitive 之间共享 operation key，避免 fallback 重复退款。

首次失败保留在 `results/experiment-comparisons/75207fa2-071d-4cd1-b05a-7bf29544dc74`，没有删除或覆盖。

## 交付接口

`dataset → collect → prepare → compare`，命令示例见 README。真实模型链路去掉 --scripted 和 --failure-fixtures，使用新采集的真实 train 轨迹和新的冻结目录。系统不会允许把工程来源直接标记为研究比较。

## 尚未完成

真实模型对照与统计分析、自动 refinement、开放域合成、退款 Skill 编译、多 Skill composition、SFT/DPO 训练和权重部署仍待完成。当前来源审计是清单绑定与确定性一致性验证，不是模型来源的密码学证明。旧 smoke suite 继续保留其回归用途。
