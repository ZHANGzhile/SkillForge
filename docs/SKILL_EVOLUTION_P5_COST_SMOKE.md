# P5 同后端 A/B/C 成本 smoke 与三轮草案（2026-10-12）

固定 main-v3 的六臂开发成本 smoke 已完成并通过独立审计：6/6 EOC、全部 autonomous、0 assisted、零 Safety 事件。真实新候选仍为 0；B/C 目录相同，配对增益为 0。这是成本与控制器验证，尚未完成正式三轮研究。

证据：[原始报告](../results/skill-evolution/v1.2/development/p5-smoke-20261012/report.json)、[可读报告](../results/skill-evolution/v1.2/development/p5-smoke-20261012/REPORT.md)、[独立审计](../results/skill-evolution/v1.2/development/p5-smoke-20261012/evidence-audits/7cb0ec1d7f4f67b68d8a28bc7c43a593083132881647ab5f6c5ece7e36ec13de.json)、[三轮草案](../results/skill-evolution/v1.2/development/p5-draft-20261012/draft.json)。

## 对照与执行约束

`scripts/run_skill_evolution_reuse.py` 在同一模型、Runtime、提示、原始工具、检索接口和执行预算下运行三臂：A 为空目录 PrimitiveOnly，B 为冻结历史静态目录，C 为 P4 实际 RETAIN_PARENT 快照。C 保留 B 的精确内容，没有伪造新学习 Skill。

两个开发任务分别为 shipment_summary 和 logistics_investigation。每个任务的三臂具有相同公开请求、授权、数据库初态和 RNG，在独立 SQLite 环境执行。顺序为 A/B/C 与 B/C/A，仅做有限顺序轮换；统计单位是两个来源组，不能把六臂算作六个独立样本。统一限制为 max_steps=12、search/load 各 3 次、每臂 65,536 tokens。

逐请求 checkpoint 在推理 ACK 前登记费用准入。已批准但状态未知的请求保守计 16,384 tokens；拒绝且从未 ACK 的请求计 0。未完成臂只审计，不自动重放。phase ledger 拒绝重复登记、未结算前序和累计成本重置；本次沿用既有共享上限 668,390 tokens / 2,626.72 秒。

## 实测结果

| 方法 | EOC | autonomous / assisted | 模型调用 | tokens | 模型来源工具调用 | search / load |
|---|---:|---:|---:|---:|---:|---:|
| A | 2/2 | 2 / 0 | 7 | 22,959 | 5 | 0 / 0 |
| B | 2/2 | 2 / 0 | 7 | 22,966 | 5 | 0 / 0 |
| C | 2/2 | 2 / 0 | 7 | 22,966 | 5 | 0 / 0 |

各臂均通过 primitive 读取完成，没有搜索、加载或执行 Skill。两组 C−B 的 EOC、调用数和 tokens 差均为 0；A/B 的 7-token 差不能支持效率或显著性结论。违规尝试、实际 policy violation、实际 workflow violation 均为 0。

增量成本为 **21 次模型调用 / 68,891 tokens / 174.8481 秒采集墙钟**。共享累计为 **606,187 tokens / 2,079.6725 秒**，剩余 **62,203 tokens / 547.0488 秒**。墙钟不等于实测 GPU 小时。

模型来源工具调用 15 次；静态覆盖检查另有 12 次 scripted CPU 调用；事后独立审计另重放 15 次 CPU 调用。后二者没有新增模型调用或 tokens，不进入真实 learn。

所有臂均满足 No-History：不携带跨任务原始 learn 轨迹、经验或修订记忆，保留当前任务必要的历史事实。C 原本就采用此约束，因此不能将一个相同的第四臂解释为独立 No-History 消融收益。

## 三轮 protocol 草案

`scripts/plan_skill_evolution_reuse.py` 先独立审计六臂原始证据，再保存不可变草案和绑定。当前 `frozen=false`、`registered_for_execution=false`、`completed_real_rounds=0`。

