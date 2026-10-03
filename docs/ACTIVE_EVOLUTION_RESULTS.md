# Active Self-Evolution v1：开发验证记录

更新日期：2026-10-02。**正式四组研究尚未运行，本页不是正式Active Learning结果报告。**

## 工程纵向闭环

目录：`results/active-evolution/v1/development/vertical-slice-v1/`。

声明范围：单个W1工程世界、公开risk/shipment有限字段、固定程序probe；控制器自主选择候选，未用真实模型生成探针。

| 项目 | 结果 |
|---|---:|
| Seed证据 | 2 |
| 主动探索查询 | 8 |
| Validation | 12（6可执行、6不可执行） |
| False allow / false block | 0 / 0 |
| Stable validation退步 | 0 / 6 |
| 实际违规 | 0 |
| 发布后新实例 | PROCESSING被拦截；NOT_STARTED退款及验证成功 |

最终规则为`shipment.status not_in [NOT_STARTED, SHIPPED, DELIVERED]`，在声明的四状态域内等价于`shipment.status == PROCESSING`禁止退款。它不是域外等价证明。

结构化等价类posterior为0.979920，OTHER为0.011174，等价类熵0.115164 nat；这些数值只适用于人工声明的有限观测模型，不是校准过的真实规则置信度。

候选写入独立实验Registry，版本`98b47f4d2ef7dd63a65169f201ac0386be67898ad640cb90bcfc0125e1b84bfe`。未修改主部署。接受/拒绝/恢复/篡改拒绝路径有测试，恢复命令已实跑并复用既有证据。

## 真实模型开发成本

目录：`results/active-evolution/v1/development/cost-smoke-v1/`。固定main-v3 SFT，六条旧策略独立开发任务，未读取正式test。

| 指标 | 测量 |
|---|---:|
| 平均完整任务耗时 | 23.85秒 |
| 小样本P95耗时 | 42.38秒 |
| 平均tokens | 12,812 |
| 平均LLM调用 | 5.17 |
| 平均工具调用 | 4.50 |

仅用于预先控制成本；n=6不能保证正式任务耗时分布。未据此选择效果较好的方法、种子或世界。W3/W5/W6模型子集按数值组合、类别组合、边界放宽三个类型事前选择。

## 回归与历史保护

独立源码回归175 passed、1 skipped；历史10,699文件SHA验证全部一致。测试回执在development/active-source-check-95b85a78a057455d854aa8d2aceacb69/。

没有新的Active/Random效率比较、正式EOC成绩或持续学习收益可报告。联合主指标、安全与Retention门槛保持预声明，正式结果出现前不填补缺失表格。

## 2026-10-02：隔离四方法开发协议

最新目录：`development/protocol-v5/`。开发seed=701，每世界6个seed、12个explore、8个validation和8个stable_validation；学习预算4次。test只生成，未评分。此小型协议的探索/验证不覆盖完整公开状态组合，不能用于正式质量结论。

| 世界 | No Adaptation | Passive | Random | Active |
|---|---|---|---|---|
| W3 | UNCHANGED / 0查询 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 |
| W6 | UNCHANGED / 0查询 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 |

8组恢复重跑全部通过，104条探针记录的内容和mtime均不变，回执为`analysis/resume.json`。代码改变后不可直接用新代码恢复；本次源码存于`source/`。

三档观测似然0.90/0.95/0.99只读重算保存在`analysis/sensitivity-*.json`。W3 Active四步的最高评分候选一致；W6 Active在0.90/0.95下有一步排序改变。所有三档最终均未收敛。这是固定历史上的重加权，未执行反事实路径，不能据此报告其成绩。Passive/Random的“是否与最高评分一致”仅是排序诊断，不能作为其是否按协议选样的判断。

No Adaptation的两组stable_validation各8条均保留原边界正确性，退步0/8。这仅验证配对统计接线，不是更新后的能力保留收益，更不是连续学习结果。

### 保留的问题记录与修正

- protocol-v2因Windows SQLite审计事件中的bytes路径解析失败；修复后新目录运行，失败目录保留。
- protocol-v3的全量posterior快照重复保存假设和历史，W3四组约426MB。增量日志格式保存一次初始状态、后续证据与哈希；同规模protocol-v4约43.7MB，减少约89.7%，支持复算恢复。
- protocol-v4的W6 Active曾在1次查询后通过开发验证，但候选实际为H0；8条验证未覆盖新放宽状态。**该记录不是适应成功**。已禁止把H0发布成新版本，并加入公开组合覆盖及准入时的变化机会检查。历史记录和当时源码均保留。
- dataset-v2的公开组合不按新世界真值选择：W1–W5共享退款组合，W6使用地址组合；CPU 80条探索/40条验证覆盖所声明组合。小规模split明确标记partial，不能凭运行通过消除覆盖缺口。

