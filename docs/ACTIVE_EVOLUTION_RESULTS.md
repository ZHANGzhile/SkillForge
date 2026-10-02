# Active Self-Evolution v1：开发验证记录

更新日期：2026-10-02。**正式四组研究尚未运行，本页不是正式Active Learning结果报告。**

## 工程纵向闭环

目录：`results/active-evolution/v1/development/vertical-slice-v1/`。

声明范围：单个W1工程世界、公开risk/shipment有限字段、固定程序probe；控制器自主选择候选，未用真实模型生成探针。

| 项目 | 结果 |
|---|---:|
| Seed证据 | 2 |
| 主动探索查询 | 8 |
| Validation | 12（6可执行、6不可执行） |
| False allow / false block | 0 / 0 |
| Stable validation退步 | 0 / 6 |
| 实际违规 | 0 |
| 发布后新实例 | PROCESSING被拦截；NOT_STARTED退款及验证成功 |

最终规则为`shipment.status not_in [NOT_STARTED, SHIPPED, DELIVERED]`，在声明的四状态域内等价于`shipment.status == PROCESSING`禁止退款。它不是域外等价证明。

结构化等价类posterior为0.979920，OTHER为0.011174，等价类熵0.115164 nat；这些数值只适用于人工声明的有限观测模型，不是校准过的真实规则置信度。

候选写入独立实验Registry，版本`98b47f4d2ef7dd63a65169f201ac0386be67898ad640cb90bcfc0125e1b84bfe`。未修改主部署。接受/拒绝/恢复/篡改拒绝路径有测试，恢复命令已实跑并复用既有证据。

## 真实模型开发成本

目录：`results/active-evolution/v1/development/cost-smoke-v1/`。固定main-v3 SFT，六条旧策略独立开发任务，未读取正式test。

| 指标 | 测量 |
|---|---:|
| 平均完整任务耗时 | 23.85秒 |
| 小样本P95耗时 | 42.38秒 |
| 平均tokens | 12,812 |
| 平均LLM调用 | 5.17 |
| 平均工具调用 | 4.50 |

仅用于预先控制成本；n=6不能保证正式任务耗时分布。未据此选择效果较好的方法、种子或世界。W3/W5/W6模型子集按数值组合、类别组合、边界放宽三个类型事前选择。

## 回归与历史保护

独立源码回归175 passed、1 skipped；历史10,699文件SHA验证全部一致。测试回执在development/active-source-check-95b85a78a057455d854aa8d2aceacb69/。

没有新的Active/Random效率比较、正式EOC成绩或持续学习收益可报告。联合主指标、安全与Retention门槛保持预声明，正式结果出现前不填补缺失表格。

## 2026-10-02：隔离四方法开发协议

最新目录：`development/protocol-v5/`。开发seed=701，每世界6个seed、12个explore、8个validation和8个stable_validation；学习预算4次。test只生成，未评分。此小型协议的探索/验证不覆盖完整公开状态组合，不能用于正式质量结论。

| 世界 | No Adaptation | Passive | Random | Active |
|---|---|---|---|---|
| W3 | UNCHANGED / 0查询 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 |
| W6 | UNCHANGED / 0查询 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 | INCONCLUSIVE / 4 |

8组恢复重跑全部通过，104条探针记录的内容和mtime均不变，回执为`analysis/resume.json`。代码改变后不可直接用新代码恢复；本次源码存于`source/`。

三档观测似然0.90/0.95/0.99只读重算保存在`analysis/sensitivity-*.json`。W3 Active四步的最高评分候选一致；W6 Active在0.90/0.95下有一步排序改变。所有三档最终均未收敛。这是固定历史上的重加权，未执行反事实路径，不能据此报告其成绩。Passive/Random的“是否与最高评分一致”仅是排序诊断，不能作为其是否按协议选样的判断。

No Adaptation的两组stable_validation各8条均保留原边界正确性，退步0/8。这仅验证配对统计接线，不是更新后的能力保留收益，更不是连续学习结果。

### 保留的问题记录与修正

