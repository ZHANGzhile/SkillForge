# SkillForge 实施进度

更新时间：2026-09-22（Europe/Paris）

**GitHub归档已完成：** ZHANGzhile/SkillForge私有仓库main分支已推送，研究快照提交9a8be059e4b927a92102b4edb2d789426de81a66。源码及8,651个持久数据/结果文件完整上传；从GitHub独立clone后，全部2,694,303,932字节产物逐文件大小与SHA-256一致，65个LFS路径对应46个独立对象，LFS fsck通过。本机回归99 passed、1 skipped，首次远程Windows/Linux CI均通过。校验回执：results/github-publication.json。仓库归档完成不改变产品HTTP验收4/6的事实。

**最新核验：研究评测已完成，产品交付未通过。** 同协议test为Base35/78、SFT57/78、DPO55/78、DPO去Gate59/78；三组稳定性已完成。HF DPO工作台HTTP验收4/6，失败为普通退款缺写后验证、自定义退款耗尽步数；交付协调器因此停止，未生成最终签收ZIP。详见[量化结果](QUANTITATIVE_RESULTS.md)。下方执行记录保留历史时间顺序。

## 已确认范围

有限可执行 Skill DSL；三态 Gate；UNKNOWN 查询成本计入；写工具幂等与事务内策略复检；Expected Outcome Contract；违规尝试与实际违规分离；全生命周期数据隔离；action-level SFT；same-context DPO；细化 NTR；最小 executor 前置；Student 仅兼容性 smoke test 前置；B0–B3 先于正式后训练；系统/决策双评测；边界学习必须使用成功轨迹、失败轨迹和业务策略。

## 阶段状态

| 阶段 | 状态 | 验收 |
|---|---|---|
| M0 契约与基础工程 | 首轮完成 | 设计约束、Pydantic schema、配置、venv 已建立；Docker 引擎未启动 |
| M1 可执行环境 | 首轮通过 | SQLite、幂等、policy、verifier、故障注入；12 项 pytest 通过；领域完整性继续扩展 |
| M2 Agent 与基础 Benchmark | 工程闭环与真实模型集成通过；效果待改进 | GPU推理与Action smoke通过；真实train五例结局合格1/5 |
| M3 Skill 与 B0–B3 | 三类Skill已冻结；真实模型使用Skill环节未达标 | 完整真实五组已运行，但实际Skill调用为0，未证明复用收益 |
| M4 完整评测 | 首次真实五组及决策探针已完成 | 390个系统任务；Decision-level 0/48、跳过15；单次合成环境评测 |
| M5 SFT / DPO | 正式SFT与DPO完成，恢复后训练评测 | SFT最终90步、DPO12步，正式adapter均实际更新并保存；验证入口导入故障已修复，效果结论仍待独立评测 |
| M6 展示与交付 | 正式工作台本轮验收通过，整体项目未完成 | 自定义 / 数据集任务、持久队列、事件、取消、恢复与隔离重试；65 项测试，6 个真实模型网页任务 |

## 执行记录

### 训练完成与评测恢复（2026-09-17）

- 22:58逐条审核SFT validation全部69个系统任务：EOC60/69（86.96%）、Skill调用16、适用精度1.0、实际违规0；模型违规尝试2/69，自动Gate权限尝试3/69。9个失败均耗尽16步，其中地址1个、退款8个。固定候选决策与held-out likelihood仍在运行；此时不宣称完整validation或test结束。
- 新增只读训练动作分布诊断，重新审核355/90语料哈希：get_order目标73、Skill目标33，全部system prompt均匹配v2；DPO对照动作仅Skill/refuse/escalate。面试复盘第28节逐步分析一个正常退款循环，区分已证实原因和未验证假设；没有修改当前模型或冻结评测协议。
- 22:40源码独立回归98 passed、1 skipped，核心执行源码哈希与冻结评测一致。真实浏览器桌面/手机检查无横向溢出、无JS错误，训练期提交禁用及历史/报告访问通过。新增检查覆盖验证结果篡改检测、Windows共享冲突有界恢复、validation-only部署选择和真实HTTP验收接线。
- 22:32在新test尚未开始时声明自动部署选择策略：仅比较已审核validation的SFT/DPO，要求实际违规0，以EOC合格率、决策准确率、平均LLM调用和固定同分顺序排序。替代自动流程此前固定SFT展示选择；不改变训练配方、test任务或两模型完整比较。来源与策略哈希将冻结在deployment-selection.json。
- SFT验证首9例全部合格且真实调用3次Skill；随后PROCESSING边界出现重复读取直至16步耗尽，已记录失败。不能将首批成功外推为总体能力；仍按冻结协议跑完。

