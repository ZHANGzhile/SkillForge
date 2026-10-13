# 两阶段自进化：实施进展

2026-10-12 启动。HEAD 与用户方案基线一致；实施顺序见 [实施映射](SKILL_EVOLUTION_PLAN.md)。

## 本轮实现

- 新增不可变内容记录、完整 SystemManifest 构造、跨轮 SplitLedger 和显式预算。
- 新增 SQLite backup 加 Runtime checkpoint 的独立 fork：保留幂等记录、工具 audit、剩余故障、pending 验证、目录/已加载版本、搜索和模型预算、随机状态。
- 新增公开词法目录、精确 revision 加载和 task 内版本冲突拒绝。搜索不使用 task.family；load 剔除统计及原始来源，条件节点只公开 field/op/value。
- 新增 search/load/use Runtime adapter，复用 Gate、DSL、ExecutionContract。Primitive 与 Skill 均可完成业务，Runtime 辅助单独标注。
- 新增固定 main-v3 的独立模型 worker，沿用私有数据 guard，以 RPC 获取工具观察、持久化回执和快照。
- 新增 preflight/smoke CLI、开发配置和 19 项安全/恢复/目录/独立审计测试，针对性测试全部通过。

## 已完成的开发运行

首轮独立源码回归 293 passed / 1 skipped；第二版 295 passed / 1 skipped。真实 P1 smoke 两轮均已完成，模型进程与 GPU 租约已释放。

- `results/skill-evolution/v1.2/development/preflight-20261012-P1/`
- `results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v1/`
- `results/skill-evolution/v1.2/development/preflight-20261012-P1-v2/`
- `results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v2/`

首轮 4/6 EOC、2 次违规尝试、0 实际违规；第二轮显式公共规则上下文下 6/6 EOC、0 违规尝试、0 实际违规。第二轮 5 例无执行干预成功、1 例 Runtime 辅助，2 个真实 Skill 调用链成功，但曾有 2 次未加载调用被阻止后恢复。独立审计覆盖两轮全部 12 例及 328 个 checkpoint。两轮合计 233,471 tokens / 834.22 秒。完整解释与证据见[开发结果](SKILL_EVOLUTION_RESULTS.md)。

最小使用链工程 smoke 通过，尚未证明总体调用可靠率或研究收益；三个 family 全部使用 Skill 尚未演示。更强模型未配置，模型比较未完成。

最终独立源码回归 **298 passed / 1 skipped**，A/B 冻结源码再次校验一致。[最终 preflight 回执](../results/skill-evolution/v1.2/development/preflight-20261012-P1-final/preflight.json)。

## 下一阶段出口

先检查真实 search/load/use 结果及失败原因，再决定是否在 dev 修正接口或比较更强模型。P2/P3 的经验归一化、Opportunity 与 TraceCompiler 尚未实现；P4/P5 的新候选准入和三轮评测尚未开展。第二阶段尚未启动。

旧 v1.1 的失败结论继续保留：连续 stable 退步 1 个；Active v2 未优于原 Active、Challenge 未触发。历史 holdout 仅作诊断和已知缺陷回归。

## 新版方案实施（2026-10-12，追加）

当前以[新版实施映射](SKILL_EVOLUTION_REVISED_IMPLEMENTATION.md)和[新版 P0 审计](SKILL_EVOLUTION_P0_REVISED_AUDIT.md)为准。旧版“下一阶段”不代表新版 P1 已全部验收。

