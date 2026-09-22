# 真实B0–B3与双评测报告

运行目录：`results\real-v2-comparisons\24dc744b-1add-43f2-8d2e-2986deb010c7`

同一冻结Qwen3 4B配置、同一78任务test集合，每组一次；无正式后训练。本轮未根据test修改提示或Skill。

| 组别 | 结局合格 | 合格且无违规尝试 | 违规尝试 | 实际违规 | 平均模型调用 | 平均工具调用 | 平均总token |
|---|---|---|---|---|---|---|---|
| B0 | 35/78 | 27/78 | 16/78 | 0/78 | 7.36 | 6.53 | 20458.8 |
| B1 | 45/78 | 34/78 | 22/78 | 0/78 | 6.87 | 6.10 | 24680.0 |
| B2 | 38/78 | 34/78 | 11/78 | 0/78 | 8.60 | 7.79 | 28492.0 |
| B3 | 37/78 | 32/78 | 11/78 | 0/78 | 7.88 | 9.51 | 25935.6 |
| B3-no-gate | 38/78 | 32/78 | 16/78 | 0/78 | 8.51 | 7.73 | 30683.1 |

## Decision-level

固定候选在预先授权读取后交给模型；不适用候选也可见，Gate不能替模型掩盖选择错误。故障或无法完成授权读取的案例跳过。

| 范围 | 正确/评测 | 跳过 |
|---|---|---|
| modify_address skill/refusal/escalation fixed-candidate probe | 0/21 | 9 |
| cancel_order skill/refusal/escalation fixed-candidate probe | 0/12 | 3 |
| refund skill/refusal/escalation fixed-candidate probe | 0/15 | 3 |

## 策略错误发生位置

同一任务可以同时出现在两列；权限/业务拒绝按轨迹错误位置分类。

| 组别 | 原子工具调用错误任务 | Skill内部错误任务 |
|---|---|---|
| B0 | 16 | 0 |
| B1 | 22 | 0 |
| B2 | 11 | 0 |
| B3 | 11 | 0 |
| B3-no-gate | 16 | 0 |

## 逐任务配对变化

以下是相对B0的观察性变化，不能作为已识别的因果NTR。

| 组别 | B0失败→本组成功 | B0成功→本组失败 |
|---|---|---|
| B1 | 11 | 1 |
| B2 | 6 | 3 |
| B3 | 7 | 5 |
| B3-no-gate | 5 | 2 |

## 解读边界

- 本轮所有组skill_reuse_attempts=0，B2/B3/去Gate组均没有实际Skill调用。组间变化不能解释为Skill执行复用收益，NTR相关分母为0。
- Decision-level为0/48：47次选择原子tool，另1次refuse也不符合目标；15个案例跳过。当前模型未遵守固定候选选择协议。
- B0无记忆/Skill，B1检索原始train经验，B2成功经验Naive Skill，B3成功＋失败＋policy且经验证Skill，最后一组去除Gate。
- 系统成绩包含环境策略拦截、Gate读取和Skill executor能力；不能替代模型自身决策成绩。
- 拒绝/转人工按Expected Outcome Contract判断，结局符合仍可能伴随违规尝试。
- 单模型、单次、合成环境；不声称显著性、稳定性或真实业务泛化。
- UNKNOWN、错误复用与成本原始指标在comparison.json/csv；causal_ntr保留null，未将UNKNOWN当作false。
- 详细错误、领域分层和配对任务ID见analysis.json；模型/GPU/冻结配置见serving_snapshot.json。
