# P4：只读程序治理与独立验证（2026-10-12）

后续已补版本目录/废弃/回滚快照和原始 Agent 证据适配，见 [最新 P4 状态](SKILL_EVOLUTION_P4_REGISTRY.md)。本页保留前批 r3 工程方法、原始结果和当时限制；真实零候选结果不变。

本批实现 P4 的去重、修订记录、独立程序验证和配对统计门。真实 P2 数据仍为六条成功轨迹、零有用 Opportunity、零候选；本批保留原目录，没有注册、激活或部署新 Skill。所有新增动态执行均为 CPU scripted 工程检查，不进入 learner。

## 去重与修订治理

`skillforge/skill_evolution/governance.py` 为历史 Catalog 增加不可变 sidecar，不修改既有 revision-v1 字节或检索行为。

- `semantic_fingerprint` 包含规范化后的程序、后置条件、Boundary、公开目标和固定 policy。Skill ID、描述、版本和私有证据不决定能力身份；按声明位置重命名输入不产生新能力。
- 相同规范化 DSL 标记 EXACT_DUPLICATE。重排读取、重复读取或支持目标不完全一致，仅按粗粒度效果签名标记 POTENTIAL_DUPLICATE，等待受控比较；有限样本行为相等不能证明一般语义等价。
- `revision_kind` 区分 metadata/program/boundary。metadata 不得改程序或 Boundary；program 必须改程序并保留 Boundary；第一阶段拒绝 boundary revision。父版本必须精确绑定、同 Skill、version +1；policy/目标变更需要独立协议。
- sidecar 保留 parent、supersedes、精确依赖和作用域。当前只读治理拒绝依赖组合，避免把尚未实现的 composition 当作可用能力。
- REJECTED/DEPRECATED/NEEDS_REFINEMENT 不能作为父版本；未验证草稿可用于开发，但不能进入正式父链。
- `RevisionMemory` 使用内容 hash 和前序 hash 的不可变编号记录。仅接受来源账本已拥有的 learn/dev 反馈，每个父版本最多两次尝试；拒绝正式 validation/test 反馈及重新贴标签的来源。拒绝/无收益的尝试同样保留。

生命周期记录 DISCOVERED、CANDIDATE、VERIFIED、REJECTED、INCONCLUSIVE、DEPRECATED。进入 VERIFIED 必须提供绑定精确目录版本的正式程序准入回执，并独立重放；工程回执不能越过门槛。当前没有 Agent 准入/激活执行入口，因此 ISOLATED_ACTIVE 被拒绝。程序通过不能自动改变工作台或服务。

## 独立程序验证

`skillforge/skill_evolution/validation.py` 先声明目标、案例、分区/实体所有权、候选与 validator 源码 hash，再运行静态检查和每例独立 SQLite 环境。

静态检查覆盖 schema、十二节点约束、唯一最终 finish、读取白名单、公开输入绑定、读取到断言的依赖、目标必需读取、身份 postconditions 及固定 policy。实例订单号、未观察 state、写操作、提前 finish、缺少目标证据或未经声明的 Boundary 均被阻止。

动态验证使用独立 workflow EOC 核对真实工具回执；另比较完整数据库 dump 的前后 hash、未完成验证义务、错误和副作用。程序的 postconditions 和“工具没有报错”都不替代 EOC。审计会重新执行程序，忽略不可重放的工具 latency，核对其余证据和汇总；重新计算伪造 artifact hash 仍不能通过。

| 工程案例 | 数量 | 预声明行为 | 本批结果 |
|---|---:|---|---|
| Positive（含一个 stable） | 2 | 收集完整事实 | 2 完成 |
| Boundary：HIGH/SHIPPED、CANCELLED/DELIVERED | 2 | 继续授权读取 | 2 完成 |
| Negative：错误顾客、对象不存在 | 2 | 环境拒绝、无事实泄漏/副作用 | 2 安全拒绝 |
| Fault：读取 timeout、读取 response_lost | 2 | 安全退出、无写入和 pending | 2 安全退出 |

八例均符合预期，其中只有四例完成业务目标。两例预期拒绝和两例故障退出不计成 EOC 成功。错误顾客探针保留一个原始 `attempted_policy_violation`，明确属于预先注入的工程拒绝检查；没有把它抹掉或算作真实模型动作。

