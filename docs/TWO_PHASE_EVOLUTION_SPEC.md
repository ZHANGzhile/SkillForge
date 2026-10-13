# SkillForge：两阶段自进化实施方案
## 第一阶段：经验驱动的技能沉淀与复用
## 第二阶段：执行驱动的主动边界进化

日期：2026-10-12。
用途：交给 Code Agent 的实施规格。
已核对基线：ecceeb317bbe967b30b36c58df5031c6e7bfbdce。
仓库：https://github.com/ZHANGzhile/SkillForge

本版取代上一版“条件持续SFT”作为当前工作计划。第一、第三条线依次实施；第二条线后训练不进入必做项。历史SFT/DPO结果和服务保留，不新增训练流水线。
文中的新模块、接口、阈值、命令和结果要求均为待实施设计，不表示已实现或已验证。

## 0. 目标、范围与不能混淆的结论

固定模型参数，让系统：
1. 从任务执行经验中发现值得抽象的流程，产生候选Skill，验证、注册，再在不同任务中检索复用。
2. 从后续交互中发现已有Skill的边界可能失效，主动选择试验，修订边界，独立验收，再继续使用。

人预先定义环境、工具、受限DSL、允许的规则语言、验证器和预算；每轮具体抽象哪个流程、提出什么程序、查询哪个案例、是否更新，由系统根据经验决定。
自进化允许“无有用候选”“证据不足”“候选拒绝”和“保留旧版”，不强制每轮修改。

研究范围：
- 现有订单领域、已有业务工具及安全Guard。
- 首版程序仍限12节点以内的call/assert/finish，不引入任意代码执行。
- 第一阶段先支持可表达的直线流程；动态分支与任意程序组合不是首版必做。
- 第三条线保留有限规则假设域，并显式处理域不足；不要求无限开放的规则发现。
- 开发阶段可以比较模型；正式实验固定执行模型、提案模型、提示、协议和解码。
- 不依靠每轮修改模型权重取得效果。

结论要区分：
- 新目录/描述不等于新程序。
- 新Skill ID不等于新增能力；与已有流程语义重复要去重或标修订。
- 不改变工具权限，但改善覆盖、可复用流程和执行成本，可以是系统层面的进化。
- 固定三个程序但换订单号，只能支持调用与实例泛化，不能证明自主能力生成。
- 限定领域内的自进化可以成立，但不宣称跨任意业务/开放世界泛化。

## 1. 核对现状，明确真正需要补的地方

| 仓库已有模块 | 已核对行为 | 本次处理 |
|---|---|---|
| skillforge/runtime.py | 根据公开task.family筛选少量Skill，hydrate后把完整候选提供给模型 | 新增主动search/load，保留旧入口作对照 |
| skillforge/retrieval.py | 主要用于Memory检索 | 新增独立Skill目录与索引 |
| skillforge/skills.py | Gate/execute/SkillRegistry已存在；compile_skill按三个family固定mutation、读取和流程 | 复用执行与安全；新增从轨迹推导程序的编译路径，旧compiler作为基线 |
| skillforge/schemas.py | Action包含tool/skill/stop/escalate/refuse；Skill DSL无动态分支 | 新增版本化公共目录/引用协议；不假定DSL支持分支 |
| skillforge/provenance.py、dataset.py | 来源、分区、数据身份审计 | 复用并增加跨轮来源ledger |
| execution_aware/contracts.py | 验证回执、pending义务、提交未知、恢复协议 | 复用，保持作用和来源可见 |
| execution_aware/runtime.py | v1.1执行契约和自动读回/终止 | 作为固定执行后端，通过adapter增加新目录能力 |
| gap_detection.py | boundary主通道使用公开EvidenceView；secondary通道消费终态诊断 | 保留通道隔离，增强线上触发和误报诊断 |
| belief.py、active_learning.py | 有限假设、OTHER、贝叶斯更新、EIG | 复用；不把posterior当已校准置信度 |
| execution_aware/controller.py、challenge.py | 已有H0 Challenge/主动获取增强 | 先完整归因；不能再把“增加H0 Challenge”当新工作 |
| evolution_registry.py、evolution_journal.py | 不可变边界版本、恢复与日志 | 复用，绑定到第一阶段Skill版本 |
| v1.1交付与实验 | 固定main-v3；A连续评测出现stable退步，B未证明增强Active优于原Active | 保留失败结论，从这些缺口出发做新实验 |

必须先阅读：
README、AGENTS.md（若存在）、docs/DESIGN.md、ISSUES.md、EXECUTION_AWARE_V1_1_DELIVERY.md、EXECUTION_AWARE_EVOLUTION_V1_1_PLAN.md、EXECUTION_AWARE_A_ASSESSMENT.md，以及相关源码和正式结果protocol。
先记录实际checkout与本文件基线差异。历史已查看holdout只作诊断/已知缺陷回归，不再当本轮新证据。

