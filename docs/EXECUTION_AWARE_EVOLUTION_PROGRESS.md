# Execution-Aware Self-Evolution v1.1：实施进展

2026-10-06 最终状态：A、B 正式实验和独立审计均已完成。实验进程已结束；以下运行状态、session 和阶段数字保留为历史记录。A 连续稳定性出现 1 个退步，B 未证明 v2 优于原 Active，不能宣称完整研究验收通过。见[正式交付总结与网页预览](EXECUTION_AWARE_V1_1_DELIVERY.md)。

更新：2026-10-05。P9–P13-A已完成：9个独立组及2个连续epoch全部执行、审计通过。连续epoch 2出现1个held-out stable退步，因此不能宣称完整retention验收通过。归因已覆盖全部64对连续有效Bundle轨迹，详见[A验收结论](EXECUTION_AWARE_A_ASSESSMENT.md)。B的24组开发消融及审计已完成，选中仅H0 Challenge Gate；正式150组已独立冻结并启动，详见[B运行说明](ACQUISITION_V2_RUNNING.md)。尚未形成完整B研究结论。

最新恢复前快照：1,293条模型执行、5/9 Belief Converged、5/9 Boundary Admitted；新Runtime下3/9 Agent Admitted并在隔离实验Activated，旧Runtime下0/9；连续模型epoch尚未完整结束。Windows日志证实约9小时21分钟睡眠，原墙钟13.092小时完整保留，证据修正后3.752小时；不再将睡眠解释为GPU运算。修正是冻结后的基础设施偏离，完整报告会明确披露，不能声称原墙钟预算合规。参见[续跑与审计说明](EXECUTION_AWARE_RUNNING.md)。最新完整回归274通过、1跳过，10,699历史文件与86个A冻结源码均通过校验。

## P9：完整回归归因

入口：`python -m scripts.attribute_execution_regressions`。只读v1冻结缓存，不调用模型。

[归因报告](../results/active-evolution/v1.1/attribution-v1/REPORT.md)与[结构化记录](../results/active-evolution/v1.1/attribution-v1/proposal_regression_report.json)覆盖4个非平凡proposal、48对FullSystem validation和32对独立Decision。FullSystem为39对不变、3对改善、6对退步。6条退步中5条缺少写后验证，1条验证后输出非法Action；四个proposal的Decision validation均为7/8→8/8。

记录包含输入文件SHA、cache身份、参数/模型设置身份、业务事件对齐、动作分歧、可支持的契约违反位置及最终EOC原因。Decision诊断与FullSystem诊断分开，未把validation改善表述为test收益。

## P10：执行契约与回执

新增独立包`skillforge/execution_aware/`，v1 Runtime未改动：

- `contracts.py`：不可变VerificationReceipt、写前公开基准、请求幂等身份、提交/验证状态、checkpoint恢复与有界reconciliation。
- `runtime.py`：统一primitive/Skill调用跟踪；Skill原有有效读回产生同格式回执，primitive由Runtime补充读回；仅在明确单目标且受支持公开后置条件满足时自动终止。
- `worker.py`：固定main-v3、旧/新Runtime选择、公开RPC与文件/模块访问隔离、写入前持久化checkpoint。
- `metrics.py`：自主/辅助EOC、干预率、配对救援、退步、强制读取和自动终止计数。
- `scripts/execution_aware_agent_eval.py`：评估器持有私有环境和独立verifier，gold不进入Agent；新Runtime的逻辑request_id实际传给工具。

恢复限制明确保留：当前真实公开工具没有按request_id查账能力，因此COMMIT_UNKNOWN不会因余额读回就被判为NOT_COMMITTED。无权威证据保持STILL_UNKNOWN。契约引擎支持恢复；开发评估器每次使用新内存环境，worker发现已有执行checkpoint时会拒绝自动恢复，防止旧请求状态被套到新环境。后续生产恢复需要同一个持久化环境及审计链，不能声称当前评估器已实现端到端崩溃续跑。

## P10.5：固定旧Bundle的真实模型开发对照

固定main-v3 adapter `f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b`，沿用旧prompt和解码；只改变Runtime。预先声明W3/W5/W6、开发seed110510、各世界索引0/1/2/6，共12个任务；不是12个独立world-seed单元。

最初启动被旧GPU租约的服务名检查拦截，未执行模型；新增仅识别已核验项目服务的租约入口，保留旧代码。第一轮24次真实执行的完整证据位于`development/runtime-only-v2/`。该轮发现“已拒绝写操作被误报为待验证”的成本缺陷；修复后在`development/runtime-only-v3/`重新执行全部12个新Runtime任务，按身份校验复用全部12个旧Runtime控制，不选择性删除失败任务。两版测量源码均已按原SHA归档在各自`sources/`。

最新[开发对照结果](../results/active-evolution/v1.1/development/runtime-only-v3/summary.json)：

| 指标 | 结果 |
|---|---:|
| 旧Runtime EOC | 1/12 |
| 新Runtime EOC | 8/12 |
| autonomous_eoc | 1/12 |
| runtime_assisted_eoc | 7/12 |
| runtime_intervention_rate | 9/12 |
| rescued_by_runtime | 7/12 |
| 配对任务退步 | 0 |
| actual violation | 0 |
| forced_readback_count | 7 |
| auto_termination_count | 7 |

