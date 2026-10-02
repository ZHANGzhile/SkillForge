# Active Self-Evolution v1：实施方案与验收计划

日期：2026-10-01（Europe/Paris）。状态：已开始实施，完成首批基础模块与开发版纵向闭环；正式研究协议尚未冻结。开发验证与正式研究结果严格分开，进度见 ACTIVE_EVOLUTION_LIVE.md。

本方案先审阅本地实现、历史报告与部分机器可读证据，再对照用户提供的下一阶段指示编写，并按后续五项修改意见修订。本文定义完整验收范围，不代表所有阶段已经完成。Active Self-Evolution v1 的必须范围为 P0–P7：主动 Boundary 学习、正式对照、Retention 与 Evolution 工作台。终态 Policy 学习为独立 secondary experiment；Continual QLoRA SFT 移至可选的 Continual Post-training v1.1，不阻塞 v1 验收。用户已授权按计划逐步实施。

## 1. 当前进度与可复用基础

当前本地 HEAD 为 `8558fc3`，审阅开始时 Git 工作区干净。主要审阅入口：README.zh-CN.md、PROGRESS、DELIVERY_STATUS、RECOVERY_RESULTS、ISSUES、既有边界/退款报告，以及 runtime、schemas、skills、learning、refinement、experiment、environment、policies、workbench、evaluation_checkpoints 和边界适应脚本/测试。

已完成的基础：

- Runtime 保存模型可见 context、Action、工具审计、Skill Event、Gate 补读和 EOC；写工具有事务内权限与业务策略检查、幂等和故障恢复。
- 三类有限程序 Skill、三态 Gate、固定读映射、文件 Registry、validation 准入、轨迹来源审核与数据集哈希已具备。
- main-v3 恢复 SFT 已完成：validation 69/69，新实例 test 68/78，对照旧 DPO 57/78；原六项真实 HTTP 验收通过。仍保留 10 个 test 失败。
- 同权重 B0/B3 为 69/78 与 68/78，支持成本/行为差异，不支持成功率提升。15 个观察到的 Skill 使用点反事实两臂均 15/15，不能外推总体 NTR。
- 边界学习已验证有限条件精化；两个新规则世界的错误放行分别从 6/54、8/56 降至 0，但来自 CPU 固定程序探针，并非自主模型探索。
- HIGH 限定的退款提示 v2 在局部诊断中从 21/24 提升至 24/24，属于人工表达修复，未替换部署，未解决主项目全部失败。

当前缺口：没有自动聚类的 Gap、有限预测假设的概率信念、EIG 选样、预算管理、自动候选版本生成与发布的一体化控制器。既有实验主要由人工确定问题和采样计划。

本次审阅重新运行 `.venv/Scripts/python.exe -m pytest -q`：148 passed、1 skipped、2 个上游弃用警告，耗时 32.57 秒。未重跑 GPU、HTTP 或浏览器验收，也未独立重算全部历史轨迹；上述研究数字来自已审阅的本地报告与部分机器可读回执，不是本次重新产生的实验结果。

## 2. 实施前必须明确的设计问题

### 2.1 六世界必须是真正的策略变化

原 policies.py 已禁止 PROCESSING 物流下改地址，也已禁止 PENDING 订单取消。因此指示文档中的 World A/B 示例不能直接作为新变化。建议改为下面六世界，并在冻结前由 evaluator 验证新旧策略存在可达差异：

| 世界 | 候选变化 | 测试重点 |
|---|---|---|
| W1 | 原本合法退款在 shipment=PROCESSING 时要求转人工 | 新的单字段限制；跨业务字段 |
| W2 | 原本合法退款在 order=PENDING 时要求转人工 | 相同学习器发现另一字段 |
| W3 | MEDIUM 风险且退款金额超过阈值时转人工 | 类别与数值的二条件组合 |
| W4 | PARTIALLY_REFUNDED 且剩余额度低于阈值时拒绝 | 派生数值与二条件组合 |
| W5 | MEDIUM 且 shipment=PROCESSING 时禁止退款 | 两个单条件各自允许、交集禁止 |
| W6 | LOW、CONFIRMED、地址有效等基础约束满足时，允许 PROCESSING 状态下改地址 | 放宽旧边界、false-block recovery |