## 2. 共同基础：先建好，两个阶段共享

推荐新增：
    skillforge/skill_evolution/       # 第一阶段
    skillforge/boundary_evolution/    # 第三条线新增连接与改进
    skillforge/evolution_common/      # 版本、经验、来源、快照、预算、报告

职责可以按仓库风格合并；不要为追求文件数量建空壳。

### 2.1 系统与Skill版本

SystemManifest：
system_id、parent_system_id、执行模型/adapter哈希、提案模型身份、tokenizer、prompt、action_protocol、Runtime/工具源码哈希、目录快照、Skill版本集合、Boundary版本集合、retrieval配置、解码、数据/protocol身份。

SkillRevision：
skill_id、revision、parent_revision、inputs、程序、公开适用/禁止条件、postconditions、来源轨迹、支持域、验证回执、状态、内容哈希。

BoundaryRevision：
目标skill_id与程序revision、父Boundary、公开predicate/patch、支持域、探索证据、假设域版本、准入回执、内容哈希。

程序和Boundary可独立版本化，但Skill发布快照必须引用完整组合，不能在运行中悄悄更换。
修程序后旧Boundary是否仍适用，必须兼容性检查和复验，不能默认沿用。
历史版本不可变；一个task固定一个目录/系统快照。
先在隔离实验中activate；不自动切换主工作台、现有模型或线上服务。

### 2.2 经验记录与公共/私有分离

每次任务保存：
任务/来源组/split、精确模型messages、搜索查询与候选、加载版本、公开观察、模型动作、实际执行动作、工具返回、执行阶段、验证回执、错误/预算、模型/系统身份、最终独立验收。

模型可见：
请求、参数、公开目标/工作流、实际工具观察、当前公开有效规则/边界、Skill公共内容。
模型不可见：
Task.expected、fixture、私有完整数据库、gold新规则、heldout标签、validation统计、未来观察、审计器的标准答案。

来源区分model、skill、gate/hydrate、runtime、proposal_model、scripted、probe。
Runtime补读/自动结束不得记为模型学会；scripted无LLM调用，不能冒充真实模型轨迹。

### 2.3 快照与隔离

使用SQLite一致性backup及Runtime checkpoint：
业务表、幂等账本、audit前缀、故障剩余状态、重试预算、随机状态、pending验证、加载表、目录身份、搜索预算。
只保存env.snapshot()不是完整恢复点。
fork分支独立DB，禁止写原运行；恢复校验身份与哈希。
延续v1.1提交未知/读回规则，不用“余额未变”推断未提交。

### 2.4 数据、预算和持久化

learn/train产生经验与提案；dev调方法；validation准入；test/stable holdout冻结研究评测。
分区按来源组、模板/结构、实体和seed隔离；同轨迹的变体和fork必须同分区。
跨轮ledger禁止把之前validation/test变为learn；正式test不触发针对性修补。
边界lane只接seed/explore的允许证据，终态EOC不回流规则learner。

每次控制器决策、候选、验证、拒绝、fallback原子落盘，恢复检查源码/模型/数据身份。
预算包含模型执行、候选生成、失败请求、检索加载、Gate、Skill内部工具、探针、全部验证与对照。
开发cost smoke后冻结全预算。CPU/scripted工程结果与真实模型结果分开；缺模型/GPU为blocked，不静默fallback。
不新增训练GPU预算。RTX5070 12GB如沿用本地模型，兼容性、显存和吞吐以实际smoke为准。

# 第一部分：技能沉淀、主动发现与经验复用

## 3. 第一部分要回答的问题

“从执行经验自动沉淀出的Skill，能否被Agent主动找到、正确调用，并在新任务上带来业务或成本收益？”

拆为两个独立子问题：
A. 使用机制：已有验证Skill能否被搜索、加载、正确使用？
B. 生成机制：新程序是否从轨迹产生，而非固定模板填参数？它是否有效、可泛化、有复用价值？

先A后B。A不可靠时先诊断，不立即改训练；可以在dev比较更强执行模型，选定后冻结。
B若没有产生比已有库更有价值的新能力，应报告no_useful_candidate，不能强行新增重复Skill。

## 4. P1：先打通主动search/load/use

### 4.1 接口

编排层虚拟工具：
    search_skills(query: str, top_k: int = 5)
    load_skill(skill_id: str, revision: str)

Action仍可type="tool"；虚拟工具由orchestrator dispatch，不传业务Environment。
现有type="skill"用于执行。增加本次task的loaded_refs表：skill_id → exact revision/content_hash。
同一task加载同ID不同revision拒绝冲突，不能覆盖；所有调用记录准确版本。