9次有干预任务包括7次成功救援和2次拦截重复的业务拒绝。自主/辅助成功互斥，总和等于EOC；这些证据说明Runtime修复了开发任务的执行失败，不能称作模型学会了验证或停止，也不能称作新Boundary的学习收益。

修复后两个业务拒绝案例均在第2次模型动作终止，不再循环16步；配对逻辑token总量从339,041降为262,435，EOC不变。剩余4条失败中，2条为旧H0在变化边界上的业务拒绝，2条为模型把Skill名称当作primitive工具且缺少参数。后两条在旧/新Runtime中均失败；没有通过自动改写Action掩盖这些错误，也未启动SFT。

两轮Runtime-only开发共36次实际模型执行，460,637 tokens，调用总墙钟916.69秒（约15.28分钟，包含启动/关闭）。第二轮复用的140,839控制tokens不重复计费。后续四臂cost smoke另有48次执行；[资源账本](../results/active-evolution/v1.1/development/resource-ledger.json)现累计84次、714,710 tokens、1,509.94秒。12小时/20M为A+B共享预算。各开发调用结束后模型服务8002和Workbench8080均已恢复，adapter身份一致。

## P11：组件、控制器和隔离进程

`admission.py`保留belief、Boundary、Agent和activation独立证据及固定分母；H0验证失败、未计划Agent评测、待评测和基础设施未完成均单列。No Adaptation不计作更新成功。

`challenge.py`实现公开H0 Challenge Gate：K个不同公开因子probe、相对最强非H0假设的posterior阈值、探索证据身份检查、预算耗尽和不可识别状态。开发默认K=2、相对阈值0.1、预算20，不是正式冻结参数。重复候选身份不能把同一个公开probe计作多次挑战，seed证据不抵扣探索挑战。

新增`controller.py`、`learner_worker.py`及独立评估入口，保留旧EvolutionController与A的原Active获取策略。高置信H0必须通过Challenge Gate，预算耗尽仍不满足则保持不确定；原始置信收敛与认证收敛分别保留，恢复会核验历史gate状态。开发集W5/110611仅使用seed/explore/validation/stable validation，未生成或读取test。active与active_v2均在10次查询后因无信息增益停止，posterior为0.85218，状态为INCONCLUSIVE；这次接线验证没有提供Active v2改善的证据。

## P12-A：成本门槛与正式冻结

[四臂cost smoke](../results/active-evolution/v1.1/development/factorial-cost-v1/summary.json)固定main-v3，在开发seed110712上执行48个模型任务，覆盖三个世界、两个Runtime、两个Bundle和FullSystem/Decision两种模式；成本Bundle是预声明的开发夹具，不是学习结果。新增254,073 tokens、593.26秒。

首动作重复性检查仅比较模型动作，12组相同公开上下文各4次执行，无首动作差异。它不证明完整轨迹确定性。初版检查错误混入后续工具执行错误，已保留原记录并用`first-action-repeatability-v2.json`明确纠正。正式validation重复数为1。

正式A保留W3/W5/W6各3个paired seed，8个变化test与8个stable test。最大预留1,344个FullSystem和768个Decision任务（包括两个连续epoch及其实际Agent parent），精确身份缓存可以减少实际执行次数。纳入全部开发消耗、基础设施失败及重试预留后，估计38,621.65秒（10.73小时）、12,892,697 tokens，通过12小时/20M门槛；未启用缩减stable test的预声明备选。

活动协议位于[formal-A-v2/protocol.json](../results/active-evolution/v1.1/formal-A-v2/protocol.json)，hash为`c565643a4e87d9b71d1875778ab71c0a6a9956d1b6b3b7adeb421a2064c93fcc`。源码、数据manifest、模型设置、预算、准入和三个factorial estimand均已冻结。第一版在任何正式CPU或模型执行之前，因报告字段需要区分H0验证状态及补足Decision/Cost计数而被替代；原协议、源码及替代说明完整保留，数据、seed、预算和准入阈值未改动。

9个独立world-seed为主要统计单元，按世界分层paired bootstrap；连续epoch单列。Candidate诊断与通过准入后的effective Bundle效应分别报告。Belief→Boundary→Agent→Activated漏斗保留固定分母、H0无更新分支和未完成分支；Activated仅代表隔离评估中生效，不代表部署。

[CPU阶段](../results/active-evolution/v1.1/formal-A-v2/cpu-report.json)9个独立单元均已完成，5个Belief Converged、5个Boundary Admitted（W3为3/3，W5为1/3，W6为1/3）。另外两个连续epoch的Boundary更新均通过。Agent及Activated结果仍待完整评测，不能由CPU结果推算。

## P13-A：真实模型评测执行中