W1/W2 的规则结构已有历史研究，必须标为已知规则族的新协议验证，不能称从未见过的规则发现。六世界衡量声明空间内的适应，不声称开放世界泛化。

所有组使用同一公开候选域和阈值网格。真实阈值及 gold rule 仅 evaluator / 环境可见。阈值网格由公开金额域或 seed 观察按固定算法生成，禁止把真实阈值专门塞进 learner。

### 2.2 边界判断与终态决策分开

Gate 的 INAPPLICABLE 不等于 refuse，更不等于 escalate。两层研究独立冻结、分别报告：

1. 主实验 `BoundaryPatch`：Skill 是否可执行，支持受限条件新增、替换和放宽。学习证据仅来自实际程序执行成功或工具业务拒绝，输出 executable / not_executable / unknown。
2. 次级实验 `DecisionPolicyPatch`：根据已观测状态产生 allow/refuse/escalate 的规则提示。若使用训练 evaluator 的终态标签，明确称 active supervised learning，单列反馈次数与成本，不能与主实验混合计算收益。

工具业务策略仍由环境执行，learner 不能修改工具 guard。主实验不学习终态补丁，各组沿用统一冻结的终态决策协议；世界表中的 refuse/escalate 是环境规则说明，不作为主学习器标签。次级实验使用统一 renderer，不用正确答案替换模型 Action。边界版本准入与真实 Agent 激活分开记录；边界通过、模型终态失败时可报告边界学习成果，但不能标记完整 Agent 发布成功。

对新世界不能继续把旧 Runtime POLICY_TEXT 作为无条件正确的新规则告知模型。新实验使用所有组一致的版本化 policy view：保留固定安全约束，将可变规则标成旧版本认知；只有获准的学习补丁可以更新该认知。保存原始 context 与实际发送字符串，旧 Runtime 和旧字符串保持冻结。

### 2.3 旧 Condition 不足以表达新假设

schemas.Condition 仅允许 eq/in，现有 forbidden 列表是任一命中即拒绝，不能把两个 forbidden 条目误当 AND。新增独立 evolution schema / interpreter，支持八种类型检查运算符、每条最多两个 predicate 的 conjunction、显式作用域和优先级。未知字段仍为 UNKNOWN；不使用 eval 或任意代码。

不修改旧 Condition 的语义。新协议使用版本化契约外层，复用旧程序执行段；新 Gate 解释新边界。执行适配器只有在新 Gate 允许时才进入固定程序，事务内工具策略始终生效。避免旧 Gate 再次误挡 W6。

### 2.4 原始轨迹不能直接交给学习器

当前 trajectory.initial_state 和 tool_audit.before_state/after_state 是完整数据库审计快照，包含模型未观察字段。增加 EvidenceView，只提供实际工具返回、合法动作参数、允许的 verifier 反馈与必要来源标识。

Gap 检测器可以在获准 seed / exploration / 自然运行诊断中接收 EOC 反馈，但主 Boundary learner/selector 的输入另设白名单，只接受可执行性证据，不传终态正确标签、完整 Task.expected、fixture、hidden state 或 test oracle。主实验的 gap 优先级也不能使用终态 gold 标签；终态诊断与次级实验单独保存。tool error 里的 refuse/escalate 细节在主学习视图中统一映射为业务拒绝。细粒度训练 evaluator 反馈仅供次级实验，显式标为监督反馈并计费。

gate_false_block 没有成功反事实时只能是 suspected；gate_false_allow 需对应业务拒绝证据。缺证据先生成探索需求，不能根据失败结果臆造因果标签。基础设施失败单独处理。

### 2.5 Registry 和策略隔离需要加固

旧 Registry.save 保障同版本不可覆盖，但自身不禁止保存 REJECTED；已有 prepare 负责过滤。新发布入口必须独立核验 VERIFIED、准入回执和父版本哈希。

旧 boundary adaptation 用进程级 monkey-patch 改 eligibility，不适合多世界与工作台共存。新 world/probe 使用独立进程及明确环境适配层，禁止在部署进程改全局策略。业务世界身份不可作为预测特征。

## 3. 模块与数据契约

