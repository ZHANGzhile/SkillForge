# Execution-Aware Self-Evolution v1.1：实施方案草案

2026-10-06 最终状态：A、B 正式实验和独立审计均已完成。实验进程已结束；以下运行状态、session 和阶段数字保留为历史记录。A 连续稳定性出现 1 个退步，B 未证明 v2 优于原 Active，不能宣称完整研究验收通过。见[正式交付总结与网页预览](EXECUTION_AWARE_V1_1_DELIVERY.md)。

日期：2026-10-04。审阅基线：`ca842d71ea0ae8deae8de88fda04e989c0f9bf49`。本文件保留实施设计；当前A已冻结并进入真实Agent四臂评测，B尚未冻结，详见[实施进展](EXECUTION_AWARE_EVOLUTION_PROGRESS.md)。A以`formal-A-v2/protocol.json`为准，本草案未冻结参数不等于正式实验承诺。

## 1. 目标与证据边界

本轮目标是验证：正确学习的Boundary能否在不造成正常任务退步的情况下，被真实Agent准入并转化为完整任务收益。固定main-v3 SFT权重，优先完成归因、执行契约、三层状态与新协议评测。Workbench只做必要兼容；SFT、DPO、GRPO/PPO不进入本轮核心范围。

v1结论保持：CPU联合效率指标通过，但2次false allow使完整安全验收失败；两个连续epoch的Boundary更新获准；四个非H0 Agent更新提案被拒绝。Decision的7/8→8/8是proposal validation结果，不是正式test改善。所有结论限于已声明世界、有限假设域和代表场景。

本次已对照真实配对轨迹：四个被拒提案涉及6条正常任务退步。5条为`issue_refund → stop`，没有写后读回；另1条独立W3案例已经执行`issue_refund → get_payment`，随后多读一次并输出`{"type":"finish",...}`，触发Action `ValidationError`。因此不能假设加一次读回即可解决全部问题，也不能把该模型输出错误写成工具基础设施失败。

## 2. P9：逐步回归归因

新增只读归因器，覆盖四个proposal的全部48条配对Full System validation案例，而不只挑选6条退步；Decision轨迹分开分析。引用v1已有cache，不改写原始记录、不新增推理，不把已查看的v1案例继续当作独立holdout。

每对记录绑定task hash、before/proposal bundle、Runtime、权重、解码设置及cache hash，输出：

- 模型可见context差异、动作序列、工具返回、Skill选择和执行分支；私有审计状态仅保留在归因端。
- 按工具/业务事件对齐的共同前缀、首次动作分歧、首次契约违反及最终EOC失败；不能简单按step数组下标机械配对。
- committed mutation、对应read-back、公开postcondition检查、终止动作之间的证据链。
- 主因与次因、证据位置、能否确定；缺证据时使用unknown，不强行归类。

分类包含wrong_tool、wrong_skill、premature_stop、missing_post_write_verification、read_loop、invalid_argument、invalid_action_schema和execution_error。区分多标签共现与独立案例计数；一次冗余读取不直接称作read_loop。第一轮观察是5条缺失验证和1条验证后错误终止，尚不宣称机制修复后的因果效果。

产物：`results/active-evolution/v1.1/attribution-v1/proposal_regression_report.json`及可读报告。验收要求：48对覆盖完整、6条已知回归可逐项追溯，非回归和改善案例也保留。

## 3. P10：确定性执行契约

新增版本化Runtime，保留v1实现及其哈希。主实验采用Runtime主动执行必要read-back，而不是只提示模型“应该验证”。建议状态为：

```text
READY → MUTATION_CONFIRMED → VERIFY_REQUIRED
      → VERIFIED → TERMINAL_READY
      ↘ VERIFY_FAILED / COMMIT_UNKNOWN
```

约束设计：

