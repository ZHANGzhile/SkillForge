# SkillForge：两阶段自进化实施方案
## 第一阶段：经验驱动的技能沉淀与复用
## 第二阶段：执行驱动的主动边界进化

日期：2026-10-12。
用途：交给 Code Agent 的可执行实施规格（根据 2026-10-12 研究讨论修订；保留 P0–P12 结构）。
状态：**设计文件，尚未执行本版新增工作**。此次修订不等于仓库代码已更新。
已核对基线：ecceeb317bbe967b30b36c58df5031c6e7bfbdce。
仓库：https://github.com/ZHANGzhile/SkillForge

本版取代上一版“条件持续SFT”作为当前工作计划。**第一条线：技能发现/选择/沉淀/治理 → 第三条线：主动边界探索与适应**；第二条线后训练不进入必做项。历史SFT/DPO结果和服务保留，不新增训练流水线。

**本轮新增的研究映射（只借鉴对应机制，不宣称完整复现论文）：**
- MUSE-Autoskill：Skill 生命周期、目录、每技能执行经验 → P1/P2/P4。
- SkillRL：分层技能检索、经验抽象 → P1/P2；**不实施其强化学习共同训练**。
- SkillAdam：修订历史、方向稳定与编辑幅度控制 → P3/P4；首版可选择简化实现。
- SAGE：相同任务配对、回退惩罚、统计接受/弃权 → P4/P10；不替代硬安全门槛。
- RSIAgent：Broad-to-Deep 环境探索 → P6/P7；不引入无约束多 Agent 探索。
- Agent0：在当前能力边界附近产生可验证探索任务 → P7；**不实施模型 RL 与联合训练**。
- Do Self-Evolving Skills Generalize to Held-Out Tasks?：未见任务泛化、训练特例固化风险 → P5/P11。
文中的新模块、接口、阈值、命令和结果要求均为待实施设计，不表示已实现或已验证。

## 0. 目标、范围与不能混淆的结论

固定模型参数，让系统：
1. 从任务执行经验中发现值得抽象的流程，产生候选Skill，验证、注册，再在不同任务中检索复用。
2. 从后续交互中发现已有Skill的边界可能失效，主动选择试验，修订边界，独立验收，再继续使用。

这两个目标要回答四个可否证的研究问题：
- **R1 检索/选择**：明明存在且适用的 Skill，Agent 为什么没有召回、加载或选择？每一级损失能否准确归因？
- **R2 能力积累**：新增/修订 Skill 是否来自跨轨迹抽象，能否在去除原始历史后迁移到未见结构任务？
- **R3 主动适应**：政策不再适用时，Agent 是否由公开交互自行触发，选出区分度高的安全探针，而不依赖显式 world-change 信号？
- **R4 稳定与验收**：收益是否超过静态 Skill 与 Memory 基线，是否伴随负迁移、旧能力遗忘、更多工具成本或违反安全条件？

**结果表述规则：**成功完成基础设施、产生候选、边界收敛、Agent 实际提升、测试泛化、稳定部署是不同事实；每项单列 `engineering_passed` / `program_admitted` / `agent_admitted` / `research_claim_passed` / `isolated_activated` / `deployed`，不可串用。

人预先定义环境、工具、受限DSL、允许的规则语言、验证器和预算；每轮具体抽象哪个流程、提出什么程序、查询哪个案例、是否更新，由系统根据经验决定。
自进化允许“无有用候选”“证据不足”“候选拒绝”和“保留旧版”，不强制每轮修改。

研究范围：
- 现有订单领域、已有业务工具及安全Guard。
- 首版程序仍限12节点以内的call/assert/finish，不引入任意代码执行。
- 第一阶段先支持可表达的直线流程；动态分支与任意程序组合不是首版必做。优先利用已有 `create_ticket`、物流查询等工具与现有任务族构造**独立验收**的新增流程机会，不能只重复三个已有程序。
- 第三条线保留有限规则假设域，并显式处理域不足；不要求无限开放的规则发现。
- 开发阶段可以比较模型；正式实验固定执行模型、提案模型、提示、协议和解码。
- 不依靠每轮修改模型权重取得效果。

结论要区分：
- 新目录/描述不等于新程序。
- 新Skill ID不等于新增能力；与已有流程语义重复要去重或标修订。
- 不改变工具权限，但改善覆盖、可复用流程和执行成本，可以是系统层面的进化。
- 固定三个程序但换订单号，只能支持调用与实例泛化，不能证明自主能力生成；新的目录、metadata、prompt 或边界修订也不能单独声称产生了新程序。
- 限定领域内的自进化可以成立，但不宣称跨任意业务/开放世界泛化。

## 1. 核对现状，明确真正需要补的地方