| 新模块 | 职责 | 可复用基础 |
|---|---|---|
| evolution_schemas.py / evolution_evidence.py | 强类型记录、脱敏可见证据、来源与 split 权限 | schemas、provenance、dataset digest |
| gap_detection.py | 12 类 gap、确定性聚类、严重度/置信度、证据不足标记 | errors、runtime 轨迹与 verifier |
| hypothesis.py | 有限假设生成、类型检查、完整预测语义、等价假设归并 | bounded_boundary_adapter 的有限枚举思路 |
| belief.py | complexity prior、log posterior、熵、可重算历史 | 原子 JSON / 哈希工具 |
| active_learning.py | EIG、成本/风险惩罚、去重、预算与停止 | 新增核心算法 |
| sandbox_probe.py | SQLite clone、固定程序探针、工具 guard、可见 observation | Environment、execute、幂等/故障机制 |
| evolution_boundary.py / evolution_policy.py | 主实验实现边界补丁；policy 模块预留接口、次级实验再启用 | 固定 Skill 程序与表示审计经验 |
| evolution_validation.py / evolution_registry.py | 双层准入、stable gate、发布、激活与回退 | 检查点、Registry 版本机制 |
| evolution.py | 持久状态机、恢复、终止、阶段身份 | jobs / worker / evaluation_checkpoints |
| scripts/run_active_evolution.py | 单命令完整流程、工程与研究模式分离 | 现有模块化 CLI 入口经验 |
| scripts/prepare_active_evolution.py / evaluate_active_evolution.py | 冻结数据、四组对照、只读最终评测 | 原数据集与离线审核模式 |

Gap 至少支持 wrong_terminal、premature_refusal、premature_escalation、read_loop、missing_verification、blocked_mutation、gate_false_allow、gate_false_block、unknown_applicability、skill_execution_failure、policy_disagreement、repeated_failure_cluster。

聚类键包含 family、failure_type、policy epoch、规范化关键已观测状态模式，不以实例 ID 聚类；保留全部 member IDs。重复读取需考虑是否获得新信息、状态是否变化和是否为合法重试。Gap confidence 不冒充校准过的概率。read_loop 等未被 v1 补丁空间覆盖的问题可以检测并标为 unsupported_revision，不强行生成业务边界规则。

控制器状态：DETECTED → HYPOTHESES_READY → EXPLORING → CANDIDATE → VALIDATING → VERIFIED/REJECTED/INCONCLUSIVE → PUBLISHED → REEVALUATED。预算耗尽、假设空间不适配、基础设施失败分别记录，不混成模型失败。

## 4. Belief 与 EIG 的可执行定义

- 假设必须对每个候选有完整预测；条件不满足时使用显式 baseline/default。空间包含 H0=no-change、H1…Hn=结构化规则，以及 H_other=现有空间未建模的解释。
- 为 H_other 显式保留固定先验质量（开发默认建议 0.10，P0 冻结）；其余质量按 exp(-complexity_lambda × predicate_count) 分配给结构化假设，避免候选数量稀释 OTHER。
- 主实验二元有效标签 likelihood 默认 0.99/0.01；H_other 初版采用归一化宽预测 0.5/0.5，并参与 posterior 和 EIG。unknown 是缺少有效证据的状态，不是第三个真实业务类别：保留成本和记录，不按业务反例更新 posterior。若次级实验采用 K 类有效标签，一致为 0.99，其余各为 0.01/(K-1)，OTHER 为 1/K。
- posterior 在报告和 UI 中明确称为“posterior under the declared finite observation model（声明的有限观测模型下的后验）”，不称 calibrated confidence，也不解释为规则有该百分比概率真实成立。
- posterior 使用 log-space 更新。超时、GPU 故障不作为业务反例；重复证据 ID 不重复更新。
- EIG(x)=H(p)-Σ_y P(y|x)H(p|x,y)，其中 P(y|x)=Σ_h p(h)P(y|h,x)。只用预测分布，不执行候选或读取其结果来选样。
- score(x)=EIG(x)-cost_lambda×normalized_cost(x)-risk_lambda×predicted_mutation_probability(x)。成本权重、量纲和估计器在正式运行前冻结。所有元数据读取成本都需记录。
- 探索池向选择器只暴露公开可设定输入与已知字段；隐藏业务状态必须通过读操作获取，并纳入预算，不能零成本扫描完整 fixture。
- 字段集合由公开 schema 与 seed 真实观察的交集初始化。新字段值不在声明域时标为 out_of_support，不在看到 test 后扩域。
- 停止预算保持 max_queries=20、min_information_gain=0.01、无收益 patience 建议 3。成功收敛要求结构化预测等价类的 posterior≥0.95、总熵≤0.15 nat、P(H_other)≤0.05，并通过预声明的拟合诊断；阈值在 P0 冻结。预算耗尽、无信息收益、OTHER 主导或失配导致的停止不记为成功收敛。
- H_other 是失配信号，不是所有未知规则的真实概率模型；有限探针下无法区分的错误规则仍可能得到高 posterior。保留绝对拟合诊断、假设空间外开发案例与独立验证；OTHER 胜出不得生成可发布规则。等价假设按预测等价类汇总。
- 预声明只读 sensitivity check：用 0.90/0.10、0.95/0.05、0.99/0.01 重算同一已保存证据序列的 posterior、候选 EIG/score 排名、首选一致率和理论停止点。不得执行新增查询、重选正式参数或替换主结论。固定轨迹重算不能估计其他参数下完整自适应路径的实际收益，若需该结论应另行预注册实验。