- 全库检索新增公开工具/观察摘要；私有审计记录分数组成、全目录排名、截断候选、目录 hash、延迟。历史 v1 搜索/load 重放保持兼容。
- Runtime 新增逐步 selection_trace、准确上下文/消息/可见集合 hash、Gate/选择/执行/验证证据；trace 和机会真值不进入模型历史。
- 独立机会评估在 SQLite fork 中实际执行，依据先声明的完整任务目标而非 family/name；首版仅覆盖初始完整任务，不覆盖任意中间子目标。
- 同状态分叉保留真实公开读取、DB/runtime/RNG、初态与上下文；只改变初始加载项。支持两臂均禁用发现及两臂均可自然发现的开发诊断。
- 新自然 smoke：6/6 EOC，0 attempted / 0 actual violation；3 个独立完整任务机会，2 个完整自然 Skill 链、1 个正确 primitive 替代。5 例无 Runtime 执行干预成功、1 例辅助成功。
- 两组零搜索预算诊断均为 provided 2/2、withheld 0/2；模型将 primitive 名输出为 Skill，提示澄清未修复，不能作为正式 Skill 收益。
- 允许搜索/加载的恢复诊断：取消订单形成 1 个完整配对，两臂均成功，预加载 2 次决策 / 10,266 tokens，自然发现 6 次 / 24,762 tokens；退款未预加载单臂也成功（5 次 / 21,792 tokens），其对应预加载臂因保守预算预留未启动。不能写成两个完整配对。
- 共享开发账本累计 **457,995 tokens / 1,677.40 秒**，包含所有旧 smoke、失败和新诊断。剩余 42,005 tokens，小于每任务 45,056-token 的预留要求；没有扩大 500k / 1,800 秒预算。
- 所有已执行自然/双臂记录经独立审计；部分运行明确记录 `evidence_integrity_passed=true`、`run_completed=false`。模型与 GPU 租约均已释放。
- 最终完整回归 **319 passed / 1 skipped**，两个上游弃用警告；正式 A/B 冻结源码及 main-v3 adapter 身份再次核对通过。[最终预检](../results/skill-evolution/v1.2/development/preflight-20261012-P1-audit-final/preflight.json)。

[新版阶段报告](../results/skill-evolution/v1.2/development/p1-revised-summary-20261012/REPORT.md)与[机器摘要](../results/skill-evolution/v1.2/development/p1-revised-summary-20261012/summary.json)。总体 P1 研究/正式准入未通过，未生成/激活新 Skill，P2/P3 尚未实施。下一步先补预算调度与可审计续跑、处理公平 PrimitiveOnly 基线，再进入公开工作流/EOC 与 learn 经验采集。

## 续跑完成、P1 开发出口与 P2 目标声明（2026-10-12，最新）

完整说明见 [P1/P2 检查点](SKILL_EVOLUTION_P1_P2_CHECKPOINT.md)。本节追加当前状态，不覆盖上节停止时的历史事实。

### 修改与原因

- `scripts/evolution_budget.py`：复用冻结 Worker 的推理前 checkpoint ACK 屏障，按 16,384-token 请求上限做共享账本准入；批准后未知请求保留预留，明确拒绝且未 ACK 的请求单独对账。
- `scripts/continue_skill_evolution_selection.py`：仅在新目录续跑从未启动臂，绑定原注册、模型、源码、快照、继承文件 hash 和成本。拒绝 mid-arm、pending 与源码不符；独立审计重放每个准入回执，检查继承和增量成本，没有把全部合并成本再计一次。
- `scripts/run_skill_evolution.py`：模型初始化支持调用方墙钟 timeout；旧 smoke 的整任务预留策略不变。新 workflow 真实采集尚无入口，之后应复用逐请求组件。
- `scripts/verify_skill_evolution_p1.py`：300/1000 合成容量、真空目录 PrimitiveOnly 与静态库的同协议 CPU 契约；合法 primitive 完成、错误 Skill 动作保留。全部 scripted，不能冒充真实 A/B/C 对照。
- `skillforge/skill_evolution/workflows.py`、`scripts/declare_skill_evolution_workflows.py`：先声明两种只读公共目标，再按真实工具回执和独立 DB 事实验收，拒绝缺证据、伪造、归属错误和未请求写操作。工单 passthrough 缺少独立验证契约，保持 `UNSUPPORTED`。
- 更新 P1 汇总脚本，区分继承臂和新执行臂，保留失败与原 partial 报告。新增 21 项预算/继承/容量/workflow 测试。

### 真实模型证据与成本

`p1-recovery-continued-20261012` 只新执行退款预加载臂：EOC 成功，2 决策 / 10,395 tokens，无 Runtime 强制读回/自动终止，无违规尝试/实际违规。三个已完成臂逐字节继承，没有重复执行。