- protocol-v2因Windows SQLite审计事件中的bytes路径解析失败；修复后新目录运行，失败目录保留。
- protocol-v3的全量posterior快照重复保存假设和历史，W3四组约426MB。增量日志格式保存一次初始状态、后续证据与哈希；同规模protocol-v4约43.7MB，减少约89.7%，支持复算恢复。
- protocol-v4的W6 Active曾在1次查询后通过开发验证，但候选实际为H0；8条验证未覆盖新放宽状态。**该记录不是适应成功**。已禁止把H0发布成新版本，并加入公开组合覆盖及准入时的变化机会检查。历史记录和当时源码均保留。
- dataset-v2的公开组合不按新世界真值选择：W1–W5共享退款组合，W6使用地址组合；CPU 80条探索/40条验证覆盖所声明组合。小规模split明确标记partial，不能凭运行通过消除覆盖缺口。

### 数据与正式门槛

`preparation/dataset-v2/`共30个数据包、10,032条任务，formal_experiment_frozen=false。模型层W3/W5/W6的model_validation和model_test共6个split未满足公开组合覆盖；详见`readiness.json`。旧模型成本草案与该缺口必须一起修订，尚未开始正式CPU或GPU评分。

第二批独立源码回归为186 passed、1 skipped，回执`development/active-source-check-79529c84a78e4c00800524e380e62d6d/report.json`；10,699个历史文件SHA一致。随后原子发布故障/并发测试及进程协议定向回归11项通过；最终独立完整回归为188 passed、1 skipped，回执`development/active-source-check-b34bd01095e24f00b4b8a1de27d69769/report.json`，历史SHA再次全部一致。

## 2026-10-02：全覆盖开发验收与冻结程序执行

`development/coverage-smoke-v1/`使用独立开发seed=701、12条seed、80条explore、40条validation、40条stable_validation、20次查询预算。未读取或评分正式test。

| 世界 | No Adaptation | Passive | Random | Active |
|---|---|---|---|---|
| W3 | UNCHANGED / 0 | INCONCLUSIVE / 20 | INCONCLUSIVE / 20 | VERIFIED / 7 |
| W6 | UNCHANGED / 0 | INCONCLUSIVE / 20 | INCONCLUSIVE / 20 | INCONCLUSIVE / 6 |

W6 Active因连续预期信息增益不足停止，等价类posterior约0.773、熵约0.643，不满足收敛阈值。其截断查询指标应计20，不能把实际6次花费算成更快成功。未因此调整学习阈值、预算或删除负结果。

W3候选为风险属于MEDIUM/HIGH且金额>3000时收紧；HIGH已被不变安全底线拒绝，因此在声明域内等价于新增MEDIUM且金额>3000限制。Validation 23个正例、17个负例，false allow/false block均0，stable_validation退步0/40，实际违规0。一个开发种子的结果不支持正式效率或显著性结论。

随后探针接入冻结父Skill的真实DSL，使用原程序、输入绑定与后置条件，单独写入`development/dsl-smoke-v1/`。W3 Active再次7次查询通过同规模验证。此轮只重复W3 Active用于检查DSL接线，不是重新选择有利方法的正式对比。

从该Registry加载候选后，在seed=9751的4个全新开发实例上实执行：MEDIUM/3001与HIGH/3001被Skill gate拦截且无退款调用；MEDIUM/3000和LOW/3001完成真实退款及读回校验。四例实际违规均0。记录见`post-publication/`。Skill不适用没有被自动转换为refuse/escalate监督标签。

同代码/配置恢复重跑通过，99条探针内容及mtime未变化，回执`post-publication/resume.json`；对应26份源码保存在`source/`。

模型层改为独立代表场景设计：退款世界共享8个分层点（风险、shipment组合与3000/3001边界对照），地址世界8个分层点（低/中/高风险、PROCESSING、已发货、订单状态、无效地址），另有4个稳定锚点。它不声称覆盖CPU的全部38/17种组合；结论范围需限定于该预声明子协议。

`preparation/dataset-v3/`共30组、10,044条任务，在各自声明的CPU/模型层覆盖范围内完整。model_validation从4增至8，其余model splits数量不变；模型清单872次基础任务+88次全局重试预留，旧smoke外推约11.30小时/1,230万tokens。新世界Runtime尚未实测，正式入口仍关闭，不能把旧耗时外推当成最终成本准入。

最新独立源码完整回归 **191 passed、1 skipped**，回执`development/active-source-check-573ee7e7cbd446ec8eb1ac81802e64fa/report.json`；10,699个历史文件SHA全部一致。工作台与原Student已恢复，adapter身份与原部署一致；原部署配置和旧签收记录未重写。