## 5. Sandbox 与安全探索

从一致 SQLite backup 创建隔离 clone，复制必要的 idempotency 与剩余 fault 状态，绑定 world/policy/程序版本。操作完成保存审计和状态哈希后关闭销毁 clone。原库前后逻辑内容必须一致，不只比较单张业务表。

主学习阶段使用固定程序 probe 的最小可执行性反馈；显式终态反馈只用于次级实验。研究主张是控制器自主选样，不冒充 LLM 自主发现实验。CPU 自然任务流与真实模型自然运行来源分别标注；真实模型 seed 和最终 EOC / Decision 双评测仅在 Cost Gate 冻结的清单内执行，不把程序自然流称作真实模型经验。

为验证 false block，探针允许在 clone 中绕过待检验的 Skill Gate，但绝不能绕过工具事务 guard。模型触发尝试、主动探针触发尝试、自动补读分别统计；被 guard 拦截的探测与实际违规分开报告。

## 6. 数据隔离与正式实验协议

默认每世界 seed 12、exploration_pool 80、validation 40、test 80；是否足够覆盖类别、合法状态和可辨识假设，先在非正式开发世界做结构检查，正式结果出现后不改样本数。

新增 stable_validation 40 与 stable_test 80：前者参与准入，后者只在冻结后衡量保留能力。反复用于准入的 stable_holdout 已是 validation，不能再宣称独立 test。所有实例 ID、客户/订单对象、模板文本及内容指纹跨 split 隔离；状态组合泛化另行声明，不能仅靠换 ID 声称新结构。

新 schema 独立表示 seed/explore/validation/test/stable_*，不把旧 Task.split 的三值限制硬改成模糊标签。进入旧 SFT 导出时只能映射获准 seed/explore 为 train，保留真实 origin_split 和 manifest membership。

旧 test、既有失败案例及历史结果仅作设计参考或工程回归，不导入本轮训练证据，也不当新独立 holdout。Learner 进程不加载任何 test 文件；evaluator 在 candidate 与实验身份冻结之后才获得读取权限。

四组共享同一 seed、初始 Skill、候选假设空间、Belief 更新、补丁转换、预算和准入规则：

| 组 | 新证据来源 | 选样方式 |
|---|---|---|
| A No Adaptation | 无更新 | 保留原版本；照常测新世界与稳定世界 |
| B Passive | 预先冻结的自然任务流及其失败 | 不看 EIG；保留公共 seed 正例作锚点，不能通过主动选反例补证据 |
| C Random | exploration_pool | 相同有效池、无放回随机查询 |
| D Active | exploration_pool | EIG-cost-risk 最大化，固定 tie-break |

B 报告自然交互总量与实际学习样本数，不只计算失败样本成本。C/D 共享 max budget 与停止规则；分别报告 early-stop 效率与共同 query 前缀的质量，不能为了凑同样实际查询数强迫已收敛方法继续学习。探索预算按整个 world/run 计数，多个 gap 不能各自获得额外 20 次。

CPU / deterministic 层固定采用六世界 × 五个配对种子 × 四组，完整运行上述数据矩阵；同世界种子配对、执行顺序预声明。真实模型层采用独立规模，不复制整个 CPU 矩阵。