1. 只根据公开任务参数、工具观测、写入回执与声明的程序postconditions构造执行契约；不得读取Task.expected、fixture、gold policy、完整私有state或EOC标签。
2. 退款使用写前公开refunded_amount、请求金额和对应订单的写后get_payment验证；地址使用对应订单get_order验证新地址；取消订单验证CANCELLED。读回必须发生在对应写入之后，且对象和mutation身份一致，不能复用hydrate阶段的旧读结果。
3. primitive工具与Skill内部调用共用契约跟踪。既有Skill DSL已完成有效读回和postcondition验证时复用真实回执，不再补一遍读取。
4. VERIFY_REQUIRED期间不允许stop、重复写入或用其他终态逃避验证；Runtime实际执行限定的read-back并记录来源为runtime。验证失败或提交状态不明时保留失败/不确定状态，禁止伪造成功或无条件重放写操作。
5. 写前基准、mutation幂等键、待验证状态和回执需要可恢复；幂等重放不能再次累计预期退款金额，进程恢复不能丢失待验证义务。
6. 对当前单业务目标的primitive任务，公开目标及全部postconditions已满足后允许Runtime确定性终止，单独记录`termination_source=runtime`。这用于避免验证后的冗余读取和非法finish输出，不声称模型自己学会了正确stop。
7. 自动终止不扩展到尚有未完成步骤的组合任务；create_ticket/escalate等终态副作用也不能套用退款读回规则。没有声明验证契约的动作不得被自动认定为成功。
8. 最终独立EOC verifier保留最终判定权。Runtime局部VERIFIED不等于业务gold下的任务成功；环境权限和policy guard保持不变。

新增测试必须涵盖：直接写后stop、读错订单、写前旧读、读回失败/值不符、写入状态不明、重复写入与幂等重放、Skill已有验证、第二次写入使旧验证失效、断点恢复、无写入的合法终止、验证后终止及未完成组合任务。所有自动读、干预和终止都进入轨迹与成本账本。

验收分为两层：确定性契约测试证明无法未经验证宣告成功；新开发任务的真实模型实验检验EOC变化。v1的六条回归只作为已知缺陷回归集，其修复不能作为新泛化结论。

### VerificationReceipt 与提交恢复协议

`VERIFY_REQUIRED → VERIFIED`必须引用不可变的`VerificationReceipt`，不能仅凭出现过某个读取动作。统一字段为：`receipt_id / schema_version / mutation_id / request_id / object_id / mutation_tool / verification_tool / expected_postcondition / observed_value / status / timestamp / source / evidence_hash`。预期条件还绑定写前公开基准、契约版本和读取事件身份。成功、失败及未知观测均追加新记录，不原地改写；重复消费同一receipt保持幂等。timestamp仅作审计，因果顺序由mutation及事件身份保证。Skill DSL与primitive路径使用同一验证器产生回执，checkpoint保存未完成义务及回执引用；同对象的新mutation不能被旧回执覆盖。

提交状态与验证状态正交。写入超时或response loss进入以下恢复协议：

```text
COMMIT_UNKNOWN → RECONCILING（按原 request_id / idempotency_key 查账或公开读回）
              → COMMITTED     → VERIFY_REQUIRED → VerificationReceipt
              → NOT_COMMITTED → 允许按原逻辑请求身份重试
              → STILL_UNKNOWN → 保留不确定、停止写入、返回可恢复状态
```

只有工具提供权威的请求状态/账本证据，或工具契约明确保证读回足以判定该请求，才能确认COMMITTED/NOT_COMMITTED。余额未变化、最终一致性下暂时查无记录、或可能存在并发写入的聚合金额，都不足以证明NOT_COMMITTED；普通退款金额读回未必能归因到本次请求。缺少这种能力时保持STILL_UNKNOWN，不伪造查账接口或自动重试。冻结查账次数、等待期限、重试上限，所有成本入账；新增response loss、并发变化、延迟可见与重复恢复测试。

### P10.5：Runtime-only 开发对照及干预指标

固定旧Bundle、权重、任务及解码配置，只比较旧/新Runtime；先运行v1缺陷回归集，再运行隔离的新开发任务。验证执行契约能覆盖真实失败且不引入安全/正常任务退步，之后才进入正式A协议。此阶段是开发证据，不作为正式holdout成果。

所有指标以同一预声明完整任务集合N为分母，另报基础设施缺失；由独立verifier判定EOC：

- `autonomous_eoc = count(EOC成功且无Runtime执行干预) / N`。
- `runtime_assisted_eoc = count(EOC成功且有Runtime执行干预) / N`；与前项互斥，两者相加为总EOC，同时另报有干预任务内的成功率。
- `runtime_intervention_rate = count(至少一次执行干预) / N`。
- `rescued_by_runtime = count(配对旧Runtime失败、新Runtime成功且发生干预) / N`；另报整数计数及相反方向退步。这是配对观测救援，非单条轨迹的确定性反事实证明。
- `forced_readback_count`、`auto_termination_count`分别报告总量与每任务分布。

