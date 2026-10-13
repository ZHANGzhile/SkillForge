# Interview Sprint：真实新 Skill 生成成立，Agent 增量复用未成立

2026-10-13；独立分支 `codex/interview-real-skill-sprint-20261013`。固定 main-v3，未新增训练，未覆盖任何历史 formal 数据。主实验和补充诊断全部完成并通过独立审计。**生成 1 个真实经验候选，Program Admission 通过；Agent Admission 未通过，未激活。**

## 1. 假设与原始问题

Stage 1 的 18 条真实 learn 全部成功，但短工作流仅需 3–4 次模型决策，无法摊销预登记的 search/load/execute/stop 四次决策，因此零候选、零 C−B 收益。此次检验：五类证据采集能否从真实轨迹产生一个新程序，并在固定模型下带来实际复用收益。预算最多七小时；第四小时无合格候选即停止扩展。候选约在开始后 25 分钟产生，全程约 70 分钟，不需要触发截止规则。

## 2. 新任务与独立 EOC

人预先声明 `order_investigation_dossier`：收集客户、订单、完整商品列表、支付、物流五类证据，禁止写入或创建工单。沿用原 SQLite 环境和五个既有读取工具、原 ownership Guard、现有 DSL；三组具有相同的只读能力、模型、提示和预算。

独立 EOC 根据初始数据库真实值核对 **get_customer/get_payment 的完整返回值**，同时核对订单、物流、完整商品列表、对象和认证归属、数据库无副作用。候选不能定义正确性。未授权/不存在对象需实际观察拒绝，然后 refuse 且不重复访问。HIGH 风险、取消/配送完成、部分退款仍允许授权只读操作。这是证据采集，不评估调查推理或生成的 dossier 文章质量。

训练、程序验证、Agent validation、held-out 和补充 dev 的实体及来源分离，均在对应模型执行前声明。主协议 hash：`7e25be0983115a3bfb1d634ea1872f150eb37431473ffbe70b58eef8b2514a73`。统计单位是 source group，不能把 63 臂或 1,557 个 checkpoint 当独立样本。

## 3. Trajectory → Skill 的实际生成

六个独立训练来源 `is13-source-131001`…`131006`，固定真实模型自然执行，每条 6 次决策、16,328 tokens，共 97,968 tokens；完整/自主 EOC 6/6。工具动作均来自模型，精确上下文、原始输出、预算回执和 SQLite checkpoint 已保存并重放。

原 Opportunity Miner 发现同一个参数化模式，原 TraceCompiler 按实际事件生成程序；没有按 workflow_id 填写工具序列。每节点均有六个真实来源的 audit_index 绑定；六条读取顺序一致，**没有加入规范化或未观察步骤**。门槛保持三个独立来源和至少一次预计决策节省；预计 6−4=2 次只是机会估计，不是实测收益。

| 节点 | 实际生成内容 | 来源 |
|---|---|---|
| 0 | get_customer(order_id=$input.order_id) | 六轨迹 audit_index=0 |
| 1 | get_order(order_id=$input.order_id) | 六轨迹 audit_index=1 |
| 2 | get_order_items(order_id=$input.order_id) | 六轨迹 audit_index=2 |
| 3 | get_payment(order_id=$input.order_id) | 六轨迹 audit_index=3 |
| 4 | get_shipment(order_id=$input.order_id) | 六轨迹 audit_index=4 |
| 5 | finish | 六条独立验证的 completed outcome |

Skill ID `trace_dae7a91522975618`，version 1。候选 revision `cb5353ae79000fee6e9b5c01d6a31cc8d1bbcc2d40d385f8c6db1b5102bff295`；程序验证后发布 revision `f36dbea4509b554eaa86ea9820a05882704f1ac48aa8f7975c1398b8f7aef011`。CANDIDATE 原字节保留，VERIFIED 为独立内容寻址版本。

静态检查和八个独立 SQLite 沙箱案例（Positive/Boundary/Negative/Fault 各二）通过，31 次工具尝试；独立重放通过，Program Admission=ADMITTED。这是 CPU 程序验收，不能当作真实 Agent 复用证据。注册为隔离探索性记录，不冒充旧 formal Registry 已支持本新增工作流。