### 6.1 P0 Cost Gate 与独立真实模型协议

在独立开发 smoke 中测平均/P95 耗时、tokens、LLM/tool calls，形成 cost-plan.json；不使用正式 validation/test 成绩裁剪规模。成本清单涵盖模型 seed、更新前后、model validation、最终测试、Decision probes、连续 epoch 和重复运行，冻结总任务数、token/时间预算及有界基础设施重试。

真实模型层独立生成 model_validation、model_stable_validation、model_test、model_stable_test，与 CPU 数据及训练证据隔离。初步规模建议每个 model_test/model_stable_test 各 24，最终数量、分层覆盖、world/seed/repeat 清单在 smoke 后正式冻结。

优先保留六世界、四组，各世界选择一个事前指定的配对种子，禁止按 CPU 成绩挑最佳种子。此时最终 Full System 测试是 6×1×4×(24+24)=1,152 条，仍不包含准入/决策/连续 epoch 成本；若不足以落入预算，在正式实验前统一调整样本数或预声明分层世界子集，并限制真实模型结论范围。不能误以为只把 80 改成 24 就解决了整体成本。

模型 GPU 串行执行。候选未通过 Agent 准入则实际服务仍使用原版本；四组按冻结清单报告部署后效果，不能跳过失败方法。结果出现后不缩规模；预算外中断保存为未完成，按同一协议恢复。主算法结论来自完整 CPU 层，真实模型结果只支持事前冻结子协议覆盖的行为结论。

2026-10-01 开发成本修订：六个独立旧策略开发任务实测平均23.85秒、12,812 tokens，小样本P95为42.38秒。原清单包含全部阶段后为3,672次任务，保守估算43.23小时（不含重试）。在尚未查看任何正式成绩前，将模型层暂定为 W3/W5/W6 三类代表世界、seed=101，每世界每组 model_validation/model_stable_validation 各4，model_test/model_stable_test 各8；加入阶段前后、决策探针、seed和连续epoch后为732次，预留最多74次全局基础设施重试。当前估计含预留约9.49小时、1,033万tokens。保留CPU六世界×五种子×四组。此修订是待新世界Runtime复核的预算草案，不是最终冻结或开跑许可；原清单与原成本回执保留。

独立六世界评估之后，增加预声明的至少两次连续 policy epoch 更新，验证 parent 链、证据时效和遗忘；不能把六个独立 restart 世界直接称为长期持续学习。旧规则已合法失效的状态不纳入“稳定不变规则”保留分母；旧版本回放与当前版本能力保留分别报告。

2026-10-02 开发覆盖修订：小型W6验证出现H0漏测变化的案例，不能算适应成功。数据准备加入不依赖新世界标签的公开组合核，退款38种、地址17种；小split必须显式标记覆盖不完整。当前模型4/8条草案因此不能最终冻结，需重新协调分层覆盖与整体成本，不能直接沿用9.49小时估计宣称门槛已通过。H0保留父版本，禁止作为新修订发布；新候选验证须包含旧边界失效的机会，缺少机会即不准入。

2026-10-02 模型子协议细化：CPU仍保留完整组合核；真实模型按预先选择的W3/W5/W6类型，另用独立8类代表场景与4个稳定锚点。退款世界的场景清单相同，含MEDIUM/LOW与3000/3001对照、risk×shipment组合及HIGH安全对照；地址场景含risk×PROCESSING、订单状态、已发货与无效地址。model_validation增至8，model_test=8、model_stable_validation=4、model_stable_test=8不变。该层只支持8类代表场景的结论，不声称覆盖CPU全部38/17种组合。新成本为872次基础任务+88次重试，旧smoke外推11.30小时/1,230万tokens；仍待新Runtime smoke，未冻结正式GPU运行。场景函数与manifest保存设计身份，禁止按正式结果再改场景。

## 7. 准入与研究成功标准

正式运行前写入 configs/active-evolution-v1.json 并冻结：