- 22:24用户继续后，核对三个旧协调进程均退出，获准恢复主评测、稳定性及交付协调器。先前恢复请求因账户用量使自动审批无法完成，未绕过。
- Base验证已实际完成69个系统任务：EOC合格35/69、Skill调用0、实际违规0；固定候选决策3/45，15例按协议跳过。likelihood在131/141进度更新时遇Windows文件共享冲突，检查点保留，本轮只补剩余打分。
- 针对进度文件共享冲突加入有界恢复，CUDA/模型/身份不匹配等错误仍立即停止。最新源码独立回归91 passed、1 skipped；新增恢复与入口8项定向检查通过。

- 16:45主Base系统验证已60/69。完整交付协调器`.runtime/release-delivery.json`已启动，等待研究评测后自动执行SFT本地部署、真实HTTP验收、浏览器刷新/移动端/报告验收、源码回归和ZIP逐文件校验。任一步失败停机留日志；当前未提前标记最终交付完成。

- 16:38源码独立回归90 passed、1 skipped，核心源码hash保持与当前评测一致。真实浏览器验证桌面/手机无横向溢出、无JS错误，训练期间禁用提交、历史可读，正确显示SFT/DPO权重已生成且独立评测未完成。
- Base-validation已实际保存34/69个系统任务；这是部分进度，不作为整体验证结论。先完成全部系统、固定候选决策和141个held-out likelihood目标，再进入SFT与DPO。
- `configs/stability.json`已在新test评测之前固定12例（三类Skill×A/B/D/E），累计各3次；后台finish_research_evaluation等待主流水线完成后取得同一GPU锁串行执行。未完成的重复结果不报告为稳定性成绩。
- 已生成`docs/RESEARCH_REPORT.md`与真实基线/训练曲线PNG、SVG，来源哈希另存；完整test之后自动更新对照与错误分析。绘图依赖固定为matplotlib3.10.8，不影响训练环境。
- 新增私有模型部署及真实HTTP验收脚本；尚未部署和运行该验收，不将脚本存在当作验收完成。根启动脚本在活跃GPU评测期间不再启动Ollama。

- 已交付面试用完整复盘 `docs/PROJECT_INTERVIEW_TRACE.md`，包含27节机制、trace、设计原因、负结果、追问和证据导航。
- 核验 main-v2 正式训练结果：SFT 从 checkpoint-10 续训至90步，完成2轮；DPO完成12步、1轮。实际 adapter_updated=true，峰值分配分别6.74GB和8.59GB。训练完成不等于独立任务效果提升。
- 流水线在 Base-validation 启动前因 `from scripts.validation_loss` 的模块路径失败，尚未开始模型验证。改为 `python -m scripts.*` 启动训练、评测和汇总；不改已冻结训练源码、配方或语料。
- 入口子进程、评测恢复/篡改检测、验证集隔离共9项回归通过。入口测试移除PYTHONPATH，实际启动各模块的--help，覆盖此前单元测试漏掉的进程边界。
- 16:24隐藏后台恢复流水线，先审核已完成权重与训练身份，再进入Base/SFT/DPO验证；实时状态继续由TRAINING_LIVE.md自动维护。

### 完整训练链路（2026-09-16，进行中）