### 数据与正式门槛

`preparation/dataset-v2/`共30个数据包、10,032条任务，formal_experiment_frozen=false。模型层W3/W5/W6的model_validation和model_test共6个split未满足公开组合覆盖；详见`readiness.json`。旧模型成本草案与该缺口必须一起修订，尚未开始正式CPU或GPU评分。

第二批独立源码回归为186 passed、1 skipped，回执`development/active-source-check-79529c84a78e4c00800524e380e62d6d/report.json`；10,699个历史文件SHA一致。随后原子发布故障/并发测试及进程协议定向回归11项通过；最终独立完整回归为188 passed、1 skipped，回执`development/active-source-check-b34bd01095e24f00b4b8a1de27d69769/report.json`，历史SHA再次全部一致。

## 2026-10-02：全覆盖开发验收与冻结程序执行

`development/coverage-smoke-v1/`使用独立开发seed=701、12条seed、80条explore、40条validation、40条stable_validation、20次查询预算。未读取或评分正式test。

| 世界 | No Adaptation | Passive | Random | Active |
|---|---|---|---|---|
| W3 | UNCHANGED / 0 | INCONCLUSIVE / 20 | INCONCLUSIVE / 20 | VERIFIED / 7 |
| W6 | UNCHANGED / 0 | INCONCLUSIVE / 20 | INCONCLUSIVE / 20 | INCONCLUSIVE / 6 |

W6 Active因连续预期信息增益不足停止，等价类posterior约0.773、熵约0.643，不满足收敛阈值。其截断查询指标应计20，不能把实际6次花费算成更快成功。未因此调整学习阈值、预算或删除负结果。

W3候选为风险属于MEDIUM/HIGH且金额>3000时收紧；HIGH已被不变安全底线拒绝，因此在声明域内等价于新增MEDIUM且金额>3000限制。Validation 23个正例、17个负例，false allow/false block均0，stable_validation退步0/40，实际违规0。一个开发种子的结果不支持正式效率或显著性结论。

随后探针接入冻结父Skill的真实DSL，使用原程序、输入绑定与后置条件，单独写入`development/dsl-smoke-v1/`。W3 Active再次7次查询通过同规模验证。此轮只重复W3 Active用于检查DSL接线，不是重新选择有利方法的正式对比。

从该Registry加载候选后，在seed=9751的4个全新开发实例上实执行：MEDIUM/3001与HIGH/3001被Skill gate拦截且无退款调用；MEDIUM/3000和LOW/3001完成真实退款及读回校验。四例实际违规均0。记录见`post-publication/`。Skill不适用没有被自动转换为refuse/escalate监督标签。

同代码/配置恢复重跑通过，99条探针内容及mtime未变化，回执`post-publication/resume.json`；对应26份源码保存在`source/`。

模型层改为独立代表场景设计：退款世界共享8个分层点（风险、shipment组合与3000/3001边界对照），地址世界8个分层点（低/中/高风险、PROCESSING、已发货、订单状态、无效地址），另有4个稳定锚点。它不声称覆盖CPU的全部38/17种组合；结论范围需限定于该预声明子协议。

`preparation/dataset-v3/`共30组、10,044条任务，在各自声明的CPU/模型层覆盖范围内完整。model_validation从4增至8，其余model splits数量不变；模型清单872次基础任务+88次全局重试预留，旧smoke外推约11.30小时/1,230万tokens。新世界Runtime尚未实测，正式入口仍关闭，不能把旧耗时外推当成最终成本准入。

最新独立源码完整回归 **191 passed、1 skipped**，回执`development/active-source-check-573ee7e7cbd446ec8eb1ac81802e64fa/report.json`；10,699个历史文件SHA全部一致。工作台与原Student已恢复，adapter身份与原部署一致；原部署配置和旧签收记录未重写。

## 2026-10-03：新 Runtime 成本测量与正式冻结