| 仓库已有模块 | 已核对行为 | 本次处理 |
|---|---|---|
| skillforge/runtime.py | 根据公开task.family筛选并截取少量Skill，hydrate后将可执行候选提供给模型；即使有正确Skill也可能在pre-top-k阶段丢失 | 新增目录检索→加载→Gate→选择的可观测漏斗；旧入口作严格基线 |
| skillforge/retrieval.py | `retrieve_memory` 是简单的词法Memory检索，不是Skill检索器 | 不覆盖原Memory语义；新增独立Skill目录/索引/排名审计 |
| skillforge/skills.py | Gate/execute/SkillRegistry已存在；compile_skill按三个family固定mutation、读取和流程 | 复用执行与安全；新增从轨迹推导程序的编译路径，旧compiler作为基线 |
| skillforge/schemas.py | Action包含tool/skill/stop/escalate/refuse；Skill DSL无动态分支 | 新增版本化公共目录/引用协议；不假定DSL支持分支 |
| skillforge/provenance.py、dataset.py | 来源、分区、数据身份审计 | 复用并增加跨轮来源ledger |
| execution_aware/contracts.py | 验证回执、pending义务、提交未知、恢复协议 | 复用，保持作用和来源可见 |
| execution_aware/runtime.py | v1.1执行契约和自动读回/终止 | 作为固定执行后端，通过adapter增加新目录能力 |
| gap_detection.py | boundary主通道使用公开EvidenceView；secondary通道消费终态诊断 | 保留通道隔离，增强线上触发和误报诊断 |
| belief.py、active_learning.py | 有限假设、OTHER、贝叶斯更新、EIG | 复用；不把posterior当已校准置信度 |
| execution_aware/controller.py、challenge.py | 已有H0 Challenge/主动获取增强，正式Active v2并未触发该挑战 | 先完整归因；在已有EIG框架外补充公开环境的Broad-to-Deep探针产生及覆盖诊断 |
| evolution_registry.py、evolution_journal.py | 不可变边界版本、恢复与日志 | 复用，绑定到第一阶段Skill版本 |
| v1.1交付与实验 | 固定main-v3；A连续评测出现stable退步，B未证明增强Active优于原Active | 保留失败结论，从这些缺口出发做新实验 |

**当前不可抹掉的正式基线（来自现有报告，非本计划重新实测）：**
- 同权重 No-Skill B0 **69/78**，Skill/Gate B3 **68/78**；模型调用减少 **48.75%**、tokens 减少 **44.43%**，工具调用增加 **19.11%**，不能声称成功率已提高。
- Active v2 与原 Active 在 150 个 CPU 配对运行中结果相同，均 **23/30** 收敛，仍有 **7** 个 false allows，H0 Challenge **0** 次触发；不能称主动获取已有改进。
- Execution-Aware v1.1 的隔离 A 研究中，新 Runtime **3/9** 组激活，但连续评测出现 **1** 个 stable 退步，故不构成完整连续保持验收；实际部署 **0**。

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
system_id、parent_system_id、执行模型/adapter哈希、提案模型身份、tokenizer、prompt、action_protocol、Runtime/工具源码哈希、目录快照、Skill版本集合、Boundary版本集合、retrieval配置、解码、数据/protocol身份；并明确当前 lane（skill/program/boundary）、候选提交状态、evaluation protocol 与优化器版本。

SkillRevision：
skill_id、revision、parent_revision、inputs、程序、公开适用/禁止条件、postconditions、来源轨迹、支持域、验证回执、状态、内容哈希；增加 `revision_kind`（metadata/program/boundary-reference）、`semantic_fingerprint`、dependency版本、`supersedes` 与禁用/废弃原因。新名字不自动获得新能力ID。

**SkillCatalogEntry（公开目录最小字段）**：`skill_id`、exact revision、名称/能力描述、任务意图标签、参数摘要、所需观测/工具、公开边界摘要、依赖、VERIFIED/DEPRECATED状态、内容hash；不放训练成功率、heldout分数或私有归因标签。

**SkillUseTrace（审计内部结构）**：`available_verified`、`retrieved`、`loaded`、`gate_status`、`offered_to_model`、`selected_action`、`executed_skill`、`verification_result`；逐级附公开/私有来源和可重放快照ID。"相关"、"能运行"、"被选择"分别定义，不共用一个布尔值。

**SkillRevisionMemory（优化器私有日志）**：`revision_id`、触发gap、拟修改节点/条件、受影响支持域、learn/dev配对案例的wins/losses、退步类型、是否接受及理由、证据来源和父版本。仅用于后续 learn/dev 的候选选择；**不得将正式validation/test逐例反馈回灌提案模型**。

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

每步增加不可省略的 `selection_trace`：目录中可用Skill → 检索候选 → load结果 → Gate判定 → 模型可见选项 → 最终决策 → 实际执行 → EOC/成本；失败阶段使用固定枚举 `NO_SEARCH`、`RETRIEVAL_MISS`、`NOT_LOADED`、`GATE_INAPPLICABLE`、`GATE_UNKNOWN`、`OFFERED_NOT_SELECTED`、`BINDING_ERROR`、`SKILL_EXECUTION_ERROR`、`MODEL_TERMINAL_ERROR`、`SUCCESSFUL_PRIMITIVE_ALTERNATIVE`。必要时允许一条轨迹多个标签，注明优先根因。

强制保存 `model_visible_context_hash` 与独立审计器的 `available_skill_set_hash`。离线真值仅供评估分母，不得在工具搜索/模型消息中出现。
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

### 2.5 跨阶段契约与数据污染防线