- 21:49用户要求继续：确认先前Python进程已退出。完整8.06GB模型此前已通过SHA-256校验；训练依赖和真实NF4前后向通过，GPU/loss/supervision共6项检查通过。原完整Qwen smoke真实更新权重，正式SFT中断前17/90步，持久checkpoint为10，未保存的11–17步需重算。
- 原smoke耗时约1098秒，峰值分配15.39GB。定位Windows PyTorch无Flash Attention以及默认GQA注意力路径；本机cuDNN完整模型最长4366-token前后向约5.32秒、峰值6.55GB，有限非零梯度和KV-cache生成均通过。证据results/training-environment/cudnn-full-model.json。
- 新配置configs/training.cudnn.json保持355个完整样本、33个Skill目标、两轮SFT、一轮DPO和优化器设置，仅显式选择cuDNN。configs/training-runs.json转向main-v2，原main-v1产物、源码和计划快照保留。
- 从main-v1/sft/checkpoint-10继承模型/optimizer/scheduler/RNG时，强制检查原run hash、相同语料/训练配方、完整checkpoint文件并记录每项哈希；不修改旧run身份。内核输出/梯度一致性、迁移约束及Student接口5项训练环境测试通过。
- main-v2流水线与工作台已隐藏后台启动；先新smoke，再续训SFT、DPO、validation冻结与test双评测。进度以docs/TRAINING_LIVE.md及/api/v1/training为准。
- 13:44源码独立性检查通过：复制源码到新目录，明确排除data、results、.runtime和本机model.local.json，仍为79 passed、1 skipped。工作台测试现自行创建隔离数据；记录results/workbench-acceptance/clean-checkout.json。CI已配置Linux/Windows矩阵，但远端CI和Docker实际运行仍未宣称通过。
- 13:36完整回归 **79 passed、1 skipped、2条上游弃用warning**。新增私有Student适配器身份绑定、训练期间GPU预留、评测恢复/报告核验和下载超时保护；浏览器实测桌面/手机布局、训练禁用提交及历史记录访问通过，证据results/workbench-acceptance/training-ui.json。
- 13:31真实CUDA BF16矩阵前向/反向通过，PyTorch2.10.0+cu128识别RTX5070 / sm120，有限梯度已验证；结果results/training-environment/torch-cuda-smoke.json。这还不是bitsandbytes NF4或完整Qwen训练验收。
- 工作台已重新上线http://127.0.0.1:8080；交付状态显示中文阶段、官方安装包/模型下载进度和实际训练状态。训练流水线运行期间暂停新的真实模型任务，防止单GPU争用，报告/历史不受影响。
- 13:25官方CUDA PyTorch wheel全部342个分片到齐，整体SHA-256为14d2831b9292c3a9b0d80116451315a08ffe8db745d403d06000bc47165b1f9e，校验通过并自动进入安装阶段。此前末尾两个分片延迟约14分钟；尝试恢复时原进程已正常退出，所有权检查使操作安全停止，没有重复下载。
- 后训练报告现与冻结适配器、运行配置、完整任务指纹及逐条检查点核对；CUDA基础设施故障单独落盘并终止评测。新增3项报告/恢复/故障回归及2项分段下载回归通过。
- 13:19续跑：现有分段下载、环境bootstrap与串行流水线仍存活。PyTorch已完成320/342个分片，模型两大分片已完成128/472和112/476；这些是下载进度，不是训练进度。
- 修复单步smoke预热吞掉唯一更新步的问题：smoke禁用warmup，正式训练保留预声明的5%预热；DPO参考打分与训练统一TF32设置。
- 评测检查点增加执行身份和内容哈希，恢复时校验任务指纹及Skill候选；完成文件存在不再直接视为已验收。全部业务环境回归72 passed、1 skipped（无torch）、2条上游弃用warning。
- 可选Xet下载客户端安装被自动审批服务因额度限制拒绝，未执行、未绕过；继续使用此前获准并已启动的分段下载和训练准备流程。
- 用户要求在已授权范围内持续执行至用量窗口结束，不逐步等待确认。
- GPU RTX5070 12GB、驱动610.88；C盘约277GiB可用。WSL无已安装分发版，采用Windows原生训练路径。
- 正在建立独立.venv-train；不修改已运行的.venv推理服务依赖。PyTorch目标2.10.0 + CUDA12.8，官方bitsandbytes文档列出Windows CUDA12.8 / sm120支持。
- 首次安装因旧pip依赖名称归一化失败而误走源码包，继而在CUDA专用索引找不到flit_core；升级训练venv的pip后重试。
- 数据方案：保留原181条真实模型样本，另建显式标注的verified-contract teacher监督集与真实执行的same-context反事实偏好；不将确定性teacher伪称LLM轨迹。
- contract-supervision-v1已生成：69条确定性运行，186个动作目标（33 Skill），135个实际反事实分支形成90对DPO偏好；跳过权限不足和故障序列的反事实分支，故障仍保留在Runtime监督中。
- 新training_data审核逐一校验manifest、文件哈希、train归属、任务指纹、实际verifier结局、SFT目标与执行一致性、偏好的相同上下文/数据库快照。与原181条真实样本合并去重为355条，corpus_hash=2b45c94a6c783be6808c6d0591650db7dd778fa9e23b974fa106f7894303c203。
- 已实现Windows单GPU NF4 QLoRA训练：只学习assistant completion，尾部logits投影节省显存；SFT与DPO checkpoint恢复、SFT reference log-prob缓存、配置/数据/权重版本绑定、非有限参数与未更新权重拦截。
- 已实现Base/SFT/DPO同HF-NF4协议评测和去Gate消融、逐任务恢复、模型冻结、配对变化与错误汇总；与旧Ollama/Q4数字明确隔离。
- 私有Student服务入口已实现（8002，要求冻结v2消息协议），接口错误不使用脚本fallback；权重尚未下载完成，暂未部署该服务。
- 12:50用户再次要求恢复；已确认原Python进程全部退出。复用已下载分片，以隐藏后台进程重启下载。大文件单连接停滞改为分段并发，按官方长度与SHA-256校验。
- 当前依赖准备与完整串行训练流水线已在后台运行，任一步失败即停止。实时文档docs/TRAINING_LIVE.md由流水线自动更新，工作台/api/v1/training同步读取真实阶段状态。
- 基础环境全套69项通过（torch数学测试在无torch环境显式skip），新增私有服务与工作台定向5项通过。GPU实际反向传播与完整模型训练smoke仍在等待依赖/权重，不提前宣称通过。

