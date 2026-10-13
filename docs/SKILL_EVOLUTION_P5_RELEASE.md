# P5 正式 Agent 准入、隔离执行与三轮控制器（2026-10-12）

本批继续实现成本 smoke 后的正式出口。新增两个控制器及工程测试；不修改旧正式 A/B、固定模型权重或既有 Runtime/检索行为。最终全量独立源码预检 **445 passed / 1 skipped / 2 upstream warnings**。正式三轮协议已冻结并启动真实 main-v3；下列脚本夹具仍不能计为研究结果。

正式协议：[formal-P5-v1/protocol.json](../results/skill-evolution/v1.2/formal-P5-v1/protocol.json)，hash `11a5a40f86153c81b7b7b57b7ba483d21fa2d78a4deafc2a76298a63f1476ce5`。[最终预检](../results/skill-evolution/v1.2/development/preflight-20261012-P5-formal-final-r2/preflight.json)。运行时页面：[只读 Evolution Trace](http://127.0.0.1:8093/skill-evolution)。

## 正式 Agent 准入

`scripts/skill_evolution_release.py` 将精确程序发布、原始模型轨迹与统计门连接起来：

1. 只有直接继承父快照的一个正式程序修订才能申请；legacy import、零更新和未通过程序验证的条目不能冒充新程序。
2. 推理前保存完整来源/实体所有权、父/候选目录、固定 main-v3、Runtime/检索/限制、配对案例、累计预算和源码快照。phase/candidate 单次正式提交，不允许换 phase 反复适配同一 holdout。
3. 每个任务 baseline/candidate 在独立同初态环境执行，逐请求费用批准先于 ACK。完整原始轨迹、数据库快照、公开上下文、No-History、静态覆盖和费用由独立 CPU 重放核验。
4. 至少 6 个 primary、2 个 stable 独立来源组；使用原预声明调用数收益门。安全事件/逐例回退拒绝，样本或增益不足弃权。Agent 准入还要观察到新版本实际成功执行，但业务 EOC 不要求使用 Skill。
5. `agent-admission.json` 明确 ADMITTED / REJECTED / INCONCLUSIVE，与程序准入、研究收益、激活和部署分别记录。统计门通过本身不构成 Agent 准入。

`activate()` 在新目录保存已准入 Catalog，实例化 `IsolatedRuntime` 并绑定执行身份，然后记录本地 `ISOLATED_ACTIVE`。`open_isolated()` 重新审计回执和目录，拒绝替换版本、权重/源码变化及伪造 disposition。执行仅在新的只读 SQLite 沙箱中进行。这是本地隔离 Runtime 的激活，不修改现有网页服务、生产业务或全局 latest，不代表生产部署。

## 三轮控制器

`scripts/run_skill_evolution_rounds.py` 提供 freeze / run / audit：

- freeze 绑定审计通过的成本 smoke、原三轮草案、完整独立源码副本预检和开发累计费用；一次登记所有 train / program validation / Agent validation / test 来源及实体。已有 phase 或被使用的来源拒绝再次登记。
- 每轮独立真实 learn → 重放 → opportunity → trace compile。零候选则明确 SKIPPED_NO_CANDIDATE 并保留精确父目录。存在候选时，按冻结顺序仅选一个，走四类程序探针与真实配对 Agent 准入；拒绝/弃权同样保留父目录。
- `ResearchRegistry` 复用旧注册和不可变快照，只扩展本研究的真实 learn 来源审计。程序通过、Agent 未通过时，候选快照保留供审计，但不能成为下一轮已激活父版本。
- 三轮完整决策冻结后才执行一次 final A/B/C test。已完成阶段不重新推理；已开始但不完整的阶段保留费用并停止，不擅自重放或清零。
- audit 只读取/重放已有证据，不能启动缺失采集、修补结果或把测试反馈回流 learner。逐轮父链和前序累计费用必须完整继承。

已登记独立研究额度 **2,800,000 tokens / 7,200 秒采集墙钟**，继承开发累计 606,187 tokens / 2,079.6725 秒后，总上限 3,406,187 tokens / 9,279.6725 秒；旧开发上限不变。phase 为 `p5-three-round-readonly-20261012-v1`，已写入不可变 research-budget-ledger。GPU 小时未实测，墙钟不能改称 GPU 小时。

## 工程证据与范围

首版准入/隔离定向 13 项、零更新三轮整链 6 项、候选程序通过但 Agent 弃权整链 1 项通过。所有这些都是 CPU/scripted 接口夹具；正路径测试显式替换模型/采集协议的信任入口，不证明真实模型学会新 Skill，也不写入正式研究结果。

最终补强包括：重放静态覆盖而不信任覆盖标签、拒绝遗漏原始臂的费用、固定候选选择和验证探针、重新核验激活版本。最终源码副本全量预检 445 项通过，385.94 秒；旧正式 A/B 的 86/100 个源文件、历史证据及固定权重均通过核验。第一次通过的预检随后因源码补强而过期，冻结入口确实拒绝了它；只使用最终 r2 回执冻结。[独立工程验收](../results/skill-evolution/v1.2/development/p5-release-acceptance-20261012/report.json)还重放已有真实 P2 零候选出口，新增模型调用/tokens 为 0，不能算新研究轮次。

只读页面位于新 `skillforge/skill_evolution_workbench/`，不修改已冻结的旧 Workbench 文件，不进入模型 Runtime source index。额外 3 项网页测试通过，覆盖无写入、已批准未知费用、只读 HTTP 路由和路径穿越拒绝；网页测试在正式源码预检之外单独记录。页面只显示已保存证据，最终审计完成前明确标为未结算。

当前范围仍是两个直线只读事实采集目标；Structural / Compositional、写入工单、Agent 授权拒绝 EOC、RevisionPlanner 与更强模型比较未实现。No-History 为所有臂共有约束，单独去除历史的处理效应不可识别。无增量时如实交付零增益；不降低 utility 或准入门槛。

## 复现入口

```powershell
.venv/Scripts/python.exe -m scripts.run_skill_evolution preflight --config configs/skill-evolution-v1.2.observable-dev.json --output <fresh-preflight>
.venv/Scripts/python.exe -m scripts.run_skill_evolution_rounds freeze --draft results/skill-evolution/v1.2/development/p5-draft-20261012 --smoke results/skill-evolution/v1.2/development/p5-smoke-20261012 --preflight <passed-preflight> --phase-id <unique-phase> --output <fresh-study>
.venv-train/Scripts/python.exe -m scripts.run_skill_evolution_rounds run --run <study>
.venv/Scripts/python.exe -m scripts.run_skill_evolution_rounds audit --run <completed-study>
```

本批未开展 SFT/DPO/RL 或部署。第二阶段仍以第一阶段实际完成和范围审查为前置。

## 正式完成与阶段冻结

[三轮正式结果](SKILL_EVOLUTION_STAGE1_FORMAL.md)已完成并独立审计，54/54 测试臂全部结算。三轮零候选，C-B 零增益，工程完成与研究收益分开。`stage1-freeze.json` 绑定保留目录、精确源码/提示/固定权重与 legacy 注册范围；Stage 2 版本化 Boundary 接口仍需开发验证。