- actual violations = 0。
- validation false allow = 0；UNKNOWN 独立报告，不能伪装拒绝正确。
- validation false block 不高于未适应基线；正常可执行任务与 procedure success 不退步。W6 要单列放宽效果。
- Agent 激活另需 model_validation 上 Full System 正常任务保留及固定候选 Decision 不低于配对基线；所有组用相同测量协议。它与 Boundary 研究准入分别出回执，不要求主学习器学习终态标签。
- stable_validation：逐任务 before-pass/after-fail 数量除以总任务数 ≤5%；另报以 before-pass 为分母的条件退步率，不靠净增分掩盖退步。
- 只要硬门槛失败就 REJECTED，保持原版本；没有足够证据则 INCONCLUSIVE，均保留负结果。

联合主指标改为 convergence_rate_within_budget 与 restricted_mean_queries_to_convergence，cap τ=20。令 T 为首次满足第4节成功收敛条件的新增查询数，seed 后已收敛为 T=0；未成功收敛为 T>τ。报告 rate=Pr(T≤τ)，RMQ=E[min(T,τ)]=Σ(q=0…τ-1)Pr(T>q)。无收益/OTHER 停止且未收敛的 run 仍以 τ 计入截断查询量，同时单列实际花费，不能把早停失败算成效率提升。

研究成功的联合点估计门槛：Active 预算内收敛率不低于 Random，且 RMQ 相对 Random 至少降低 20%；另必须满足预声明安全与独立边界质量约束，不能仅凭过度自信宣称识别更快。Random RMQ=0 时相对降幅无定义，报告绝对差且不宣称通过20%门槛。这是可失败的研究假设，不是软件正确性测试；报告配对区间，不把点估计通过自动称作统计显著。

未收敛记录保留 censoring 标识，不当作第20次成功；median queries_to_convergence 降为辅助指标，不可估计时如实注明。基础设施导致未完成预算且不可恢复的 run 另列 incomplete，不伪装统计删失或能力失败。正式汇总应完成预注册运行。所有方法按同一等价类与收敛定义评分，同时报告验证拒绝率、错误收敛和假设识别准确率；test 只能事后评估正确性，不能决定在线停止。

queries_to_zero_false_allow 仅由最终 evaluator 对冻结的逐步候选快照事后重放计算，不参与选样/停止；同时报告 false block，防止全拒绝带来的虚假改善。

报告学习指标、成本、系统 EOC/Decision、程序探针违规尝试、模型违规尝试、实际违规、Retention、Forgetting，区分单位与分母。置信区间保留世界/种子配对结构，不能把同场景重复运行当独立样本。

## 8. 发布、再执行与证据目录

新结果统一位于 results/active-evolution/v1/<world>/<method>/<seed>/，包括 identity、manifest、gap、hypotheses、belief/、queries/、candidate-skill、validation、test、stable-holdout、report。model-layer/、sensitivity/、secondary-terminal/ 分别保存真实模型、只读敏感性及次级终态实验；candidate-policy 仅后者启用。根目录保存 cost-plan.json 和两层完整运行清单。

每条查询保存 candidate_id、可见输入、各候选预测/EIG、成本/风险分量、选择理由、执行结果、来源、belief 前后哈希和实际信息增益。训练信息不足与探针执行失败也留记录。

发布采用新的实验 Registry：候选在隔离目录，只有验证通过才能原子写入新 immutable 版本和 active pointer。发布的是新实验命名空间，随后必须真实重新执行任务验证加载了新版本。主工作台当前已签收部署保持原版本；主部署切换是研究与产品全量准入之后的独立交付动作。

checkpoint 必须绑定数据、world policy、程序、假设域、renderer、模型、代码和配置。query_id 幂等，恢复不能重复提交 mutation 或重复累计 posterior。改变身份后需新 run，不把旧记录拼接成新结果。

所有旧实验 artifacts 与其原文件不改写。允许新增方案与新报告入口；若需改共享 UI/API，保持历史结果渲染与原数字，并分别记录新代码身份。历史审核依赖精确源码哈希时使用旧提交的独立只读快照，不能重写旧 hash 使其通过。

## 9. 分阶段实施与退出条件

