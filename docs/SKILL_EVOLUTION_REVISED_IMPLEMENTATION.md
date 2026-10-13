# 新版实施映射（2026-10-12）

规格原文：[新版两阶段方案](TWO_PHASE_EVOLUTION_SPEC_REVISED_2026-10-12.md)。历史旧版规格和开发结果保留，当前顺序以本文件为准。

## P0 / P1 的具体交付

[P0 审计](SKILL_EVOLUTION_P0_REVISED_AUDIT.md) 已完成。新版 P1 分成三个互不混淆的证据层：

1. **CPU 工程对照**：搜索排名重放、私有审计隔离、真实 SQLite 执行机会、Gate/错误分类、合法 primitive 替代、同状态分叉、成本失败保留。
2. **自然调用 smoke**：固定 main-v3，从空加载目录自主搜索/加载/选择；独立评估器预先声明任务目标、从初始快照执行候选，得到分母。不会把真机会标签发送给 Agent。
3. **可见性分叉 smoke**：每组从同一份只读准备后的 DB/runtime/RNG 快照恢复；一臂提供全部三个已验证静态程序，另一臂不提供。早期两轮禁用 search/load，保留模型动作类型混淆导致的失败；最终恢复诊断两臂同样允许正常 search/load。公共规则、工具、预算和模型相同，首个上下文仅 `catalog.loaded_skills` 不同；后续自然分歧正常保留。最终两组配对全部完成并经独立审计，仍是已知 dev 任务上的静态 Skill 诊断，不是新技能学习。

P1 不以模型必须用 Skill 作为 EOC 条件。正确 primitive 同时计业务成功与 `SUCCESSFUL_PRIMITIVE_ALTERNATIVE`。机会分母首版明确限于**固定初始快照上的完整任务目标**，尚不枚举所有中间状态/任意工作流子目标。

## 接口与兼容性

- `Catalog.search()` / 默认 `public_load()` 保留历史 v1 结果；新版 Runtime 使用 `search_audited()` 和增强公开 load，排名组成、截断候选和延迟只进入私有审计。
- `skillforge/skill_evolution/trace.py` 保存逐步 public-event selection trace。私有 trace 不回填 model history。
- `scripts/evolution_opportunities.py` 执行独立任务目标与沙箱检验，没有 family/name 相关性筛选。
- `scripts/evolution_forks.py` 拒绝非初始 checkpoint、未处理提交、写入准备或伪造公开观察；只接受实际公开只读回执中的事实。
- `scripts/run_skill_evolution_selection.py` 提供独立 fork smoke 和只读审计。
- Runtime `public_start` 是显式实验准备入口，不是恢复旧提交的捷径。恢复 pending mutation 仍走既有 checkpoint / ExecutionContract，不允许通过 fork 清空义务。

## 后续阶段的出口约束