新 Agent Runtime 使用独立版本化 policy view，传入公开任务、旧公开契约和已学习的 boundary patch；模型进程不接收 gold policy、fixture、期望终态或私有评测状态。主实验沿用统一的旧终态规则，Boundary 不适用不会自动获得新的 refuse/escalate 标签。隔离为 Python 协作式访问防护，不声称抵御任意恶意原生代码。

三个独立开发测量均保留原始记录与对应源码：

| 开发测量 | 执行数 | 资源外推 | 处理 |
|---|---:|---|---|
| new-runtime-cost-v1 | 12 Full System | 原清单约30.51小时 | 未通过；包含重复业务拒绝后耗尽步数 |
| new-runtime-cost-v2 | 12 Full System | 原清单约17.76小时 | 未通过；压缩工具schema出现4次无效模型输出 |
| new-runtime-cost-v3 | 12 Full System + 12 Decision | 完整清单10.74小时、约730万tokens | 资源门槛通过，使用完整schema与重复拒绝中止 |

前两次为当时工作量清单的估算，不与v3直接比较效率；原清单遗漏的更新前Decision和连续epoch对照已在最终冻结前补齐。v3 Full System小样本P95为49.99秒，Decision为6.49秒。正式清单上限为644 Full System + 368独立Decision，102次全局重试和600秒启动预留。只能按精确task/bundle/model身份复用必然相同的执行，不凭效果删减工作量。

开发smoke的更新后patch为人工声明的接线测试，不是学习成果。资源门槛不是质量准入；v3仍保留重复拒绝和max_steps任务失败，无效模型输出也不会被当作基础设施错误重试。

正式协议为`formal-v1/protocol.json`，标识`de3eae4b913556249d5d761b636b88dac87038f833a22825f62c899f6c9de60e`，73份源码及30组数据manifest均绑定SHA。冻结前源码完整回归201 passed、1 skipped，回执`development/active-source-check-31e54159c4f141c8a6d5a986d1da3b10/report.json`。

恢复前发现96个完整metrics检查点、原进程已退出；恢复使用同一冻结入口，不更换参数，不覆盖不同内容的记录。冻结后新增的只读审计脚本单独记录自身代码身份，不进入学习或改变原协议。

## 2026-10-03：正式 CPU 完整结果

`formal-v1/cpu-report.json`包含完整120组结果，每方法30组、2,400个新世界test和2,400个stable test案例。没有删掉未收敛、错误收敛或未发布结果。

| Method | 预算内收敛 | RMQ（cap=20） | 实际查询总数 | 新版本发布 | False allow | False block | Actual violation | Stable退步 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Adaptation | 0/30 | 20.000 | 0 | 0 | 130 | 6 | 0 | 0 |
| Passive | 0/30 | 20.000 | 600 | 0 | 130 | 6 | 0 | 0 |
| Random | 1/30 | 20.000 | 588 | 1 | 123 | 6 | 0 | 0 |
| Active | 26/30 | 8.033 | 188 | 25 | 2 | 5 | 0 | 0 |

Active相对Random的截断平均查询数下降59.83%，预算内收敛率差83.33个百分点。按预声明world-seed配对bootstrap，95%区间分别为RMQ差[-13.633, -10.067]、收敛率差[0.700, 0.933]。联合点估计指标通过，**held-out安全门槛失败，因此完整研究验收为false**。Random唯一收敛发生在第20次，故其RMQ仍为20。

失败定位：W5/seed401/Active在6次查询后收敛到H0（class posterior约0.98285）。Validation已有1次false allow；H0路径记录UNCHANGED、保留旧边界，没有发布“新能力”。该组test仍有2次false allow，因此在线收敛不等于正确适应。W6只有seed307获得发布，其余四组未收敛，合计5次false block。未据此扩大预算、调prior或重选种子。

零actual violation反映环境业务guard仍生效，不抵消false allow。此层执行固定程序探针，不是自主Agent EOC。边界变化能否转化为真实模型改善，仍由后续固定main-v3双评测决定。

`formal-v1/independent-audit.json`审核通过：120组、19,200条held-out案例、1,376条查询。审核核对manifest成员、任务/探针哈希、有效版本、预测/标签、违规计数、逐组指标、Active排名选择与最终配对统计；不新增查询，不等于在新环境重执行全部实验。

## 2026-10-03：两个连续 policy epoch

冻结的W3→W5、seed1701协议完成8个epoch×method组合。Active的两个连续更新均获准，第二次更新的parent_revision核对为第一次实际发布bundle的revision。