## 4. 真实三组对照

同一来源的三组共享任务、初态、模型、Runtime 和预算，仅目录分别为空、旧静态库、旧库＋新程序；方法顺序预先轮换。所有任务均从无历史、无预加载状态开始。

| 阶段 | 方法 | 完整/自主 EOC | 模型 calls | tokens | 业务工具尝试 | search/load/成功 Skill |
|---|---|---:|---:|---:|---:|---:|
| Validation：6 新任务＋2 旧只读保留 | PrimitiveOnly | 8/8 | 43 | 114,790 | 35 | 0/0/0 |
| 同上 | StaticLibrary | 8/8 | 43 | 114,833 | 35 | 0/0/0 |
| 同上 | ExperienceEvolution | 8/8 | 43 | 114,962 | 35 | 0/0/0 |
| Held-out：9 新任务＋2 旧只读保留 | PrimitiveOnly | 11/11 | 53 | 140,879 | 42 | 0/0/0 |
| 同上 | StaticLibrary | 11/11 | 53 | 140,932 | 42 | 0/0/0 |
| 同上 | ExperienceEvolution | 11/11 | 53 | 141,091 | 42 | 0/0/0 |

Held-out 包含未见订单 3、请求改写 2、极端状态 1、部分退款 1、权限拒绝 1、不存在对象 1，另加两个旧只读工作流。全部配对 ΔEOC=0、Δmodel_calls=0，无旧成功退步；C−B 合计多 288 tokens，来自目录身份上下文差异，无成本收益。六个主要 validation 来源为 0 wins / 0 losses / 6 ties，保守门 p=1，**INCONCLUSIVE，Agent Admission=false**。不把零收益包装成小样本显著提高。

主实验无非法写入/错误 Skill 调用或 actual violation，Runtime intervention=0；每组保留一次合法任务中观察到的原始 permission_denied 尝试，独立标为 expected denial，并非隐藏该计数。没有数据泄露、错误对象访问后的继续尝试。旧保留实证限于两个只读工作流；旧三个写业务程序和旧验收字节保留，但不声称本只读协议重新验证了全部写业务能力。

## 5. 失败归因：预加载也未形成有效复用

主实验问题是 **NO_SEARCH**，不能直接推断模型不会执行新 Skill。因而在 held-out 结果出现前另行冻结三个新 dev 来源的可见性诊断：同一个完整目录、模型、初态、预算，唯一差异是新 Skill 是否已精确预加载。诊断不回流候选或准入，不改变主结论。

| 诊断 | 完整/自主 EOC | calls | tokens | search/load | Skill 动作尝试/接受/成功 |
|---|---:|---:|---:|---:|---:|
| WITHHELD | 3/3 | 18 | 48,850 | 0/0 | 0/0/0 |
| PRELOADED | 3/3 | 28 | 128,642 | 2/3 | 5/0/0 |

模型五次使用展示名称 `Order investigation dossier` 作为 action.name，未复制 `trace_dae7a91522975618`，均被严格版本/ID 接口拒绝为 `skill_not_loaded`。即使搜索/加载正确版本，两个来源仍重复错误引用。随后模型改走 primitive 完成任务；三个配对的 calls 收益为 −4/−4/−2，tokens 增加 79,792。**EOC 3/3 来自回退，不是新 Skill 执行。** 两臂初始上下文除 loaded_skills 外完全一致，六臂/204 checkpoint 独立审计通过；Runtime 未修正动作名称、未代模型完成目标。

因此有两个独立执行缺口：自然检索未触发；提供 Skill 后，动态执行 ID 与展示名称仍混淆。此结果不证明模型永远不能学会引用，也不支持强行修改提示或别名映射后回填本实验。

## 6. 全部成本、基础设施失败和限制

真实模型合计 **69 臂、370 次决策、1,042,947 tokens**；其中主实验 865,455、补充诊断 177,492。实际业务工具尝试 291，另有虚拟 search 2 / load 3。模型加载与采集累计墙钟约 2,281.79 秒（38.03 分钟），包括初始失败、主实验中断/续跑和诊断；不是 GPU 利用小时，后者未测量。实现、CPU 检查和实验总时长约 70 分钟，远低于七小时上限；没有调高 4M-token 上限或恢复预算。

