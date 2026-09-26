# main-v3 同模型无Skill对照

固定同一SFT权重、system prompt、任务初态及工具政策，覆盖全部78个已冻结新实例test。该test此前已被查看，本实验是事后系统消融，不用于训练或部署选优。

| 指标 | B0（无Skill） | B3（冻结Skill） |
|---|---:|---:|
| EOC合格率 | 88.46% | 87.18% |
| 平均LLM调用 | 4.6282 | 2.3718 |
| 平均工具调用 | 4.0256 | 4.7949 |
| 平均token | 11971.7692 | 6653.2564 |
| Skill调用 | 0 | 15 |
| 模型违规尝试率 | 14.10% | 0.00% |
| 自动Gate权限尝试率 | 0.00% | 3.85% |
| 总违规尝试率（旧口径） | 14.10% | 3.85% |
| 实际违规率 | 0.00% | 0.00% |

合格任务数：B0 69/78；B3 68/78。

调用/token成本包含失败任务，不仅统计成功案例；自动Gate和Skill内部工具调用也计入。以下为整个配置的成本差异，不是纯执行器收益：

- 平均LLM调用相对B0减少 48.75%。
- 平均工具调用相对B0增加 19.11%。
- 平均token相对B0减少 44.43%。

## 按任务族分解

| 任务族 | B0合格/总数 | B3合格/总数 | 改善 | 退步 |
|---|---:|---:|---:|---:|
| cancel_order | 15/15 | 15/15 | 0 | 0 |
| composite | 3/9 | 3/9 | 0 | 0 |
| modify_address | 27/30 | 27/30 | 0 | 0 |
| refund | 18/18 | 17/18 | 0 | 1 |
| shipment_investigation | 3/3 | 3/3 | 0 | 0 |
| ticket | 3/3 | 3/3 | 0 | 0 |

逐任务配对：启用Skill的B3相对B0改善0例、退步1例。

全任务分母的系统退步率：1.28%；B0成功条件下的退步率：1.45%。

退步且实际尝试Skill的任务：0。这仍是关联描述；same-context causal NTR保持null。

B0移除Skill候选，也同时取消自动Gate补读，因此初始可见状态与后续决策上下文会改变。差值属于整个系统配置的影响，不能全部归因于Skill执行器。B0经真实HTTP服务，B3复用同身份的直接HF检查点；不据此声称严格延迟加速或统计显著性。

权限读取失败也属于现有attempted_policy_violation口径。B0中的读取由模型发起，B3中同一检查可能由自动Gate发起；归因变化不等于非法写入倾向增加。须结合总尝试、具体工具审计和实际违规共同解释。

成本分母为完整保存并审核的逻辑任务轨迹；未保存的中断请求开销不在其中，因此这些数字不是含服务启动和中断浪费的总运营成本。恢复事件另存resume-*.json；恢复路径复核并复用已完成任务，不通过重跑挑选更好答案。

## 原B3失败自动归类

| 证据类型 | 任务数 |
|---|---:|
| read_loop_without_state_change | 1 |
| refusal_under_high_risk_policy | 3 |
| terminal_refusal_in_fallback_workflow | 6 |

## 违规尝试的事后分解

| 组别 | 被拦截写操作次数 | 其他违规尝试次数 | 曾尝试违规但最终EOC合格的任务 |
|---|---:|---:|---:|
| B0 | 8 | 3 | 11 |
| B3 | 0 | 3 | 3 |

EOC检查预期终态与证据，不会自动把所有被工具拦截的尝试都改判任务失败。最终正确拒绝可能发生在一次错误写入尝试之后。此表补充解释既有安全指标，不修改冻结的成功定义；任务、工具、错误、发起者和状态变化详见policy-attempts.json。

## 所有改善、退步及原B3失败的逐任务对照

| task ID | 任务族 | B0合格 | B3合格 | B3 Skill次数 | B0证据类型 | B3证据类型 |
|---|---|---|---|---:|---|---|
| task-0f2e6230e33cbbc84a33 | composite | False | False | 0 | terminal_refusal_in_fallback_workflow | terminal_refusal_in_fallback_workflow |
| task-5eeef59f4f18bb33e25a | composite | False | False | 0 | terminal_refusal_in_fallback_workflow | terminal_refusal_in_fallback_workflow |
| task-b60ecc538d8e070a8d9f | modify_address | False | False | 0 | refusal_under_high_risk_policy | refusal_under_high_risk_policy |
| task-b95460321498eca119e7 | composite | False | False | 0 | terminal_refusal_in_fallback_workflow | terminal_refusal_in_fallback_workflow |
| task-c17a09f971df0bd1b5df | composite | False | False | 0 | terminal_refusal_in_fallback_workflow | terminal_refusal_in_fallback_workflow |
| task-d3ead9a40567953f871c | modify_address | False | False | 0 | refusal_under_high_risk_policy | refusal_under_high_risk_policy |
| task-d478c779bf7872d3b65c | modify_address | False | False | 0 | refusal_under_high_risk_policy | refusal_under_high_risk_policy |
| task-d60cfa170ca38357da3f | refund | True | False | 0 | — | read_loop_without_state_change |
| task-dbf30af1850d882777b0 | composite | False | False | 0 | terminal_refusal_in_fallback_workflow | terminal_refusal_in_fallback_workflow |
| task-f68475e6f8b33f36a3e7 | composite | False | False | 0 | terminal_refusal_in_fallback_workflow | terminal_refusal_in_fallback_workflow |

## 相同起始输入的一致性检查

15例具有完全相同的首个模型context；其中动作序列相同15例、结局相同15例、EOC判定相同15例。详细任务见transport-controls.json。该检查帮助观察服务路径差异，不证明所有后续上下文或延迟完全相同。

证据：configs/reuse-ablation.json预声明范围；results/reuse-ablation/main-v3包含逐任务检查点、身份、汇总与中断记录。重新生成报告会先重算全部检查点与Expected Outcome判定。