现在取消/退款共 **2 个完整配对、4/4 EOC、0 attempted / 0 actual violation**。预加载臂总 4 决策 / 20,661 tokens，自然发现臂总 11 决策 / 46,554 tokens。它们是已知 dev 任务、静态历史程序，只支持初始预加载诊断，不是新 Skill 学习或统计显著性。

续跑新增 49.32 秒；共享账本累计 **468,390 / 500,000 tokens、1,726.72 / 1,800 秒**，包括所有历史失败。原 partial 报告未覆盖，缺失臂已补齐。独立 source/message/context/DB/checkpoint/Receipt/EOC/成本及续跑准入审计均通过。模型进程、GPU 租约已释放。

[最新 P1 摘要与报告](../results/skill-evolution/v1.2/development/p1-revised-summary-20261012-v2/REPORT.md)：`plumbing_passed=true`、`agent_smoke_passed=true`；`research_claim_passed=null`、激活/部署 false。自然 smoke 仍为 6/6，3 个初始目标机会中 2 个完整自然 Skill 链、1 个合法 primitive。

### P2 当前出口与数据身份

[P2 声明](../results/skill-evolution/v1.2/development/p2-workflow-declaration-20261012-v2/report.json)先于候选程序：`shipment_summary` 与 `logistics_investigation` 两种只读事实采集目标，共 6 个待采集 train/learn 案例登记到来源账本。同源实体/seed 重贴分区会冲突；没有生成 validation/test。v2 对证据做严格类型比较，拒绝 `True == 1` 产生的数量伪匹配；首版仍保留。

已运行 6 次独立 EOC 的 scripted CPU 演练，**真实 learn 轨迹 0、Opportunity 0、候选程序 0**，不会把这些演练送给 learner。资料采集不等于调查推理；不能声称工单证据已验证。新 workflow EOC 必须由后续真实采集入口显式路由，不能调用旧 verifier 代替。P2 新源码改变下一次运行身份，不作为原 P1 serving 源码继续执行。

### 验证与下一步

最终源码完整独立回归 **340 passed / 1 skipped / 2 upstream warnings**；正式 A/B 的 86/100 个冻结源码、历史资产和 main-v3 adapter 身份检查通过。[最新预检](../results/skill-evolution/v1.2/development/preflight-20261012-P1-P2-contracts-v2/preflight.json)。历史两份 README 例外保持原记录。

主要命令：

```powershell
.venv-train/Scripts/python.exe -m scripts.continue_skill_evolution_selection continue --parent results/skill-evolution/v1.2/development/p1-main-v3-fork-20261012-v3-discovery-recovery --output results/skill-evolution/v1.2/development/p1-recovery-continued-20261012
.venv/Scripts/python.exe -m scripts.continue_skill_evolution_selection audit --run results/skill-evolution/v1.2/development/p1-recovery-continued-20261012
.venv/Scripts/python.exe -m scripts.verify_skill_evolution_p1 --output <fresh-CPU-output>
.venv/Scripts/python.exe -m scripts.declare_skill_evolution_workflows --output <fresh-declaration-output>
.venv/Scripts/python.exe -m scripts.run_skill_evolution preflight --config configs/skill-evolution-v1.2.observable-dev.json --output <fresh-preflight-output>
```

第一条记录当时的实际续跑；现在因 P2 源码增加而有不同 serving 身份，不能原样强行重新执行旧父实验。审计命令仍适用。所有输出目录必须是新的，且来源账本不能清空。

下一步：先注册新的 workflow 真实采集协议与预算/源码身份，接入独立 EOC 及逐请求预算，采集真实 learn；再实现归一化、跨来源 Opportunity、TraceCompiler 和候选验证。P1 开发工程出口满足，真实 PrimitiveOnly/StaticLibrary/ExperienceEvolution 的正式对照留 P5。P2/P3 整体、三轮演化和第二阶段尚未完成；没有新 Skill 准入、SFT/DPO/RL、隔离激活或部署。

## P2 真实 learn 与 P3 只读编译初版（2026-10-12，前批）

完整说明见 [P2/P3 阶段文档](SKILL_EVOLUTION_P2_LEARN.md)与[本批报告](../results/skill-evolution/v1.2/development/p2-learn-summary-20261012/REPORT.md)。保留前文“尚未采集”的历史状态，不覆盖旧证据。

