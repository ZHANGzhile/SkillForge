# 隔离实验协议

## 数据与授权边界

保留旧 24 任务 smoke suite。experiment-v1 使用 6 个任务族、3 个分区、A–E 分层，每个场景默认 3 个动态实例。模板 ID 为模板文本哈希；检查的是内容，而非人为命名的 split 标签。Level A 允许相同任务族和状态类别，Level C 的三分支结构仅用于 test。模板隔离不等于已证明语义泛化。

生成固定 seed 得到相同 JSONL 和 manifest。非空目录不能被另一数据配置覆盖。读取时检查 manifest 哈希、文件哈希、任务 ID、实例、订单、请求文本、模板内容及组合结构约束。

训练任务没有 test 的 Expected Outcome、fixture 或 oracle 混入模型上下文。Task 的 task_hash、level、dataset_id 和实例元数据只进入离线记录；工作流语义及用户提供的参数属于可见任务输入。

## 顺序

1. dataset：写入 train/validation/test 与 manifest。
2. collect：仅训练分区执行；真实模型先做一次接口预检，连接失败即停。
3. prepare：审核源轨迹与 manifest 的绑定及 verdict 一致性；CLI 默认生成地址/取消/退款三个 Skill 族，可指定子集。
4. Naive Skill 从成功轨迹单独生成并保存，不使用失败或 validation 结果；主方法使用成功＋业务失败＋policy。
5. 在 validation 验证主方法候选；必要时最多两轮领域修订，完整保留逐版历史。保存候选、已通过集合、验证报告和训练记忆快照；冻结包整体哈希。
6. compare：冻结后才运行 test，所有系统同任务同模型同 Runtime 配置；B0/B1/B2/B3 和可选 B3-no-gate。

若所有主方法 Skill 未通过 validation，B3 保留 primitive fallback，不能偷偷只为 B2 保留同样通过的候选。未提供足够真实失败轨迹时，编译失败，不自动伪造真实模型失败。

## 验证的含义

Skill validation 测试 admission、safe rejection 和执行后置条件。读取失败时安全退出不代表已经完成端到端 escalation；任务层是否创建工单，由 Full System 的 Expected Outcome Contract 判定。两者分别报告。

Decision-level 在固定授权读取后提供候选，不由 Gate 屏蔽错误候选。权限不足案例及 D 类故障案例显式跳过并计数；故障恢复属于 Full System。当前覆盖地址/取消/退款的 Skill、refusal、escalation 选择，不声称覆盖所有工具规划。

## 有界修订

只支持已实现领域中的边界段（preconditions/forbidden_conditions）及执行段（inputs/procedure/postconditions）修订。规则来自相同 train 证据和 policy 的 canonical compiler；validation 失败定位修订段。不会根据 test 调整，不会用持续工具故障学习新的禁止业务条件，不会调用另一个 Agent。

每次版本加一，最多三次验证（初次＋两次修订）。修订不足或不适用于故障时最终 REJECTED。该功能是可审计的有限领域修复，不代表开放域自动程序发现。

## 重试与幂等

Gate 补查异常必须通过 gate_observations 进入模型上下文；耗尽后的同逻辑调用不能靠更换 step ID 重置预算。相同任务、相同 mutation payload 使用同一幂等 operation key，包含 Skill fallback 与 primitive 重试。当前业务任务只授权同 payload 的一次变更；将来若支持同任务多次相同退款，需要明确独立授权操作标识。

## 报告与复现

记录 dataset_hash、bundle_hash、源代码哈希、Git commit（无提交时 null）、Runtime 配置、任务 seed 和 Skill 内容。每个任务完成即追加 JSONL，避免中断后只剩最终汇总。

报告包括 comparison.csv、comparison.json、A–E 分层、错误明细和完整 trace。repeats 使用完全相同初始任务重新运行；pass_all_repeats 是同任务所有重复均成功的比例。它不是 pass@k，也不提供显著性结论。因果 NTR 没有反事实干预证据时保持 null。

来源校验检查 manifest 绑定与确定性 verdict 一致性，不是模型来源的密码学证明。真实服务模型版本固定、日志保全及独立测试封存仍是研究复现责任。
