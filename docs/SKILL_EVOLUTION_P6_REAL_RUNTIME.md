# P6 真实 H0 Runtime 接口与成本验证

2026-10-12。7/7 固定 main-v3 真实任务完成，独立 SQLite、工具/VerificationReceipt、242 个 checkpoint 和逐请求费用重放通过。6 autonomous EOC、1 runtime-assisted EOC；辅助案例包含 1 次 forced read-back 与 1 次 auto-termination，不能计作模型自主完成。实际/尝试违规均为零。

5 个无变化案例输出 NO_CHANGE；HIGH 风险案例为 INCONCLUSIVE、Guard 不可放宽；超时后恢复案例仍归类 INFRASTRUCTURE，不进入业务 Bayes 证据。该组是预声明开发接口与费用 smoke，H0 固定，没有 Boundary 学习、准入、激活或泛化收益结论。

新增 **47 calls / 222,348 tokens / 604.82 秒采集墙钟**，低于登记 250,000 tokens / 900 秒。继承完整第一阶段后累计 **1,655,789 tokens / 4156.85 秒**。GPU 小时未实测；不将墙钟等同 GPU utilization。所有请求使用实际已知 usage 结算，未知批准请求 0。

protocol `e99e2d11716246c4b61ea449732726fe9848dc334f30d6085d711baa8f66aae9`；report `2b88047cc947e5319c300386d6df64b0e14d8147c3cfe76202f867b39e78c6ec`；audit `cb270dacf471824b820ea8b7c5aaa6f2fc28f9161a5bbf9000ac04cacd23cf7d`。

新增版本化 Boundary Runtime 未修改冻结 Stage 1/旧 v1.1 源码、程序、权重、系统提示或检索排名。变更仅为开发版本独立公共业务 Boundary、Gate 和精确 bundle 恢复身份；业务终态仍继承旧公共规则，未知条件不由 gold 覆盖。Python cooperative guard 不等于恶意原生扩展的 OS 沙箱。

复现审计：

```powershell
.venv/Scripts/python.exe -m scripts.audit_boundary_runtime_smoke --run results/skill-evolution/v1.2/development/p6-real-runtime-smoke-20261012
```

[原始结果](../results/skill-evolution/v1.2/development/p6-real-runtime-smoke-20261012/report.json)、[审计](../results/skill-evolution/v1.2/development/p6-real-runtime-smoke-20261012/independent-audit.json)。
