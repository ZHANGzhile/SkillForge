# P1 开发出口与 P2 工作流契约（2026-10-12）

P1 的工程与真实模型 smoke 已完成；P2 已建立先于候选程序的目标和独立 EOC。没有生成、准入或激活新 Skill，没有正式研究收益或泛化结论。

后续 P2 真实采集与 P3 初版已推进，当前状态见 [最新阶段说明](SKILL_EVOLUTION_P2_LEARN.md)：六条真实 learn 全部通过 EOC，增量效益不足而保留零候选。以下保留进入采集前的检查点，包括当时“真实 learn 为 0”的事实。

## 原预算内完成缺失配对

原停止不是模型已经花完额度，而是要求一次预留整个 45,056-token 臂。控制器现在在已有 Worker 的同步 checkpoint ACK 处逐请求准入；Runtime、提示、固定 main-v3、目录、初始状态和每臂上限均与父实验一致。

- 每请求先保存 DB/runtime 快照与预算回执，再 ACK 放行推理。
- 已批准但未确认完成的请求按 16,384-token 上限计费；明确拒绝、从未 ACK 的请求有独立记录，不当成未知已执行请求。
- 仅恢复从未启动的臂。已有臂目录、pending 成本、源码/模型身份不同均拒绝；没有放宽 COMMIT_UNKNOWN 恢复规则。
- 在新目录继承三个已完成臂，逐字节绑定父证据，只运行缺失退款臂。父 partial 报告与旧摘要保持不变。

[新运行报告](../results/skill-evolution/v1.2/development/p1-recovery-continued-20261012/report.json)、[继承与续跑身份](../results/skill-evolution/v1.2/development/p1-recovery-continued-20261012/continuation.json)。

| 已知 dev 任务 | 预加载 EOC / 决策 / tokens | 自然发现 EOC / 决策 / tokens |
|---|---|---|
| 取消订单 | 成功 / 2 / 10,266 | 成功 / 6 / 24,762 |
| 退款 | 成功 / 2 / 10,395 | 成功 / 5 / 21,792 |

两组配对共四臂全部成功，违规尝试 / 实际违规均为 0；均无 Runtime 强制读回或自动终止。两臂均允许后续搜索/加载，因此这是初始预加载与自然发现的诊断，不是 PrimitiveOnly 对照。早期零发现预算的动作类型失败仍保留，不能把恢复结果描述为模型学会了正确命名动作。

只新增 1 臂，10,395 tokens / 49.32 秒；合并四臂的 67,215 tokens 包含继承成本，不能再次完整加到账本。共享开发账本累计 **468,390 / 500,000 tokens、1,726.72 / 1,800 秒运行墙钟**，剩余 31,610 tokens / 73.28 秒。CPU 工程测试另存耗时；墙钟不是实测 GPU 小时。

## P1 的证据和限制

[最新 P1 汇总](../results/skill-evolution/v1.2/development/p1-revised-summary-20261012-v2/REPORT.md)：自然 smoke 6/6 EOC，5 例无 Runtime 执行干预、1 例辅助。初始完整任务机会漏斗为 3 → 2 → 2 → 2 → 2 → 2 → 2 → 2 → 2；另一个正常任务走合法 primitive。

[CPU 容量与 PrimitiveOnly 契约](../results/skill-evolution/v1.2/development/p1-cpu-capacity-20261012/report.json)：

- 300 / 1000 合成干扰条目分别与 3 个历史静态 Skill 一起进入全库排序；排名重放一致。合成条目不是新增业务能力，容量通过不代表 Recall 提升。
- 真空目录与静态库空加载状态采用同 Runtime、提示、原始工具、公开事实和预算；首上下文仅目录身份不同。
- 两臂的合法 primitive 均完成，强制读回/自动终止仍记 Runtime；错误 Skill namespace 仍原样拒绝，不把动作改写成成功。
- 此处均为 scripted CPU 工程证据、0 模型调用；真实 Agent 的 A/B/C 正式对照仍待 P5 冻结与执行。

P1 开发出口支持进入 P2。它不证明三轮能力积累、完整 Agent 准入、独立 heldout 泛化、显著性或部署。

## P2：先声明目标，再采集经验

[目标声明与校验](../results/skill-evolution/v1.2/development/p2-workflow-declaration-20261012-v2/report.json)、[不可变目标定义](../results/skill-evolution/v1.2/development/p2-workflow-declaration-20261012-v2/goals.json)。首版保留，v2 增强事实的严格类型核对，布尔值不能冒充整数数量。

1. `shipment_summary`：采集订单与物流身份/状态，不修改业务数据。
2. `logistics_investigation`：在上述事实之外采集完整商品列表；范围是资料采集，不要求生成调查结论或工单。

目标要求事实而不指定程序顺序；不同合法读取顺序均可验收。EOC 不接收 Skill、候选程序或其 postconditions，而是核对实际公开工具回执、独立 SQLite 原始事实、对象/归属、完整证据及无写副作用。只 stop、缺读、伪造状态/商品数量或归属错误均失败。合法业务操作若违反只读目标，计 workflow violation，与 business policy violation 分开。

声明了 6 个待采集 train/learn 案例；实体和 source_group 不含 split，同源重贴 test 会被账本拒绝。这里没有生成正式 validation/test。6 次 CPU 回执演练明确标为 scripted，不进入 Opportunity 或 TraceCompiler：**真实 learn 轨迹 0，候选程序 0，program/Agent admission 均未执行**。

工单暂为 `UNSUPPORTED`：现有 `create_ticket` 可调用，但 ExecutionContract 将其 passthrough，不产生对应 pending mutation 与 VerificationReceipt；也没有 `get_ticket`，DSL 不保留非 dotted 的 ticket_id / item-list 作为可绑定验证状态。不能仅凭增加工单数量声称“带正确证据的服务工单”已支持。保留旧 Runtime，不修改冻结 v1.1 来掩盖限制。

下一步是有预算与源码身份的新 learn 采集入口，强制路由独立 workflow EOC；随后归一化、跨来源 Opportunity、轨迹依赖 TraceCompiler 与候选验证。目标声明不等于生成了 Skill，scripted 校验不等于真实 Agent 学习。

## 核验命令

最终源码的完整独立回归 **340 passed / 1 skipped**，2 个上游弃用警告。正式 A 的 86 个、B 的 100 个冻结源码及 main-v3 adapter SHA256 均保持一致；历史 README 例外仍绑定已发布基线。[预检回执](../results/skill-evolution/v1.2/development/preflight-20261012-P1-P2-contracts-v2/preflight.json)。没有后台模型进程或 GPU 租约。

```powershell
.venv/Scripts/python.exe -m scripts.continue_skill_evolution_selection audit --run results/skill-evolution/v1.2/development/p1-recovery-continued-20261012
.venv/Scripts/python.exe -m pytest tests/test_skill_evolution_budget.py tests/test_skill_evolution_continuation.py tests/test_skill_evolution_capacity.py tests/test_skill_evolution_workflows.py -q
.venv/Scripts/python.exe -m scripts.run_skill_evolution preflight --config configs/skill-evolution-v1.2.observable-dev.json --output <fresh-preflight-dir>
```

续跑命令历史记录：`scripts.continue_skill_evolution_selection continue --parent <original-partial-run> --output <fresh-run>`。它要求与父注册完全一致的 serving 源码；P2 新模块已经改变新运行的源码身份，不允许强行把当前源码冒充父 Runtime。只读审计使用已保存的源码和身份，仍可运行。不是通用跨源码 resume。