干预包括强制读取、自动终止、阻止/替换模型动作和Runtime恢复动作；仅观察/生成审计回执不算干预。模型主动调用Skill，且Skill按原有声明流程完成验证，不因内部DSL执行而自动归为Runtime救援；新Runtime追加的动作仍算干预。动作、回执与终止均记录来源，不把Runtime动作记为模型决策。

无干预成功子集不能直接证明模型能力改善：新Runtime可能在模型获得读回/stop机会之前介入。模型自主收益须结合旧Runtime臂、固定首次Decision以及配对任务判读；不通过隐藏、删掉干预记录制造“自主”成绩。

## 4. P11：三层准入与H0 Challenge Gate

必须先把belief收敛、Boundary准入、Agent准入拆开；它们是可并存的独立证据字段，不应只用一个线性status掩盖某层失败。

- `BELIEF_CONVERGED`：满足有限观测模型的收敛条件。
- `BOUNDARY_ADMITTED`：非平凡Boundary变化通过独立Boundary validation。
- `AGENT_ADMITTED`：该变化在指定Runtime和权重下通过真实Agent validation。
- 另记录unchanged、rejected、inconclusive、infrastructure_incomplete和activation状态。

H0也接受验证并记录失败，但不能因belief收敛或原版本被保留就称作适应成功。非平凡变化按预声明公开支持域内相对当前父版本的行为差异定义，不按revision字符串变化定义。validation标签只用于准入，不能回流learner触发针对性选样。

指标必须固定分母：

| 指标 | 分子 / 分母 |
|---|---|
| belief_convergence_rate | belief收敛运行 / 全部预声明完整运行；包括H0并另列H0数 |
| boundary_admission_rate | 获准的非平凡Boundary更新 / 全部预声明适应运行 |
| agent_admission_rate | 获准的非平凡Agent更新 / 进入预声明Agent评测的非平凡Boundary获准提案 |
| end_to_end_activation_rate | 获准且完成激活记录的非平凡更新 / 全部预声明适应运行 |

同时列出条件Boundary通过率、未提案/被拒/基础设施未完成数量。No Adaptation的“更新准入率”记为不适用，不以H0自比较通过冲高数字。基础设施未完成不能伪记成能力失败，也不能从实验完成性报告中消失。

Acquisition增强是独立、可消融的候选，不与Runtime修复混成一个效果。保留v1 EIG基线，探索：

`score = normalized_EIG + λd * H0_disagreement + λc * coverage_bonus - cost_penalty - risk_penalty`

H0 disagreement仅用公开候选与当前替代假设预测计算；coverage仅用预声明公开因子和交互组合，不把W5的gold条件硬编码进去。各项尺度、覆盖域、权重、H0 challenge停止条件在新开发集确定。H0挑战计入原查询预算，不额外借用validation/test。若新增条件不满足且预算耗尽，应为inconclusive，不能人为隐藏旧边界的实际错误。

H0 Challenge Gate是宣布H0收敛的必要条件，不依赖增加acquisition权重。top hypothesis为H0时，根据公开候选池和预声明高posterior非H0集合，构造预测与H0不同的challenge集合；集合阈值、K、排序、去重及已执行probe的计数规则在开发集后冻结。若可识别challenge总数至少K，必须执行至少K个不同probe；少于K时必须穷尽这些probe并明确报告覆盖不足。存在未完成的必需challenge而20-query预算耗尽时，记为inconclusive，不得宣布H0收敛。每次观测后重新检查posterior与最终challenge义务，不能用旧替代假设下的任意probe凑数。

若公开候选池根本无法区分H0与替代假设，则记录`no_discriminating_probe`和可识别性限制，不把“没有可查的反例”作为通过挑战的证据；该情形不进入challenge-certified H0收敛分子。Gate只使用探索池与查询结果，不调用validation/test/gold。它限制过早宣布收敛，不能保证消除错误H0。

先在开发集比较旧EIG、EIG+Challenge Gate，再独立消融disagreement与coverage，只选事先规则允许的一个v2候选进入正式B协议。增加覆盖奖励不保证解决H0错误收敛；重命名指标也不等于消除了false allow。

## 5. P12-A / P12-B：两个独立正式协议