- 第一阶段默认固定业务policy；第一阶段变更程序/描述，不能偷偷调整有效业务Boundary。第二阶段默认固定第一阶段的程序与Skill目录检索方法，只允许Boundaries变化，便于归因。
- `program_revision` 必须校验原Boundary兼容；`boundary_revision` 不得修改程序；`metadata_revision` 只改变公开描述/检索索引，仍需搜索与选择的独立验证。
- 正式validation用于一次冻结候选的准入决策；可在dev迭代，但不可循环读取同一正式validation的逐题错误做修复，再声称其独立。train/dev/validation/test的版本和接触历史写入跨轮ledger。
- 静态安全属性及授权边界始终优先于候选更新；真实线上副作用任务不得用探索式写入探针。候选的成功也不得反过来定义期望EOC。

# 第一部分：技能沉淀、主动发现与经验复用

## 3. 第一部分要回答的问题

“从执行经验自动沉淀出的Skill，能否被Agent主动找到、正确调用，并在新任务上带来业务或成本收益？”

拆为四个依次验收的子问题：
A. **召回与选择**：已有验证Skill是否被搜索、加载、判定适用，并被Agent正确考虑？失败具体发生在哪一级？
B. **技能生成**：新程序是否真正从轨迹推导，而不是固定模板填参数？
C. **生命周期维护**：不同版本能否去重、修订、追踪经验、拒绝、废弃和回滚？
D. **增量与泛化**：排除同题记忆后，是否优于StaticLibrary/PrimitiveOnly，并在未见组合结构上保持收益？

先A后B。A不可靠时先诊断，不立即改训练；可以在dev比较更强执行模型，选定后冻结。
B若没有产生比已有库更有价值的新能力，应报告no_useful_candidate，不能强行新增重复Skill。

## 4. P1：先打通主动search/load/use

### 4.1 接口

本阶段优先解决**Skill存在但未被选**的可观测性，不假设“未选择”一定错误。旧Runtime只凭 `task.family` 预筛选Skill是必须保留的对照，不再直接作为新搜索器的候选上限。

模型路径应为 `task/public observations → search_skills → load_skill → Gate/hydrate → choose(skill|primitive|terminal) → execute/verify`。`search_skills` 搜索**当前冻结目录的全部可用公共条目**；公开family仅作软特征或可消融过滤，不得先硬截断为前3个再搜索。防止加载未经请求的完整Skill。

编排层虚拟工具：
    search_skills(query: str, top_k: int = 5)
    load_skill(skill_id: str, revision: str)

Action仍可type="tool"；虚拟工具由orchestrator dispatch，不传业务Environment。
现有type="skill"用于执行。增加本次task的loaded_refs表：skill_id → exact revision/content_hash。
同一task加载同ID不同revision拒绝冲突，不能覆盖；所有调用记录准确版本。

search返回：
ID/revision、名称、任务用途、输入摘要、公开适用/禁止摘要、依赖、状态、内容哈希和公开所需观测/工具；搜索返回**相关候选**，不返回"已经可执行"的承诺。记录查询、排序分数分量、catalog snapshot、被截断的候选和耗时。
load返回：
完整输入契约、程序、当前有效Boundary、postconditions及支持范围。
验证统计、完整来源轨迹、私有标签留给审计器，不随load给模型。

首版本地词法索引，FTS5可用时采用，否则纯Python确定性fallback。先实现 **keyword/BM25或确定性词法 + 类型/工具/输入 metadata** 的独立评分与去重，不混入Gate的真值；embedding/hybrid召回只作为P1稳定后的可选独立消融，不能因为"向量检索更先进"就默认替换。

目录可分**General procedural guide**（跨任务操作原则，非可执行Skill）和 **Executable Skill**（有DSL/边界/验证）；对应SkillRL的分层经验思想，但首版不要求分层模型训练。通用guide不能冒充可直接执行的程序。
检索不能靠私有gold类别路由。公开task.family仅可作辅助，并单列不使用family的检索结果。

开发默认：top_k=5、最多3次search/3次load、总16个模型决策，cost smoke后冻结。
初始上下文不塞全量程序，只给能力入口和必要公共目录说明。
primitive路径仍允许，正确primitive不能被判业务失败。

**检索—选择漏斗及反事实评测（先基线，后优化）：**
1. 定义独立标签：在当前公开规则与固定task/snapshot下，审计器验证某Skill确实在声明支持域内、可成功完成相关子目标，才记 `opportunity=true`；不能只靠名称相似或"数据库里有这个Skill"做分母。
2. 分母分别计算：`eligible_opportunities` → `search_invoked` → `retrieved@k` → `loaded` → `gate_applicable` → `offered_to_model` → `selected` → `executed_and_verified`。同时报告合法Primitive完成数。
3. 在**同一可重放状态/同一模型可见前缀**下，对"提供Skill"与"不提供Skill"做隔离fork，区分Agent选择行为与真实结局；模型非确定性时重复并报告分布。自然执行时先搜索会改变后续context，不能直接把不同完整轨迹称为同上下文因果比较。
4. `OFFERED_NOT_SELECTED`只有在Skill与Primitive结果都合法时属于潜在效率机会，而不是业务错误；分别衡量成功率、模型调用、tokens、内部工具数和总成本。
5. 大目录压力测试使用同能力的metadata改写、近似但边界不符Skill、版本冲突Skill及300–1000合成干扰条目。合成干扰不算新增已验证业务能力。

### 4.2 执行约束

