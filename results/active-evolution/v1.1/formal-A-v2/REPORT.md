# Execution-Aware Self-Evolution v1.1-A 正式结果

协议：`c565643a4e87d9b71d1875778ab71c0a6a9956d1b6b3b7adeb421a2064c93fcc`。固定 main-v3、原 Active 获取策略；Acquisition v2 不进入本实验。

9 个独立 world-seed（W3/W5/W6 各 3 个 seed）；另有两个连续 epoch，后者不并入主要统计样本。

## 固定分母漏斗

| Runtime | Planned | Belief | Boundary | Agent | Activated | Deployed |
|---|---:|---:|---:|---:|---:|---:|
| old | 9 | 5 | 5 | 0 | 0 | 0 |
| new | 9 | 5 | 5 | 3 | 3 | 0 |

Activated 仅为隔离评估中的 Bundle 生效。拒绝更新保留实际父 Bundle；不代表已部署。

## 预注册 factorial 效应

效应单位为 EOC 比例差；bootstrap 按世界分层重采样配对 seed，不把任务视为独立重复。每世界仅 3 个 seed，区间精度有限。

| Bundle 口径 | Estimand | 点估计 | 95% 配对区间 |
|---|---|---:|---|
| candidate | bundle_effect_under_new_runtime | 0.0417 | [0.0139, 0.0694] |
| candidate | interaction | 0.1111 | [0.0694, 0.1528] |
| candidate | runtime_effect | 0.2639 | [0.2222, 0.3056] |
| effective | bundle_effect_under_new_runtime | 0.0417 | [0.0139, 0.0694] |
| effective | interaction | 0.0417 | [0.0139, 0.0694] |
| effective | runtime_effect | 0.2639 | [0.2222, 0.3056] |

candidate 为隔离候选诊断；effective 为 Runtime 各自准入后的有效 Bundle。test 不会追溯改变 validation 准入。

## Runtime 贡献（同一旧 Bundle）

| World / seed | N | autonomous EOC | assisted EOC | 干预任务 | 救援 | 强制读回 | 自动终止 |
|---|---:|---:|---:|---:|---:|---:|---:|
| W3/12811068 | 16 | 4 | 10 | 11 | 6 | 10 | 10 |
| W3/29835885 | 16 | 3 | 10 | 11 | 6 | 10 | 10 |
| W3/84113846 | 16 | 4 | 10 | 11 | 6 | 10 | 10 |
| W5/12811068 | 16 | 3 | 10 | 11 | 6 | 10 | 10 |
| W5/29835885 | 16 | 3 | 10 | 11 | 7 | 10 | 10 |
| W5/84113846 | 16 | 2 | 9 | 10 | 3 | 9 | 9 |
| W6/12811068 | 16 | 4 | 7 | 8 | 3 | 7 | 7 |
| W6/29835885 | 16 | 2 | 7 | 7 | 3 | 7 | 7 |
| W6/84113846 | 16 | 4 | 7 | 7 | 4 | 7 | 7 |

自主与辅助成功互斥；上述配对包括变化与 stable test。救援属于系统执行契约的贡献，不能解释为模型权重学习。

## 新 Runtime 下更新 Bundle 的逐臂归因

以下为变化test的描述性计数，各单元单列。candidate是CPU准入后的候选；effective按Agent准入回退。完整旧/新Runtime、变化/stable分区见`execution-attribution.json`，不新增主estimand。

| World / seed | 口径 | Bundle | N | EOC | autonomous | assisted | 有干预任务 |
|---|---|---|---:|---:|---:|---:|---:|
| W3/12811068 | candidate | old | 8 | 7 | 1 | 6 | 7 |
| W3/12811068 | candidate | proposal | 8 | 8 | 2 | 6 | 6 |
| W3/12811068 | effective | old | 8 | 7 | 1 | 6 | 7 |
| W3/12811068 | effective | proposal | 8 | 8 | 2 | 6 | 6 |
| W3/29835885 | candidate | old | 8 | 7 | 1 | 6 | 7 |
| W3/29835885 | candidate | proposal | 8 | 8 | 2 | 6 | 6 |
| W3/29835885 | effective | old | 8 | 7 | 1 | 6 | 7 |
| W3/29835885 | effective | proposal | 8 | 7 | 1 | 6 | 7 |
| W3/84113846 | candidate | old | 8 | 7 | 1 | 6 | 7 |
| W3/84113846 | candidate | proposal | 8 | 8 | 2 | 6 | 6 |
| W3/84113846 | effective | old | 8 | 7 | 1 | 6 | 7 |
| W3/84113846 | effective | proposal | 8 | 8 | 2 | 6 | 6 |
| W5/12811068 | candidate | old | 8 | 6 | 0 | 6 | 7 |
| W5/12811068 | candidate | proposal | 8 | 7 | 1 | 6 | 6 |
| W5/12811068 | effective | old | 8 | 6 | 0 | 6 | 7 |
| W5/12811068 | effective | proposal | 8 | 7 | 1 | 6 | 6 |
| W5/29835885 | candidate | old | 8 | 7 | 1 | 6 | 7 |
| W5/29835885 | candidate | proposal | 8 | 7 | 1 | 6 | 7 |
| W5/29835885 | effective | old | 8 | 7 | 1 | 6 | 7 |
| W5/29835885 | effective | proposal | 8 | 7 | 1 | 6 | 7 |
| W5/84113846 | candidate | old | 8 | 5 | 0 | 5 | 6 |
| W5/84113846 | candidate | proposal | 8 | 5 | 0 | 5 | 6 |
| W5/84113846 | effective | old | 8 | 5 | 0 | 5 | 6 |
| W5/84113846 | effective | proposal | 8 | 5 | 0 | 5 | 6 |
| W6/12811068 | candidate | old | 8 | 5 | 2 | 3 | 3 |
| W6/12811068 | candidate | proposal | 8 | 4 | 1 | 3 | 3 |
| W6/12811068 | effective | old | 8 | 5 | 2 | 3 | 3 |
| W6/12811068 | effective | proposal | 8 | 5 | 2 | 3 | 3 |
| W6/29835885 | candidate | old | 8 | 4 | 1 | 3 | 3 |
| W6/29835885 | candidate | proposal | 8 | 4 | 1 | 3 | 3 |
| W6/29835885 | effective | old | 8 | 4 | 1 | 3 | 3 |
| W6/29835885 | effective | proposal | 8 | 4 | 1 | 3 | 3 |
| W6/84113846 | candidate | old | 8 | 5 | 2 | 3 | 3 |
| W6/84113846 | candidate | proposal | 8 | 5 | 2 | 3 | 3 |
| W6/84113846 | effective | old | 8 | 5 | 2 | 3 | 3 |
| W6/84113846 | effective | proposal | 8 | 5 | 2 | 3 | 3 |

