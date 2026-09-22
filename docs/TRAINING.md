# 本地后训练与恢复

本阶段交付目标是实际QLoRA SFT / DPO适配器权重及同协议独立评测。训练完成以对应`result.json`和通过哈希校验的`adapter_model.safetensors`为准；存在代码或数据不等于完成训练。

2026-09-17：正式main-v2 SFT已完成90步、DPO已完成12步，两个adapter均实际更新。Base/SFT/DPO独立评测已恢复运行；模型效果尚未得出最终结论。

重复稳定性方案在新test结果产生前冻结为`configs/stability.json`：三类Skill×A/B/D/E各取task ID字典序首例，共12例，每模型累计3次。后台`python -m scripts.finish_research_evaluation`等待主流水线完成后获得同一GPU锁，再串行补跑Base/SFT/DPO各24次、生成`docs/RESEARCH_REPORT.md`及PNG/SVG图表。它使用相同greedy设置，报告pass_all_repeats，不声称pass@k或统计独立性。

研究评测全部完成后可手工运行`powershell -File scripts/deploy_trained_project.ps1 -Stage SFT`部署指定Student。自动交付使用新test开始前声明的`configs/deployment-selection.json`，仅按validation选择SFT或DPO：实际违规必须为0，再按EOC合格率、决策准确率、较少LLM调用排序，完全同分优先SFT。两种权重仍全部进入test，不按test选择部署模型。部署脚本核对权重身份与发布证据，只停止PID记录中属于本项目的旧工作台；部署后还必须执行真实任务验收。成功部署标记让根目录启动项目.cmd以后自动恢复相同模型；评测期间不会额外启动Ollama争用GPU。

## 数据与监督来源

- 真实自由Action语料：`results/training-data/free-action-v2`，74条真实轨迹筛出181个动作目标。
- 显式契约教师：`results/training-data/contract-supervision-v1`，69条Runtime轨迹，186个SFT目标，其中33个Skill动作。它是确定性监督，不是模型实验成绩。
- 反事实偏好：从同一个SQLite数据库备份和同一个模型上下文分别执行Skill / refuse / escalate，按原Expected Outcome Contract独立验收。135个分支形成90对偏好；高风险正确escalation不被错误替换为refusal。
- 合并去重355个SFT样本。原始真实轨迹、教师轨迹、反事实分支及文件哈希全部保留。训练输入不含fixture、expected、完整环境快照或verifier答案。
- 只用冻结train任务；validation用于独立检查，test在模型冻结后运行。故障和权限不足案例不进入该固定候选反事实偏好，已明确记录跳过原因。

## 环境与模型

训练使用独立`.venv-train`；现有`.venv`运行工作台和Ollama适配器。

模型固定为官方Qwen/Qwen3-4B，revision `1cfa9a7208912126459214e8b04321603b3df60c`。原始safetensors下载到`.runtime/hf-models/Qwen3-4B`，验证官方LFS SHA-256；不把GGUF推理文件作为可训练权重。

依赖版本见`requirements-training.txt`；安装成功后生成完整`requirements-training-lock.txt`。GPU兼容性检查要求真实CUDA NF4前向和反向均产生有限非零梯度，不能只用nvidia-smi判断训练兼容。