search返回：
ID/revision、名称、任务用途、输入摘要、公开适用/禁止摘要、依赖、状态、内容哈希。
load返回：
完整输入契约、程序、当前有效Boundary、postconditions及支持范围。
验证统计、完整来源轨迹、私有标签留给审计器，不随load给模型。

首版本地词法索引，FTS5可用时采用，否则纯Python确定性fallback；embedding可后续独立消融。
检索不能靠私有gold类别路由。公开task.family仅可作辅助，并单列不使用family的检索结果。

开发默认：top_k=5、最多3次search/3次load、总16个模型决策，cost smoke后冻结。
初始上下文不塞全量程序，只给能力入口和必要公共目录说明。
primitive路径仍允许，正确primitive不能被判业务失败。

### 4.2 执行约束

相关性、注册VERIFIED、当前适用性、已加载，是不同状态。
load不证明APPLICABLE；Gate保持无I/O三态，UNKNOWN需公开读取，不默认允许。
复用Skill execute、ExecutionContract、幂等、授权和environment Guard。
明确区分不可变授权/安全约束与可变化的业务适用规则；learner没有改权限的能力。

### 4.3 验收与失败分类

分别报：
search触发率、相关Skill Recall@k、load有效率、Gate三态、准确版本与参数绑定、Skill使用机会/次数、完整EOC、成本。
错误区分没有搜索、检索miss、描述误解、未加载、版本错误、不适用、调用错误、程序错误、模型执行错误。
既有Skill已提供但不选：
- 先核对协议是否要求/允许另一条正确primitive路径。
- 有效primitive完成，仅可评估是否放弃了已证明的效率收益。
- 不以固定候选探针低分推断业务理解低分。

300–1000条合成目录用于容量与干扰测试，明确非真实验证能力数量。

## 5. P2：从经验发现“值得沉淀的流程”

输入：learn/train中的成功、失败、高成本真实轨迹及公开规则。
必须保存原轨迹，不把所有Runtime工具审计拼成“模型自主经验”。

### 5.1 归一化

1. 依据调用参数、结果和后续用途建立实体/值绑定。
2. order_id等实例值转换为$input变量，不保留具体O123。
3. 区分公开输入、前序返回值、固定枚举、派生predicate。
4. 按因果顺序保留读取→动作→读回/断言。
5. 仅消除可证明冗余的步骤，不能删写后验证、权限读取或必要故障恢复。
6. 模型动作和Runtime修复分别标记；允许编译完整有效流程，但报告额外保护的来源。

### 5.2 模式发现与机会判定

首版用确定性序列/子序列聚类、输入绑定模式和公开目标分组；模型辅助总结用途、提出抽象，非必需由LLM完成所有步骤。
统计：
独立source_group支持数、流程差异、合法执行频率、重复决策成本、失败/边界反例、与现有Skill覆盖关系。

OpportunityRecord：
pattern_id、来源组、归一化流程、公开目标、覆盖缺口、预期复用场景、暂定参数、可能边界、成本机会、证据引用。
不能只因出现3次就认定通用。默认≥3独立来源组是开发起点，不是泛化证明。
成功refuse/escalate不是“成功执行退款程序”，按现有语义保留。
失败轨迹用于限制适用范围/纠正流程，工具超时不是业务边界反例。

与现有能力重复时：
相同程序/输入/行为支持域→去重；
更好描述→metadata_revision；
边界变化→待第三条线，第一阶段规则固定；
流程改进→program_revision；
存在新的可验证复用目标→new_skill。

首版第一阶段固定环境业务规则，避免混入规则漂移。

## 6. P3：从轨迹生成候选程序，禁止固定family套模板冒充学习

现有compile_skill按family写固定程序，只保留为StaticCompiler基线。
新增TraceCompiler：
- 从归一化事件与数据依赖推导call节点和输入绑定。
- 从公开目标/后置契约推导必要postconditions。
- 根据真实读回事件构造assert与finish。
- 根据公开规则和允许证据生成适用条件；缺少必要事实保持UNKNOWN。
- 输出候选而非直接VERIFIED，保留每个节点的来源引用。

可选ProposalModel：
- 根据Opportunity与裁剪后的learn/train证据，提出删除冗余、重排序、组合已有流程等候选。
- 只能使用现有schema/工具白名单。
- 执行模型与提案模型可以不同，均记录身份和成本。
- 模型提出的条件和程序必须实际验证，LLM评语不作为最终准入。

第一版必须支持“输入轨迹改变会导致候选程序改变”的测试：
不同有效工具顺序/数据依赖产生相应程序，而不是只由family返回同一个数组。
不根据测试案例ID、金额、订单号预设输出。
为方便工程约束可以固定规则语言和工具类型，但不能固定每轮正确修复程序。

### 6.1 DSL边界与组合能力