| 阶段 | 交付 | 退出条件 |
|---|---|---|
| P0 协议和边界 | 冻结旧文件、schema、六世界/splits、Cost Gate、两层清单与联合主指标 | 真变化证明、无 oracle 通道、旧文件未变、预算可执行 |
| P1 Gap + Hypothesis + Belief | 三个核心模块、EvidenceView、H_other | 12 类缺口有测试；概率可复算；主实验反馈隔离；失配不强制发布 |
| P2 Active Explorer | EIG、cost/risk、预算、停止 | 手算小例对照；不读取候选结果；随机基线预算一致 |
| P3 Sandbox + Revision | 隔离探针、BoundaryPatch | 原 DB 不变；guard 生效；二条件/阈值/放宽均可表达 |
| P4 验证发布闭环 | 控制器、验证器、实验 Registry、单命令 | 自动检测→查询→学习→验证→新版本→再执行；拒绝、无结论和中断路径通过 |
| P5 四组正式 Benchmark | 完整 CPU 矩阵、独立限额真实模型双评测、只读敏感性分析 | 联合主指标及两层清单完整审核；负结果不删 |
| P6 Retention / Continual | stable 双划分、连续 epoch、回退证据 | 更新前后和旧能力退步可复算；跨 epoch 证据不混 |
| P7 Workbench Evolution | 轨迹、posterior、选样原因、补丁 diff、准入结果 | 页面逐项对应证据；运行中不发布不完整组的最终成绩；桌面/手机检查 |
| P8（可选 v1.1）Continual QLoRA SFT | verified 探索监督、replay、训练/独立双评测 | 独立立项与预算；不阻塞 P0–P7 的 v1 完成 |

Retention 的数据设计在 P0 完成、准入检查在 P4 接入；P6 是正式持续学习结果验收，不能到 P6 才发现没有独立稳定数据。每阶段先工程检查，正式研究流程一次冻结执行；开发 smoke 与研究结果彻底区分。

## 10. 测试与验收

新增用户指定的 test_gap_detection、test_belief、test_hypothesis、test_active_learning、test_sandbox_probe、test_evolution、test_active_evolution_dataset、test_retention。

核心检查：聚类确定性、posterior 归一化与可复算、EIG 手算、假设空间遗漏处理、双条件不是 OR、金额边界类型、未知状态、证据重复去重、原数据库及 idempotency/fault 保真、world 进程隔离、oracle 禁读、split 成员审核、test 冻结前禁读、REJECTED 无法激活、版本不可覆盖、发布后实际加载新版本、resume 保留 query/belief 历史。

修订新增验收：OTHER 参与归一化/EIG 但不能生成补丁；OTHER 主导低熵不能算成功；unknown 不作为业务负例；主学习器禁读终态标签；sensitivity 不改正式配置或发起新查询；RMQ 对 T=0、T=20、未收敛、早停失败和 incomplete 的处理正确；成本清单包含全部真实模型阶段并在正式结果前冻结。

除新增测试，运行现有完整源码回归，核对历史文件 hash。最终从独立目录、禁止网络与原本机 artifact 绝对路径读取的环境重算结果。GPU/HTTP/浏览器验收独立于 CPU 测试，不把 pytest 通过当研究假设成立。

## 11. 可选后续版本：Continual Post-training v1.1

P0–P7 完成即满足 Active Self-Evolution v1 的范围要求，不以重新训练 QLoRA 为条件。本节仅保留接口与数据 lineage 设计；P8 的脚本实现、GPU 训练和额外测试在后续版本单独安排。终态 Policy secondary experiment 同样不作为主 Boundary 实验成立的先决条件。

新增 scripts/prepare_continual_supervision.py 和 scripts/train_continual_adapter.py，复用既有训练与身份检查实现，不另造整套 trainer。仅接收 seed/explore 的 verified action-level 样本，new:replay 默认 1:2。

Replay 不能盲目混用旧政策冲突标签：稳定任务保留，变化规则区的数据隔离或显式携带 policy epoch；不把已经失效的旧答案当新世界监督。程序教师与真实模型轨迹维持不同来源标签。训练采用新 adapter lineage，不覆盖 main-v3。

对 Original SFT / Continual SFT 使用相同冻结 Skill/Policy bundle 做权重对照，防止把同时更新 Skill 的收益归给训练。同时评估新策略 holdout、稳定旧策略 holdout、Decision、违规尝试和遗忘；如这些 holdout 已用于 P5/P6 的分析与选型，训练前另冻新的最终测试批次。

本轮不以 PPO/GRPO 或新的大型模型模块为前提。优先完成可审计主动选样与安全版本演进，再判断参数更新是否带来独立价值。