### 实现与证据

- `scripts/collect_skill_evolution_learn.py`：采集前登记源码/目标/目录/模型/预算；共享 ledger 拒绝重复 phase、前序未结算和累计成本重置。接入逐请求 checkpoint/ACK 准入与独立 workflow EOC。审计重放请求、真实观察、精确 messages、SQLite 快照、EOC、状态及安全/成本汇总。
- `configs/skill-evolution-v1.2.learn-dev.json`：单独 P2 开发额度 200,000 tokens / 900 秒，保留 P1 累计 468,390 tokens / 1,726.72 秒；P1 原 500k / 1,800 秒上限不变。
- Runtime dev5：增加公开只读目标与终态规则；授权读取不因 HIGH/CANCELLED/SHIPPED 而停止。Worker 文件访问收窄到 public scratch，私有 fixture/EOC 不可读；旧 business Guard 和冻结 A/B 不改。
- `skillforge/skill_evolution/experience.py`：learn-only 公共输入绑定、实际调用顺序及节点来源；失败/不可表达绑定保留排除，scripted 检查不进入经验。筛选核对新颖结构、至少三组来源、预声明目标及包含发现开销的效益。
- `skillforge/skill_evolution/compiler.py` 与 `scripts/compile_skill_evolution_traces.py`：逐节点从归一化轨迹生成 CANDIDATE；程序随有效调用顺序改变。缺来源、heldout 混入、事件不一致和效益造假拒绝。现阶段仅直线只读流程；无合格 Opportunity 时直接 NO_USEFUL_CANDIDATE。

### 真实结果

六个预先声明的 train 案例全部执行完成、独立审计通过：**6/6 EOC、6 个无 Runtime 执行干预成功、0 个辅助成功**。21 次模型决策、15 次模型来源工具调用；违规尝试、实际 policy violation、实际 workflow violation 均为 0。静态覆盖检查另有 22 次 scripted 工具调用，明确排除于 learn。

新增成本 **68,906 tokens / 178.10 秒墙钟**。共享累计 **537,296 / 668,390 tokens、1,904.82 / 2,626.72 秒**；没有改变旧 P1 账本。模型 Worker 已退出、GPU 租约已释放。没有继续花剩余预算追逐正结果。

两模式各有三个独立来源；新颖结构和有效目标通过，但摘要自然执行三次决策、调查资料四次决策。按 search/load/execute/stop 四次决策估计，节省为 -1 / 0，未达到预声明的至少一次节省。因此真实结果为 **NO_USEFUL_OPPORTUNITY → NO_USEFUL_CANDIDATE，0 Opportunity / 0 候选**。没有把重复出现或业务成功等同于有用能力沉淀。

真实采集 protocol hash：`4cf95916a058f4a69ce948993557b2fce285cdab72db7942fdf458167559eb31`；编译绑定 hash：`d6130d4e57b0e6193760fc64a75801b2386a70c30e280c99c3b1f316fcf46743`。源码、注册、原轨迹与零更新回执均保留。

### 验证与后续出口

最初完整预检发现旧审计器只识别 dev3/dev4，造成 search replay 两项失败；显式加入 dev5 兼容后通过。随后增加安全聚合独立重算、编译轨迹变化与伪造拒绝测试。最终独立源码副本 **360 passed / 1 skipped / 2 upstream warnings**，正式 A/B 的 86/100 个冻结源码、历史文件保护与 main-v3 adapter 再次通过核验。

P2 首版真实采集/归一化/无机会出口完成；P3 只读编译路径完成工程验证，真实候选尚不存在。返回值依赖、写入读回 assert、组合、RevisionPlanner 未实现。下一步补 P4 语义去重/修订治理和正/边界/负/故障及配对验证约束；本批不进入新 Skill 真实准入。后续若扩展 learn 结构，必须先声明公开目标/独立 EOC、冻结筛选规则并登记新累计预算。

`program_admitted=false`、`agent_admitted=false`、`research_claim_passed=null`、`isolated_activated=false`、`deployed=false`。没有新 SFT/DPO/RL；第一阶段三轮正式研究与第二阶段未完成。