## 有效 Bundle：Decision / Safety / Cost

| World / seed | Runtime | 新世界 EOC 前→后 | Decision 正确 前→后 | FA / FB / UNKNOWN 后 | 实际违规 | stable 退步 | Tokens 前→后 |
|---|---|---|---|---|---:|---:|---|
| W3/12811068 | new | 0.875→1.000 | 7→8 / 8 | 0 / 0 / 0 | 0 | 0 | 44954→43613 |
| W3/12811068 | old | 0.500→0.500 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 90420→90420 |
| W3/29835885 | new | 0.875→0.875 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 45043→45043 |
| W3/29835885 | old | 0.500→0.500 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 96744→96744 |
| W3/84113846 | new | 0.875→1.000 | 7→8 / 8 | 0 / 0 / 0 | 0 | 0 | 44954→43613 |
| W3/84113846 | old | 0.500→0.500 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 87441→87441 |
| W5/12811068 | new | 0.750→0.875 | 7→8 / 8 | 0 / 0 / 0 | 0 | 0 | 44957→43550 |
| W5/12811068 | old | 0.500→0.500 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 90316→90316 |
| W5/29835885 | new | 0.875→0.875 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 44996→44996 |
| W5/29835885 | old | 0.500→0.500 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 84621→84621 |
| W5/84113846 | new | 0.625→0.625 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 85718→85718 |
| W5/84113846 | old | 0.500→0.500 | 7→7 / 8 | 1 / 0 / 0 | 0 | 0 | 112934→112934 |
| W6/12811068 | new | 0.625→0.625 | 6→6 / 8 | 0 / 0 / 2 | 0 | 0 | 104432→104432 |
| W6/12811068 | old | 0.375→0.375 | 6→6 / 8 | 0 / 0 / 2 | 0 | 0 | 146925→146925 |
| W6/29835885 | new | 0.500→0.500 | 6→6 / 8 | 0 / 0 / 2 | 0 | 0 | 93359→93359 |
| W6/29835885 | old | 0.375→0.375 | 5→5 / 8 | 1 / 0 / 2 | 0 | 0 | 138815→138815 |
| W6/84113846 | new | 0.625→0.625 | 6→6 / 8 | 0 / 0 / 2 | 0 | 0 | 86138→86138 |
| W6/84113846 | old | 0.500→0.500 | 6→6 / 8 | 0 / 0 / 2 | 0 | 0 | 122012→122012 |

Decision 为独立首动作探针；UNKNOWN 单列，不能当作正确阻断。Tokens 为完整 test 的逻辑比较成本，跨臂缓存复用不重复计入实际资源账本。

## 连续 epoch 与实际 Agent 父链

| Epoch | World | CPU 更新 | Runtime | Agent 更新 | EOC 前→后 | stable 退步 | 实际违规 |
|---:|---|---|---|---|---|---:|---:|
| 1 | W3 | True | new | True | 0.875→1.000 | 0 | 0 |
| 1 | W3 | True | old | False | 0.500→0.500 | 0 | 0 |
| 2 | W5 | True | new | True | 0.750→0.875 | 1 | 0 |
| 2 | W5 | True | old | False | 0.375→0.375 | 0 | 0 |

CPU 与每种 Runtime 的实际 Agent lineage 分开；被拒绝的提案不成为下一 epoch 的 Agent 父版本。

## 审计与资源

独立审计通过 1608 条实际模型执行与 293 份 VerificationReceipt。
v1.1 开发及正式累计计费 7,739,014 tokens、13.733 小时（含失败预留与调用启动/关闭）。
基础设施失败 2 次，失败 token 保守预留 524,288。
结论限于已声明的规则世界和有限代表场景；权重保持不变，未执行 Continual SFT。

## 睡眠中断与协议修正披露

本轮在原冻结墙钟预算下中断，后依据 Windows 系统电源日志进行基础设施计时修正后续跑。原记录完整保留，不能声称满足未经修正的原墙钟预算。
修正记录：`1a80e1c34e16fe0e5383bb310c8c269695a7f27214cb32447dff3fd5bbaf67b5`。原始墙钟 13.733 小时；证实睡眠扣除 9.339 小时；修正后 4.394 / 12 小时。
扣除范围仅为日志证实的睡眠区间，并保留 60 秒过渡余量；这不是 GPU 利用率测量。失败 token 预留、重试限制、模型、数据、准入和统计规则未修改。