| 阶段 | 下一个具体出口 | 当前状态 |
|---|---|---|
| P1 | 真实自然完整链、逐步漏斗、同状态双臂证据及独立审计 | 开发工程和 smoke 出口已满足；自然 6/6、恢复诊断 2 配对 / 4 臂全成功；300/1000 合成容量与 PrimitiveOnly CPU 契约通过。真实 A/B/C 正式对照留 P5 |
| P2 | 先定义新工作流公开目标与独立 EOC，再采集 learn；输出机会或无机会 | 六条真实 learn 已完成、6/6 EOC、独立审计通过；两模式增量决策效益不足，NO_USEFUL_OPPORTUNITY |
| P3 | 轨迹改变导致程序改变、节点绑定/来源、程序去重；初始候选验证后才做局部 RevisionPlanner | 直线只读 TraceCompiler 初版与无候选出口通过工程测试；真实输出 NO_USEFUL_CANDIDATE。组合、返回值绑定、RevisionPlanner 未实施 |
| P4 | revision_kind / semantic fingerprint / RevisionMemory、静态动态验证与配对准入 | 只读治理、独立程序验证、版本注册/废弃/祖先回滚快照与原始 Agent 证据到统计门适配已实现；真实六条动作重放通过，零候选保留父目录。正式成功注册尚无真实候选实测；Agent admission/activation controller 待接 P5 |
| P5 | 三轮完整父链；固定 A/B/C 后端；No-History、四类迁移、拒绝/无更新保留 | 成本 smoke 完成；正式 Agent 准入与本地隔离 Runtime 控制器工程验收通过。445 项全量预检后冻结 formal-P5-v1；真实三轮与 54 臂完成并独立审计，零候选、C-B 零收益，保留父目录。实现与目录已冻结。Structural/Compositional 不支持 |
| P6–P11 | 第一阶段冻结后，公开漂移触发、既有 acquisition 全审计、开发消融、独立 Boundary/Agent 准入与三阶段连续适应 | P6 受控公开触发/工具回执已独立审计；P7 30 对历史诊断与新开发 30 运行消融均完成并审计，KEEP_EXISTING。统一 Boundary Runtime 与 P8/P9/P10 版本/门槛契约通过；真实 H0 7/7 完成并审计，独立 Boundary 验证 2 通过/4 弃权。变化规则 6 臂与独立 Boundary 验证已审计；497 项全量预检通过后冻结 v1.3/formal-P11-v1 并启动 CPU 90 运行 / 真实 Agent 12 阶段。工程规模，world-sequence 聚类；正式最终结果待采集和审计 |
| Workbench | 读取已保存证据，展示漏斗、版本差异、泛化、准入和成本 | 第一阶段只读预览已接入正式进度、父链、准入/激活、费用与轨迹；3 项网页测试通过。第二阶段尚未接入 |

更强执行模型尚无经过验证的配置；主张范围仅限 main-v3。第一阶段有限只读正式矩阵已完成；没有启动后训练、第二阶段正式矩阵、隔离激活或部署。

## 运行入口

工程预检使用 `.venv`；GPU smoke 的父进程使用已有 `.venv-train`，因为 GPU 租约需要 `psutil`。不为此修改旧冻结依赖或执行器。

```powershell
.venv/Scripts/python.exe -m scripts.run_skill_evolution preflight --config configs/skill-evolution-v1.2.observable-dev.json --output <fresh-preflight-dir>
.venv-train/Scripts/python.exe -m scripts.run_skill_evolution smoke --config configs/skill-evolution-v1.2.observable-dev.json --output <fresh-smoke-dir>
.venv-train/Scripts/python.exe -m scripts.run_skill_evolution_selection smoke --config configs/skill-evolution-v1.2.fork-dev.json --output <fresh-fork-dir>
.venv/Scripts/python.exe -m scripts.audit_evolution_run --run <organic-smoke-dir>
.venv/Scripts/python.exe -m scripts.run_skill_evolution_selection audit --run <fork-dir>
```

配置中的 prior paths 是本轮固定开发账本；重跑必须创建新目录并显式追加 prior。禁止复用输出目录、重置累计预算或覆盖已完成实验。Windows 不可变文件写入需要硬链接权限。

逐请求全局预算组件为 `scripts/evolution_budget.py`，已接入新 `continue_skill_evolution_selection` 与 `collect_skill_evolution_learn` 控制器。旧 `smoke` 入口保留整任务预留行为，不能误称所有历史入口已改成逐请求或通用恢复。续跑及独立审计命令见检查点报告；真实 learn / mine / compile 命令见 [P2/P3 说明](SKILL_EVOLUTION_P2_LEARN.md)。

## 当前出口与历史发现

最新交付见 [Stage 1 三轮正式结果与冻结](SKILL_EVOLUTION_STAGE1_FORMAL.md)：18 条 learn、54 臂均完成并独立审计，三轮零候选，三臂均 18/18 EOC、C-B 零增益。累计 1,433,441 tokens / 3,552.03 秒采集墙钟。第一阶段实现与保留目录已冻结，正候选/复用收益仍未证明；第二阶段以此明确范围推进 P6 与 P7。下列发现保留为之前各批次的历史记录。