## P4 只读治理、独立验证和配对统计门（2026-10-12，前批）

详细范围和限制见 [P4 阶段说明](SKILL_EVOLUTION_P4_GOVERNANCE.md)，原始证据见 [最终工程报告](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/REPORT.md)。本批保留真实 P2/P3 的零候选及原目录，未运行模型。

### 新实现

- `governance.py`：按输入规范化的 semantic/program/boundary 指纹、精确重复与潜在重复分开；metadata/program/boundary 修订约束、父版本与 supersedes、第一阶段 Boundary 禁改；不可变 RevisionMemory 与生命周期。正式反馈不得回流优化器，每父最多两次 learn/dev 尝试，未验证/被拒父版本不能进入正式父链。
- `validation.py`：先声明验证协议与来源所有权、绑定候选/目标/源码；静态检查输入/观察依赖、读取白名单、唯一终止及后置身份契约。每例独立 SQLite 执行，由独立 workflow EOC 与完整数据库 hash/pending 核验；审计重新执行，防止重算 hash 后伪造结果。工程模式不能准入。
- `admission.py`：预声明同任务/初态/来源、共同执行后端、两个目录及相同预算；按来源组计算平均差和 exact sign gate，stable 不进入 primary 分母。缺配对/费用未知弃权，逐例回退/违规拒绝。成本 protocol-v2 不奖励双方失败后更早结束，保留这些单元的零收益。
- `verify_skill_evolution_p4.py`：保存完整源码快照，执行 scripted CPU 验收，再独立重放归档证据。连接真实 learn/编译回执，证明零候选时保留父目录；不把工程夹具送入 learner，也不注册 Skill。

### 工程结果与边界

8 例全部符合预声明行为：2 Positive、2 Boundary 完成事实采集；2 Negative 由环境安全拒绝；2 Fault 安全退出。只有四例业务 EOC 成功，不能把八例工程通过写成八例任务成功。一次原始权限违规尝试保留，明确是工程注入的错误顾客探针；无数据库变化、无 pending、无非预期违规。

工程程序回执 **INCONCLUSIVE**，生命周期最终同样 INCONCLUSIVE，没有进入 VERIFIED。六来源组的合成成本增益通过算术统计门，但 `agent_admitted=false`；单来源组 100 任务仍弃权。合成记录不是模型轨迹、正式研究数据或学习证据。

最终 r3 执行 19 次程序验证 +19 次准入重放，独立事后审计另重放 19 次。所有调用都是 scripted CPU，新增模型调用/tokens 为 0。前两版工程结果与审计保留；r3 补上成本收益条件，不能拿旧门槛支持新结论。

真实目录 hash 保持 `d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa`；真实模型累计仍为 **537,296 tokens / 1,904.82 秒采集墙钟**。CPU 工程/测试耗时另计，未启动 GPU；Worker 与租约均不存在。

### 最终核验与待办

P4 定向 30 项通过；完整独立源码副本 **390 passed / 1 skipped / 2 upstream warnings**。正式 A/B 冻结源码、历史文件保护及 main-v3 adapter SHA256 均通过。[预检](../results/skill-evolution/v1.2/development/preflight-20261012-P4-final-r2/preflight.json)；[独立 P4 审计](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/evidence-audits/954f75226dace9a479693059c21241492a1ac7738517c9a5625408dc12aded2f.json)。

当前仅支持直线只读程序。正式程序 API 没有真实候选实测；配对门还未接真实 Agent 原始轨迹/费用审计；正式注册、废弃/回滚目录快照与 ISOLATED_ACTIVE 执行入口待补。P3 返回值依赖、写入读回 assert、组合和 RevisionPlanner 尚有限制。

下一步补完上述治理与真实 Agent 证据接入，再进行 P5 同后端 A/B/C 成本 smoke 和三轮 protocol 冻结。真实候选仍为 0，不降低筛选门槛填补轮次。没有新训练、正式准入、研究收益、隔离激活或部署；第一阶段三轮和第二阶段尚未完成。

## P4 版本目录、祖先回滚和原始 Agent 证据（2026-10-12，前批）

