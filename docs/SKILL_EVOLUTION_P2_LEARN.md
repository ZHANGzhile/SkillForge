# P2：真实 learn 采集与机会筛选（2026-10-12）

本阶段把先前声明的工作流目标接入真实固定权重 Agent。入口为 `scripts/collect_skill_evolution_learn.py`，开发配置为 `configs/skill-evolution-v1.2.learn-dev.json`。本页用于记录开发结果，不是正式研究协议。

后续 P4 已补只读治理、版本目录与原始 Agent 证据接入，见 [当前阶段说明](SKILL_EVOLUTION_P4_REGISTRY.md)。以下保留本批 P2/P3 的原始结果、成本与当时待办；真实零候选结果不变。

## 身份与预算

使用固定 main-v3 adapter，SHA256 为 `f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b`。新 Runtime 协议为 `skill-search-load-use-v1.2-dev5-readonly-goals`：公开目标允许在 HIGH 风险、已取消或已发货状态读取授权事实；没有修改历史业务规则或安全 Guard。

P1 在原 500,000 tokens / 1,800 秒上限内结束，累计 468,390 tokens / 1,726.72 秒。P2 单独登记 200,000 tokens / 900 秒开发采集额度，对应项目累计上限 668,390 tokens / 2,626.72 秒。墙钟包含加载、RPC、快照与关闭，不当作实测 GPU 小时。这不是提高原 P1 上限，也不是正式研究预算冻结。

控制器在任何模型调用前保存完整源码快照、配置、目标、六个 train 案例、目录和预算所有权。账本拒绝重用 phase ID、未结算前序运行和不保留累计成本的新预算。每次推理先保存 SQLite/runtime checkpoint 和准入回执，再 ACK；批准但未知的请求继续按 16,384 tokens 预留。

## 证据边界

- Worker 只接收公开任务、目录、公开规则与真实工具回执。文件读取范围缩到 `worker-public`，不能读取父目录中的私有 fixture/EOC。
- `shipment_summary` 与 `logistics_investigation` 共六个 learn 案例，目标在采集前声明。工单仍为 UNSUPPORTED；不声称完成调查推理或工单验证。
- 每条结果保存精确模型 messages、动作、工具来源、初始/最终事实、独立 EOC、逐请求预算和 SQLite checkpoint。
- 旧静态 Skill 在独立环境中做覆盖检查；这些 scripted 执行不进入学习轨迹，不计成模型自主经验。
- 归一化依据真实参数绑定到公开 `$input`，保留调用顺序与每个节点的原轨迹位置。歧义绑定、失败、超时和 workflow violation 保留，不能变成可用成功模式。
- 初版只支持直线只读序列；没有返回值绑定、任意分支或写入边界学习。不同有效顺序分别形成模式，不能人为合并支持数。

机会筛选要求至少三个独立来源组、有独立预声明目标、程序结构不重复以及预期增量效益。成本估计计入 search、load、execute、stop 共四次模型决策；门槛为平均至少减少一次决策。该估计不是实际候选 Agent 收益，仍需要后续独立配对验证。允许输出 `NO_USEFUL_OPPORTUNITY`。

## 本轮结果

真实采集已结束并通过独立审计。六条轨迹、六个来源组，**6/6 EOC**；无 Runtime 执行干预成功 6，辅助成功 0，强制读回/自动终止 0，违规尝试、实际 policy violation 和实际 workflow violation 均为 0。共 21 次模型决策、15 次模型来源工具调用，**68,906 tokens / 178.10 秒**。独立静态覆盖检查另有 22 次 scripted 工具调用，不进入学习经验，不伪装成模型动作。

| 工作流 | 独立 learn 来源 | 自然决策数/例 | 估计 Skill 决策数 | 估计节省 | 筛选结果 |
|---|---:|---:|---:|---:|---|
| shipment_summary | 3 | 3 | 4 | -1 | NO_USEFUL_OPPORTUNITY |
| logistics_investigation | 3 | 4 | 4 | 0 | NO_USEFUL_OPPORTUNITY |

两种模式的程序结构未与旧静态库重复，目标与来源支持有效；只有增量效益门槛失败。不能把“发现两种重复流程”写成“学到了两项有用能力”，也不能删去搜索/加载成本使结果转正。这里仅评估模型决策节省，尚未实测候选 bundle 的 tokens/时延或任务收益。