相关性、注册VERIFIED、当前适用性、已加载，是不同状态。
load不证明APPLICABLE；Gate保持无I/O三态，UNKNOWN需公开读取，不默认允许。
复用Skill execute、ExecutionContract、幂等、授权和environment Guard。
明确区分不可变授权/安全约束与可变化的业务适用规则；learner没有改权限的能力。

### 4.3 验收与失败分类

分别报：
按独立opportunity集计算的检索Recall@k、搜索触发率、加载有效率、Gate三态、可见选项覆盖、条件选择率、准确版本与参数绑定、执行/验证成功率、完整EOC、分层成本。`Recall@k` 的相关性标签来自冻结离线评估，不送给运行时检索器。
错误区分没有搜索、检索miss、描述误解、未加载、版本错误、不适用、调用错误、程序错误、模型执行错误。
既有Skill已提供但不选：
- 先核对协议是否要求/允许另一条正确primitive路径。
- 有效primitive完成，仅可评估是否放弃了已证明的效率收益。
- 不以固定候选探针低分推断业务理解低分。

300–1000条合成目录用于容量与干扰测试，明确非真实验证能力数量。

**P1出口**：必须拿到至少一组真实模型完整 `search → load → gate → select → execute → verify` 证据；同时跑有Skill却未被搜索、检索漏召回、load错误、Gate UNKNOWN及正确Primitive替代的对照。若仍大量在 `OFFERED_NOT_SELECTED` 丢失，先排查选项可理解性、公开描述、任务协议及模型能力，不立即开展P2训练或第三条线。

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

### 5.3 技能发现质量与真正的新能力

针对每个Opportunity明确四个判断：`novel_program_structure`、`independent_sources`、`valid_generalization_target`、`expected_incremental_utility`。先用变量重命名标准化、工具依赖图与状态/效果签名做去重；对可能等价但无法形式证明的程序，标记 `POTENTIAL_DUPLICATE` 并做受控支持域比较，不把有限样本相等冒充语义完全等价。

**优先新增的业务流程机会**：用仓库现有 `get_shipment/get_order/get_order_items/create_ticket` 等工具，从真实learn任务轨迹挖掘**物流调查、带证据的服务工单**等合法直线子流程；具体可表达性、tool schema 与EOC在P0审计后确定。不能预填某个固定的新Skill程序来满足研发指标。无法产生新流程时交付 `NO_USEFUL_OPPORTUNITY`，不为了计数扩充重复技能。

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

### 6.3 SkillAdam启发：有证据的局部修订，不重写整个Skill

在TraceCompiler已能产生**独立通过验证的初始候选**之后，才引入 `RevisionPlanner`：从learn/dev的 `SkillRevisionMemory` 获取反复出现的失败、上次改动效果及退步风险，提出**最小修改集合**，例如只增一条读后断言、修改参数绑定或调整一个调用顺序。保留受影响节点/条件及父版本diff。

首版不用照抄Adam数值公式：固定最多2个候选程序修订、限制改动节点数；只有在dev发现不同修订方向相互覆盖/回退时，才添加"历史效果波动 → 编辑预算"的可检验消融。安全必需修复不受文本编辑预算的激励左右，始终重新走独立验证。禁止通过validation/test反馈训练RevisionPlanner。

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

### 7.1 生命周期与准入策略（MUSE + SAGE思想）

**状态机：** `DISCOVERED → CANDIDATE → VERIFIED → ISOLATED_ACTIVE → DEPRECATED`，所有阶段都可显式 `REJECTED/INCONCLUSIVE`；`REJECTED`保留原因与父版本，但不参与后续正式父链。已有Registry状态以原始schema为准，新增生命周期状态放在治理层，不绕过现有`VERIFIED`检查。

版本变动分三种：
- `metadata_revision`：改善发现/理解，必须验证检索与选择，无新程序能力主张。
- `program_revision`：修改call/assert/finish/绑定，重新验证功能和原Boundary兼容性。
- `boundary_revision`：第二阶段才允许，不能悄悄修改程序或不可变Guard。

**SAGE式配对准入**：在同一冻结validation任务与独立数据库状态上运行旧版和候选，记录逐例wins/losses/ties、旧题退步、关键安全病例、成本差异；以预声明硬安全约束优先。统计证据足够时，可加入**以独立任务组为统计单位**的一侧配对检验/置信区间；样本不足就`INCONCLUSIVE`，绝不能用"平均分+1"直接发布或声称显著。统计门控不对真实不可逆安全写操作作放松。

为了避免optimizer反复适配同一小验证集：每次formal只评一个在learn/dev确定并冻结的候选；若validation拒绝，允许回到下一轮learn/dev，但旧validation已成为已接触数据，不再作为新的独立holdout。测试集仅在所有决策冻结后使用一次。

## 8. P5：验证复用与连续积累

至少三个完整 `learn → opportunity/no-opportunity → candidate/reject → validation/admission → isolated activation或retain parent` 轮次，所有轮固定模型和业务规则；**不要求每轮有候选，更不要求每轮激活**。
没有新候选或被拒的轮次正常保留，不挑“成功轮”展示。
候选从执行经验产生，不能按heldout成绩追加。

对照：
| 组 | 模型/Runtime | 外部能力 |
|---|---|---|
| A PrimitiveOnly | 固定 | 无Skill，保留原始工具 |
| B StaticLibrary | 固定 | 预先冻结的Skill库，不更新 |
| C ExperienceEvolution | 固定 | 根据learn经验生成/修订并验证 |
| D 可选Memory | 固定 | 仅轨迹Memory，无可执行Skill |

