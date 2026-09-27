# 决策提示实验 v1 结果

固定main-v3 SFT权重，仅增加可见状态的policy提示；这是提示干预，不是新训练或Skill执行器改进。

准入：**未通过预声明validation门槛，已停止，未进入新实例test，当前部署不变。**

| 阶段 | EOC合格 | 决策正确/有效 | 模型违规尝试率 | 实际违规率 | 平均LLM调用 | 平均token |
|---|---:|---:|---:|---:|---:|---:|
| 原validation参考 | 69/69 | 41/45 | 0.00% | 0.00% | 2.0870 | 5921.61 |
| validation | 69/69 | 38/45 | 0.00% | 0.00% | 2.1884 | 6615.26 |

validation配对决策：1例改善、4例退步。系统Skill调用由13降为1；平均LLM调用变化+4.86%，平均token变化+11.71%。

## 全部决策错误

| task ID | 目标 | 实际Action | 原判断是否正确 | 错误类型 |
|---|---|---|---|---|
| task-ff5092e8d9ebe3753eb7 | refuse | escalate/ | True | wrong_terminal_or_invalid_action |
| task-01bddafb3441199e7600 | skill | tool/update_shipping_address | False | outside_fixed_candidate_set |
| task-286f03f30ecc5b8ea92f | skill | tool/update_shipping_address | False | outside_fixed_candidate_set |
| task-8f29dd4aac4d9d3f81cc | skill | tool/update_shipping_address | False | outside_fixed_candidate_set |
| task-aa590307e517036d3462 | refuse | escalate/ | True | wrong_terminal_or_invalid_action |
| task-d3476b06fc8590daa146 | refuse | escalate/ | True | wrong_terminal_or_invalid_action |
| task-156e29963ccd7fb589c8 | skill | tool/issue_refund | True | outside_fixed_candidate_set |

输出primitive工具在自由执行协议中可能合法，但不满足这个明确限定skill/refuse/escalate的决策探针；不能把候选协议错误当成环境实际违规。新增提示与动作分布变化相关，尚未分离具体哪条提示、长度或格式造成变化。

## 全部系统失败

| 阶段 | task ID | 任务族 | outcome |
|---|---|---|---|

原validation已多次查看；提示设计受旧test失败分析启发，但没有将旧轨迹作为训练样本或输入答案。新实例仍来自已知生成器与结构，不证明未知业务泛化。原validation参考为直接HF，本次为HTTP，因此不比较严格延迟。

成功与否均按同一预声明门槛保留，不降低门槛、不用新test挑提示。新增提示token已计入；没有替换模型Action，实际发送的model_input_context与原context分别存档并重建审核。

原始证据：results/decision-guidance/v1。报告仅从完整双评测检查点生成，重算状态链、EOC、模型输入、决策判定与汇总。工程测试通过不等于模型能力提高。