现有DSL无branch。首版仅沉淀可以表达的直线子流程，声明支持域。
不能把需要条件fallback的任务压成错误的直线程序。
组合只支持已声明、静态展开后≤12节点、输入/输出依赖合法的流程；记录parent Skill revisions。
没有可表达/可验证的新组合时返回unsupported。

任务公开目标和隐藏EOC必须支持验证所沉淀流程。
如需新增工作流，先定义版本化公共workflow schema、环境可执行工具语义、独立EOC，再做采集；不能直接按生成的Skill定义“正确答案”。
新增任务结构在freeze前声明，源实例和组合结构有独立heldout。
人提供环境任务族不等于人提供每轮Skill程序，必须分开记录。

### 6.2 候选内容

skill_id/revision、用途、参数及类型、公开支持域、适用/禁止条件、程序、postconditions、节点来源、父版本、支持/反例来源、预期效益。
输出不得包含validation统计或未来观察。
未能证明参数化、条件或结果正确时拒绝，不强行导出可执行程序。

## 7. P4：独立验证、注册和管理

静态：
schema、节点上限、工具白名单、输入/状态绑定、顺序依赖、终止、版本冲突、权限/依赖。
动态：
Positive、Boundary、Negative、Fault案例；真实环境独立fork；检查EOC、actual/attempted violation、验证义务、幂等、未知提交。
表面工具无报错不等于任务成功。

候选生成仅用learn。允许最多2次基于learn证据的程序修订；validation只给准入器，不回流proposer做逐例优化。
开发集可用于调方法，正式validation/test不能混用。
Candidate验证与真实Agent调用验证分开：
- Skill自己执行有效，记skill_admitted。
- Agent在新目录下能调用并满足任务，记agent_admitted。
- 实际隔离发布另记isolated_activated。

目录管理：
不可变版本、同内容去重、明确依赖、索引快照、废弃记录、运行版本固定、rollback。
不要仅靠调用频率淘汰Skill；低频可能是关键边界任务。
暂不自动物理删除历史版本。

## 8. P5：验证复用与连续积累

至少三个learn→candidate→validation→isolated activation轮次，所有轮固定模型和业务规则。
没有新候选或被拒的轮次正常保留，不挑“成功轮”展示。
候选从执行经验产生，不能按heldout成绩追加。

对照：
| 组 | 模型/Runtime | 外部能力 |
|---|---|---|
| A PrimitiveOnly | 固定 | 无Skill，保留原始工具 |
| B StaticLibrary | 固定 | 预先冻结的Skill库，不更新 |
| C ExperienceEvolution | 固定 | 根据learn经验生成/修订并验证 |
| D 可选Memory | 固定 | 仅轨迹Memory，无可执行Skill |

核心A/B/C，D是可选消融。主要C-B检验经验更新增量。
每组相同业务任务、工具权限和预算上限；真实成本分别记录。
若EOC相同，验证Skill是否减少模型决策/tokens；内部工具/Gate/生成验证成本必须计入，不能只算外层调用。

报告两层：
- 能力层：候选数量/去重/支持域、独立验证通过率、程序有效性、覆盖变化。
- 系统层：search/load/选择、EOC、自主与Runtime辅助、违规、成本。
调用率不是主收益指标。不得要求“用Skill”才能业务通过。

迁移评测：
新实体/输入值、新表述、声明的边界、预先划分的流程/组合结构；
同family新订单只叫实例泛化；
新程序只换ID不算能力扩展；
不能证明新组合时如实限于流程复用。

第一部分DoD：
1. 真实模型可主动search/load/use。
2. 候选程序确由轨迹依赖推导，旧固定compiler只作为基线。
3. 新/修订Skill有来源、静态与动态独立验证。
4. 新任务上能正确复用，错误复用/成本可审计。
5. 有三个完整轮次父链、无更新/拒绝路径、恢复和回滚。
6. 工程通过与C-B研究收益分别记录；无增量时不能写“能力已持续提升”。

第一部分验收后冻结其实现和目录快照，开始第二部分；不用等后训练。

# 第二部分：主动边界进化与真实执行收益

## 9. 第二部分要回答的问题

“已有Skill遇到新环境规则时，系统能否从交互发现失效，自主选择试验，更新适用边界，并在保持旧能力的前提下改善真实执行？”

本阶段主实验固定：
- 第一部分准入的Skill程序和发现机制。
- 执行模型/提案模型权重、Runtime、提示和动作协议。
- 不同时修程序、换模型和改Boundary，避免无法归因。
- 模型选择/程序错误可被诊断，但不送边界learner。

Scope：有限predicate/patch假设域。新增开放式假设生成不是首版必做；现域不足正确输出OTHER/DOMAIN_INSUFFICIENT。

## 10. P6：从日常交互自主触发适应

