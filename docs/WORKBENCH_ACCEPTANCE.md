# 正式研究工作台验收

日期：2026-09-16。范围是正式执行与研究管理入口，以及训练数据导出。本报告不代表整个 SkillForge 已完成。

## 可使用的交付

- 本机地址：http://127.0.0.1:8080；根目录启动项目.cmd。
- 216个冻结数据集任务；支持完整自定义Task、业务初始状态与Expected Outcome Contract。
- 自由Action下B0 / B1 / B2 / B3 / B3-no-gate，以及明确区分的受限Skill目录协议。
- SQLite持久任务队列、单worker排他锁、实时事件、运行历史、取消、隔离重试、轨迹和业务数据库下载。
- 冻结Skill契约、真实历史评测和SFT语料审计统一展示。

每个任务固定模型配置、代码哈希、数据来源和Skill包哈希。自定义任务使用manual-unregistered，不能充当冻结train来源。代码 / 模型配置发生变化时，排队任务拒绝静默切换版本。

## 实际验收

`python -m pytest -q`：**65 passed，2 warnings**，警告来自Starlette / AnyIO上游弃用接口。

浏览器真实Qwen3-4B调用，全部来自train或明确手工任务：

| 场景 | 结局 | 实际Skill调用 | 验收 |
|---|---|---:|---|
| 正常改地址 | completed | 1 | 通过 |
| 正常取消订单 | completed | 1 | 通过 |
| 正常退款 | completed | 1 | 通过 |
| 已发货改地址 | refused | 0 | 通过 |
| 高风险取消 | escalated，有工单 | 0 | 通过 |
| 自定义部分退款：已退500，再退250 | completed，累计750 | 1 | 通过 |

所有六例模型违规尝试和环境实际违规均为0。此处属于受限目录协议的工程集成验收，不是新的test泛化成绩。

原始证据：`results/workbench-acceptance/browser.json`；自定义任务ID `e6e90b46-9c17-4b5d-8c37-693a78b2135c`，完整业务数据库和轨迹位于`results/workbench/runs/<run_id>/`。

网页额外检查：刷新继续查看同一run、下载轨迹对应正确run、历史记录、3个冻结Skill、实验报告、1440px桌面 / 390px手机无溢出、无浏览器脚本错误。截图位于docs/assets/workbench-desktop.png和workbench-mobile.png。

服务实际重启后保留13条运行记录，证据：`results/workbench-acceptance/restart.json`。异常中断的恢复、并发重复请求、同键异参、排队取消、模型返回后取消不写入、退款提交后取消保留唯一账务，均有独立回归测试。

## 恢复和取消语义

- queued在服务启动后继续执行；原running标记interrupted。
- 不会自动重放可能已提交的mutation。重试创建新run和新隔离业务数据库，保留旧记录。
- 取消是协作式：当前HTTP模型调用结束后、下一次工具调用前检查。已提交事务不回滚。
- 工具审计事件与业务事务分别持久化；突发进程崩溃可能发生在业务提交之后、事件落盘之前，应以保留的业务SQLite / 幂等表核对状态，不能把缺失事件解释为没有执行。
- 旧兼容接口`/tasks`和`/benchmark/run`仍使用BackgroundTasks；新恢复语义适用于`/api/v1/runs`。

## 训练数据交付与剩余工作

`scripts/export_sft_data.py`校验真实train来源、原提示哈希和同数据集完整真实B0–B3前置结果；使用action-level filtering，保留模型看到的历史，导出assistant完成目标和来源证据。拒绝test来源、脚本来源、oracle字段、混用受限目录协议及不完整基线。

有效产物：`results/training-data/free-action-v2/train.jsonl`与`audit.json`。74条真实轨迹 / 69任务，561个原始动作筛成181条：139 tool、13 stop、22 refuse、7 escalate。**Skill目标为0**，`ready_for_skill_learning=false`。v1因为Windows换行转换导致哈希错误，作为失败产物保留，不用于训练。

完整项目仍需：补齐Skill监督与same-context反事实偏好、QLoRA SFT训练及权重、DPO训练及权重、同协议Base / SFT / DPO双评测、消融与复现验收。不能把当前网页和181条数据作为全部交付。
