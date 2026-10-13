# P6：公开交互触发器工程验证

触发器只读可信适配器导出的 EvidenceView 和实际查询来源；不读取 world、policy epoch、新规则、EOC 或终态 gold。既有 gap_detection 的 boundary 通道继续使用，epoch 规范化为 public-stream，不参与触发聚类。

开发策略为 60 个交互的滑动窗口、至少 3 个独立 source group 且不同对象的同模式冲突，探索上限 20 查询。二部匹配避免别名/重试和来源顺序夸大独立性。parent_revision 改变后证据不混用。重复 UNKNOWN 仅在父边界和 Guard 均明确允许时产生不确定性怀疑；不提供 Bayes 负标签。

超时/提交未知、权限拒绝、参数错误、程序失败、漏验证、终止错误、业务拒绝分开。Gate 阻止且未执行时保持 unknown，不能叫 false block；HIGH 等不可变 Guard 异常只要求暂停相关能力，禁止学习 relaxation。当前模块输出暂停指令，尚未接入正式 Agent 服务执行暂停。

实际成功标签要求同对象、同 mutation/request_id、postcondition、后续公开 read-back 与不可变 VerificationReceipt 一致；只有看到一次 get_payment 不够。适配器从 pinned raw/task membership 提取公共读值，mutation 后的值不当作适用性条件；private snapshot/gold/expected/EOC 不导出。Hash 保证已声明来源身份，不代替可信采集者或操作系统隔离。

触发与探索分离；SUSPECTED_DRIFT 本身不更新 Belief、不发工具、不激活。进入授权探索后每次真实回执都计费；UNKNOWN/故障同样消耗预算但不给可执行性标签。完整 observe/begin/probe action journal 可逐步恢复重放，防止恢复时丢探针费用。

## 受控真实工具流

结果 `p6-controlled-tools-20261012-r2`：11 个隔离 SQLite 交互、56 次实际工具调用、11 次 checkpoint 重放；模型调用/tokens 均 0。

| 阶段 | 结果 |
|---|---|
| no-change 3 条 | 全部 NO_CHANGE，0 次触发 |
| fault-only 3 条 | 全部 INFRASTRUCTURE，0 次触发 |
| changed 3 独立来源 | INCONCLUSIVE → INCONCLUSIVE → SUSPECTED_DRIFT |
| 探索 2 条 | 两次均计费，业务拒绝 1 条可学；超时 1 条不可学 |

独立审计重算公开投影、成员/来源、逐状态与预算，已通过；没有新工具/模型调用。该批是程序化受控工具流，真实 SQLite 回执不等于真实 Agent 日常交互，不能报告正式 precision/recall 或自主适应率。私有变化/故障日程只在 evaluator 与子进程中，未发给触发器。

P6 触发/回执定向 19 项、P7 历史 3 项、公开 acquisition 4 项、learner/进程访问 guard 2 项，共 28 项定向测试通过；不冒充第一阶段 445 项源码预检。

[受控结果](../results/skill-evolution/v1.2/development/p6-controlled-tools-20261012-r2/report.json)、[独立审计](../results/skill-evolution/v1.2/development/p6-controlled-tools-20261012-r2/independent-audit.json)。

第一阶段冻结源文件、程序和权重不变。第二阶段真实模型日常流、统一版本化 Boundary Runtime、独立准入和连续三阶段研究仍需后续验证。未启动训练、激活或部署。