### 正式研究工作台与持久任务（2026-09-16，本轮验收通过）

- 用户明确最终交付为完整项目。演示只保留为验收案例；本轮把正式入口改为研究工作台，完整交付仍须包含 QLoRA SFT、DPO 权重及训练后双评测。
- 已实现 SQLite 持久队列、单工作进程锁、任务输入 / 模型配置 / 代码 / Skill 包版本绑定、逐工具与逐决策事件、取消、隔离重试、轨迹与业务数据库下载。
- 正式任务入口支持冻结数据集全部 216 个任务及自定义 Task / Expected Outcome Contract；自定义数据标记 manual-unregistered，不能伪装为冻结 train 来源。
- 自由 Action 的 B0–B3 / 去 Gate 与受限 Skill 目录协议独立选择、独立标注。恢复的 queued 可执行，原 running 标记 interrupted，不重放已提交 mutation。
- 新增 8 项关键边界测试通过：并发重复提交、同键异参冲突、进程恢复、队列 / 执行中取消、模型返回后取消不写入、退款提交后取消保留唯一账务、手工任务来源隔离、配置漂移。
- 首轮测试暴露 Windows 文件区域锁读冲突及审计字段名误用，已修复。原 50 项回归通过；正在进行正式入口真实模型、网页和重启验收。
- 本轮不将演示 27/27 外推为完整研究结论；正式训练和最终项目验收尚未完成。
- 9月15日重启请求曾因自动审批服务额度耗尽被拒绝，未绕过限制；9月16日用户要求继续后只读确认服务归属，再获准重启。
- 正式入口现为 http://127.0.0.1:8080；根目录启动项目.cmd启动服务及浏览器，原演示保留。
- 浏览器真实 Student 验收 **6/6**：地址、取消、退款、拒绝、转人工及自定义已有退款案例。4个正常完成案例各执行1个Skill，两个边界案例分别拒绝 / 创建人工工单；全部无违规尝试或实际违规。
- 自定义退款：初始已退500，本次250，累计750，业务账务新增1笔，来源为manual-unregistered。下载、刷新恢复、Registry、报告、桌面 / 手机无溢出及无浏览器脚本错误均通过。
- 网页任务切换旧状态闪现已修复；本轮服务重启实测保留 **13条** 运行记录。异常中断恢复 / 重试语义另由回归测试验证。
- 最终 **65 passed，2条上游弃用warning**。验收详情见docs/WORKBENCH_ACCEPTANCE.md。
- 已导出自由Action的真实SFT语料：74条来源 / 69任务 / 561个原始动作，经action-level筛选为181条；139 tool、13 stop、22 refuse、7 escalate，Skill目标为0。正式有效产物results/training-data/free-action-v2，v1因Windows换行哈希问题保留为失败版本。