| Epoch | Active查询 | 新世界正确数（前→后 /80） | False allow | False block | Actual violation | Stable退步 /80 |
|---|---:|---:|---:|---:|---:|---:|
| 1 / W3 | 6 | 77→80 | 0 | 0 | 0 | 0 |
| 2 / W5 | 5 | 75→80 | 0 | 0 | 0 | 0 |

No Adaptation、Passive和Random均没有获准新更新；三方法W3保持77/80、W5保持76/80。第二epoch的Active更新前基线是它自己的W3 bundle，因此为75/80，不将其替换成H0的76/80。Stable分区同时排除相邻两个policy epoch标签变化的案例，逐任务统计遗忘与negative transfer。

记录：`formal-v1/continuous-report.json`、各`continuous/<epoch>/<method>/lineage.json`与`test.json`。独立只读审核核对了实际父revision、bundle哈希、有效patch、准入、manifest成员、探针/任务哈希、逐任务前后预测、相邻stable标签与指标，`continuous-audit.json`记录8组及2次获准更新。

这是固定程序Boundary层的连续适应证据。模型激活有独立准入，不能直接继承CPU的成功结论。

## 2026-10-03：固定 main-v3 真实 Agent 正式结果

完整20组配对完成：独立W3/W5/W6 × 四方法，以及两个连续epoch × 四方法。按精确任务/patch/模型身份复用控制组后，实际执行300次，token合计1,335,942，无基础设施失败重试。任务耗时2,477.84秒；包含启动和关闭的整次调用2,514.10秒（41.90分钟），均在冻结的12 GPU小时/20M token限制内。

四个Active的非H0更新提案全部未通过Agent准入：

| 阶段 | World | Full System validation EOC（前→提案 /12） | 独立Decision（前→提案 /8） | 正常任务退步 | 主要退步原因 |
|---|---|---:|---:|---:|---|
| 独立 | W3 | 4→4 | 7→8 | 1 | 执行错误 |
| 独立 | W5 | 2→2 | 7→8 | 1 | 缺少写后读回验证 |
| 连续epoch1 | W3 | 3→3 | 7→8 | 1 | 缺少写后读回验证 |
| 连续epoch2 | W5 | 6→3 | 7→8 | 3 | 缺少写后读回验证 |

以上是proposal validation诊断，**不是被拒绝提案的held-out收益**。W6的预声明seed101未产生新Boundary，Agent准入通过的是同一H0对照，不是激活成功。

正式test使用独立准入后的有效bundle；四方法最终均保留H0，因此各方法的更新前后成绩相同：独立层New-world EOC 12/24、Stable EOC 9/24、Decision 20/24；连续epoch1为2/8、5/8、7/8；连续epoch2为3/8、5/8、7/8。独立层Decision含2次false allow和2次UNKNOWN，actual violation为0；stable无退步，但不能把未更新的保留率解释成成功适应后的抗遗忘能力。有效bundle未变，因此配对test中的工具调用、tokens和耗时亦相同；共享控制组不是独立重复推理样本。

结论：有限空间的Boundary学习提升了CPU查询效率，并在两个连续epoch产生正确的新边界；模型validation的单步Decision有局部改善，完整任务执行却出现回归，故没有形成可激活的Agent更新。环境guard保证实际违规为0，不能抵消错误放行或执行失败。未据此调模型、改提示、换种子、重跑能力失败或训练QLoRA。

`formal-v1/delivery-audit.json`核验了全部父链、20组Agent任务/bundle配对、模型身份、准入、EOC/Safety证据重算、retention及成本账本。完整分组表和提案诊断见`formal-v1/DELIVERY.md`、`delivery-summary.json`，原始被拒绝提案仍在各`activation.json`和cache中。

## Evolution Trace 正式页面

工作台主页新增Evolution入口，支持120组独立轨迹和8组连续轨迹，逐查询展示Gap、hypotheses/posterior、Probe选择理由、Observation、Belief变化、最终Boundary和Validation；另有连续父链、CPU联合指标、真实Agent前后成绩与拒绝原因。页面只读，不发起模型调用或发布技能。

正式浏览器回执：`formal-v1/workbench/browser.json`；桌面/手机截图同目录。验证成功、错误收敛、No Adaptation及未收敛轨迹，切换查询、刷新恢复、方法完整性、主工作台入口、20组模型结果和手机无横向溢出。旧工作台源码、页面、部署配置、模型权重及历史签收均不改写，新入口通过独立package wrapper接入。
