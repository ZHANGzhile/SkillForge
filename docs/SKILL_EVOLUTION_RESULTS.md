> 2026-10-13 最新状态：Stage 1 正式完成后，P6/P7/P8–P10 开发证据已审计；真实变化规则 smoke 仍无 EOC / 尝试违规改善。Stage 2 工程规模三阶段协议已冻结并运行，CPU 90 单元、真实 Agent 12 阶段/4 独立 world-sequence；最终结果未结算。见 [冻结与预算](BOUNDARY_EVOLUTION_FORMAL_PROTOCOL.md) 和 [变化模型诊断](SKILL_EVOLUTION_P9_REAL_CHANGED.md)。

# Skill Evolution v1.2：P0/P1 开发结果

当前最新：[Stage 1 三轮正式结果与冻结](SKILL_EVOLUTION_STAGE1_FORMAL.md)。18 条真实 learn、54 个正式 A/B/C 测试臂完成，独立重放审计通过；三臂均 18/18 EOC，三轮零候选，C-B 增益为零。累计 1,433,441 tokens / 3,552.03 秒采集墙钟，无新程序/Agent 准入、激活或部署。第二阶段公开漂移触发工程已启动，P7 历史全量诊断完成；不把 CPU 工程证据算作真实 Agent 适应。下文旧批次按时间保留。

最新工程状态见 [P4 只读治理与验证](SKILL_EVOLUTION_P4_GOVERNANCE.md)与[P4 报告](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/REPORT.md)：8 例 scripted 预期行为通过，工程程序准入 INCONCLUSIVE，没有真实新 Skill 准入或激活。真实数据见 [P2/P3](SKILL_EVOLUTION_P2_LEARN.md)：learn 6/6 EOC、零违规，增量效益不足而保留 0 Opportunity / 0 候选。累计模型成本仍为 537,296 tokens / 1,904.82 秒。P1 历史见 [检查点](SKILL_EVOLUTION_P1_P2_CHECKPOINT.md)和[P1 汇总](../results/skill-evolution/v1.2/development/p1-revised-summary-20261012-v2/REPORT.md)。下文保留早期历史结论与成本，不能当作当前累计值。

2026-10-12。本页报告两阶段计划的启动批次。该启动批次当时尚未完成第一阶段；当前状态以上方正式报告为准。

## P0 与工程实现

HEAD 与指定基线 `ecceeb317bbe967b30b36c58df5031c6e7bfbdce` 一致；现有未跟踪 `interview.md` 保留。A 的 86 个、B 的 100 个冻结源码校验一致。旧 10,699 文件保护清单仅有两份 README 与历史哈希不同，均核对为该已发布基线的首页更新；旧检查器本次因此失败，新回执显式披露差异，原清单未改。

实现了主动目录 adapter、精确版本加载、Gate/DSL/Receipt 复用、公共视图、来源账本、预算与完整数据库 fork API。独立源码副本回归首次 293 passed / 1 skipped，随后加入容量和成本测试后为 295 passed / 1 skipped，加入独立审计测试后的最终全量回归为 **298 passed / 1 skipped**。[最终验证回执](../results/skill-evolution/v1.2/development/preflight-20261012-P1-final/preflight.json)。

1000 条目录容量测试使用 999 条合成干扰项加 1 条工程目标，不能解释为 1000 项真实已验证能力。真实 smoke 使用原有 3 个 VERIFIED Skill。

## 两轮真实 main-v3 smoke

权重固定为 main-v3，adapter SHA256 为 `f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b`。模型在独立受限进程中仅接收公共任务、目录和实际工具观察。两个 smoke 均为开发规模，每轮 6 个新实体案例，包括正常取消/地址/退款、FAILED 付款、SHIPPED 地址和 HIGH 风险退款。没有正式 holdout 结果。

| 开发批次 | EOC | 无执行干预成功 | Runtime 辅助成功 | 违规尝试 / 实际违规 | 搜索 / 加载任务 | 成功 Skill 调用 | tokens | 含加载等开销墙钟 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 | 4/6 | 2/6 | 2/6 | 2 / 0 | 5 / 5 | 1 | 130,983 | 467.21 秒 |
| v2 | 6/6 | 5/6 | 1/6 | 0 / 0 | 2 / 2 | 2 | 102,488 | 367.00 秒 |

