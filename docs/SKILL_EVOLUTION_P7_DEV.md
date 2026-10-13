# P7 五方法新开发消融：保留现有方法

2026-10-12。预先登记 W1/W5/W6 × 2 个新开发种子（2026101241/2026101242）× 5 方法，共 30 个运行。每个方法最多 20 次探索，Bayes/EIG、原六字段有限谓词域和收敛阈值保持不变。固定历史程序，零模型调用/训练。

| 方法 | budget 内收敛 | RMQ（cap=20） | FA / FB | stable 错误 | 探索查询 | 生成候选 |
|---|---:|---:|---:|---:|---:|---:|
| OriginalActive | 4/6 | 11.8333 | 2 / 3 | 0 | 53 | 0 |
| ExistingActiveV2 | 2/6 | 16.3333 | 2 / 3 | 0 | 64 | 0 |
| BroadOnly | 2/6 | 16.5000 | 2 / 3 | 0 | 70 | 0 |
| DeepOnly | 2/6 | 16.3333 | 2 / 3 | 0 | 65 | 8 |
| BroadThenDeep | 2/6 | 16.5000 | 2 / 3 | 0 | 70 | 10 |

按登记规则，必须提高 convergence、RMQ 与有效 FA/FB/stable 不劣、实际 probe 违规为零，才选择新方法。结果为 **KEEP_EXISTING**，不把覆盖/弃权/额外生成本身当成收益，也不调门槛或 λ。W5 的两个 OriginalActive 收敛至 H0，但各有一个开发验证 false allow；原 v2 与新候选避免宣布该 H0 收敛，最终仍回退 H0，因此有效错误未改善。收敛率不是正确适应率。独立 Boundary validation 仍是必要条件。

Broad 使用前 3 次查询做公开单/双因子覆盖优先，之后恢复原 EIG-cost-risk。Deep 在实际公开矛盾后，只针对两个不同预测等价类提议已有阈值两侧、单因子对照、至多一次新对象独立重复；最多 8 个候选，不扩展假设语言。所有生成请求由可信沙箱设计器检查可实现性，得到真实工具回执后才更新 Belief。未实现矛盾时不强制生成。

学习器是独立进程，仅收到公共 Candidate / EvidenceView、假设和选项；通过 RPC 请求 probe / expand。访问私有结果或导入 evaluator/gold 的测试被拒绝。该保护是 Python cooperative audit guard，不是对恶意原生扩展的 OS sandbox。私有开发验证只在每个候选冻结、学习器退出后打开，不回传 learner。

322 次逻辑探索查询；同任务真实沙箱回执在配对方法间缓存，物理实际探针 379 次（含 seed / development validation）、实际工具调用 3,140 次，实际 probe 违规 0；CPU 墙钟 353.99 秒。逻辑方法费用分别完整计入，不能把缓存当免费查询或把 379 个任务当独立研究样本。统计单位为 6 个 world-seed，属于已知规则族的新参数/种子开发验证，无正式显著性、结构泛化或真实 Agent 改善主张。

独立审计重新执行保存回执的完整 DSL、验证实际 tool/request 顺序与 postcondition，重算所有 Bayes/EIG 排名、生成/RPC 选择、停止、候选、私有开发验证和最终选择，共 30 个运行/322 查询/379 探针；新增工具与模型调用均 0，207.48 秒。审计已通过。

protocol：`0fd5348f173c70bdd4c872c79328565bb8fe86a305285bbf37e1b82ef3da059b`。
report：`3f2c2293e0d09880d4ea1c534bd276107a6860af3e194b3080115fd78933c8e1`。
audit：`ef753136a7b338b756261ade7d509f73616a1c53ca798bc9ed4d470d21081370`。

本结果不替代独立 Boundary/Agent 准入、changed/no-change/fault 连续日常流或三阶段父链。后续重点是明确未准入的安全隔离/fallback 代价，以及版本化 Boundary 在固定程序/模型/统一 Runtime 下的真实执行；不继续为制造 acquisition 创新增加研究方向。

[原始结果](../results/skill-evolution/v1.2/development/p7-acquisition-ablation-20261012/report.json)、[独立审计](../results/skill-evolution/v1.2/development/p7-acquisition-ablation-20261012/independent-audit.json)。
