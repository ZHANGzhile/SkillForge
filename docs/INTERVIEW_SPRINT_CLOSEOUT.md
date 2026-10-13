# Interview Sprint 最终交付：新程序生成成立，真实 Agent 增量收益未成立

2026-10-13。固定 main-v3、原安全权限和既有 DSL。**一个真实经验 Skill 通过 Program Admission；Agent Admission=false，Activated=false。** 原主实验、预加载诊断、metadata 诊断及本次共用接口说明实验均保留原始结果，分别审计，不合并为一个正结果。

## 1. 假设与原始问题

Stage 1 的短任务无法摊销 search/load/execute/stop 的四次决策成本。本 Sprint 检验：一个真实五读工作流能否经经验挖掘自动生成新程序，并在计入发现成本后至少节省一次模型决策。原机会门槛始终保持至少三个独立来源；所有收益比较以 source group 为单位。

## 2. 新任务及独立 EOC

人预先声明 `order_investigation_dossier`，要求完整客户、订单、商品列表、支付、物流证据，禁止写入和工单。复用 SQLite 和五个原读取工具，不增加写权限。

EOC 从初始数据库独立取得真实值，核对完整 customer/payment 返回及其余三类证据、对象/身份归属、数据库无副作用；拒绝案例必须真实观察 permission_denied/not_found 后 refuse，不能继续访问。候选不定义正确性。评估对象是证据收集，不是 dossier 文案的推理质量。

## 3. 实际生成过程与版本

六个真实训练来源 `is13-source-131001`–`131006` 自然完成任务，各六次决策。原 Opportunity Miner 和 TraceCompiler 从实际事件产生一个新候选 `trace_dae7a91522975618`；没有 workflow_id→工具序列模板，也没有读取顺序规范化。每个节点均绑定六条原始轨迹的 audit_index：

`get_customer → get_order → get_order_items → get_payment → get_shipment → finish`。

五个读取的 order_id 均由 `$input.order_id` 绑定。四次发现/执行/停止决策下的预计节省为 6−4=2，仅是机会估计。v1 的 VERIFIED revision 为 `f36dbea4509b554eaa86ea9820a05882704f1ac48aa8f7975c1398b8f7aef011`；Positive/Boundary/Negative/Fault 各二 CPU 沙箱通过。v2 仅将展示名对齐执行 ID，并建立父版本关系，程序/边界语义不变，不计作第二个新程序。

## 4. 原真实三组对照

无预加载的 validation（六主要＋两旧保留）和 held-out（九主要＋两旧保留）独立冻结。三组同模型、提示、Runtime、工具能力、初态和预算；方法顺序轮换。

| Validation＋held-out | 完整/自主 EOC | 模型决策 | tokens | 业务工具尝试 | 检索/加载/成功 Skill |
|---|---:|---:|---:|---:|---:|
| PrimitiveOnly | 19/19 | 96 | 255,669 | 77 | 0/0/0 |
| StaticLibrary | 19/19 | 96 | 255,765 | 77 | 0/0/0 |
| ExperienceEvolution | 19/19 | 96 | 256,053 | 77 | 0/0/0 |

未见订单、请求改写、极端状态、部分退款、权限拒绝和对象不存在均保留逐例数据。全部配对 ΔEOC=0、Δcalls=0；C−B 多 288 tokens。六主要 validation 来源为零 wins、零 losses、六 ties，门为 INCONCLUSIVE。旧只读任务无退步；原写业务程序/验收字节保留，但本只读实验不重新证明写业务 retention。

## 5. 独立 dev 诊断与最后一次补充实验

各诊断用全新来源，不回写旧实验，不改变门槛。

| 条件，每条件三个来源 | 完整/自主 EOC | 模型决策 | tokens | 成功 Skill |
|---|---:|---:|---:|---:|
| 可见性：未预加载 v1 | 3/3 | 18 | 48,850 | 0 |
| 可见性：精确预加载 v1 | 3/3 | 28 | 128,642 | 0 |
| Metadata：原名称 v1，预加载 | 3/3 | 30 | 146,390 | 0 |
| Metadata：精确 ID 名称 v2，预加载 | 3/3 | 22 | 74,332 | 0 |
| 新共用接口说明：PrimitiveOnly | 3/3 | 18 | 53,944 | 0 |
| 新共用接口说明：StaticLibrary | 3/3 | 18 | 53,962 | 0 |
| 新共用接口说明：ExperienceEvolution | 3/3 | 18 | 53,908 | 0 |

可见性诊断的五个 Skill 动作错误地使用展示名，全部被拒绝；metadata 旧名称再出现六次错误引用，精确名称三次复制对 ID 却提交空 arguments，被严格 Runtime 拒绝。所有任务随后靠 primitive 回退完成。少了错误动作带来的调用下降不能算 Skill 复用收益。