### 可操作的真实Skill演示（已交付）

- 入口：http://127.0.0.1:8080/skill-demo；双击根目录启动演示.cmd可启动服务和网页。
- 新增受限动作目录协议：真实模型选择Skill/读取/拒绝/转人工，stop要求成功验证回执。错误选择不由脚本代替。
- 地址、取消、退款train九例9/9；validation二十七例27/27，9个正常案例各调用1次Skill，其余正确拒绝或转人工，违规尝试及实际违规均为0。
- 网页三个地址场景实际点击通过、轨迹下载通过、桌面与手机截图检查通过。50项pytest通过。
- 这是新协议的受限流程验收，不替代旧B3结果，不宣称独立泛化提升；详情docs/SKILL_DEMO_ACCEPTANCE.md。

### 真实B0–B3与双评测（执行完成，核心假设未验证）

- 已核验当前ModelClient设置、公开policy及关键代码哈希与上轮decision_config完全一致；重启本地Student。
- 同一78任务test分区五组完成，共390任务：B0 35/78、B1 45/78、B2 38/78、B3 37/78、B3-no-gate 38/78。全部实际违规为0，但存在模型违规尝试。
- 关键缺口：所有组实际Skill调用为0；Decision-level为0/48、15例跳过。不能用系统得分变化宣称Skill复用/边界学习带来收益。
- 评测文件已在9月12日落盘，9月15日才完成汇总交付和状态纠正；之前“进行中”是过期记录。报告docs/REAL_EVAL_REPORT.md；正式SFT/DPO仍未启动。

### 真实决策改进、采集与Skill冻结（本阶段完成）

- 保留原1/5基线，新增v1/v2/v3可重放提示版本、全文与SHA-256记录；每条轨迹绑定实际模型配置。
- train五例：v2为2/5，v3为0/5；保留失败版本，选择v2继续扩大train采集。不是test成绩。
- 实测发现公开policy中CONFIRMED/NOT_STARTED未明确字段，模型误将物流规则用于退款；改为完整字段名并明确领域适用范围，实际业务策略函数不变。
- 全69条真实train轨迹采集并通过来源审计：40/69结局合格，13/69违规尝试，实际违规0；33/69结局合格且无违规尝试。
- 与之前v2五例完整真实轨迹合并为74条；三类Skill均满足成功执行＋业务失败＋policy证据门槛，编译条件未放宽。
- validation契约检查地址27/27、取消15/15、退款18/18；3个Skill已冻结于results/real-v2-frozen/frozen.json，工程脚本来源为false。
- 46项测试通过。完整真实B0–B3/双评测仍待下一阶段；详见docs/REAL_TRAIN_REPORT.md。模型漏验证、重复调用等仍保留为真实失败。

### 本地 Student 部署（服务与集成验收完成，业务效果待改进）

- 用户已授权安装并部署 Ollama＋Qwen3 4B。
- 使用项目内独立 .runtime 目录放置服务及模型，避免依赖系统 PATH；先验证显卡和接口，再使用训练分区做小批真实执行。
- Ollama v0.34.0与Qwen3 4B权重完成下载；完整安装包SHA-256与官方值一致。完整服务监听127.0.0.1:11434。
- RTX 5070实测37/37层在GPU；16K上下文，模型驻留约4.75GiB。正式训练兼容性未验证。
- 修复聊天模板/思考解析兼容问题，使用显式Qwen3 raw适配器；通用OpenAI兼容客户端仍保留。验收smoke：`results/local-student-smoke-accepted/model_smoke.json`。
- 真实模型5个train案例：1/5满足Expected Outcome，2/5发生违规尝试，0/5实际违规；唯一结局合格案例仍有被拦截的违规尝试，不能称为全程正确。结果：`results/local-student/9354139e-ad4f-4a02-b140-06d8dfe41c37`。
- 回归45 passed，保留2项上游弃用警告；未执行正式SFT/DPO。详细失败与下一步见 `docs/LOCAL_STUDENT_REPORT.md`。
- 安装与验证命令见 `docs/LOCAL_STUDENT.md`，下载进度保存在 `.runtime/model-download-status.json`。

### 本地部署准备：硬件检查

