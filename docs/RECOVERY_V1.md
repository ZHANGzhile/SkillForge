# main-v3 恢复训练与产品验收

启动日期：2026-09-25。目标是处理main-v2真实服务验收中的退款漏验证与重复读取问题；当前尚未证明新权重已修复这些问题。

## 保留已有研究结论

main-v2训练权重、69例validation、78例test、消融、稳定性及4/6服务验收全部保留。核心Runtime、Gate、工具policy、Verifier、自由Action提示、HF推理协议和训练器源码未改动。configs/training-runs.json继续描述原main-v2；新计划单独放在configs/recovery-runs.json。

## 新训练数据来自哪里

只使用原冻结数据集的69个train任务，以及原有明确标注的契约教师和真实模型动作来源。每个train任务实际执行15种轨迹：5种只读前缀，分别接优先Skill、primitive工具、primitive写入后插入读取三种路径。新增1,035条轨迹均由原Verifier确认符合EOC，没有实际违规。

这些是确定性教师轨迹，llm_calls=0，不冒充模型成功轨迹。prefix及写后插入的读取只制造上下文，不作为SFT目标；只有后续实际执行并通过验收的教师动作才纳入。这样可教授冗余读取之后选择Skill、执行mutation之后回读验证，而不奖励人为注入的重复读取。

原186条教师目标加新增1,911条目标，再与原真实模型样本合并去重，为1,267个SFT样本。原90对same-context DPO数据完整保留，但本轮先验证新的SFT候选，不预设DPO一定改善结果。

生成命令：

```powershell
.\.venv\Scripts\python -m scripts.prepare_recovery_supervision --output results/training-data/recovery-v1
```

目标目录不可已存在。manifest记录父语料哈希、生成脚本哈希、全部文件哈希和注入步骤。load_training_data重新核对train归属、任务指纹、来源轨迹、动作上下文和最终结局。

## 训练与选择预声明

- 配置：configs/training.recovery-v1.json；输出：results/training/main-v3。
- 沿用原Qwen3-4B/NF4/cuDNN、LoRA r=8、两轮SFT和相同优化器设置；从基座重新训练，不冒充原checkpoint续训。
- 先对最长完整样本做一次真实GPU更新smoke，再正式训练。语料增加会带来更多更新步，所以不能把收益严格归因于数据内容而排除计算量变化。
- 完整运行原69例validation系统任务、固定候选决策和141例held-out likelihood。新候选至少达到已部署main-v2 DPO的63/69 EOC，且实际违规为0，才进入产品验收；不根据test选模型。
- 恢复入口：`.venv-train/Scripts/python -m scripts.run_recovery_pipeline`。使用原GPU进程锁，不与其他训练/服务争用GPU；现有阶段先审核身份再复用。

## 新评测边界

原test已被查看，其后运行只能作为回归，不能重新宣称从未看过。新实例集data/recovery-holdout-v1已在本轮训练前生成并冻结，seed=20260925，test为78例。它沿用已知任务生成器和结构族，因此属于新实例泛化，不是未知业务或未知结构证明。该目录任何分区都不进入本轮optimizer。

模型选择后应在冻结的新实例集进行Full System / Decision-level评测，并继续原六项真实HTTP验收。失败时保留原记录，不替换退款样例、不降低验收门槛、不让脚本代替Student作答。部署、浏览器签收和完整包仍须以实际通过为准。

## 进度与证据

实时子阶段：.runtime/training-pipeline.json与docs/TRAINING_LIVE.md；本轮总状态：.runtime/recovery-pipeline.json。训练与验证完成后再给出新模型成绩。