详见 [阶段说明](SKILL_EVOLUTION_P4_REGISTRY.md)与[工程报告](../results/skill-evolution/v1.2/development/p4-registry-20261012/REPORT.md)。本批补齐版本选择和原始证据适配，没有运行模型。

`registry.py` 增加不可变 registrations/snapshots。新程序注册绑定正式程序准入、独立重放的真实 learn/机会筛选/编译、精确提案与新的 VERIFIED 发布 hash；不覆写原候选。一个 Skill 只能选中一个版本，依赖闭包检查保留。legacy import 不冒充新准入；零更新、废弃和祖先回滚均生成新快照，旧字节完整保留，没有 latest 或服务状态写入。

`agent_evidence.py` 在独立 SQLite 中重放保存的模型响应，从公共上下文、原始响应/Action、工具因果、全部 durable checkpoint、对象/RNG/fault 状态、费用批准/结算到独立 EOC/Safety 逐项核对。`provenance.py` 将此审计接回原 P2 真实采集和 P3 筛选/编译。六条真实轨迹全部通过：6 EOC / 6 autonomous / 0 assisted，原成本仍为 21 calls / 68,906 tokens。

配对适配器冻结完整案例、source/entity 所有权、共同模型/Runtime/提示/源码/限制、两个 Catalog 和累计预算；从不同原始证据目录生成统计输入，独立审计再次从文件重算。真实 train 被 validation 协议拒绝，工程程序回执被注册入口拒绝，重算 hash 不能使篡改报告通过。

真实结果依然 `NO_USEFUL_CANDIDATE`。工程链 `LEGACY_IMPORT → RETAIN_PARENT → engineering DEPRECATED → engineering ROLLBACK` 的保留/恢复目录 hash 均为 `d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa`。废弃和回滚只在新工程快照分支中演练，未操作实际服务。

工程记录执行 15 次 CPU 轨迹重放工具调用，事后独立审计另 15 次；真实模型 calls/tokens 增量为 0，共享累计仍为 **537,296 tokens / 1,904.82 秒采集墙钟**。Worker 已退出，无本阶段 GPU 租约或后台模型任务。

新增定向 21 项通过；全量独立源码副本 **411 passed / 1 skipped / 2 upstream warnings**。正式 A/B 冻结源码、历史保护和固定 main-v3 adapter 验证通过。[预检](../results/skill-evolution/v1.2/development/preflight-20261012-P4-registry/preflight.json)；[独立审计](../results/skill-evolution/v1.2/development/p4-registry-20261012/evidence-audits/74ea582059366dcc35155060d0a3db67d52cd7c95ce4e3d7da585038ede23183.json)。

当前没有真实新候选，正式成功注册分支尚未实测。raw evidence → statistical gate 已接通，P5 正式配对采集控制器、正式 Agent admission receipt 和 isolated activation controller 尚未接入，所有 admission/activation/deployed 仍为 false。只读完整已结算轨迹之外的写入/故障/中断 Agent 重放不受支持；返回值绑定、组合、RevisionPlanner 和新版 Workbench 仍待办。

下一步接 P5 同后端 A/B/C、No-History 与三轮父链的采集/费用控制器，成本 smoke 后冻结正式协议；真实候选验收维持原效益门槛。没有新训练或研究收益声明。

## P5 同后端成本 smoke 与三轮草案（2026-10-12，当前）

详见 [阶段说明](SKILL_EVOLUTION_P5_COST_SMOKE.md)与[本批报告](../results/skill-evolution/v1.2/development/p5-smoke-20261012/REPORT.md)。补齐 A/B/C 同后端采集控制器、逐请求费用和 phase ledger 绑定、No-History 检查、未完成臂保守对账及原始六臂独立审计；草案生成器在审计通过后输出不可变三轮计划。

两个开发来源组、六臂真实 main-v3 均完成：**6/6 EOC、6 autonomous、0 assisted、零 Safety 事件**。A 空目录，B 静态目录，C 为真实零更新父快照；三臂执行预算、工具和后端相同。所有臂走 primitive，未搜索/加载/执行 Skill；B/C 内容相同，配对 EOC / calls / tokens 增益均为 0。真实候选仍为 0，无学习收益声明。