触发不能只因为脚本告诉controller“这是新world/epoch”。policy_epoch可作已检测的来源记录，world身份/新gold规则不进入learner。
正式任务流包含changed和no-change阶段，controller只见允许的公开交互。

复用EvidenceView与gap_detection主通道：
- 父Boundary预测与公开tool/probe可执行性反馈冲突。
- 多独立来源的同模式冲突。
- 原已知条件下出现无法解释的UNKNOWN。

必须区分：
暂时性错误/超时、权限拒绝、参数错误、程序执行错误、漏验证、终止错误、业务适用性拒绝。
HIGH风险拒绝等不可变授权/安全约束，不允许Boundary relaxation绕过。
成功refuse变escalate是终态选择问题，不直接标成Boundary变化。

在Gate阻止后未尝试时，不知道真实可执行性，不能凭空标false block。
需使用现有明确授权的只读probe能力/探索沙箱或允许的公开证据；不能用生产mutation试探资格。
learn/explore label必须绑定真实查询回执与来源，禁止由隐藏gold直接填label。

开发默认触发：≥3独立来源组中一致的公开业务冲突；另设明确非暂时性的高风险冲突可立即暂停相关Skill。
冻结触发阈值、观测窗口、探针预算；用no-change与故障阶段评估误报和无谓探针成本。
暂停仅影响隔离运行的相应能力，保留公开允许的fallback，不暂停整个系统掩盖问题。

输出：
NO_CHANGE、SUSPECTED_DRIFT、EXPLORING、INFRASTRUCTURE、MODEL_OR_PROGRAM_ERROR、INCONCLUSIVE。
阈值不是“规则变了”的证明，需要后续探索。

## 11. P7：先诊断v1.1，再决定如何改主动选样

已有正式B：active_v2与active配对结果相同，H0 Challenge未触发。
这不自动证明Challenge代码有bug，也不证明它有效。新增只读审计覆盖全部正式配对运行，不挑案例。

逐step检查：
1. H0有没有达到普通convergence入口？
2. 收敛的时点是否还存在可区分且有意义的替代假设？
3. 可公开获取的candidate pool是否覆盖区分区域？
4. challenge集合大小、去重、posterior阈值、已探测计数是否正确？
5. 原Active是否已经执行了全部必要challenge？
6. remaining budget够不够？UNKNOWN是否阻止认证？
7. 增强打分实际改变过排序或所选query吗？
8. 失败来自H0错误收敛，还是未收敛fallback后仍使用错误父Boundary？

输出counterfactual selection report：
触发入口、集合/覆盖、选择差异、未触发原因、证据不足、预算和有效fallback错误。
最后一种失败不能靠新增H0 Challenge自动解决。

### 11.1 开发候选与独立消融

从审计证据选择有限改进：
- 候选可识别性检查：无discriminating probe就声明不可识别。
- 独立H0挑战义务：防止高H0 posterior过早结束；已有实现先验证，不重复建立。
- 根据公开因子覆盖缺口增强选样；不硬编码W5真实规则。
- 查询可靠性/UNKNOWN处理，未知不当作否定。
- 按剩余预算分配challenge/信息获取；预算不足inconclusive。
- 带安全代价的保守fallback：未知支持域升级/限制，而非默默继续错误H0；明确false block和成本代价。

先比较原EIG、原v1.1增强、每项单独候选，按预声明dev规则只选一个新方法进入formal。
不保证增强一定有收益，不为“让Challenge触发”人为改正式标签。
新方法改善效率/安全必须分别验证；把错误收敛改成inconclusive不是学习效率提升。

## 12. P8：假设域充分性与停止

保留H0、restrict、relax、OTHER；predicate schema/version和公开支持域提前声明。
posterior依据有限观测模型，不等于校准的全局置信度。
检查证据拟合、等价类、OTHER mass、unknown比例、候选支持域和未覆盖因子。
出现多次无假设能解释的可靠证据，输出DOMAIN_INSUFFICIENT，不把最佳有限假设强行发布。

OTHER不是可执行补丁，不进入Skill Gate。
首版不自动扩大规则语言。可输出域扩展提案供独立后续协议处理，不能在formal过程中加入新hypothesis并沿用旧分母。
未来若生成新hypothesis，必须声明公共来源、归纳偏置、候选预算和新冻结协议。

停止状态：
SUPPORTED_CANDIDATE、SUPPORTED_H0、NO_DISCRIMINATING_PROBE、DOMAIN_INSUFFICIENT、BUDGET_EXHAUSTED、UNKNOWN_OBSERVATIONS、INCONCLUSIVE。
没有可反证案例不等于旧规则已被证明正确。

## 13. P9：边界版本、适用性与终态选择分开