本次另行预登记唯一一个共用提示变体，明确先搜索一次，并要求按 loaded inputs 从公开 parameters 逐键绑定；没有提供候选 ID、业务工具序列或测试答案。三组提示完全相同，Runtime 不补参、不映射别名、不代搜索/加载/停止。三个全新来源分别为实例、改写、极端边界。新候选版本先过八个独立程序沙箱，再运行九个真实臂。

结果三组均未搜索或加载，Skill action attempts=0，实际 Skill execution=0，每源 C−B calls 收益为 0。C 的 54-token 合计下降来自目录身份的输入 token 差异，没有程序被调用，不能归因于 Skill。Runtime-assisted EOC、intervention、错误复用、违规意图及 actual violation 均为零。**dev 门要求实际 search→load→成功 Skill 且每源省至少一次决策，故失败。** 预留 validation/held-out 未使用，未启动新正式矩阵，不再添加提示变体。

## 6. 成本、验证与实验限制

真实模型累计 **84 个臂、476 次决策、1,425,483 tokens、367 次业务工具尝试**。主实验 865,455 tokens；预加载诊断 177,492；metadata 诊断 220,722；本次补充 161,814。累计仍在原 4M tokens 和 09:06:38–16:06:38 UTC 七小时预算内，没有预算重置；有效候选约在原第 25 分钟产生。

本次模型采集墙钟 372.48 秒；GPU 利用小时未测量，不能用墙钟冒充。CPU 单列：程序验证 31 工具尝试＋独立重放 31，静态覆盖 49，采集回执重放 45，最终独立审计再重放 45 个业务工具＋62 个父/子程序工具，共 263 次已记录 CPU 工具调用。新增五项 CPU 契约通过；第一次沙箱运行有一项因 Windows hard-link 权限失败，工具会话保留原始输出，并另存人工转录记录，获准运行后全通过。合成测试工具数未另测量，不计入真实学习样本。此前 CPU 成本和一项不能恢复精确计数的早期拒绝见原报告，不伪造累计精确值。

四项真实审计分别覆盖主实验 63 臂/1,557 checkpoints、预加载 6/204、metadata 6/224、新说明 9/261。最后一项核对原轨迹重新编译、程序等价、模型权重/解码设置、同源非目录上下文一致、来源隔离、原始输出、实际 SQLite 和全部费用。P11 的 370 个冻结源码在补充前后均保持不变，GPU 租约已释放。

最终统一交付复核再次通过全部 84 臂/2,246 checkpoints；单独新增 367 次 CPU 响应重放和 155 次程序重放，模型 calls/tokens 均为零，原回执字节保持不变。此额外复核费与前面的 263 次分开列账，完整回执见 `closeout-verification.json`。

样本小，任务共享模板，确定性解码，无结构外推；正式统计单位不能改成任务内 steps/checkpoints。只支持受限领域的程序归纳成功和执行接口失败诊断，不宣称统计显著、权重能力提升或开放世界自主进化。没有 SFT/DPO/RL、权限放宽或生产激活。

## 7. 面试讲解与复核

关键取舍：目标/EOC 独立于候选；程序来自真实多源交互并逐节点可追溯；机会效用计入发现成本；程序准入、Agent 准入和激活分开；保留原始错误而不由 Runtime 修正；无收益时保留父库。

证据定位到三个环节：自然检索没有触发；展示名称与动态 ID 混淆；正确 ID 后仍漏绑定参数。共用公开接口说明未解除检索缺口。这里的观察不证明任何提示或接口永远无效，也不证明未实际运行的绑定分支得到改善。**交付结论是“真实新程序已生成并可由 DSL 执行，固定 Agent 的有效自主复用尚未成立”。**

- [原主报告和完整生成来源](INTERVIEW_SPRINT_RESULTS.md)
- [Metadata 失败报告](INTERVIEW_REFERENCE_RESULTS.md)
- [本次单一变体预登记](INTERVIEW_BINDING_PLAN.md)
- [本次完整协议](../results/interview-sprint/binding-followup-20261013-v1/plan.json)
- [九臂原始汇总](../results/interview-sprint/binding-followup-20261013-v1/discovery_dev/report.json)
- [独立审计](../results/interview-sprint/binding-followup-20261013-v1/final-independent-audit.json)
- [逐源收益与所有费用](../results/interview-sprint/binding-followup-20261013-v1/delivery-summary.json)
- [Agent 准入处置](../results/interview-sprint/binding-followup-20261013-v1/agent-admission.json)
- [全阶段交付复核与新增 CPU 费用](../results/interview-sprint/binding-followup-20261013-v1/closeout-verification.json)

CPU 独立复核：`.venv-train/Scripts/python.exe -m scripts.verify_interview_closeout --output <全新输出文件>`；不加载模型，不改原回执，重复检查纳入新复核费用。