核心A/B/C，D是可选消融。**B与C必须使用相同search/load/Gate/Execution后端、相同目录检索策略与运行预算，唯一实验因素是目录是否允许根据learn经验新增/修订已验证的Skill。**主要C-B检验经验更新增量；A-B检验已有静态库的收益，不可把"更好的运行协议"计作新增技能贡献。D用于检验能否由原始Memory解释收益。
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

### 8.1 泛化实验：阻止“训练集技巧被固化为通用规则”

参照Skill泛化研究设计互不重叠的四类迁移：
- **Instance**：新订单、顾客与参数；只证明实例层迁移。
- **Paraphrase**：新任务表达与无意义字段扰动；证明描述鲁棒性。
- **Boundary/Negative**：符合/不符合、缺少事实、风险禁止条件；证明安全适用与拒绝。
- **Structural/Compositional**：冻结前预声明的未见调用结构、子流程组合或不同顺序依赖；仅当DSL与EOC真正支持时才计结构泛化。

对每个候选比较 `G_learn = Score(candidate, learn_eval) - Score(static, learn_eval)` 与 `G_heldout = Score(candidate, heldout) - Score(static, heldout)`；同时报告 `G_heldout - G_learn`、负增益比例和原成功案例回退。learn_eval只是描述/诊断，不用于夸大泛化，heldout为冻结后的最终评估。不得在分母太小/增益接近0时计算不稳定的相对保留比而不加说明。

必须增加 **No-History** 条件：在执行上下文移除完整历史轨迹，只允许加载独立Skill目录；与Memory-only及StaticLibrary比较。若优势在移除历史后消失，不宣称形成了持久的可复用技能。新任务结构一旦被正式test看到不能再转入learn修改Skill。

### 8.2 因果归因与检索消融

至少区分两种效应：`catalog/retrieval effect`（同一Skill库，只改可见搜索机制）和 `skill evolution effect`（同一搜索机制，允许Skill迭代）。在开发资源允许时做小规模独立消融：旧family预筛选、词法全库、metadata增强；不要同时更换模型与Skill库。

另报告 `skill_opportunity`条件下的选择与正确使用；这只是条件子集指标，不能替代**全任务**意向性总体EOC。版本选择、任何fallback、找不到技能以及失败成本都必须计入。

第一部分DoD：
1. 真实模型可主动search/load/use。
2. 候选程序确由轨迹依赖推导，旧固定compiler只作为基线；有内容/语义去重与至少一个真实新流程候选机会，若未通过则如实报告。
3. 新/修订Skill有来源、静态与动态独立验证。
4. 新任务上能正确复用，错误复用/成本可审计；分层漏斗含独立opportunity分母，报告No-History、未见结构与新旧成功例的回退。
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

**触发与探索解耦**：触发器只能报告`DRIFT_SUSPECTED`及冲突类型，不提前获知世界变化时间/真实规则；进入探索后保留完整的`probe_origin`、父预测、公开输入、工具实际反馈和沙箱ID。真实交互没有可归因工具反馈时，只能记`suspected/unknown`，不能强行更新Belief。
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

### 11.1 RSIAgent启发：Broad-to-Deep探针预算，而非简单堆EIG

在现有`active_learning.py`和`execution_aware/acquisition.py`上增加**两层可审计选择**，不重写Belief更新：
- **Broad**：按可公开访问的`risk/status/amount/tool family/缺失字段`分层，先用小预算扫描与当前支持域相邻的区域；此时优先覆盖未探测因子组合和旧边界预测冲突，不根据隐藏gold选择。
- **Deep**：一旦出现明确的可执行性矛盾，围绕两个以上竞争假设生成最小区分案例（阈值两侧、单因子对照、交集与反例），再使用当前EIG-cost-risk排序进行筛选。
- **Stop / Fallback**：没有区分探针、预算耗尽或OTHER主导时明确`INCONCLUSIVE`/`DOMAIN_INSUFFICIENT`；不能以强行保持H0解释为"成功适应"。

训练/开发实验分别记录Broad与Deep已用查询数、有效差异探针覆盖率、无信息查询率、H0错误认证率、false allow/false block与CPU成本。建议先做**现有Active vs Active+Broad覆盖 vs Active+Deep候选生成 vs 两者组合**的单因素开发消融，只有开发结果支持的最小修改进入正式协议。若固定候选池已足以区分假设，优先修正H0/回退逻辑，避免无用扩展。

Agent0只启发"在当前能力边界生成有用任务"，首版用冻结的程序化环境/独立验证器检查任务是否合法；不运行联合RL，不允许探索者控制Oracle。

### 11.2 开发候选与独立消融

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

**可选后续研究接口，不是P8当前发布条件**：`HypothesisExpansionProposal`记录来自公开交互的缺失字段、候选谓词、反证案例与表达性理由；只可进入新dev协议与新的独立holdout。`H_other`是模型失配信号，不能自动变成可执行Patch或概率为1的真规则。
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