BoundaryProposal包含：
父Skill/程序/Boundary身份、公开patch、support domain、探索证据、预测变化区域、rule schema、预算和内容hash。
绑定第一部分SkillRevision后进入验证。

边界learner预测的是executable/not_executable/unknown，不能自动学习refuse vs escalate。
现有terminal policy保持独立版本；新版policy_view明确：
- 新有效边界替代父业务边界的对应条件，父规则是prior，不是第二次否决。
- 权限/授权/不可变Guard仍必须通过。
- INAPPLICABLE本身不提供拒绝/转人工标签。

出现stable refuse→escalate退步：
先做配对归因，检查公开context差异、terminal policy、模型输出和非确定性。
修公共规则表达/上下文应在dev中进行，随后冻结新的prompt版本，所有正式对照统一使用。
不能根据gold在Runtime中覆盖模型终态来宣称自主能力提高。
若选择问题仍存在，独立记MODEL_SELECTION_LIMITATION；暂不触发SFT，也不混入规则证据。

规则变化必须由环境真实支持。Environment当前业务Guard、公开Boundary、执行器的旧条件检查要核对：
不可变安全Guard一直保留；
可变化业务规则由各实验环境版本执行；
候选不能修改环境gold policy；
旧硬编码business veto不能意外否决合法relax；
这项兼容性修复在dev先测并固定，不能只给新方法放宽环境。

## 14. P10：独立准入、连续保持与回退

三层证据分开：
BELIEF_SUPPORTED、BOUNDARY_ADMITTED、AGENT_ADMITTED；另有ISOLATED_ACTIVATED。
不能仅看Boundary预测正确就说Agent适应成功。
相同候选在固定Runtime/模型下独立验证，按验证结果决定隔离active版本。
被拒候选仍存档，不成为下一轮parent。

候选与effective结果分别记录：
候选诊断显示它的潜在结果；
effective按准入/保守fallback后的实际系统结果计算。
无更新或H0保留不是非平凡更新成功。

默认开发准入门槛，formal前冻结：
- Boundary validation actual violation=0、false allow=0、false block不劣。
- Agent validation实际违规=0、违规尝试不增加、stable无新增退步、完整EOC不劣。
- 至少一个预声明目标改善，才能发布非平凡更新。
- 证据不足/模型噪声难区分→inconclusive。

零stable退步是有限样本上的准入规则，不是总体零遗忘保证。
dev估计模型非确定性，再冻结2–3次重复/聚合；不挑最佳一次。
正式test不用于激活、再次修订或选择seed。
连续不少于3个规则阶段：只沿真实准入父链继续，并包含不变阶段或回归先前规则的开发/正式声明序列。

## 15. P11：第二部分实验

独立CPU Boundary和真实Agent两套结果，不能混称。

Boundary对照：
no_adapt、passive、random、现有active、开发冻结的新方法；同探索池/预算/seed。
Agent核心对照：
| 方法 | 发现/程序/模型/Runtime | 边界更新 |
|---|---|---|
| NoAdapt | 固定第一部分交付 | 不更新 |
| ExistingActive | 同上 | 原Active与既有准入 |
| ImprovedActive | 同上 | 本轮改进与相同准入 |

模型只读相应公共目录/Boundary，主动查找机制相同。
OracleBoundary可作为隔离诊断上界，明确oracle，不能计作自主进化成果；预算不够时省略。

指标：
- 日常变化触发precision/recall、false alarm、延迟和无变化查询成本。
- budget内收敛、RMQ、H0错误认证、domain不足、UNKNOWN、未收敛。
- heldout false allow/false block和effective fallback风险。
- Boundary/Agent准入及非平凡激活数量，固定总分母和条件分母均列。
- 完整EOC、stable保留、终态混淆、自主/Runtime辅助、模型动作限制。
- 探针、模型、工具、tokens、CPU/GPU推理/墙钟成本。
- 三轮父链、拒绝、旧规则恢复、回滚。

CPU检测/主动学习提高不代表真实Agent提高。Runtime固定，因此不再重复v1.1旧/新Runtime四臂，也不做模型×Skill四臂。

统计单位：
独立world-seed/sequence；task和连续epoch嵌套，不能把数千任务当独立样本。
paired methods使用同任务/初始状态；按簇报效应和区间。
沿用世界族的新seed叫该族实例泛化；新世界需另行冻结且单列。
小样本结论标工程/探索规模，不承诺统计显著。

正式规模由cost smoke决定：
工程smoke可2world×2seed；
研究候选3已声明world×3独立sequence seeds×3epochs，冻结前按预算调整。
所有对照、验证、盲测、故障、可允许的基础设施重试计入成本清单。
冻结后不按成绩缩减/补seed或更换模型。

