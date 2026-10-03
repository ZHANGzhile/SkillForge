# Active Self-Evolution v1 — 正式验证

协议：`de3eae4b913556249d5d761b636b88dac87038f833a22825f62c899f6c9de60e`。固定 main-v3 SFT；未进行 Continual QLoRA。

## 独立 CPU Benchmark

完整6 worlds × 5 paired seeds × 4 methods；每组最多20次交互。未收敛组的截断查询数计20。

| Method | 收敛率 | 截断平均收敛查询数 | 实际查询总数 | False allow | False block | Actual violation | Stable退步 |
|---|---:|---:|---:|---:|---:|---:|---:|
| active | 86.7% | 8.033 | 188 | 2 | 5 | 0 | 0 |
| no_adapt | 0.0% | 20.000 | 0 | 130 | 6 | 0 | 0 |
| passive | 0.0% | 20.000 | 600 | 130 | 6 | 0 | 0 |
| random | 3.3% | 20.000 | 588 | 123 | 6 | 0 | 0 |

联合主指标点估计门槛：True；held-out安全门槛：False；完整研究验收：False。
Active相对Random的RMQ下降：59.8%。配对bootstrap 95%区间：收敛率差[0.7, 0.9333333333333333]；RMQ差[-13.633333333333333, -10.066666666666666]。

收敛是有限假设空间内的在线指标。其错误收敛、未获准发布及held-out错误均保留，不能把收敛等同于正确规则。

## 连续 policy epoch

W3→W5、seed=1701。每个epoch重新学习，版本继承上一实际准入bundle；拒绝更新时保留原patch。

| Epoch | World | Method | 获准更新 | 新世界正确数（前→后 /80） | False allow | False block | Stable退步 |
|---|---|---|---|---:|---:|---:|---:|
| 1 | W3 | no_adapt | False | 77→77 | 3 | 0 | 0 |
| 1 | W3 | passive | False | 77→77 | 3 | 0 | 0 |
| 1 | W3 | random | False | 77→77 | 3 | 0 | 0 |
| 1 | W3 | active | True | 77→80 | 0 | 0 | 0 |
| 2 | W5 | no_adapt | False | 76→76 | 4 | 0 | 0 |
| 2 | W5 | passive | False | 76→76 | 4 | 0 | 0 |
| 2 | W5 | random | False | 76→76 | 4 | 0 | 0 |
| 2 | W5 | active | True | 75→80 | 0 | 0 | 0 |

## 固定权重真实 Agent 双评测

独立层只覆盖预声明W3/W5/W6、seed=101；每世界8个新世界及8个stable test，另做8个独立单动作Decision。连续层沿用两个epoch的独立数据。UNKNOWN Decision计错；EOC要求正确终态、状态与必要读回。

| Stage | Method | 实际bundle变化数 | New EOC 前→后 | Stable EOC 前→后 | Decision 前→后 | 尝试违规 前→后 | 实际违规 前→后 | Stable退步 |
|---|---|---:|---|---|---|---|---|---:|
| independent | no_adapt | 0 | 12/24→12/24 | 9/24→9/24 | 20/24→20/24 | 2→2 | 0→0 | 0 |
| independent | passive | 0 | 12/24→12/24 | 9/24→9/24 | 20/24→20/24 | 2→2 | 0→0 | 0 |
| independent | random | 0 | 12/24→12/24 | 9/24→9/24 | 20/24→20/24 | 2→2 | 0→0 | 0 |
| independent | active | 0 | 12/24→12/24 | 9/24→9/24 | 20/24→20/24 | 2→2 | 0→0 | 0 |
| epoch-1 | no_adapt | 0 | 2/8→2/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |
| epoch-1 | passive | 0 | 2/8→2/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |
| epoch-1 | random | 0 | 2/8→2/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |
| epoch-1 | active | 0 | 2/8→2/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |
| epoch-2 | no_adapt | 0 | 3/8→3/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |
| epoch-2 | passive | 0 | 3/8→3/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |
| epoch-2 | random | 0 | 3/8→3/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |
| epoch-2 | active | 0 | 3/8→3/8 | 5/8→5/8 | 7/8→7/8 | 1→1 | 0→0 | 0 |

Agent准入通过可以是同一bundle的对照通过；实际bundle变化数单独列出。表格评测的是准入后有效版本，被拒绝的proposal保存在activation及validation轨迹中，不替换为成功更新。

### 更新提案为何未激活（仅Validation）

| Stage | World | Method | EOC 前→提案 | Decision 前→提案 | 正常任务退步 | Agent准入 |
|---|---|---|---|---|---:|---|
| independent | W3 | active | 4→4 /12 | 7→8 /8 | 1 | False |
| independent | W5 | active | 2→2 /12 | 7→8 /8 | 1 | False |
| epoch-1 | W3 | active | 3→3 /12 | 7→8 /8 | 1 | False |
| epoch-2 | W5 | active | 6→3 /12 | 7→8 /8 | 3 | False |

四个Active更新提案的独立Decision validation均由7/8提高到8/8，但均引入正常任务退步；退步轨迹包括缺少写后读回验证和执行错误。Decision局部改善没有转化为可获准的完整Agent更新。这是Validation诊断，不是被拒绝proposal的held-out收益；正式test使用回退后的有效旧bundle。

### 配对测试成本

| Stage | Method | Full System tokens 前→后 | 工具调用 前→后 | Full System秒数 前→后 |
|---|---|---:|---:|---:|
| independent | no_adapt | 316400→316400 | 283→283 | 539.6→539.6 |
| independent | passive | 316400→316400 | 283→283 | 539.6→539.6 |
| independent | random | 316400→316400 | 283→283 | 539.6→539.6 |
| independent | active | 316400→316400 | 283→283 | 539.6→539.6 |
| epoch-1 | no_adapt | 75355→75355 | 79→79 | 132.1→132.1 |
| epoch-1 | passive | 75355→75355 | 79→79 | 132.1→132.1 |
| epoch-1 | random | 75355→75355 | 79→79 | 132.1→132.1 |
| epoch-1 | active | 75355→75355 | 79→79 | 132.1→132.1 |
| epoch-2 | no_adapt | 81540→81540 | 82→82 | 143.1→143.1 |
| epoch-2 | passive | 81540→81540 | 82→82 | 143.1→143.1 |
| epoch-2 | random | 81540→81540 | 82→82 | 143.1→143.1 |
| epoch-2 | active | 81540→81540 | 82→82 | 143.1→143.1 |

实际唯一执行300次；基础设施失败尝试0次；计费任务耗时0.688小时、1,335,942 tokens。
上表成本包含按同一任务配对复用的控制组，不能跨方法加总作为真实资源消耗。计费账本则按唯一执行计算，包括验证、独立Decision与失败尝试的最坏token预留；任务耗时不包含进程启动，成本计划另留600秒。

## 解释范围

人工声明的六世界、公开状态域与有限假设空间；模型层为代表场景子协议。Boundary证据来自固定程序探针，不能称为模型自主探索。模型测试使用固定SFT权重，终态规则未学习；安全guard仍由环境执行，零实际违规不等于零错误决策。报告不据结果新增种子、调门槛或选择性重跑；负结果与未更新版本完整保留。

本次完整调用实测（含模型进程启动和关闭）41.90分钟，时间和token均在12小时/20M限制内；见model-layer/invocations。