参考依据：[bitsandbytes Windows/CUDA安装](https://huggingface.co/docs/bitsandbytes/installation)、[PEFT量化训练](https://huggingface.co/docs/peft/en/developer_guides/quantization)、[Qwen3接口与logits_to_keep](https://huggingface.co/docs/transformers/v4.57.1/en/model_doc/qwen3)、[Trainer checkpoint接口](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/trainer)。依赖是否实际兼容仍以本机测试为准。

## 训练协议

当前配置`configs/training.cudnn.json`：NF4双量化、BF16计算、LoRA rank8 / alpha16、all-linear、dropout0、单GPU microbatch1、梯度累积8、最大8192 token。SFT两轮，DPO一轮，seed42。当前355个样本全部保留，最长4366 token；过长样本如出现则显式记录ID，不能静默截掉目标或上下文。

原`configs/training.json`及main-v1结果保留。Windows wheel没有Flash Attention，原完整smoke训练部分1097.6秒、峰值15.39GB；显式选择cuDNN后，相同8个最长样本39.6秒、峰值6.61GB。内核输出/梯度一致性和缓存生成已验证。main-v2显式继承原checkpoint-10的模型、优化器、调度器及RNG；父run和checkpoint逐文件哈希写入新run，不修改旧版本身份。

SFT只计算assistant目标损失；输入使用与本地HF推理相同的Qwen3 ChatML和空think前缀。尾部logits投影与完整causal likelihood等价，减少大词表的显存占用。

DPO以SFT适配器为初始policy和固定reference，先缓存完整的chosen/rejected completion log概率，再更新policy。目标为标准sigmoid DPO，beta0.1，reference绝不偷偷换成未训练Base。

训练保存optimizer / scheduler / RNG checkpoint；resume要求相同配置、语料、初始SFT权重和训练实现。完成后验证参数有限且确实更新，保存适配器SHA-256。smoke权重单独标记，不能当正式SFT交付。

单步smoke选择最长完整样本检查显存，并禁用学习率预热以保证唯一一步能够更新权重；正式训练保留5%预热。长度过滤后统计SFT动作及来源覆盖，若全部Skill目标被过滤则停止，不生成虚假的Skill学习结论。

## 操作入口

新机器先创建两个venv，安装基础项目依赖，并下载固定CUDA wheel和完整模型。以下为Windows/Python3.10路径；已有文件会校验/复用，已有后台流水线时不要并行启动第二份。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
python -m venv .venv-train
.\.venv-train\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python scripts/download_torch.py
.\.venv\Scripts\python scripts/download_training_model.py
```

```powershell
.\.venv\Scripts\python scripts/prepare_supervision.py --dataset data/experiment-v1 --bundle results/real-v2-frozen/frozen.json --output results/training-data/新的监督版本目录
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_training.ps1
.\.venv\Scripts\python -m scripts.run_training_pipeline
```

当前配置的正式产物根目录：`results/training/main-v2`，评测根目录`results/post-training/main-v2`。流水线已运行时不要启动第二份；进程锁会拒绝多个协调器。监督数据已经存在时跳过prepare_supervision命令；配置中的main-v1父checkpoint须保留。

手工执行或恢复指定阶段：

```powershell
.\.venv-train\Scripts\python scripts/train_student.py --config configs/training.cudnn.json --stage sft --output results/training/main-v2/sft --resume-checkpoint results/training/main-v1/sft/checkpoint-10 --resume
.\.venv-train\Scripts\python scripts/train_student.py --config configs/training.cudnn.json --stage dpo --sft-adapter results/training/main-v2/sft/adapter --output results/training/main-v2/dpo
```

## 评测与服务

顺序为smoke → SFT → DPO → 三模型validation → 冻结 → 三模型test → DPO去Gate消融 → 汇总。每个模型均进行Full System和Decision-level检查；评测任务逐个落盘，resume核对模型、数据、代码身份。

Base / SFT / DPO均使用同一HF-NF4推理协议、v2 prompt、贪心解码与512 token输出预算。HF生成不使用Ollama的JSON约束采样，因此结果与旧Ollama/Q4实验分开报告。原始B0–B3已在后训练之前完成，不能用新量化后的Base数字覆盖原实验。

适配器完成后可启动本地私有Student：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_trained_student.ps1 -Stage SFT
```

服务地址8002，仅绑定localhost；加载固定适配器并串行生成，要求冻结v2消息协议，错误不使用脚本fallback。`configs/model.hf-sft.json`供自由Action客户端连接，受限菜单演示继续使用原Ollama协议。

另提供`configs/model.hf-base.json`与`configs/model.hf-dpo.json`。通过`SKILLFORGE_MODEL_CONFIG`选择配置后重启工作台，界面会按实际适配器关闭不兼容的菜单协议。私有服务的实际权重身份在任务提交和每个生成响应中核对，防止同名模型被替换后混写轨迹。训练期间工作台预留GPU，报告和历史仍可查看；`scripts/start_project.ps1 -DashboardOnly`仅启动工作台，不加载Ollama模型。

## 持久进度

- `docs/TRAINING_LIVE.md`：协调器自动更新的实时文档。
- `.runtime/training-bootstrap.json`：安装、GPU和loss测试阶段。
- `.runtime/training-pipeline.json`：当前子进程和日志。
- `results/training/main-v2/<stage>/progress.json`：step、epoch、loss、耗时、显存及checkpoint。
- 工作台`/api/v1/training`和“交付状态”读取这些实际文件，不靠手工写死已训练状态。

故障记录统一保存在`docs/ISSUES.md`。当前尚未声称训练、部署及最终评测完成。

## 完整交付包

`python -m scripts.package_project --check-only`核对正式权重、数据审核、父checkpoint、同协议评测与当前源码是否一致。仅全部通过后，`python -m scripts.package_project --output release/SkillForge.zip`才会生成包含源码、数据、适配器和评测证据的归档，并逐文件回读校验SHA-256。基础模型和CUDA运行时通过上述固定下载脚本准备，不重复塞入源码交付包。