新增 **21 calls / 68,891 tokens / 174.85 秒采集墙钟**；共享累计 **606,187 / 668,390 tokens、2,079.67 / 2,626.72 秒**。剩余 62,203 tokens / 547.05 秒。模型工具调用 15 次、静态覆盖 CPU 12 次、独立审计 CPU 重放 15 次分别登记。Worker 已退出，GPU 租约已释放，无后台模型任务。

P5 定向 **14 passed**；独立全量预检 **425 passed / 1 skipped / 2 upstream warnings**，冻结正式 A/B、历史资产与 main-v3 核验通过。

[三轮草案](../results/skill-evolution/v1.2/development/p5-draft-20261012/draft.json)已保存，`frozen=false`、真实完成 0 轮：18 次 learn、最多 48 次候选条件 Agent validation、54 次最终 A/B/C test，最多 120 次模型执行。实测加两倍余量规划约 **276 万 tokens / 1.94 小时采集墙钟**；GPU 小时未实测，正式研究预算未登记。当前只支持 Instance / Paraphrase / 授权只读 Boundary，Structural / Compositional 与 Agent 授权拒绝 EOC 不支持。各臂已无跨任务原始记忆，不能另宣称独立 No-History 消融效果。

下一步补正式 Agent admission receipt 与隔离激活控制器，核验候选成功/拒绝/弃权与零更新父链；登记继承开发成本的独立研究预算、源码/来源/实体账本后冻结并执行三轮。没有新训练、程序/Agent 准入、激活、部署；第一阶段正式三轮、Workbench 新版页及第二阶段仍未完成。

## P5 正式出口控制器（2026-10-12，实施中）

新增 [正式出口说明](SKILL_EVOLUTION_P5_RELEASE.md)。`scripts/skill_evolution_release.py` 接正式 Agent 回执与固定版本本地隔离 Runtime；`scripts/run_skill_evolution_rounds.py` 接三轮 learn/compile/程序验证/Agent 准入/保留父目录及最终同后端 A/B/C。最终独立源码预检 **445 passed / 1 skipped / 2 upstream warnings**。上述 CPU 工程夹具不代表真实准入。

正式三轮协议已冻结并启动真实 main-v3：`results/skill-evolution/v1.2/formal-P5-v1`，hash `11a5a40f86153c81b7b7b57b7ba483d21fa2d78a4deafc2a76298a63f1476ce5`。独立研究额度 2,800,000 tokens / 7,200 秒，完整继承开发 606,187 tokens / 2,079.67 秒；旧开发上限不变。当前属于正式运行中，最终结果和费用以独立审计回执为准。前两轮已得到零候选并保留父目录，后续轮次及最终 test 正在继续；不把零更新冒充新能力。