两轮合计 233,471 tokens、834.22 秒，处于共享 500,000 tokens / 1,800 秒开发上限内。各自模型调用为 34 和 30；搜索、加载、Gate、Skill 内部工具、失败请求及快照开销均进入记录。“无执行干预”按既有 ExecutionContract 口径统计，不意味着 Skill 内部读取或 Gate hydrate 全由模型逐步规划。此处为墙钟成本，不是实测 GPU 小时。

首轮出现两个错误终态：FAILED 付款尝试退款后被阻止并 escalate；SHIPPED 地址在读到禁止条件后 escalate。独立 EOC 均要求 refuse。HIGH 风险案例虽最终正确 escalate，仍有一次被环境阻止的退款尝试，计入安全成本。

第二轮在开发提示/上下文中显式提供既有静态公共规则与终态优先级；Runtime 未按隐藏答案替换模型动作。新 seed 六例均通过，取消和退款由模型主动 search/load/use 后 stop；地址通过正确 primitive 完成。另有 **2 次未加载 Skill 调用**被 adapter 拒绝，之后模型搜索、加载并成功恢复，原动作和额外成本保留。

这里同时变化了开发上下文版本和实例 seed，且每类仅一个案例，不能把 4/6→6/6 当作独立配对因果效应、总体可靠率或泛化收益。第二轮满足最小工程 smoke 门槛，尚未证明所有 family 都使用 Skill，也未比较 PrimitiveOnly/StaticLibrary/ExperienceEvolution。调用频率不作为业务收益。

## 证据

- [首轮原始汇总](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v1/report.json)、[失败与调用诊断](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v1/audit.json)、[追加完整审计](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v1/evidence-audits/bb6a0f88384b6cb8fca3bf5f24924488a58b689829ddf66232f8c18f245857b0.json)。
- [第二轮原始汇总](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v2/report.json)、[使用诊断](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v2/audit.json)、[独立证据审计](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v2/evidence-audit.json)。
- [第二轮 SystemManifest](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v2/system-manifest.json)、[源码快照索引](../results/skill-evolution/v1.2/development/p1-main-v3-smoke-20261012-v2/source-snapshot.json)。SystemManifest 是开发批次的追溯绑定，不冒充预注册正式协议。
- 每个任务目录保存精确 messages、动作、工具 audit、Receipt、live.sqlite 和逐事件 checkpoint。独立审计覆盖 12 例、328 个 SQLite/Runtime checkpoint，重算 EOC/成本并验证公开 search/load，不重跑推理。

首轮源码从同时执行的独立 preflight 副本恢复保存，13 个 Runtime 源码逐个匹配原 registration 哈希，另保留 evaluator/verifier；恢复来源有明确回执。第二轮在推理前保存 24 个源码文件。不同版本不混用恢复身份。

## 当前限制与下一步

最小 search/load/use 机制成立，模型仍可能先调用未加载 Skill；没有完成更强模型比较。没有新增程序、没有 Skill 新能力准入、没有隔离激活、没有训练，也没有正式两阶段研究收益主张。

下一步进入 P2/P3：建立 learn 专用经验记录和轨迹依赖归一化，发现 Opportunity 并实现 TraceCompiler。两个已用于接口开发的 smoke 由 ledger 标为 dev，不能重新包装成正式 learn 来源。之后实施独立候选验证、三轮父链及对照成本 smoke，再冻结正式协议。
# 新版 P1 追加结果入口

2026-10-12 新版方案的独立机会漏斗、三组同状态诊断、全部失败与预算停止，见[新版阶段报告](../results/skill-evolution/v1.2/development/p1-revised-summary-20261012/REPORT.md)及[新版实施进展](SKILL_EVOLUTION_PROGRESS.md)。下文保留早先两轮 smoke 的原始解释；不得以追加实验覆盖原始负面记录。