formal API 要求候选绑定 train 来源、validation/stable_validation 所有权、至少六个来源组、四类案例与 stable 覆盖；所有预声明行为和硬安全约束均需通过。工程模式始终不能 ADMITTED。本批程序回执为 INCONCLUSIVE，`program_admitted=false`。formal API 尚无真实候选实测，不能据此称正式准入完成。

这里只覆盖直线只读程序。读取响应丢失不会造成写提交未知，不能用本批结果宣称新增了 mutation reconciliation、工单验证或任意程序恢复能力。

## 配对统计门

`skillforge/skill_evolution/admission.py` 的 protocol-v2 在结果之前固定任务/初始状态/source_group、两个目录、共同执行身份、预算、主指标和门槛。

当前开发默认门槛：至少六个 primary validation 来源组、存在 stable 验证、零逐例 EOC 回退、零候选违规、成本已结算、所有预声明配对齐全；按来源组内平均增益计算 wins/losses/ties，一侧 exact sign test 的 alpha ≤0.05。正式 P5 还需成本 smoke 后单独冻结，不能把这些开发默认值当作已冻结正式研究协议。

同一来源组的 100 个任务仍计一个独立单元。stable_validation 只参与保持/安全门槛，不增加 primary 统计样本。成本主指标仅对双方 EOC 都成功的任务记正负成本差；双方失败不能通过更早停止获得正收益，其预声明单元仍保留在分母。所有原始成本保留在输入记录中。

六个独立组均节省一次决策的合成算术检查得到 p=1/64，通过统计门；单组增加到 100 个任务仍 INCONCLUSIVE。稳定退步、违规立即 REJECTED；缺少配对或成本未知则 INCONCLUSIVE；任务、初态、来源、后端、目录或预算不匹配会拒绝输入。

统计门返回 `STATISTICAL_GATE_PASSED`，同时保留 `agent_admitted=false`。它目前消费已计数的配对记录，还没有接入真实 Agent 的 messages/checkpoint/模型费用审计；合成检查不构成 Agent 成功率提升、显著性或研究收益。

## 本批结果与证据

[最终工程报告](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/report.json)、[不可变验证协议](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/protocol.json)、[程序验证](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/program-validation.json)、[程序准入回执](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/program-admission.json)、[独立审计](../results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/evidence-audits/954f75226dace9a479693059c21241492a1ac7738517c9a5625408dc12aded2f.json)。

本批最终工程运行执行 19 次验证工具调用、19 次准入重放调用；独立事后审计另重放 19 次，合计 57 次 scripted CPU 调用。之前两个工程版本保留：首版没有完整快照/审计入口，r2 补齐归档，r3 补上“双方成功才计成本收益”的 protocol-v2。前两版的业务案例结果没有变化，不能用旧版统计门支持未通过新版约束的结论。

所有模型调用/tokens 增量为 0，未启动 GPU。真实模型累计仍是 **537,296 tokens / 1,904.82 秒采集运行墙钟**；CPU 工程/测试耗时另计，不冒充 GPU 小时。保留的真实目录 hash 为 `d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa`，真实候选、program/Agent admission、隔离激活和部署均为 0。

最终独立源码副本回归 **390 passed / 1 skipped / 2 upstream warnings**，P4 定向测试 30 项通过。正式 A/B 的 86/100 个冻结源码、历史文件保护及固定 main-v3 adapter 核验通过。[最终预检](../results/skill-evolution/v1.2/development/preflight-20261012-P4-final-r2/preflight.json)。

## 重放与后续

```powershell
.venv/Scripts/python.exe -m scripts.verify_skill_evolution_p4 --compiler-run results/skill-evolution/v1.2/development/p3-trace-screen-20261012 --output <fresh-engineering-output>
.venv/Scripts/python.exe -m scripts.verify_skill_evolution_p4 --run results/skill-evolution/v1.2/development/p4-engineering-20261012-r3
.venv/Scripts/python.exe -m pytest tests/test_skill_evolution_governance.py -q
```

首条只运行 scripted 工程夹具，会登记新的 dev 工程来源，不采集 learn 或启动模型。审计拒绝与注册不符的 validator 源码；旧版须使用其归档版本。单控制器不可变编号日志不声称支持多写者事务。

下一步补齐正式版本化注册/废弃/回滚目录快照与真实 Agent 证据接入，再做 P5 同后端 A/B/C 成本 smoke 和三轮 protocol 冻结。P3 的返回值依赖/写入读回 assert、组合与 RevisionPlanner 仍有限制。本批没有合格真实候选，正式候选准入必须等待满足原门槛的新证据；不降低筛选门槛来填满演化轮次。
