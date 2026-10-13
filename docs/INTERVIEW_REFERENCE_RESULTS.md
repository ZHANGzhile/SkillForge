# 引用接口后续结果：正确 ID 不等于正确参数绑定

2026-10-13。按照原 Sprint 继续验证，保留 [原零收益报告](INTERVIEW_SPRINT_RESULTS.md) 和全部冻结证据。本轮完成三个全新 dev 来源的六个真实配对臂；**metadata 变体未通过 dev 门，后续共用新提示、正式 validation/held-out 未启动，未激活。**

## 变化与保持

原 Skill 由六条真实训练轨迹编译，本轮只有一个 metadata 修订：展示名称改为原精确 skill_id，版本从 1 升为 2，并绑定原 VERIFIED 父 revision。procedure、inputs、postconditions、安全规则及边界完全不变，治理记录为 metadata_revision，程序/边界语义指纹相等。不是第二个新程序，不伪造 v2 编译来源。

旧/新名称两臂使用同一固定 main-v3、原系统提示、原严格 Runtime/DSL/Guard、同一任务和初态，都预加载各自精确版本。独立 EOC 完整核验五类真实证据和无副作用。三个新来源为 instance、paraphrase、boundary，各源两臂，未复用原 validation/test。

比较前，新 metadata 版本已通过八个预声明 CPU 沙箱（Positive/Boundary/Negative/Fault 各二），31 个实际工具尝试，独立重放 31 次。程序准入由与已验证真实父程序的等价关系继承；CPU 检查不当作模型复用。

## 真实配对数据

| 条件 | 完整/自主 EOC | 模型决策 | tokens | 业务工具尝试 | search/load | Skill 动作尝试/成功 |
|---|---:|---:|---:|---:|---:|---:|
| OldName：原展示名称 | 3/3 | 30 | 146,390 | 15 | 3/3 | 6/0 |
| ExactName：名称等于执行 ID | 3/3 | 22 | 74,332 | 16 | 0/0 | 3/0 |

逐例决策为 OldName 10/10/10，ExactName 7/8/7，差值为 −3/−2/−3；这是**减少错误引用后的回退开销**，不是成功执行 Skill 的收益。两组全部靠 primitive 完成。新名称一例重复读取了商品列表，工具总量由 15 增至 16。

旧名称六次 `skill_not_loaded`；精确名称三次都复制了正确 ID，但遗漏全部输入：

```json
{"type":"skill","name":"trace_dae7a91522975618","arguments":{}}
```

当时公共上下文已含 `parameters.order_id`，加载结果也明确列出 `inputs=["order_id"]`。Runtime 正确返回 `skill_input_binding_mismatch`，没有自动补参，也没有实际进入 Skill。错误不是工具环境或候选程序缺少 order_id。三个配对均无 actual violation、无非法写入尝试、无 Runtime intervention，EOC 仍来自模型选择的 primitive 回退。

## 准入与停止原因

预声明 dev 门要求三例均真实成功执行 Skill、EOC 成功、至少节省一次决策且安全。调用次数下降只满足其中一项，**正确 Skill 执行 0/3，故 dev_gate_passed=false**。RevisionMemory 保存失败，不把 metadata 对齐的局部改善提升为 Agent Admission。

因此没有运行已实现的共用新检索提示，没有启动后续三组正式矩阵，没有使用为其保留的 validation/held-out 来源，没有改 Opportunity 阈值、Agent 门或参数绑定规则。原失败结论不回填，不再添加本协议未声明的新变体。

本轮进一步区分出三个执行环节：原提示下未主动搜索；展示名称混淆可由 metadata 对齐缓解；随后仍存在动态参数绑定失败。**模型能复制 ID，并不表示能正确形成一个可执行动作。** 这仍不能证明固定权重无法通过其他接口复用程序，也不能宣称闭环增量收益已成立。

## 审计、成本和范围

六个真实臂、224 个 checkpoint 独立审计通过，包含真实父轨迹重新编译、metadata 等价、全部原始模型输出、SQLite 初始/逐 checkpoint/最终状态、来源隔离和费用。Agent Admission=false，activation=false。统计单位仅三个 dev 来源，不宣称显著性。

新增 **220,722 tokens / 52 次模型决策**；与原 Sprint 合计 **1,263,669 tokens / 422 次决策 / 75 个真实运行臂**，仍在原累计 4M tokens 与七小时截止内，没有预算重置。GPU 利用小时未测量。新增业务工具尝试 31、静态覆盖工具 64、逐臂记录响应重放 31；最终审计再重放 31 个业务工具，程序验证/重放费用单列于各回执，不计新模型调用。原协议声明时父程序复核 31，子程序预检 31＋31，最终审计父/子程序各复核 31。新增 CPU 契约最终 5 passed，合成测试工具量另属工程检查，不计真实模型样本。

保留来源账本、plan、metadata 版本/父链、失败 RevisionMemory、真实原始动作和核验回执。没有训练、写操作权限放宽、程序节点扩展或生产切换。本轮只支持受限领域的执行接口失败归因；原有一个真实经验程序仍有效，但 Agent 有效复用未得到证明。

- [预声明计划](../results/interview-sprint/reference-followup-20261013-v1/plan.json)
- [真实 dev 结果](../results/interview-sprint/reference-followup-20261013-v1/metadata_dev/report.json)
- [Metadata 治理](../results/interview-sprint/reference-followup-20261013-v1/metadata-governance.json)
- [子程序沙箱](../results/interview-sprint/reference-followup-20261013-v1/metadata-preflight-validation.json)
- [完整独立审计](../results/interview-sprint/reference-followup-20261013-v1/final-independent-audit.json)
- [最终准入 disposition](../results/interview-sprint/reference-followup-20261013-v1/agent-admission.json)
