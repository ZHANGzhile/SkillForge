# 两阶段自进化：实施映射

启动日期：2026-10-12。用户规格原文保存于 [TWO_PHASE_EVOLUTION_SPEC.md](TWO_PHASE_EVOLUTION_SPEC.md)，当前基线 `ecceeb317bbe967b30b36c58df5031c6e7bfbdce`。本文件描述代码落点与阶段出口，不构成已冻结的研究协议。

## 实施范围

先完成经验驱动 Skill 沉淀与复用，再冻结其工程交付并实施执行驱动 Boundary 进化。固定权重；开发阶段允许模型比较，正式实验冻结模型、提示、数据、源码、预算和准入。SFT/DPO/RL 不进入本轮实施。

| 阶段 | 复用及新增实现 | 出口 |
|---|---|---|
| P0 | 核对原 Gate/DSL、ExecutionContract、Registry、来源和正式协议；新增 preflight | 历史差异有证据，冻结源码一致，独立源码回归通过 |
| 共同基础 | evolution_common/artifacts、snapshot；System identity、split ledger、预算与完整 SQLite fork | 身份不符拒绝恢复，来源不跨分区，提交未知不盲重放 |
| P1 | skill_evolution/catalog、runtime、model、worker；主动 search/load/use | 真实模型调用链、版本和安全约束可审计；最小能力与模型限制明确 |
| P2/P3 | 归一化、来源绑定、Opportunity、TraceCompiler | 程序随输入轨迹依赖变化；同内容去重、不可表达流程返回 unsupported |
| P4 | 静态、环境 fork、Agent 独立验证及版本注册 | 正/边界/负/故障案例与 fallback；validation 不回流提案器 |
| P5 | 三轮父链、PrimitiveOnly/StaticLibrary/ExperienceEvolution | 工程准入与 C-B 研究收益分别结论；cost smoke 后冻结独立正式协议 |
| P6–P11 | 公开冲突触发、v1.1 全量归因、开发消融、域不足、Skill/Boundary 绑定 | 三规则阶段与不变阶段；独立 CPU/Agent 结果，候选及 effective 分开 |
| P12 | 现有 Workbench 增加只读证据展示 | 两阶段可复现报告、成本、拒绝及真实证据跳转 |

## 已核对的复用边界

- `skills.py` 的 Gate、hydrate、execute 继续执行；原 compile_skill 固定三个 family 的程序，保留作 StaticCompiler 对照。
- 原 `runtime.py`、`execution_aware/runtime.py` 不改动；新 adapter 用现有 ExecutionContract 追踪 mutation、Receipt、reconciliation 和辅助终止，并新增主动目录入口。
- Model worker 沿用 v1.1 私有数据访问 guard，工具请求由独立 evaluator 处理；不会向模型发送 fixture 或 EOC 答案。
- 旧环境工具再次执行授权与业务规则检查。第一阶段规则固定；第二阶段需单独验证可变规则与不可变 Guard 的兼容性。
- 所有新结果写入 `results/skill-evolution/v1.2/`；v1/v1.1 formal 文件保持只读。

## P0 历史账目说明

原 `check_execution_aware` 使用 v1 准备阶段保护清单。2026-10-12 实际检查发现 README.md、README.zh-CN.md 与该旧清单不同，均来自已发布的 v1.1 交付首页更新。新 preflight 逐项记录旧哈希、现哈希，并要求它们与指定已发布基线完全一致；其他差异继续失败。原清单和检查器保持原样，不能将其本次失败隐去或追写为通过。

本地原有未跟踪 `interview.md` 不参与实现或证据。未找到 AGENTS.md；问题记录实际位于 `docs/ISSUES.md`。

## 当前开发入口

```powershell
.venv/Scripts/python.exe -m scripts.run_skill_evolution preflight --config configs/skill-evolution-v1.2.dev.json --output <fresh-preflight-dir>
.venv-train/Scripts/python.exe -m scripts.run_skill_evolution smoke --config configs/skill-evolution-v1.2.dev.json --output <fresh-smoke-dir>
```

输出目录必须全新。当前 CLI 仅实现 preflight/smoke，freeze/run/resume 尚未开放。已有快照 API 支持隔离 fork 与身份校验，不等同于正式控制器完成全部恢复功能。

快照保存显式环境 RNG 和执行契约；Skill DSL 中途节点游标及完整控制器续执行还需 P4 实现。环境的 UUID 标识不承诺逐位复现。当前测试验证幂等、剩余故障、独立数据库和 pending 验证保留，不据此宣称所有中断位置都能无损继续原调用栈。

P1 开发 smoke 上限为 500,000 模型 tokens、1,800 秒墙钟；单任务最多 16 个决策、3 search、3 load、131,072 tokens。未知失败保留请求预算预留。此预算仅限本次开发 smoke，不是两个阶段正式实验总预算。

当前仅核验本地 main-v3。更强模型端点尚未配置，比较记为未完成；不将它解释为 main-v3 已经胜出或模型选择完成。