**统计准入的可执行规则：**
1. 固定旧Boundary和新Boundary对应的`parent_skill_revision`、同一组验证任务/初态/解码，按world-seed或sequence分组计算配对差异；重复抽样时不把同task重复运行当独立世界。
2. 硬安全条件：实际违规不得新增、关键稳定约束不能放宽、不可变Guard一直独立执行；出现安全违规直接REJECT而不是被均值覆盖。
3. 非安全效益：逐项计`wins/losses/ties`、stable退步的种类/严重度、总EOC差、成本差。预先设定"改善至少一个目标且稳定任务不劣"为最低工程门槛；条件允许时采用SAGE式单侧配对证据，统计证据不足标`INCONCLUSIVE`，不事后变更阈值。
4. 类似v1.1的`correct refuse → incorrect escalate`必须走`MODEL_TERMINAL_LIMITATION`归因，不算二值Boundary学习失败，也不能靠真实gold直接覆盖模型终态。
5. 统计决策的**validation**与冻结最终效果的**test**严格分离；不允许用test修正更新门槛。
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

**探索方法的必做消融与独立验证**：先只读重算既有v1.1失败归因；在新dev world比较`OriginalActive`、`ExistingActiveV2`、`BroadOnly`、`DeepOnly`、`BroadThenDeep`，按预声明效用/安全准则仅选一个候选方法。不能在正式实验中用失败结果继续挑算法。对固定候选和有效fallback分别报告成绩；若新方法只把错误判定改为弃权而未改善最终EOC，结果必须如此陈述。

**泛化独立性**：规则变化世界至少含已见规则族的新参数/种子，以及预先冻结的结构外推世界（若有限假设域无法表达，应报告`DOMAIN_INSUFFICIENT`而非失败优化）。同时保留`no-change`和`fault-only`的顺序阶段，计算误触发与无谓探针成本。

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

第一部分（调用闭环与沉淀闭环分开可审计）：
`TASK → SEARCH → LOAD → GATE → CHOOSE → EXECUTE → VERIFY → RECORD`；
`RECORD → FIND_OPPORTUNITY → DEDUP → PROPOSE_PROGRAM → STATIC_VALIDATE → SANDBOX_VALIDATE → AGENT_VALIDATE → ADMISSION/REJECT/INCONCLUSIVE → ISOLATED_ACTIVATE或RETAIN_PARENT → 后续新任务复用`。每次修订写RevisionMemory并更新不可变Registry。

第二部分：
`EXECUTE → PUBLIC_GAP_CHECK → TRIGGER或NO_CHANGE → BROAD_PROBE → DEEP_DISCRIMINATING_PROBE → BELIEF_UPDATE → HYPOTHESIS_CHECK → PROPOSE_BOUNDARY或DOMAIN_INSUFFICIENT → BOUNDARY_VALIDATE → PAIRED_AGENT_VALIDATE → ISOLATED_ACTIVATE或FALLBACK → 后续规则阶段`。Broad/Deep均为有条件触发，可按dev审计选择只启用其中一项，不得为制造新颖性强制运行。

每个状态支持恢复与取消，记录输入/输出身份和预算；resume identity不符拒绝。
已提交写入不因取消而回滚；隔离重试保留原任务证据。
使用现有Windows兼容锁与单进程/单GPU租约。

### 实施顺序与阶段出口

| 顺序 | 实施工作 | 交付与出口 |
|---|---|---|
| P0 | 核对AGENTS/源码/协议、共同版本/来源框架 | 复用映射、基线回归、无历史证据改写 |
| P1 | 主动search/load/use、全库候选、漏斗追踪与同状态选择对照 | 真实search/load/use证据；NO_SEARCH/RETRIEVAL_MISS/OFFERED_NOT_SELECTED等归因可复现 |
| P2 | 经验归一化、模式/机会发现与语义去重 | 有独立来源的候选机会；区分新程序、修程序、改metadata、无机会 |
| P3 | TraceCompiler/可选ProposalModel + RevisionMemory简版 | 候选随不同轨迹依赖改变；每次修订保留父diff和来源 |
| P4 | 静态/沙箱/Agent验证、完整Skill生命周期及配对准入 | 正/边界/负/故障；旧任务退步可见，弃权/拒绝/回滚不丢证据 |
| P5 | 三轮复用、No-History、未见结构/边界及C-B对照 | 分离检索收益和新增Skill收益；完整留存/成本与局限并冻结 |
| P6 | 公开变化触发及通道隔离 | 真变化/不变/故障的触发检查 |
| P7 | v1.1全量归因 + Broad/Deep区分探针开发消融 | 明确未触发原因与可区分探针覆盖；选择一个最小新方法 |
| P8 | 假设域/OTHER/停止改进 | 不可识别和域不足不过度认证 |
| P9 | Skill绑定、有效policy与终态分离 | 公开context和Guard兼容性检查 |
| P10 | 分层准入、SAGE式配对效应、retention与回退 | 候选/effective分离；安全硬门槛、统计弃权、三轮父链 |
| P11 | 第二部分独立CPU/真实Agent正式评测 | 效率、安全、EOC、retention分别结论 |
| P12 | 现有工作台只读展示和最终报告 | 每项结论可跳到真实证据 |

不要求第一部分必须取得显著收益才开发第二部分，但进入第二部分的Skill必须通过工程/执行准入，发现机制足够稳定。
若第一部分真实使用仍明显失败，先定位或选可用模型；不能直接用第三条线掩盖调用问题。