最新阶段报告：[P1 完成与 P2 契约检查点](SKILL_EVOLUTION_P1_P2_CHECKPOINT.md)；最新 P1 汇总：`results/skill-evolution/v1.2/development/p1-revised-summary-20261012-v2/REPORT.md`。旧汇总保留为停止时的历史状态。

1. `dev3-observable` 自然 smoke 的三个完整任务机会中，两例走 Skill、一例正确 primitive。此诊断与 `dev4-action-contract` 分叉不是同协议跨批比较。
2. 在零发现预算下，main-v3 会混淆 primitive 和 Skill 的动作类型；明确公开类型、隐藏不可用虚拟工具后仍有相同失败。保留模型动作，不自动转换以提升 EOC。
3. 发现预算非零时，空加载臂可通过真实 search/load 自行恢复。现在取消/退款均形成完整配对，两臂均成功；这两个已知 dev 单元只能支持诊断，不计算正式泛化或显著性。
4. 已实现控制器侧逐请求预算准入与从未启动臂续跑。沿用原 Worker 的 checkpoint ACK 屏障，在推理前持久化准入回执；审批后的未知请求仍计满额预留，拒绝且从未 ACK 的请求单独对账。只新执行缺失退款臂，新增 10,395 tokens / 49.32 秒，累计 468,390 tokens / 1,726.72 秒，没有提高原 500k / 1,800 秒上限。
5. 续跑绑定原 Runtime/提示、模型、目录、每臂预算、父快照、继承文件逐字节 hash 和 prior 成本；原 partial 报告不改。源码不同或已有未完成臂会拒绝续跑；这不是通用 mid-arm recovery。P2 新增模块产生新的源码身份，不能再假装运行原注册身份。
6. 空目录 PrimitiveOnly CPU 对照确认原始工具与预算保留，合法 primitive 完成；错误的 Skill 动作不自动转换。这不替代真实模型 PrimitiveOnly/StaticLibrary/ExperienceEvolution 评测。更强模型比较未配置。
7. P2 独立 EOC 拒绝缺证据、伪造事实、归属错误和未请求副作用。`create_ticket` 是缺少 mutation ledger/read-back Receipt 的 passthrough，工单工作流明确 `UNSUPPORTED`；当前只支持事实采集，不声称调查推理或工单生成。

最新交付见 [P2 真实 learn / P3 TraceCompiler](SKILL_EVOLUTION_P2_LEARN.md)：6 条真实轨迹，6/6 EOC，68,906 tokens / 178.10 秒；独立审计、归一化与筛选完成。两种流程自然只需 3/4 决策，没有达到预登记的增量效益，输出 0 Opportunity / 0 候选。固定 main-v3，无新训练或激活。共享累计成本 537,296 tokens / 1,904.82 秒；P2 独立 200k / 900 秒额度不更改 P1 原上限。最终全量回归 360 passed / 1 skipped。

当前 P4 进展见 [只读治理与验证](SKILL_EVOLUTION_P4_GOVERNANCE.md)：去重/修订日志、四类独立程序验证、按来源组的配对统计门及可重放零更新证据已实现。工程模式不能准入，统计门通过不能激活，正式反馈不能流回 RevisionMemory。本批 0 新模型调用，真实六条 learn 的零候选结果和共享成本不变。

历史待办（已由 P4/P5 完成）：版本化注册/废弃/回滚、Agent 审计、P5 成本 smoke 与三轮协议冻结。没有合格真实候选前不开展新 Skill 准入；新增 learn 结构必须先声明独立目标/EOC和新累计预算。第一阶段三轮和只读证据页现已完成，第二阶段继续实施；真实新 Skill 的正面收益仍未证明。
