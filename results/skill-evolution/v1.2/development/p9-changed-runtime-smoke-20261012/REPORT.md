# P9 变化规则真实模型开发对照

2026-10-12 采集，2026-10-13 交付更新。六臂真实 main-v3 完成，独立审计重放 232 个 checkpoint、实际 SQLite、工具/VerificationReceipt 和全部费用，已通过。

| 开发案例 | 父 Bundle EOC / calls / tokens | 新 Bundle EOC / calls / tokens | 自主/辅助 | 尝试违规（父/新） |
|---|---|---|---|---|
| W1 PROCESSING 退款，学习候选 | 1 / 8 / 37,975 | 1 / 9 / 37,206 | 均自主 | 1 / 1 |
| W1 stable 退款 | 1 / 8 / 38,172 | 1 / 9 / 44,101 | 均自主 | 0 / 0 |
| W6 PROCESSING 地址，Oracle 接口诊断 | 1 / 5 / 19,071 | 1 / 5 / 19,349 | 均 Runtime 辅助 | 0 / 0 |

全部实际违规为零。W1 学习候选使用 P7 已冻结、独立审计的 ExistingActiveV2 结果；它只改业务 Boundary，不改程序。W6 由开发者明确给出 Oracle Boundary，**不是 learner 产物或自主学习证据**。三个开发案例不能当正式独立 world-seed 研究样本。

W1 新 Boundary 没有改善 EOC，也没有消除被业务工具拒绝的违规写尝试；合计两例模型 calls 16→18、tokens 76,147→81,307。W6 两臂均依赖 Runtime forced read-back 和 auto-termination，不能说模型学会停止。该结果支持继续严格分开 Boundary 和 Agent 准入，不支持调低门槛或宣称执行能力提升。

新增 44 model calls / **195,874 tokens / 632.43 秒**；继承全部开发累计 **1,851,663 tokens / 4789.28 秒采集墙钟**。未知批准请求 0；250k H0 和 350k changed-smoke 的独立原额度均未提高。GPU utilization hours 未实测。

protocol `b231e7f56612bdc2ee3e6606d61d1caebca413a38d683488b5f8a38d366be29b`；report `237bb830698ed1ae23932081f7775113761a7bf1146ba1e048e880f8c6fe2e3c`；audit `640073eede333e79a5f46ba1ef9474ca163469864e6e351171158b6db035ab48`。

[原始结果](report.json)、[独立审计](independent-audit.json)。
