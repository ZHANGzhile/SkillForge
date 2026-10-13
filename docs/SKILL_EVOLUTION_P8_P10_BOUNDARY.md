# P8–P10 有限支持、版本绑定与独立 Boundary 开发验证

2026-10-12。保留 P7 已冻结的 6 个 ExistingActiveV2 world-seed 结果；不重新选 acquisition 或调参。所有候选先冻结，之后用全新来源/实体的 validation 60 + stable_validation 16 做独立 CPU 沙箱验证。

两个 W1 提案通过 Boundary 算术门槛：每个 28 正/32 负、FA/FB 均 0、实际违规 0、stable 新退步 0；原 Boundary 各有 2 个 false allow，被候选修复。四个 W5/W6 提案仍 INCONCLUSIVE，不生成可执行 OTHER 或使用未收敛最高 posterior。合计 152 个实际探针、1,140 工具调用、CPU 58.38 秒；零模型调用/训练。

独立审计重新生成全部 validation 来源、重放实际返回值的 DSL/postcondition、重算 Belief support/proposal 与逐例门槛，已通过。该审计是保存回执的逻辑重放，不是重新调用业务工具；实际采集 provenance 由冻结控制器和原始文件索引绑定。Boundary 算术通过与 Agent 准入分开：尚未执行这批真实 Agent validation，所有 Agent admission/activation 为 0。

新代码 `boundary_lineage` 不修改冻结旧 study：

- 证据检测基线使用当前 effective Boundary，学习假设相对原始冻结规则绝对表达；当前父身份包含 program revision 与 Boundary revision，禁止跨轮混用。
- 重新计算有限支持上的 Bayes 收敛，OTHER/UNKNOWN/域不足/预算/不可区分均有显式弃权；H0 必须满足两个不同因子点的实际 challenge，重复来源不充数。
- BoundaryProposal 精确绑定冻结程序、当前父 Boundary、候选 bundle、公开支持、全部查询回执；业务 Boundary 不充当 refuse/escalate 终态标签。
- H0 在父规则已改变时表示恢复原规则，不被机械地当 no-op；拒绝或不确定候选不能成为下一轮父版本。
- 分层配对门保留 test 禁入、stable 退步与费用未知；持久父链必须经独立原始证据回放后才可隔离激活。当前成功激活路径仅 CPU engineering 夹具，不能冒充真实准入。

新增相关 8 项工程测试通过（lineage 6、private evaluator 2）；原 Runtime 5 项同时通过。模型 guard 与固定 main-v3 保持原状，更强模型仍未配置。

protocol `2533c132485a1648f39915ae522bdcfe47c683842d4b22bad442aa5f0353097a`；report `726c23edbcabfaa308bf35cbf079309130e250563d0bfbbb42cb77dc4e78551e`；audit `359078e3d58bef0602ba526810e5d0361fddbd633296c1de398ad474f4f00189`。

[原始结果](../results/skill-evolution/v1.2/development/p10-independent-boundary-dev-20261012/report.json)、[审计](../results/skill-evolution/v1.2/development/p10-independent-boundary-dev-20261012/independent-audit.json)。

剩余出口：变化规则真实模型成本/能力 smoke、完整独立 Agent 准入审计接线、统一 protocol 预检及冻结、至少三规则阶段正式 CPU/真实 Agent 双评测。开发 smoke 不作为正式数据；不按失败调整正式门槛。