项目累计成本为 **537,296 / 668,390 tokens、1,904.82 / 2,626.72 秒**，保留 P1 的所有历史失败。没有使用剩余额度重试直到出现正结果。采集 Worker 已退出，GPU 租约已释放。

[原始报告](../results/skill-evolution/v1.2/development/p2-learn-main-v3-20261012/report.json)、[预先登记身份与预算](../results/skill-evolution/v1.2/development/p2-learn-main-v3-20261012/registration.json)、[汇总报告](../results/skill-evolution/v1.2/development/p2-learn-summary-20261012/REPORT.md)、[机器摘要](../results/skill-evolution/v1.2/development/p2-learn-summary-20261012/summary.json)。真实采集 protocol hash 为 `4cf95916a058f4a69ce948993557b2fce285cdab72db7942fdf458167559eb31`。

最终源码副本回归为 **360 passed / 1 skipped / 2 upstream warnings**；正式 A/B 冻结源码和固定 adapter 身份均通过。[最终预检](../results/skill-evolution/v1.2/development/preflight-20261012-P2-P3-final/preflight.json)。最初预检因旧审计器没有识别 dev5 而失败，已修复协议兼容，失败日志原样保留。

尚未生成或准入新 Skill；program/Agent admission、研究收益、隔离激活与部署必须分别验收。

## P3 只读 TraceCompiler 初版

`skillforge/skill_evolution/compiler.py` 从归一化事件逐节点产生 call，保留真实调用顺序、参数绑定、原轨迹位置和 model/skill/runtime 来源。finish 绑定已独立验收的 completed 证据；身份 postconditions 来源于预声明的公开目标，不采用某个实例的订单状态作为通用断言。候选状态始终为 CANDIDATE，不直接进入可检索的 VERIFIED 目录。

编译前重新核对 learn 分区、独立来源、效益、事件/模式一致性、逐节点出处、旧库覆盖、固定业务规则和十二节点上限。当前仅支持公开 order_id 输入的直线读取；不支持的绑定/工具显式返回 UNSUPPORTED。已有目标覆盖转入 POTENTIAL_DUPLICATE，等待 P4 治理；语法 hash 不冒充语义等价证明。item-list 与完整事实仍必须由独立 workflow EOC 验收，现有 DSL 不会保留非 dotted 列表为通用 state 变量。

工程测试在模拟 RPC/费用接口和独立真实 SQLite 环境中验证：不同有效轨迹顺序生成不同程序；候选可完成预声明目标；篡改来源、分区、调用或效益被拒绝；没有有用机会时不生成程序。这些测试不计入六条真实学习证据，也不是 program/Agent admission。

真实采集经同一入口得到 **NO_USEFUL_CANDIDATE，0 候选**。[编译回执](../results/skill-evolution/v1.2/development/p3-trace-screen-20261012/report.json)、[来源/源码绑定](../results/skill-evolution/v1.2/development/p3-trace-screen-20261012/binding.json)。编译没有模型调用。

P3 的只读提案路径和无更新出口已实现；数据依赖返回值绑定、写入/读回 assert、组合与 RevisionPlanner 尚未实现。P4 的语义去重、RevisionMemory、独立正/边界/负/故障验证及配对准入仍待实施。本批没有候选，不能开始真实新 Skill 的准入实验；可先完成这些工程约束，后续若扩展 learn 工作流，必须先声明目标与 EOC、冻结筛选规则并登记新的累计预算。

## 重放入口

```powershell
.venv-train/Scripts/python.exe -m scripts.collect_skill_evolution_learn collect --config configs/skill-evolution-v1.2.learn-dev.json --output <fresh-output>
.venv/Scripts/python.exe -m scripts.collect_skill_evolution_learn audit --run <collection-output>
.venv/Scripts/python.exe -m scripts.collect_skill_evolution_learn mine --run <collection-output>
.venv/Scripts/python.exe -m scripts.compile_skill_evolution_traces --run <collection-output> --output <fresh-compiler-output>
```

首条是已登记预算的一次采集，不应原样重复执行。重跑须先结算原运行，登记新 phase 并累计历史费用；审计和筛选不运行模型。原始证据不覆盖，追加回执以审计器/筛选器源码 hash 命名。
