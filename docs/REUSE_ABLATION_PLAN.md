# main-v3无Skill对照实施说明

本轮权重与已发布结果不变。此前68/78的总体结果来自带Skill的系统，而没有该训练模型在相同任务上的无Skill对照，因此不能把提升全部归因于Skill复用。

## 固定范围与指标

- 使用已冻结新实例test的全部78个任务，不按成功、失败或是否调用Skill挑样本；该test已经查看，属于事后分析。
- B3引用已审核的main-v3/fresh/SFT逐任务检查点；B0使用相同adapter、完整服务settings、prompt、任务、工具和步数/重试预算。服务响应指纹逐请求检查。
- B0不提供Skill和Memory，也没有自动Skill Gate补读。这个系统干预会改变观察上下文，所以配对退步率不能标成同上下文动作级causal NTR。
- 输出全任务配对改善/退步、以B0成功为分母的退步率、实际Skill尝试关联、模型违规尝试及环境实际违规；causal NTR保持null。
- B0使用已经部署的HF服务，不重复加载GPU模型。其延迟包含HTTP开销，与旧直接HF检查点不作严格延迟归因。

## 执行与恢复

```powershell
.\.venv\Scripts\python -m scripts.evaluate_reuse_ablation
# 中断后核对所有已有任务的身份、哈希、状态链与结局，再继续剩余任务：
.\.venv\Scripts\python -m scripts.evaluate_reuse_ablation --resume
.\.venv\Scripts\python -m scripts.report_reuse_ablation
```

GPU服务错误、网络故障或模型身份切换单独保存并停止，不作为能力失败记入分母；真实模型输出非法Action按模型失败保存。完成的恢复只重算审核，不调用模型。正式结果只有在全部78例保存并审核后生成。

## 已确认的原B3失败

6个复合流程未执行后续分支，3个高风险与已发货冲突时错误拒绝，1个超额退款循环读取；它们均没有实际Skill尝试。分类只依据已保存的结局、状态与工具证据，不等于确认唯一根因。新对照将检验没有Skill候选及Gate补读时这些结局如何变化。

进度见[实时记录](REUSE_ABLATION_LIVE.md)。本轮不将查看过的test混入训练、不更换已通过验收的部署模型。