## 18. 文件、入口与测试建议

新增示例：
    skillforge/evolution_common/{manifest,experience,snapshot,split_ledger,budget,paired_eval,immutable_registry}.py
    skillforge/skill_evolution/{catalog,retriever,selection_trace,discovery,normalization,opportunities,trace_compiler,revision_memory,revision_planner,admission,validation,controller,reporting}.py
    skillforge/boundary_evolution/{trigger,attribution,probe_curriculum,learner_adapter,paired_gate,admission,controller,reporting}.py
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

**与现有源码的最小改动原则：** 原`retrieval.py`继续提供Memory基线；原`skillforge/skills.py`保留`gate/execute/SkillRegistry`和旧StaticCompiler；`runtime.py`或`execution_aware/runtime.py`仅通过受控adapter接入搜索/加载，不复制订单工具执行逻辑；原`belief.py/active_learning.py`保留数学核心，`probe_curriculum`只负责公开探针候选与可识别性。若新增文件与当前代码责任重合，由Code Agent合并到已有模块，并在P0映射表标注。
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

- 检索器真正搜索冻结目录全体；不能先按family截断后声称全库检索；同词不同支持域的硬负例不误当可执行。
- 独立opportunity分母、NO_SEARCH/RETRIEVAL_MISS/NOT_LOADED/OFFERED_NOT_SELECTED漏斗互不混淆；正确Primitive不被标错。
- 在相同快照分叉时，修正模型可见上下文差异或显式报告不具因果可比性。
- TraceCompiler不由family直接选固定程序；实例参数泛化和依赖正确。
- 验证成功refusal不算mutation成功；超时不当边界反例。
- 多个正确primitive/Skill路径不制造错误标签。
- 12节点与直线支持限制；不可表达分支明确unsupported。
- rollback和目录快照不可变、跨轮来源隔离。

- metadata/program/boundary三类修订不可越权；RevisionMemory不吸收正式test错误；父Revision失效、依赖冲突、语义重复、版本破坏可正确拒绝。
- 同一批配对案例的wins/losses/ties、旧成功任务退步与统计弃权；低样本量不伪称显著。
- snapshot故障消耗、幂等、pending验证和提交未知恢复。
- 变化触发不看world/gold；故障/不变阶段误报统计。
- Gate false block缺公开证据时不伪造标签。
- H0 Challenge各状态、候选覆盖不足、预算/UNKNOWN/OTHER。

- Broad/Deep的公开因子覆盖、阈值两侧区分探针、额外探针真实计费；没有区分候选时停止，隐藏world信息不能渗入。
- Instance/Paraphrase/Boundary/Structural四类heldout、No-History、MemoryOnly对照与训练集特例固化检测。
- 不适用二值与refuse/escalate终态隔离。
- 原Guard保留、有效Boundary替换旧business条件。
- 候选与effective分开；拒绝不进入下一轮parent。
- 自主与Runtime辅助分别计费、两阶段无新训练调用。
测试聚焦真实约束与失败路径，避免镜像实现的无效测试堆积。

## 19. 工程展示与研究验收

复用工作台，只增只读页面：
- 第一部分：检索漏斗（目录→search→load→Gate→choose→execute）和沉淀链（轨迹→模式→Skill候选→修订记忆→独立验证→版本→未见任务复用）。
- 第二部分：冲突→Broad覆盖→Deep区分探针→belief/OTHER→Boundary候选→配对统计/两层准入→父链。
- 任何图表可查看原始证据。
- 显示拒绝、OTHER、无更新、成本、stable退步、模型限制。

- 首屏同时呈现`retrieval_opportunities`、`search_hit`、`loaded`、`offered`、`selected`、`verified_execution`以及训练/heldout收益差；点击定位task快照、Skill exact revision和成本明细。
- 不把optimizer内部分数当业务成果，不把Runtime补救当自主模型能力；Skill版本编辑内容与验证退步能逐条追溯。
- 区分CPU/scripted/真实模型；engineering_passed、research_claim_passed、isolated_activated独立字段。

首轮fixture只用于工程测试，可刻意制造程序错误/规则冲突，明确scripted。
真实模型实验不能注入人为错误并声称模型自主失败。
验收器、任务生成器和进化器职责分离，不能由新Skill自己定义正确性。

总体验收：
第一部分至少能证明经验程序生成与可靠复用机制成立；
第三条线至少能证明自主触发、主动获取、候选/有效系统分离和连续保持机制可运行。
“收益成立”需独立真实结果，不预先要求所有研究假设通过。
没有足够真实数据、无有用候选或新方法无提升都允许完整交付，写清证据与限制。

## 19.1 论文到模块的转化边界（供实现时核对，而非额外功能清单）

