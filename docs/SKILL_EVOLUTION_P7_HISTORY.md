# P7：v1.1 全量历史诊断

2026-10-12。只读覆盖正式 B 全部 6 worlds × 5 seeds 的 30 对 active / active_v2，重放 186 个实际 query 与每个前查询/终态。新增模型调用、tokens、工具探针均为 0。

- H0 普通收敛入口：0。最终最佳类别全部为非 H0（restrict 25 / relax 5），不是满足 H0 收敛条件后 Gate 漏触发。
- 排名/查询/证据差异：0。正式 variant 为 gate-only，disagreement/coverage 权重均为 0；原源码明确零权重时返回原排名，所以相同结果不能单独证明 bug 或有效性。
- 23/30 收敛，7/30 no_information_gain。认证错误收敛与 H0 认证错误收敛均为 0。
- 7 个未准入运行退回 H0，共 12 个有效 fallback 错误（原报告 false allow 7 / false block 5）。这些运行的最佳候选在已存诊断集上均为 0 错误，但这不是可以跳过收敛或准入的理由。
- 7 个失败运行均还有 6–14 query 预算；剩余 H0 区分点为空，已有必要 challenge 均测过（其中 5 个运行仅 1 个可区分点，coverage_shortfall 如实记录）。这不是把 K 再调大就能解决的问题。

| world | seed | 已查询 | 剩余 | 最佳类别 posterior | fallback 错误 |
|---|---:|---:|---:|---:|---:|
| W5 | 39410652 | 14 | 6 | .9145 | 3 |
| W5 | 82834875 | 10 | 10 | .9342 | 3 |
| W5 | 94032190 | 11 | 9 | .9158 | 1 |
| W6 | 32187782 | 6 | 14 | .7736 | 1 |
| W6 | 39410652 | 6 | 14 | .7730 | 2 |
| W6 | 94032190 | 6 | 14 | .7735 | 1 |
| W6 | 94966939 | 7 | 13 | .7736 | 1 |

每步另计算 H0 challenge 反事实诊断（112 个 challenge_required 状态、104 个 challenge_passed 状态），仅说明如果当时进入 H0 gate 会怎样，不是实际触发或新增查询。UNKNOWN 计数、区分集合/去重、替代假设 cutoff、预算和普通收敛分别保存。

审计独立重算 Bayes/posterior hash、普通收敛与 challenge；原 EIG 使用已存逐步数值并检查配对排名完全一致、成本/打分/选样一致，**没有独立重算每个原始 EIG**。报告明确此限制。旧 heldout 错误仅供事后归因，不进入学习器或开发查询。

原 B protocol：`a0e86e16229bf895402531bec9119aa2747ec1c18bbbdc63d23627909ff33540`。
本次报告 hash：`2264f1a988e72e735de7ab8071e407321f9a86db526669f26985ad5ae5aeb907`。
审计控制器 SHA：`742b1595d27e778c20ab65c439fa687d0962f4fc8863265bba913f8faec5c46a`。
CPU 墙钟 103.67 秒，3 项 toy 审计测试通过。

下一批仅在新开发来源上按预声明规则比较 OriginalActive、ExistingActiveV2、BroadOnly、DeepOnly、BroadThenDeep；原 Bayes/EIG、有限谓词域、20-query 上限不变。Deep 只提议公开因子对照/已有阈值两侧/有限独立重复，必须经沙箱实际查询。保守弃权和学习效率分别计分；没有支持改进则 KEEP_EXISTING，不降低收敛门槛。

原始逐对结果：[全量诊断目录](../results/skill-evolution/v1.2/preparation/p7-history-audit-20261012-r2/REPORT.md)。
