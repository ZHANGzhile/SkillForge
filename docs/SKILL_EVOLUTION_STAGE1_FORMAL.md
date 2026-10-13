# Stage 1 三轮正式验证：零候选、零增量

2026-10-12。固定 main-v3，三轮真实 learn 18/18 完成、EOC 18/18；冻结父链后最终 18 个独立 source group × A/B/C = 54 臂全部完成，独立原始证据重放审计通过。

| 方法 | 完整 / 自主 EOC | Runtime 辅助 EOC | 模型调用 | tokens | search / load |
|---|---:|---:|---:|---:|---:|
| A PrimitiveOnly | 18/18 | 0 | 63 | 206,804 | 0 / 0 |
| B StaticLibrary | 18/18 | 0 | 63 | 206,867 | 0 / 0 |
| C ExperienceEvolution | 18/18 | 0 | 63 | 206,867 | 0 / 0 |

Instance、Paraphrase、authorized readonly Boundary 各 6 个 source group，三臂每层均 6/6。所有臂 attempted/actual policy violation 和实际 workflow violation 均为 0。C-B 的 EOC、联合成功条件下模型调用/token 节省均为 0；18 个配对来源无成功案例回退。B/C 目录完全相同，没有新 Skill 被调用或激活，不能解释为学习增益、结构泛化或新 Skill 复用成功。A/B 的 63 token 差来自目录上下文，不支持研究效益主张。

三轮各 6 条 learn，21 次模型决策，分别消耗 68,902 / 68,906 / 68,908 tokens。两种只读事实采集工作流自然只需 3/4 次决策；按已冻结的发现成本与效用门槛，三轮均为 0 Opportunity / 0 Candidate。程序与 Agent 验证均 SKIPPED_NO_CANDIDATE；每轮明确 RETAIN_PARENT，不能把三个无更新父链计作三次非平凡进化。原有三个静态业务 Skill 以 legacy_import 保留，没有在本研究中重新准入。

程序准入、Agent 准入、研究收益、隔离激活、部署分别为 false / false / 未宣称 / false / false。研究结果对象 research_claim_passed=null，表示没有统计收益认证；不能把它变成 true。第一阶段工程与有限只读协议完成，但正候选生成、真实新 Skill 泛化复用等 DoD 没有正面实证；第二阶段以保留的历史程序开展工程集成，不伪造第一阶段成功。

本轮 learn+test 252 次真实模型决策，新增 827,254 tokens / 1,472.3601 秒采集墙钟；继承开发费用后累计 1,433,441 tokens / 3,552.0325 秒。低于登记总上限 3,406,187 tokens / 9,279.6725 秒。GPU hours 未测量，墙钟不是 GPU 利用率积分。54 次 learn 与 108 次 test 静态覆盖工具调用为独立 CPU 脚本诊断，不计模型学习证据。没有新训练。

No-History 在 54/54 臂核验，仅允许当前任务交互与独立目录；因三臂都如此，没有单独移除历史的因果效应。Memory-only 未实现；Structural/Compositional、Agent 授权负例 EOC、工单写入、RevisionPlanner 不在已验证范围。G_heldout(C-B)=0；G_learn 未估计，因为 learn 不是独立配对 learn_eval，不能计算泛化保留比。统计单位是 source_group，不能将 54 臂当 54 个独立世界。

## 冻结与审计

- protocol：`11a5a40f86153c81b7b7b57b7ba483d21fa2d78a4deafc2a76298a63f1476ce5`
- report：`b13702af3c5b2c6b6c0e5ee14f06156e0b2ae1e4d6b8a92054d73106d4f92cee`
- Stage 1 freeze：`1e95da3de5f86f258dd4493961c24907ae5e2ffa161f87f56c61361b023aab43`
- retained catalog：`d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa`
- 固定权重：`f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b`
- 完整源码副本预检：445 passed / 1 skipped，385.94 秒；后加网页与历史诊断测试分别记录，不冒充同一全量预检。
- [独立审计回执](../results/skill-evolution/v1.2/formal-P5-v1/evidence-audits/0547d24034d51c5f1b0071bba8c6df6c770ec4454c0e42bdde9a8feccd615363.json)、[协议](../results/skill-evolution/v1.2/formal-P5-v1/protocol.json)、[结果](../results/skill-evolution/v1.2/formal-P5-v1/report.json)、[最终目录](../results/skill-evolution/v1.2/formal-P5-v1/stage1-catalog.json)、[冻结清单](../results/skill-evolution/v1.2/formal-P5-v1/stage1-freeze.json)、[三轮决策冻结](../results/skill-evolution/v1.2/formal-P5-v1/decisions-frozen.json)。

第二阶段必须保持上述程序结构与模型不变。版本化 Boundary 与 CatalogRuntime 的接入尚未验证；开发期先完成统一接口与兼容性检查，再冻结第二阶段所有方法共同使用的 Runtime/提示。不能暗改第一阶段冻结源文件或只给新方法放宽环境。