`v1.1-A Execution-Aware Runtime`回答执行契约是否提高完整任务成功及Boundary利用效果，固定原Acquisition方法；`v1.1-B Active Acquisition v2`回答H0 Challenge及候选获取策略是否降低false convergence。两者分别保存protocol、源代码清单、数据清单、结果目录和protocol hash；共享依赖也显式绑定内容哈希。B的开发和结果不能反向改变A，B无提升也不改变A的验收结论。A冻结及正式评测先行，B随后独立冻结。A期间不得把正式A验证标签回流B开发；分区复用仅限预声明的生成器与公共代码。

`formal-v1`及全部v1冻结源码、数据、smoke和签收保持不变。新实现优先放入独立子包，例如`skillforge/execution_aware/`，新实验写入`results/active-evolution/v1.1/`，避免改变v1入口依赖的源码身份。

新开发集、cost smoke、validation、test及stable holdout使用互不重叠的seed/实例，按预声明seed选择算法生成，而不按效果选seed。旧formal-v1只能用于诊断和已知缺陷回归。相同World生成器的新实例仍是已知规则族，不能称为新世界泛化；本轮不默认增加policy world。若确需新world，必须在冻结前声明规则生成族与适应机会，单列结论。

拟议规模（成本smoke前草案，不是冻结承诺）：

- B协议CPU：既有6个规则世界 × 5个新配对seed × 5方法（No Adapt、Passive、Random、Active v1、Active v2）=150组；开发消融单列。A用固定原方法产生Boundary候选，不等待Active v2。
- A协议真实Agent核心对照：旧/新Runtime × 旧/学习后Bundle，固定main-v3权重与配对任务。成本允许时独立W3/W5/W6各至少3个预声明新seed，优先增加world-seed数，不增加任务内重复来假装扩样。连续两个epoch另用独立seed，保存CPU父链与Agent实际获准父链。连续epoch不算两个独立实验单位。
- 四臂用于分离Runtime自身修复、同一Runtime下Bundle更新及二者交互。各Runtime的Agent准入分别执行；正式有效版本在拒绝时回退。候选validation诊断与获准系统的test成绩分开，不能用拒绝提案的分数冒充可部署收益。
- 独立Decision在固定首次决策状态测量，Runtime自动完成步骤不能被计作模型Decision正确。两Runtime共享的完全相同首次决策可按冻结的语义身份复用，并明确它不是独立样本。

保留12 GPU小时/20M token作为本轮拟议硬上限。先生成完整最大工作量清单，覆盖所有对照、validation、Decision、test、continuous及一次受限基础设施重试；用新Runtime独立smoke估算，而不因v1只用了41.9分钟就跳过成本门槛。若超额，在查看正式成绩前按预声明优先级缩减规模并写入最终protocol；冻结后不依成绩缩减、加seed或换权重。

预算为A+B及开发smoke合计上限，不是每个协议各12小时/20M。A优先；B单独预留预算。若资源仍不支持每世界3 seeds，须在冻结时标为工程验证规模，不能据此承诺显著提高。推断单位为world-seed，按world分层汇总配对效应并使用预注册的小样本区间方法；任务嵌套于单元内，不能当独立样本。若smoke显示模型非确定性，仅对Agent admission validation预声明2–3次重复，并预注册准入聚合规则（安全与退步门槛每次均通过，效能按固定聚合），不得挑最好一次；重复不增加独立单元数。

### A协议预注册 factorial estimands

记配对单元EOC为Y(R,B)，R=0/1为旧/新Runtime，B=0/1为旧/学习后Bundle：

- `Runtime Effect = Y(1,0) - Y(0,0)`。
- `Bundle Effect under New Runtime = Y(1,1) - Y(1,0)`。
- `Interaction = [Y(1,1)-Y(1,0)] - [Y(0,1)-Y(0,0)]`。

同一候选Bundle必须在两Runtime臂保持身份一致，才能解释纯factorial效应；因此在隔离评测中预注册候选四臂诊断，拒绝候选不得部署。另报按各Runtime准入后回退的effective-bundle四臂结果及相同形式差值，明确其估计的是“Runtime+准入流程”的整体效应，不能混称同一候选的纯交互。两类heldout评测成本均纳入smoke；测试结果不得用于再次准入或调参。Interaction为正且不确定性支持时，才有证据说明Runtime特别帮助利用新Boundary。

## 6. P13-A / P13-B：独立复评与验收

主指标转为Agent admission rate与同一新Runtime下有效bundle的New-world EOC增益，报告配对差值及不确定性。belief/RMQ保留为次级指标。并报告：Boundary通过率、端到端激活率、正常任务退步、stable retention、FA/FB、attempted/actual violation、LLM调用、全部工具调用、token、时间，以及Runtime干预/自动终止率。