- 三轮各 6 个新来源 train 案例，两个公开只读目标各 3 个来源；允许 NO_USEFUL_CANDIDATE 并精确保留父目录。
- 每轮每个目标 8 个 CPU 程序探针：Positive / Boundary / Negative / Fault 各 2 个，共 16 个。探针不提供程序模板，不替代模型学习。
- 每轮 8 个 Agent validation 案例，其中 primary 6、stable 2；候选出现后才执行父/候选 B/C 配对。每轮最多 1 个正式候选，每父最多 2 次 learn/dev 修订，正式验证反馈不能回流优化器。
- 三轮决策及实现冻结后才执行一次 final test：Instance、Paraphrase、授权只读 Boundary 各 6 个来源，共 18 个新案例 × A/B/C = 54 臂。来源、任务、实体跨轮次和分区保持独立。
- 主比较 C−B，次比较 B−A，以 source_group 为统计单位。准入维持至少 6 个 primary 来源、2 个 stable、零逐例回退/违规、至少一次模型调用节省及 alpha=0.05；双方 EOC 成功才计成本收益。

本草案只覆盖两个既有只读目标。Structural / Compositional 迁移、工单写入和 Agent 拒绝授权任务的 EOC 尚不支持；CPU 权限拒绝探针不等于 Agent 安全任务评测。Memory-only 对照未实现，单独 No-History 去除效应不可识别。这些范围限制必须保留在正式研究协议中。

最多 18 次 learn + 48 次条件 Agent validation + 54 次 final test，即 120 次模型执行。根据本次较高的方法平均成本 11,483 tokens/臂及 29.14135 秒/臂，加两倍规划余量后为 **2,755,920 tokens / 6,994 秒（约 1.94 小时墙钟）**；逐臂硬上限合计 7,864,320 tokens。这些是规划值，GPU 小时未实测，正式研究预算尚未登记，不能从开发剩余额度直接启动。

## 验证、运行状态与下一出口

P5 定向测试 **14 passed**；最终独立源码副本预检 **425 passed / 1 skipped / 2 upstream warnings，102.80 秒**。正式 A/B 的冻结源码、历史文件保护和固定 main-v3 adapter 均通过核验。

smoke 初始化期间一个日志读取线程出现 UTF-8 解码异常；主 Worker 随后正常就绪、完成六臂且通过独立重放。根因未定位，原 stderr 保留。没有据此修改冻结依赖或丢弃失败日志。

模型 Worker 已退出，GPU 租约已释放。当前没有新程序/Agent 正式准入、隔离激活、部署或训练，也没有真实三轮完成记录。

下一步补齐正式 Agent admission receipt 与隔离激活控制器，验证候选成功/拒绝/弃权和零更新父链；登记继承开发成本的独立研究预算、源码/来源/实体账本，明确上述不支持范围后，才冻结并执行三轮协议。

## 入口与身份

```powershell
.venv-train/Scripts/python.exe -m scripts.run_skill_evolution_reuse smoke --output <fresh-run>
.venv/Scripts/python.exe -m scripts.run_skill_evolution_reuse audit --run <run>
.venv/Scripts/python.exe -m scripts.plan_skill_evolution_reuse --smoke <run> --output <fresh-draft>
```

相同 phase ID 不能仅换输出路径重新采集；重跑必须登记唯一 phase 和累计剩余预算，不能清空账本。

| 身份 | SHA256 |
|---|---|
| Smoke protocol | `3d9150481bdd856faca1d745bc190bcfca64ad2518a644a5a731405466c0f446` |
| Smoke report | `abdb29cd90603aaf1931a8015c82f54b1622970a53516b128f7ed6649a965bd1` |
| B/C Catalog | `d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa` |
| main-v3 adapter | `f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b` |
| 三轮草案 | `7b59ea321c9608f6fe5a237fd075430f176e8c56eb7a7471d78e5038761f9ed3` |