| 论文 | 核实链接 | 本项目可复用机制 | 明确不做/不宣称 |
|---|---|---|---|
| MUSE-Autoskill | https://arxiv.org/abs/2605.27366 | Skill目录、创建→Memory→管理→评测→修订；P1/P2/P4 | 不直接复制其Agent框架，也不引用论文成绩作为SkillForge成绩 |
| SkillRL | https://arxiv.org/abs/2602.08234 | 经验抽象、General/Task-specific候选、分层检索；P1/P2 | 暂不实现SkillBank与RL策略协同训练 |
| SkillAdam | https://arxiv.org/abs/2609.08944 | 修订历史、局部编辑、避免覆盖旧修复；P3/P4 | 首版不必引入Adam式数值更新器 |
| SAGE | https://arxiv.org/abs/2609.36043 | 逐例配对wins/losses、旧能力退步惩罚、接受/弃权；P4/P10 | 统计测试不能代替安全Guard，不能在小样本上强求显著 |
| RSIAgent | https://arxiv.org/abs/2609.15364 | Broad-to-Deep探索、环境因果/边界知识；P6/P7 | 不复制多Agent自主浏览/开放环境结果 |
| Agent0 | https://arxiv.org/abs/2511.16043 | 当前能力前沿的探索任务产生与区分案例；P7 | 不实现其Curriculum/Executor联合RL |
| Do Self-Evolving Skills Generalize to Held-Out Tasks? | https://arxiv.org/abs/2609.39148 | heldout泛化、特例固化风险、No-History研究；P5/P11 | 不把论文的相对效果作为本项目预设目标 |

**新增工作按依赖优先级执行**：P1检索/选择漏斗是硬前置；P2/P3评估是否能发现真正新程序；P4版本治理与配对准入；P5泛化及因果对照。第二部分先读v1.1全量失败证据再决定是否加入Broad/Deep；P10增加SAGE式评估。研究启发不构成代码复制要求，算法若在dev消融无收益应保留负结果而不强行部署。

## 20. 直接交给Code Agent的启动指令

> 你是SkillForge仓库的实施Agent。严格按本Markdown修订版执行。**先完成P0审计并提交审计报告，再逐阶段实施；不要一次性大改整套框架。**读取实际checkout的AGENTS.md（若存在）和现有源码/测试/正式报告，对照基线`ecceeb317bbe967b30b36c58df5031c6e7bfbdce`，列出可以复用的函数与不能修改的历史结论。实验结果另建版本化目录，历史formal、模型和业务Guard不可覆写。
>
> **优先P1：** 建立冻结Skill目录的主动 `search_skills/load_skill`、三态Gate和Skill调用链，保证search在全库公共条目上发生而不是先按family截断；新增逐级`SkillUseTrace`，分清未搜索、漏召回、未加载、Gate拒绝、已提供但不选择、参数错误、执行失败和合法Primitive替代。先跑小规模固定上下文与真实模型双诊断，再考虑Embedding或更强模型。禁止把未选择Skill一概当业务错误。
>
> **接着P2–P4：** 从train真实Trajectory抽象不同的程序性Skill机会；不把固定三个family编译器换ID当自主能力。实现语义去重、TraceCompiler、版本化Catalog、最小RevisionMemory、独立Positive/Boundary/Negative/Fault验收以及SAGE式逐题配对准入。修订只依赖learn/dev，formal validation/test不回流proposer；允许`NO_USEFUL_CANDIDATE/REJECTED/INCONCLUSIVE`。
>
> **P5阶段冻结并评测：** 在同一模型/Runtime/工具/检索协议上比较PrimitiveOnly、StaticLibrary和ExperienceEvolution，MemoryOnly可选。至少三轮经验演化；运行No-History、Instance/Paraphrase/Boundary四类前置定义的heldout，并在DSL/EOC支持时运行Structural/Compositional heldout；不支持则明确`UNSUPPORTED`，报告EOC、安全、选择漏斗、工具与模型成本、负迁移/遗忘。区分静态检索收益与Skill新增能力收益。没有C-B增量也可如实交付，不得声称持续能力提升。
>
> **第二阶段P6–P11：** 只在第一阶段冻结的程序与执行条件上学习Boundary。由公开交互发现变化，不从world ID或gold标注触发。先全量审计v1.1为何H0 Challenge没有触发、为何连续阶段存在stable退步；使用原Belief/EIG，按审计结果开发Broad-to-Deep安全探针与选择消融，不能无理由重建主动学习算法。严格区分二值executable与refuse/escalate；DOMAIN_INSUFFICIENT、不可识别、预算不足必须弃权，不能伪造收敛。
>
> **统计准入/发布：** Boundary与完整Agent分层评估，先过不可变安全硬约束，再基于同一任务的旧/新版本配对wins/losses/退步和独立world-seed证据决定`ADMIT/REJECT/INCONCLUSIVE`。候选与effective fallback分别评测。连续至少三个规则阶段，失败不更新父链，只有通过独立准入者可隔离激活；真实部署不自动切换。
>
> **本轮不新增SFT/DPO/RL或持续训练流水线。** 开发阶段可以检查更强固定模型是否能使用目录，但正式冻结后一律固定模型/解码/数据/预算。Runtime的自动补读和修复必须与自主Agent行为分别计数。严禁用test选择候选、用隐藏gold驱动探针、注入真实模型错误或用mock替代能力结果。
>
> 每个P阶段在同一进度文档更新：修改文件、设计原因、运行命令、正式/开发数据身份、真实证据、通过/拒绝/阻塞状态、下一步。先执行CPU与合成工程测试，再做模型smoke，预算冻结后跑独立正式实验。代码与网页演示展示的结论必须能追溯到不可变原始证据。最终交付所有复现命令、两阶段报告、至少三轮父链、工作台只读视图，以及未解决的限制。不要把工程通过写成研究通过。