第二部分DoD：
1. 系统从公开日常交互自主触发，而非依赖新world提示。
2. 原v1.1全量归因和新dev消融完成。
3. 假设域不足、不可识别和预算失败正确处理。
4. 新Boundary与具体Skill准确绑定，不绕过Guard。
5. Boundary与Agent验收分开，终态错误不伪装边界学习。
6. 三阶段真实父链、安全与stable保持、fallback完整。
7. 允许研究结论“无额外提升”或“尚未达到持续保持标准”。

## 16. 模型选择限制：保留诊断，暂不训练

开发阶段设置最小能力检查：
search→load→正确绑定→调用；读取缺事实；refuse/escalate区分；Skill验证成功后的停止。
对同一公共接口比较当前main-v3与一个可用更强模型，保留成本和输出。强模型不可用时记录blocked，不假定可用。

允许在dev修描述、接口、上下文、prompt；选择模型后formal冻结。
修Runtime确定性行为要公开统计，它不是模型参数学会。

后训练只保留未来接口：
导出精确上下文、动作、来源与已验证错误，但不构造新SFT/DPO训练、不引入训练触发threshold、不自动更新adapter。
只有未来明确证实能力正确、接口充分而模型仍长期出现高收益同类错误，再立项独立训练对照。
当前项目即使永不训练，也可完成两阶段系统自进化目标。

## 17. 持久化控制器与阶段顺序

第一部分：
EXECUTE → RECORD → FIND_OPPORTUNITY → PROPOSE_PROGRAM → STATIC_VALIDATE
→ SANDBOX_VALIDATE → AGENT_VALIDATE → ACTIVATE或RETAIN_PARENT → 新任务复用。

第二部分：
EXECUTE → PUBLIC_GAP_CHECK → TRIGGER或NO_CHANGE → ACTIVE_PROBE
→ BELIEF_UPDATE → PROPOSE_BOUNDARY → BOUNDARY_VALIDATE → AGENT_VALIDATE
→ ACTIVATE或FALLBACK → 后续规则阶段。

每个状态支持恢复与取消，记录输入/输出身份和预算；resume identity不符拒绝。
已提交写入不因取消而回滚；隔离重试保留原任务证据。
使用现有Windows兼容锁与单进程/单GPU租约。

### 实施顺序与阶段出口

| 顺序 | 实施工作 | 交付与出口 |
|---|---|---|
| P0 | 核对AGENTS/源码/协议、共同版本/来源框架 | 复用映射、基线回归、无历史证据改写 |
| P1 | 主动search/load/use及最小模型能力检查 | 真实调用证据、失败分类、版本正确 |
| P2 | 经验归一化、模式/机会发现 | 有来源的机会，无重复能力冒充新增 |
| P3 | TraceCompiler/可选ProposalModel | 候选程序确随输入轨迹变化 |
| P4 | 静态/沙箱/Agent验证、注册管理 | 正/边界/负/故障与fallback通过 |
| P5 | 第一部分独立复用和三轮评测 | 第一部分结果与限制，冻结交付 |
| P6 | 公开变化触发及通道隔离 | 真变化/不变/故障的触发检查 |
| P7 | v1.1全量归因与主动选样开发消融 | 明确未触发原因，选择一个候选方法 |
| P8 | 假设域/OTHER/停止改进 | 不可识别和域不足不过度认证 |
| P9 | Skill绑定、有效policy与终态分离 | 公开context和Guard兼容性检查 |
| P10 | 分层准入、retention、恢复与回退 | 三轮父链机制完整 |
| P11 | 第二部分独立CPU/真实Agent正式评测 | 效率、安全、EOC、retention分别结论 |
| P12 | 现有工作台只读展示和最终报告 | 每项结论可跳到真实证据 |

不要求第一部分必须取得显著收益才开发第二部分，但进入第二部分的Skill必须通过工程/执行准入，发现机制足够稳定。
若第一部分真实使用仍明显失败，先定位或选可用模型；不能直接用第三条线掩盖调用问题。

## 18. 文件、入口与测试建议

新增示例：
    skillforge/evolution_common/{manifest,experience,snapshot,split_ledger,budget}.py
    skillforge/skill_evolution/{catalog,discovery,normalization,opportunities,trace_compiler,proposals,validation,controller,reporting}.py
    skillforge/boundary_evolution/{trigger,attribution,learner_adapter,admission,controller,reporting}.py
    configs/skill-evolution-v1.2.dev.json
    configs/boundary-evolution-v1.3.dev.json
    scripts/run_skill_evolution.py
    scripts/run_boundary_evolution.py
    scripts/audit_evolution_run.py
    docs/SKILL_EVOLUTION_PLAN.md
    docs/SKILL_EVOLUTION_PROGRESS.md
    docs/SKILL_EVOLUTION_RESULTS.md
    docs/BOUNDARY_EVOLUTION_NEXT_PLAN.md
    docs/BOUNDARY_EVOLUTION_NEXT_RESULTS.md

