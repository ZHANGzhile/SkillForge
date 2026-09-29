# 动作级反事实评测（2026-09-29）

本轮补齐相同决策上下文与状态下的动作干预。此前B0/B3消融同时取消Skill与Gate，不能识别一次Skill执行的负迁移。本实验不改旧NTR字段，不训练、不改prompt、不选择部署版本。

## 预声明范围

- 从main-v3冻结新实例test的全78条轨迹扫描所有实际Skill动作，不按结局筛选。支持地址/取消/退款；前缀必须只有读取，Skill在当时确实被提供，且总16步预算内仍有模型续跑空间。全部排除原因单独保存。实际源数据有15个可支持调用点。
- 每个调用点先CPU重放读取前缀与Gate补查，要求每步context逐字段一致；记录完整SQLite SQL dump、业务状态、剩余故障队列和已经发生的工具调用数。随后两臂各自从fixture重放到该调用点，完整状态必须等于同一冻结快照。
- 在相同调用点只干预下一动作：一臂执行原Skill，另一臂执行对应primitive mutation，参数与原Skill绑定一致。两臂随后均由同一个固定权重HTTP模型选择全部动作；保留同样的Skill候选、Gate、policy、重试和总步数预算。primitive臂后续仍可选Skill，因此这是单次动作干预，不是整个运行禁用Skill。
- 原轨迹前缀与分叉动作由实验控制，不计作模型推理。真实续跑请求才计入llm_calls与token；总decision_calls仍包含重放/强制步骤。工具与模型续跑成本分别说明分母。
- 同一上下文两臂交替先后顺序，各运行一次确定性续跑。HTTP故障、身份变化或重放不一致停止实验，不把未完成记录计作模型失败。完整分支可恢复且先审核，禁止挑选重跑结果。

## 指标与解释限制

记录Skill成功/primitive成功、改善/退步与实际违规。`observed_reuse_counterfactual_ntr`定义为primitive成功而Skill失败的上下文数，除以primitive成功上下文数；若分母0则null。另列全部入选上下文分母上的退步率。

这只是在本模拟器、固定模型续跑、可重放的已观察Skill使用点上的动作反事实估计。原模型没有选择Skill的任务、没有被提供的Skill、其他模型/策略、训练分布之外的上下文均不在推断范围。不能把15个上下文的结果推广成全78任务或总体因果NTR；`population_causal_ntr`保持null。旧10例B3失败是否修复，也不能由这轮试验回答。

新结果位于results/action-counterfactual/main-v3，不覆盖旧报告。运行：`.venv/Scripts/python -m scripts.evaluate_action_counterfactual --resume`；只读审核：追加`--audit-only`。所有预声明配置和代码hash绑定检查点，实时进度写入docs/ACTION_COUNTERFACTUAL_LIVE.md。
