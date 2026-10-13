# P4 Registry / Raw Agent Evidence：CPU 工程报告

2026-10-12。工程通过，真实候选仍为 **0 / NO_USEFUL_CANDIDATE**。本报告不构成正式 Skill/Agent 准入或研究收益。

## 实际验证

| 检查 | 结果 |
|---|---|
| 真实 P2 原始响应/动作/工具/完整 checkpoint/SQLite/费用重放 | 6/6 通过 |
| 原始 EOC | 6/6，6 autonomous / 0 assisted |
| 原始模型费用（历史采集） | 21 calls / 68,906 tokens |
| 独立筛选/TraceCompiler 重算 | NO_USEFUL_CANDIDATE，0 新候选 |
| Legacy import / retain parent | 同一原目录、完整来源与父链 |
| 工程精确版本废弃 / 祖先回滚 | 通过；不改旧快照、不操作实际服务 |
| 工程回执冒充正式注册 | 拒绝 |
| 真实 learn 冒充 Agent validation | 拒绝 |
| 新模型 calls/tokens | 0 / 0 |
| 新正式 Skill / Agent admission / activation / deployment | 0 / 0 / 0 / 0 |

工程运行和独立事后审计分别重放 15 次 CPU 工具调用。测试中的脚本 token 接口仅用于检查审计和拒绝路径，不是模型实验或 learn 来源。

## 不可变身份

- 保留/恢复的 Catalog：`d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa`
- 真实提案审计：`1527741b5098f0c8c9dba24afd32c07b8818cc298aecbb94ec5aeadfdba5b891`
- 源码 index：`e183c2492ae328ece46c02edcd5c5df312f644755a0c6874e745ebd04ffb7978`
- report.json SHA256：`4d918d62356c8ceecdef402c0cefd67b1a895173247bdc59f127622ecdf14430`

选择快照链：

```
LEGACY_IMPORT       de4da336dfc87cf82b5433194f3fb2dc60e45196ff4d8c306755da2bdb54688a
       ↓
RETAIN_PARENT       61c909dc03d49818393f3ff16cd729e17a132fac37c341ea039d92867f697d27
       ↓
engineering DEPRECATED
                    ee47c8bb14a00057b80c1d11639328a65ace9b1af84b38098badf8800e8b2ad9
       ↓
engineering ROLLBACK → imported ancestor
                    8c54f55eccf4e0978a01089521fb6484ae5d4d32b5e8b6e53c1c24cd59d96c82
```

这是一条 CPU 工程分支。正式准入过的新版本不存在，不能称为真实演化成功父链。

## 独立核验

[工程 JSON](report.json)、[源码 index](source-index.json)、[真实提案与逐条证据](real-proposal-audit.json)、[声明](declaration.json)、[独立审计](evidence-audits/74ea582059366dcc35155060d0a3db67d52cd7c95ce4e3d7da585038ede23183.json)。

新增定向测试 **21 passed**。完整独立源码副本 **411 passed / 1 skipped / 2 upstream warnings**（69.72 秒）；正式 A/B 的 86/100 个冻结源码、历史文件保护、固定 main-v3 adapter SHA256 通过。[预检](../preflight-20261012-P4-registry/preflight.json)与[测试日志](../preflight-20261012-P4-registry/pytest.log)。

共享真实模型累计仍为 537,296 tokens / 1,904.82 秒采集墙钟；CPU 工程/测试另计。没有后台 skill_evolution.worker，没有占用本阶段 GPU 租约。

## 限制与下一步

正式新程序注册入口已实现，但尚无真实候选验证成功分支。配对证据从原始文件接入统计门；P5 正式配对采集、Agent admission receipt、isolated activation controller 尚未接入。统计通过和 VERIFIED 均不能自动激活。

当前 Agent 重放仅支持完整、已结算、无注入故障的只读工作流。费用验证以原 worker/controller 结算为依据，不是重新推理或硬件生成证明。写入/返回值绑定/组合/RevisionPlanner 与新版 Workbench 仍待办。

下一步接 P5 同后端 A/B/C、No-History 与三轮父链的采集和累计费用控制，成本 smoke 后冻结正式协议；保持原候选效益门槛，不为产生正结果追加无效动作。
