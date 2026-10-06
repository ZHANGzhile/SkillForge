# v1.1-A：完成情况与验收结论

2026-10-05。正式A矩阵及独立审计已完成：9个独立world-seed、2个连续epoch、1,608条真实模型执行和293份VerificationReceipt。固定main-v3；未执行SFT、DPO或RL。主报告保留在[REPORT.md](../results/active-evolution/v1.1/formal-A-v2/REPORT.md)，本文件是结果解读，不修改冻结指标和准入。

## 可以支持的结论

- 固定分母漏斗：9 → 5 Belief Converged → 5 Boundary Admitted → 新Runtime下3 Agent Admitted / Activated；旧Runtime下0。条件Agent准入率为3/5与0/5，端到端激活率为3/9与0/9；Activated仅为隔离实验。
- 变化test上的Runtime Effect为+26.39个百分点；新Runtime下有效Bundle额外收益为+4.17个百分点。候选交互+11.11个百分点，有效Bundle交互+4.17个百分点，两者口径不同，不能混用。
- 独立9组的有效Bundle test没有实际违规或stable配对退步。拒绝的候选保持实际父Bundle，不能把被拒候选诊断得分算为部署收益。
- 两个连续epoch的新Runtime均通过预先声明的validation并建立实际Agent父链；旧Runtime均拒绝提案、维持H0。

## 连续实验未通过零稳定性退步

只读归因覆盖两个epoch、两种Runtime、变化与stable test的全部64对有效Bundle轨迹：61对不变、2对改善、1对退步。证据：[continual-attribution.json](../results/active-evolution/v1.1/formal-A-v2/posthoc/continual-attribution.json)。

唯一stable退步发生在epoch 2 / W5 / 新Runtime，任务`71223d56fcfe462e7b5e3645`：付款FAILED、风险LOW、请求退款2999。更新前后公开Boundary gate均为INAPPLICABLE、Decision均为False；模型终态从正确的refuse变为escalate。两次均无Runtime干预、无实际违规；更新后创建了人工工单，独立verifier以unexpected_outcome判失败。

因此，这个案例支持“保持不适用判断时，Bundle更换伴随终态选择退步”，不支持“Boundary错误放行”“Runtime漏掉退款读回”或“真实违规”的解释。只观察一次配对轨迹，不能排除模型执行非确定性，不能宣称已经确定普遍因果机制。没有为修复这一test而重跑、修改准入、补写terminal规则或更改权重。

最终状态：**执行收益与部分Boundary利用收益有证据；连续实验零stable退步验收失败。** validation通过不等于test保持全部旧能力。两个epoch不是两个独立研究样本；9个world-seed的区间也受小样本限制。

## 成本、复现与下一阶段

共享预算累计7,739,014 tokens，包括524,288失败预留。原始墙钟13.733小时；Windows睡眠证据扣除9.339小时后为4.394/12小时，保留60秒过渡余量。原始预算超限事实及冻结后的修正已在报告披露，不能声称未经修正的原墙钟预算合规。

B只研究CPU Boundary acquisition：6个既有规则世界、5个新配对seed、5种方法，独立protocol hash。开发消融和正式数据与A隔离；A的这条测试失败不用于B选样/调参。B不新增真实模型调用或训练，亦不能用B的结果补成A的连续retention通过。v1.2 Continual SFT仍为后续条件性方案。