- 2026-09-10确认RTX 5070（约12GB显存）、Ryzen 9 7900X、95.1GiB系统可见内存，具备小型量化Student推理的硬件条件。
- 详情见 docs/LOCAL_HARDWARE.md；尚未下载权重或安装推理服务，实际推理/训练兼容性仍待验证。

### 第三轮：退款 Skill 与有界修订（已验收）

- 新增退款金额/剩余额的确定性适用条件、账务后置条件及反例来源。
- 修订最多两轮，仅使用 train 编译证据与 validation 反馈；每次候选与验证结果单独保存，test 不进入修订。
- 扩展三类 Skill 对照入口，保持旧数据集和冻结产物不可变。
- 退款和两轮修订的首批4项定向测试通过；正在验证重试耗尽、无可用修订和三类 Skill 集成。
- 修订限制为领域已支持的边界/执行两类修复，不引入通用 DSL 或另一个 Agent；原候选保持不变。
- 三类 Skill 冻结成功，42项测试通过。两轮修订实际演示保存于 results/round3-repair-demo，v1→v2→v3，12→9→0 个验证失败。
- 三类完整对照1,170次工程执行通过，但退款 Decision-level 首轮0/15，发现脚本额外要求物流观察；新增回归修复，不把完整系统成功率当作决策评测通过。
- 最终 **43项测试通过，2条上游弃用warning**。相同冻结数据五组×78任务×3重复全部通过；决策探针地址21/21、取消12/12、退款15/15。
- 最终产物：`results/round3-comparisons/8a5bee11-0d2c-417f-af8a-2a7245615c89`；失败探针结果保留，未覆盖。
- 本轮报告：`docs/ROUND3_REPORT.md`；两轮修订 CLI 实跑 VERIFIED，超预算和无可用修订情况均有回归测试。
- 仍无真实Student模型实验结果；本轮未启动正式训练。

### 第二轮：实验数据隔离与对照运行

- 本轮目标：版本化实验数据集、真实内容/模板隔离检查、测试独占组合、训练轨迹来源校验、冻结 Skill 后的 B0–B3 对照入口。
- 保留原 24 个 smoke tasks 作为回归集，实验数据单独生成；不将前一轮脚本数字升级为研究结论。
- Skill 编译加强失败证据筛选，增加取消订单领域；继续采用有限 DSL。
- 每完成一个模块先验证，再更新本节结果和 ISSUES。
- 数据集模块已通过：29 项测试通过；实验模式每组实例生成 train=23、validation=23、test=26 个任务，覆盖 A–E 和测试独占三分支组合。
- 环境已支持动态订单/用户/金额，26 个实验测试任务在脚本策略下执行成功；保留原 smoke 回归。
- Compiler/来源审核：33 项测试通过；新增取消 Skill、success-only Naive Skill、业务反例筛选、轨迹指纹和 verdict 复核。
- 冻结对照初跑：B3 75/78，其余配置 78/78。发现 Gate 隐藏重试耗尽，完整失败产物保留于 `results/experiment-comparisons/75207fa2-071d-4cd1-b05a-7bf29544dc74`。
- 修复 Gate 异常观察、耗尽预算和跨 step mutation 幂等后：**36 项测试通过，2 条上游弃用 warning**。
- 同冻结数据五组×78任务×3重复=**1,170 次工程执行全部通过**。产物：`results/experiment-comparisons/c34701a6-41ef-42b8-a22d-eb14cfd0f896`。这些是脚本验证，不是模型研究结论。
- 数据集：`data/experiment-v1/manifest.json`（train=69、validation=69、test=78）；训练源90条（69原任务执行＋21明确标注的失败工程轨迹）。
- 冻结包：`results/frozen-experiment-v1/frozen.json`，包含两个已验证 Skill、独立 Naive Skill、源数据哈希、验证证据。
- 新 CLI：dataset / collect / prepare / compare，支持 --ablation、--repeats；真实模型 compare 先预检连接，避免服务不可用时批量空跑。
- 运行方法与协议：README 的“隔离实验”和 `docs/EXPERIMENTS.md`。
- 补齐 source_code_hash 后最终重跑：`results/experiment-comparisons/680408b2-3c0a-45fa-8bfe-a71aa6ce7c04`，五组各234/234通过。上一轮结果保留。
- 本轮交付报告：`docs/ROUND2_REPORT.md`。Student 再次 smoke 失败，记录在 `results/round2-model-smoke/model_smoke.json`；未开展真实模型评测/正式训练。