CPU 开销单列：已记录的静态覆盖工具 410 次；程序验证及重复独立验证 186 次；记录响应/SQLite 重放 1,113 次，包含续跑重审及最终可重复审计核验。另有首次异常路径至少一次 CPU 拒绝尝试未保存精确回执，具体计数不可恢复，不能报成零；pytest 合成夹具工具量未单独测量。CPU 检查/重放不计为真实学习样本，也不增加模型 token。

保留的基础设施失败：v1 在推理前被原文件访问 Guard 拦下（0 tokens，20.586 秒）；v2 声明时相对/绝对路径错误（无推理）；v3 完成 51 臂后，静态覆盖辅助器错误抛出预期 permission_denied，负例尚无模型请求。v4 通过单独 hash 的扩展只修复 CPU 覆盖异常分类，逐字节复用 51 臂及 784,517 tokens，仅新增 80,938 tokens 完成余项。原失败报告不改，核心协议、EOC、任务、模型、候选和门槛不变。诊断 v1 因主实验未完成而未推理，v2 仅更换主结果位置；三个 dev 来源和干预条件逐项一致。

P11 先独占 GPU；确认其 12 阶段及审计完成、租约释放后才启动 sprint，未终止它。其 370 个冻结源码 hash 全部不变。CPU 回归原批 62 passed；新增完整契约最终 8 passed。主实验最终独立审计覆盖 63 臂/1,557 checkpoint，补充诊断覆盖 6 臂/204 checkpoint；可重复入口再次重放并保持原回执字节不变。

结论仅限受控 SQLite、共享任务模板、固定 main-v3、现有直线 DSL 的探索性样本。没有结构外推、开放世界自主进化、模型权重能力提升或统计显著性主张；没有 SFT/DPO/RL、生产发布或新 Skill 激活。旧失败、拒绝、父目录及无收益结果全部保留。

## 7. 面试讲解的算法取舍与复核入口

最有解释力的取舍是：先声明目标/EOC，再采集经验；程序节点来自实际交互且逐节点可追溯；参数来自公开输入；门槛包含发现成本；程序准入与 Agent 准入分离；原始输出不自动纠正；拒绝更新保留父目录。预加载反事实诊断定位执行引用问题，但不偷换自主检索收益。**成功产出新程序，与证明新程序实际有益，是不同的验收出口。**

- [主结果与研究汇总](../results/interview-sprint/20261013-v4/report.json)、[候选与逐节点来源](../results/interview-sprint/20261013-v4/candidate-screen.json)、[程序准入](../results/interview-sprint/20261013-v4/program-admission.json)。
- [原协议](../results/interview-sprint/20261013-v4/protocol.json)、[Agent gate](../results/interview-sprint/20261013-v4/agent-paired-gate.json)、[逐例配对效应](../results/interview-sprint/20261013-v4/paired-effects.json)。
- [主独立审计](../results/interview-sprint/20261013-v4/final-independent-audit.json)、[续跑账目](../results/interview-sprint/20261013-v4/continuation-reconciliation.json)、[保留的中断结果](../results/interview-sprint/20261013-v3/report.json)。
- [可见性诊断](../results/interview-sprint/availability-dev-20261013-v2/report.json)、[诊断独立审计及错误引用计数](../results/interview-sprint/availability-dev-20261013-v2/final-independent-audit.json)、[可重复交付核验](../results/interview-sprint/20261013-v4/delivery-verification.json)。

复核现有证据，不加载模型、不覆盖原回执：

```powershell
.venv/Scripts/python.exe -m scripts.verify_interview_delivery
.venv/Scripts/python.exe -m pytest tests/test_interview_sprint.py tests/test_interview_sprint_continuation.py tests/test_interview_sprint_availability.py -q --basetemp=.runtime/interview-review-new
```

真实采集入口为 `scripts.run_interview_sprint declare/run`；重跑必须使用新目录和明确追加的费用/来源登记，不能直接重复既有输出目录。`continue_interview_sprint` 仅支持已诊断且零未知推理的 CPU 覆盖中断，不是通用崩溃恢复。