命名v1.2/1.3是本计划建议，实际版本以仓库核对为准；不能改历史v1.1 identity。
新结果写新目录，历史formal只读。

待实现CLI：
    python scripts/run_skill_evolution.py preflight --config <dev-config>
    python scripts/run_skill_evolution.py smoke --config <dev-config> --output <fresh-dev-dir>
    python scripts/run_skill_evolution.py freeze --config <dev-config> --output <fresh-protocol-dir>
    python scripts/run_skill_evolution.py run --protocol <frozen-protocol> --output <fresh-run-dir>
    python scripts/run_skill_evolution.py resume --run <existing-run-dir>
    python scripts/run_boundary_evolution.py <同类子命令与参数>
    python scripts/audit_evolution_run.py --run <run-dir>

P0后Code Agent自行核对实际CLI风格，保持旧入口兼容。Windows PowerShell和Linux CPU测试都应可用。

必要测试：
- public视图无oracle、未来数据、验收统计。
- search/loading/Gate三态/版本binding/依赖/废弃与内容篡改。
- TraceCompiler不由family直接选固定程序；实例参数泛化和依赖正确。
- 验证成功refusal不算mutation成功；超时不当边界反例。
- 多个正确primitive/Skill路径不制造错误标签。
- 12节点与直线支持限制；不可表达分支明确unsupported。
- rollback和目录快照不可变、跨轮来源隔离。
- snapshot故障消耗、幂等、pending验证和提交未知恢复。
- 变化触发不看world/gold；故障/不变阶段误报统计。
- Gate false block缺公开证据时不伪造标签。
- H0 Challenge各状态、候选覆盖不足、预算/UNKNOWN/OTHER。
- 不适用二值与refuse/escalate终态隔离。
- 原Guard保留、有效Boundary替换旧business条件。
- 候选与effective分开；拒绝不进入下一轮parent。
- 自主与Runtime辅助分别计费、两阶段无新训练调用。
测试聚焦真实约束与失败路径，避免镜像实现的无效测试堆积。

## 19. 工程展示与研究验收

复用工作台，只增只读页面：
- 第一部分：轨迹→模式→Skill候选→验证→版本→新任务复用。
- 第二部分：冲突→探针→belief→Boundary候选→两层准入→父链。
- 任何图表可查看原始证据。
- 显示拒绝、OTHER、无更新、成本、stable退步、模型限制。
- 区分CPU/scripted/真实模型；engineering_passed、research_claim_passed、isolated_activated独立字段。

首轮fixture只用于工程测试，可刻意制造程序错误/规则冲突，明确scripted。
真实模型实验不能注入人为错误并声称模型自主失败。
验收器、任务生成器和进化器职责分离，不能由新Skill自己定义正确性。

总体验收：
第一部分至少能证明经验程序生成与可靠复用机制成立；
第三条线至少能证明自主触发、主动获取、候选/有效系统分离和连续保持机制可运行。
“收益成立”需独立真实结果，不预先要求所有研究假设通过。
没有足够真实数据、无有用候选或新方法无提升都允许完整交付，写清证据与限制。

## 20. 直接交给Code Agent的启动指令

> 按本文件实施SkillForge的两阶段自进化。先读AGENTS并核对当前仓库与基线，复用现有Gate/DSL/ExecutionContract/验证回执/Active Learner/Registry/数据隔离，不重写历史正式证据。
>
> 先完成第一部分：主动search/load/use、经验模式发现、从轨迹推导程序、独立验证、版本注册、真实新任务复用及三轮评测。现有按三个family输出固定流程的compiler只能作基线，不能冒充新程序学习。动态分支不在现有DSL能力内时明确unsupported。
>
> 第一部分工程验收并冻结后，完成第三条线：从公开执行证据自主触发、全量诊断v1.1的Challenge未触发与stable退步、开发消融、假设域不足处理、Skill-Boundary绑定、独立Agent准入和连续保持。不要重复宣称“增加H0 Challenge”；它已经存在。不要把refuse/escalate错误当成二值边界学习。
>
> 本轮不新增SFT/DPO/RL、不实现持续训练流水线。开发可选择更合适的固定模型，正式实验固定。模型选择失败记录为独立限制，先检查描述、接口、上下文和模型，不能用Runtime覆盖gold来伪造自主改进。
>
> 每阶段更新实现状态、运行命令、验收证据、剩余问题。成本smoke后冻结数据、方法、预算与准入规则；候选被拒、无更新、域不足和无研究增量都保留。缺模型/GPU或证据时标blocked/inconclusive，不用mock替代真实结果。最后交付源码、配置、必要测试、两部分独立结果、三轮父链、复现命令和现有工作台只读展示。