- 检查项目：仅有 .git，无已有源码或 AGENTS.md。
- 系统 Python 3.10.11；业务和测试依赖未安装。创建项目独立虚拟环境。
- 每阶段完成后记录实际测试，不以 mock 结果代替模型效果，不伪造训练和评测数据。
- 最小依赖安装完成。`python -m pytest -q`：12 passed；覆盖 commit 后响应丢失退款重试、同键冲突、身份、超额退款、策略复检和验证证据。
- Agent/Benchmark 阶段：首次 23/24 工程任务通过，修复全额退款后的错误资格复检后 24/24 通过。
- Skill 阶段：18 项测试通过；三态与固定只读查询、工具内二次校验、不可变 Registry、禁止任意 DSL 节点。
- 学习管道：20 项测试通过；成功/失败训练轨迹编译、validation 验证、脚本 B0–B3、SFT 导出与 DPO 隔离。
- API 阶段：21 项测试通过（2 条上游依赖 deprecation warning），含后台任务和退款响应丢失端到端测试。
- 最终本轮验收：`python -m pytest -q` → **25 passed，2 warnings，2.59s**。
- `python -m skillforge.cli demo` 实际运行成功：72 个训练正向工程任务、2 个刻意失败训练任务、16 个地址验证案例、4×24 个系统工程案例和 7 个有效决策探针（1 个权限不足案例显式跳过）。
- 最新产物：`results/engineering/38371ff0-cf2d-4086-a2d1-0ba3ef794a77/pipeline_summary.json`。
- 系统工程案例 24/24 通过；全部为脚本策略。指标明确区分 decision_calls 和 llm_calls，脚本的真实 LLM 调用数为 0。
- Student smoke：`results/model_smoke.json`，compatible=false，ConnectError/WinError 10061。
- 本地 Uvicorn 启动成功；真实 HTTP 页面 GET=200，任务 POST=202；退款响应丢失 API 案例已通过自动测试。
- 已提供 README、Dockerfile/compose、CPU CI 配置、requirements-lock.txt；Docker 实跑与远端 CI 均未验收。

## 本轮设计决策与运行方法

- 为尽快验证闭环，使用标准库 SQLite，文件式不可变 Skill Registry；未引入 SQLAlchemy/PostgreSQL 或通用编排。
- 当前使用词项相似度 Raw Memory、地址领域受限 Compiler、固定映射 Gate 补查；这些限制在 README 明示。
- 运行：`.venv/Scripts/python -m skillforge.cli demo`；测试：`.venv/Scripts/python -m pytest -q`。
- 服务：`.venv/Scripts/python -m uvicorn skillforge.api:app --host 127.0.0.1 --port 8080`。
- 修改文件类别：skillforge 核心模块、tests、configs、docs、README、部署/CI/依赖配置；未提交 Git commit。

## 下一阶段顺序

1. 补齐可执行Skill选择的监督目标，明确训练与部署协议；受限目录证据不得静默冒充自由Action的同上下文模型输出。
2. 从train状态构造并验证same-context / same-snapshot反事实偏好数据，保留正负动作及验收依据。
3. 在本机完成训练依赖兼容性检查、可恢复QLoRA SFT和DPO训练，交付实际适配器权重、配置、日志。
4. 冻结训练版本后，按同协议完成Base / SFT / DPO系统和决策双评测、消融、错误分析与复现验收。

## 当前不可混淆的边界

- 已有真实自由Action五组各78任务与Decision-level结果；该协议实际Skill调用为0。受限目录的27个validation与本轮6个网页验收是独立结果，不能混算。
- 原 smoke suite 保留共享模板；新增实验数据集具有内容/实例/模板隔离及 test 独占组合，但仍是受限合成环境，不能据此直接证明真实业务泛化。
- Compiler 支持地址、取消、退款及最多两轮的领域修订；仍无开放域合成及递归 Skill composition。
- main-v2正式SFT/DPO训练与适配器权重已完成并核验；正在执行同协议独立评测与预声明稳定性测试。最终模型效果、私有服务验收和发布包尚未交付，整个项目不标记完成。