新只读页面 [Evolution Trace](http://127.0.0.1:8093/skill-evolution) 展示实时保存进度、程序/Agent/激活漏斗、父链、成本与轨迹。新页面 3 项测试通过；未改变模型 Runtime 源码身份或旧 Workbench。没有生产部署、新训练或第二阶段运行。

## Stage 1 正式完成与 P6/P7 启动（2026-10-12）

三轮真实 learn 18/18 EOC；54/54 最终臂完成，独立重放审计通过。A/B/C 各 18/18 自主 EOC、零违规；三轮零候选、无新准入或激活，C-B 费用/成功率增益为零。新增 827,254 tokens / 1,472.36 秒，累计 1,433,441 tokens / 3,552.03 秒。第一阶段实现与保留目录已冻结，详见 [正式报告](SKILL_EVOLUTION_STAGE1_FORMAL.md)。

P6 已新增独立公共工具回执适配和触发器，18 项 CPU 契约测试通过，尚非真实 Agent 日常流实验。P7 全部 30 active/v2 对、186 个实际 query 已审计：H0 普通收敛入口 0、排名/查询差异 0；7 个未收敛 fallback 合计 12 个有效边界错误，无已认证 H0 错误收敛。不能用此结果宣称 Challenge 有效或直接选择优化超参。

## P6/P7 开发出口追加

[P6 受控触发](SKILL_EVOLUTION_P6_TRIGGER.md) 11 个 SQLite 事件/56 次工具调用和恢复费用重放通过。[P7 历史诊断](SKILL_EVOLUTION_P7_HISTORY.md)与[五方法开发消融](SKILL_EVOLUTION_P7_DEV.md)均已独立审计：30 新运行、322 次逻辑 query，结论 KEEP_EXISTING，无新增 acquisition 收益。独立 learner 通过私有数据/规则访问拒绝测试。新增 Boundary Runtime 保持原程序/权重/系统提示/检索算法，版本化业务 Boundary 替代父业务条件、保留 Guard；5 项工程契约通过。7 例真实 H0 Runtime 成本 smoke 已单独登记 250k token / 900 秒额度并启动，尚未最终审计。

Workbench 新增第二阶段开发证据卡；桌面/移动精确视口校验通过（1440 / 430，均无横向溢出），只读页面与费用状态不运行实验。最新定向合计 35 项通过；原 UI 3 项另行复核。

## P6 真实验证与 P8–P10 接线追加

[真实 H0 smoke](SKILL_EVOLUTION_P6_REAL_RUNTIME.md) 已完成并独立审计：7/7 EOC、6 自主/1 辅助、47 calls / 222,348 tokens / 604.82 秒，累计 1,655,789 tokens / 4,156.85 秒。新 [Boundary 版本与准入](SKILL_EVOLUTION_P8_P10_BOUNDARY.md) 已通过独立 CPU 验证：六个计划单元，两个 W1 通过门槛、四个 W5/W6 弃权；152 探针 / 1,140 工具调用。新增 8 项工程测试通过，真实 Agent 准入/激活仍为 0。变化规则六臂真实 smoke 已登记 350k token / 1,200 秒并执行中，W6 明确为 Oracle 接口诊断；最终结论待完成和审计。

## Stage 2 工程规模正式冻结与启动（2026-10-13）

[变化模型 smoke](SKILL_EVOLUTION_P9_REAL_CHANGED.md) 六臂独立审计通过；W1 新 Bundle 无 EOC/违规尝试改善，W6 Oracle 对照仍 Runtime-assisted。累计 1,851,663 tokens / 4,789.28 秒。精确预检 497 passed / 1 skipped，源码复制/测试期间不变均核验通过。首次 Windows 长路径失败日志保留。

[正式协议与命令](BOUNDARY_EVOLUTION_FORMAL_PROTOCOL.md) 已冻结并启动：`15bc371cf0011b0965ccffa98a22c95a6d12efb983780fdcebd78f3b012afdbb`；CPU 90 运行、真实 Agent 12 阶段/4 world-sequence，固定 changed/unchanged/restore_original。Agent gate 以 world-sequence 聚类，样本不足不激活。后台流程自动串联两条采集、独立审计和报告；本段不是完成或收益声明。只读 Workbench 已展示分离漏斗和真实费用，5 项 UI 回归与桌面/移动宽度检查通过。

## 正式审计路径修复并续跑（2026-10-13）

CPU 90/90 已完成，独立审计进行中。Agent 原 10 臂因审计器无法重放真实无效 Action 的已知 usage 失败路径而中断；原 Runtime 正确记录 error/EOC=false。已新增版本化审计扩展及两项失败/篡改回归，10 臂/281 checkpoint/259,057 tokens 复核一致。只复用完成证据并继续缺失任务，不改冻结策略、样本、门槛或预算。原 partial report 保留，最终结果另写 continuation-v2；[原因、版本及命令](BOUNDARY_EVOLUTION_AUDITOR_CONTINUATION.md)。后台流程恢复运行，尚非最终完成。

## Stage 2 CPU 正式评测独立审计通过（2026-10-13）

CPU 90/90、3,058 实际探针回执、416 逻辑查询全部重放通过，审计 hash `e88791b66b0d6507409a76fa49097f5699acd5fac601b7d0ebc43c200d9ed156`。[正式 CPU 报告](BOUNDARY_EVOLUTION_FORMAL_CPU.md) 分开列全阶段 raw convergence/RMQ、effective FA/FB、stable 退步和 CPU-only 更新；不当作真实 Agent 激活或显著提升。Agent 审计器修复续跑已越过原失败点，目前继续原 cohort；采集结束自动独立审计、生成最终报告。