当前正式调用为`1bdc3caed371406fb28ba95b7cc7e2c4`。首个W3/12811068单元已完成完整四臂validation及test，并通过独立逐项重算。[单元审计](../results/active-evolution/v1.1/formal-A-v2/audits/group-W3-12811068.json)保留候选及有效Bundle两种口径。validation中旧Runtime因正常任务退步3、stable退步2拒绝更新，新Runtime通过准入；两类退步计数可能重叠，不能相加。

该单元的变化test共8个任务：旧Runtime+旧Bundle为4/8，旧Runtime+候选Bundle为2/8（因此有效Bundle已回退，仍为4/8）；新Runtime+旧Bundle为7/8，新Runtime+更新Bundle为8/8。新Runtime下独立Decision由7/8到8/8，false allow由1到0，更新后实际违规为0且stable无新增退步。逐臂归因显示，自主EOC为1/8→2/8，辅助EOC为6/8→6/8；完整成功不能统称为模型自主能力。变化+stable共16个test中，新Runtime更新前后分别14/16和15/16，仍有1个stable失败未解决。

上述仅为1个world-seed的完整结果；其余独立单元及连续epoch尚未完成，没有总体效应或显著性结论。

独立审计入口`python -m scripts.audit_execution_aware`不改变冻结源码或准入决策：重算私有verifier、核对task/model/protocol身份、将VerificationReceipt绑定到同一对象同一次写入后的真实读取，并复核干预和自动终止计数。完整矩阵完成后还会从cache重建validation准入、candidate/effective四臂、漏斗、factorial估计与每种Runtime的实际父链。

2026-10-05补齐逐臂描述性归因：旧/新Runtime、candidate/effective Bundle及变化/stable test分别报告自主/辅助EOC，确保学习后Bundle的收益也能追溯到模型动作与Runtime干预。原预注册estimand、准入与实验执行源码未改变。离线端到端测试使用真实沙箱工具和脚本动作，从四臂执行、cache、准入、独立审计一直运行到Markdown/JSON报告；能检出篡改的stable退步计数，并禁止把Decision探针或重复任务当作EOC独立样本。

`scripts.finalize_execution_aware`正在等待当前调用关闭。正常完成且审计通过后自动生成`formal-A-v2/REPORT.md`及独立审计回执；基础设施失败、超预算或其他未完成状态只生成未完成记录，不发布总体效应。当前正式源码86份的SHA仍与冻结协议一致。续接时不要在现有进程仍运行时重复启动模型矩阵，操作说明见[运行与续接](EXECUTION_AWARE_RUNNING.md)。

2026-10-05发生一次外部进程中断，原调用在183条完整cache后退出且未写正常关闭记录。已核验主机进程、归档无主租约、恢复原服务，并补记最多一个未完成FullSystem请求的262,144 token保守预留；原调用墙钟保守计2,074.28秒，包含停机及恢复间隔。当前调用复用全部183条缓存后续跑，协议和共享预算未重置。恢复点累计1,662,186 tokens、3,584.22秒；后续调用仍在结算中。恢复调度重建、幂等记账及报告链的5项测试通过。

## 只读进度与执行Trace预览

新增独立`skillforge/execution_workbench/`，本机预览为`http://127.0.0.1:8091`。它显示旧/新Runtime的固定分母漏斗、Agent待评测状态、candidate/effective效应、Runtime干预归因、首动作Decision与FullSystem分开判分，以及不可变回执和原始工具审计。连续epoch不计入主分母，Activated与Deployed明确区分；完整矩阵未完成时不计算总体factorial效应。

此版本暂为独立只读预览，没有挂接或改写当前被cost smoke记录的主Workbench入口。无模型、工具、学习或部署路由。[浏览器验收](../results/active-evolution/v1.1/development/workbench-qa-v1/browser.json)通过桌面1440px、手机390px、过滤与Trace点击，页面无横向溢出和JavaScript异常；截图保存在同目录。

## 验证与保护

最近一次[全量测试回执](../results/active-evolution/v1.1/development/source-check-f377484f49494270b6daaa37d2f2e0e5/report.json)：267 passed、1 skipped；测试在独立源码副本运行。覆盖错误对象、陈旧读取、错误后置值、读取失败、退款已有基准、Skill回执复用、取消/改地址、重复写入、写前崩溃、提交后response loss、权威未提交重试、无查账能力、受限组合任务和Agent gold访问拒绝。包含证据审计、只读页面和完整四臂报告链测试；之后新增外部中断恢复测试，相关5项检查通过。

10,699个历史文件SHA一致；v1正式协议的73个冻结源码与数据manifest验证通过，protocol hash仍为`de3eae4b913556249d5d761b636b88dac87038f833a22825f62c899f6c9de60e`。顶层结果页已修正过期进度说明，旧config及冻结protocol中的status保留，历史身份未追溯修改。

## 后续阶段出口

1. 按冻结A执行9个独立CPU单元及两个连续epoch，随后运行真实Agent四臂与每个Runtime的实际父Bundle lineage。
2. 独立审核原始轨迹、VerificationReceipt、资源账本、漏斗与factorial效应，完整保留失败和negative transfer。
3. A正式实验完成后，B单独完成Gate/获取策略消融及protocol hash，再运行正式CPU实验；SFT维持条件性的v1.2。