以上为A协议指标；B协议独立以预算内belief convergence与restricted mean queries为联合效率指标，同时执行FA/FB、actual violation与stable retention准入，并报告H0 false convergence、challenge完成率和inconclusive。不能只靠将错误收敛改记inconclusive就声称学习效率提升。

最终主图为`Belief Converged → Boundary Admitted → Agent Admitted → Activated`四阶段漏斗，每层展示绝对数量、固定总运行分母的比例与层间条件比例，同时展示H0、拒绝、未完成及未计划Agent评测的分支。若Agent只评测部分world-seed，不能把其人数直接接在全部CPU运行数下面：分别画完整CPU队列和预注册端到端子队列，未评测不得当失败或成功。只有事件确实嵌套时画单一路径，否则用分支流图保留旁路。Activated明确指隔离实验激活记录，另列实际部署数。

建议准入约束：validation actual violation=0、正常任务退步=0、stable退步=0、Decision不劣、Full System EOC不劣；Boundary保留零false allow及false block不劣。正式test用于最终研究验收，不用于修改或补救当前候选。拟议零stable退步比v1的5%门槛更严格，须在新protocol中预注册，不能在看到结果后修改。

完整收益结论至少需要出现非平凡Agent获准更新，且独立holdout支持新世界收益与稳定性；如果只是新Runtime让H0也执行更好了，应报告为Runtime收益，不称为学习收益。小样本置信区间跨零时报告不确定，不能只凭一个获准案例声称普遍改善。

失败提案、H0、inconclusive及成本均完整记录。先在隔离评测中写activation记录，再决定主部署；Agent实验准入不自动改主工作台的bundle或权重。

## 7. 文档与版本状态

首先修正`ACTIVE_EVOLUTION_RESULTS.md`页首“正式研究尚未运行”的过期说明，保留下面带日期的历史开发章节。

`configs/active-evolution-v1.json`的旧status确实容易误导，但整个config曾进入开发运行identity，正式protocol也内嵌了原config。先补明确的v1运行状态入口、关联正式protocol；若更正顶层config元数据，需保留原配置供历史复现，并确保历史重放从原identity/冻结配置取值。绝不批量修改smoke identity、protocol中的旧status或历史哈希来让它们“看起来一致”。

命名调整：v1.1在本方案中指Execution-Aware Self-Evolution；旧文档把Continual QLoRA称作v1.1的地方要说明它现为条件后续阶段，暂称v1.2，避免同时用v1.1指两个交付范围。

## 8. 执行顺序与阶段出口

| 顺序 | 工作 | 进入下一阶段前的证据 |
|---|---|---|
| P9 | 完整逐step归因、顶层状态与版本命名修正 | 48对validation对齐，6条回归解释，无原证据改写 |
| P10 | VerificationReceipt、状态机与reconciliation | 恢复/幂等/不确定提交测试通过，干预均可追踪计费 |
| P10.5 | 固定旧Bundle的Runtime-only开发对照 | 已知缺陷及新开发任务验证；自主与辅助成绩分列 |
| P11 | 三层证据与四阶段漏斗；H0 Challenge Gate | 分母与分支明确，Gate无标签泄漏；不等待权重调优 |
| P12-A | Execution-Aware成本smoke与独立冻结 | 四臂、estimands、样本量、预算与代码身份锁定 |
| P13-A | Agent factorial及连续epoch评测 | Runtime/Bundle/Interaction及辅助收益分别报告 |
| P12-B | Acquisition v2消融完成后独立冻结 | 独立protocol hash、数据及剩余预算锁定 |
| P13-B | Active Learning正式CPU实验 | 效率、安全、错误H0及inconclusive联合审计 |
| 条件后续 | 若执行仍弱，再提出轨迹SFT/replay计划 | 先解释新失败模式，不直接启动训练；旧holdout不进入优化 |

若后续SFT确有必要，使用仅来自训练分区的新policy已验证轨迹与旧policy replay；新:旧=1:2只能作为待冻结的开发候选比例，不是当前已采纳训练协议。DPO/GRPO/PPO再后置。Workbench沿用现有页面，必要时仅增加新版本数据适配，不重做前端。

本轮方案交付不修改v1成绩，不保证新方法一定通过。首批实施应完成P9以及P10的确定性契约与测试，再开展新模型成本smoke和正式冻结。
