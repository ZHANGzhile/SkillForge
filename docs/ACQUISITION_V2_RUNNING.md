# v1.1-B：正式运行与续接

2026-10-06 最终状态：A、B 正式实验和独立审计均已完成。实验进程已结束；以下运行状态、session 和阶段数字保留为历史记录。A 连续稳定性出现 1 个退步，B 未证明 v2 优于原 Active，不能宣称完整研究验收通过。见[正式交付总结与网页预览](EXECUTION_AWARE_V1_1_DELIVERY.md)。

2026-10-05。开发24组已完成并通过独立证据重放审计；正式B已冻结并运行。A的研究结论以[验收解读](EXECUTION_AWARE_A_ASSESSMENT.md)为准，B不用于补成A的连续retention通过。

## 协议与工作量

- 协议：`results/active-evolution/v1.1/formal-B-v1/protocol.json`。
- hash：`a0e86e16229bf895402531bec9119aa2747ec1c18bbbdc63d23627909ff33540`。
- 正式矩阵：W1–W6 × 5个按namespace派生的新seed × no_adapt/passive/random/active/active_v2，共150组；30份数据集经过与既有manifest的实例去重检查。
- 选中v2：仅H0 Challenge Gate，K=2，替代假设posterior阈值相对最强非H0为0.1；仍在原20次查询预算内。disagreement/coverage的0.25加权开发候选未选中。
- 开发选样不读取test。开发中gate查询34次，两种加权候选各35次，验证错误均为0；这没有提供gate优于原Active的证据。
- 两个联合效率指标、H0错误收敛、原始/认证收敛、安全与stable保留要求均见protocol；不能仅将错误收敛改为inconclusive就宣称成功。
- CPU探针不调用模型。B新增GPU时间与LLM tokens均为0；A累计7,739,014 tokens、睡眠修正后4.394小时的共享资源快照已绑定B协议。

## 运行与审计

启动入口：`.venv/Scripts/python.exe -m scripts.run_acquisition_v2_delivery`。

当前调用`20df6b62acf447268d50b17afb8cfcfb`，工具session `80634`（仅当前Codex会话有效）。入口持有`.runtime/acquisition-B.lock`并请求临时防自动睡眠。4个CPU工作线程并行处理不同world-seed；每个单元的五种方法串行，复用具有严格身份的私有固定程序探针。各方法的逻辑查询仍全部计费，不把共享探针当独立样本。

每组完成时保存`cpu/<world>/<seed>/<method>/metrics.json`。完整矩阵完成后写`cpu-report.json`及`REPORT.md`，随后独立审计器重放原始探针、后验、Challenge、准入、heldout统计和总体配对估计，成功后保存`audits/evidence.json`。只有invocation final=complete且audit通过才能称为完整交付；矩阵完成不代表研究假设通过。

审计不重新执行探针，不读取heldout标签给learner。选样排序由冻结源码及查询记录绑定，当前独立审计器没有再次独立实现整个排序算法；此边界在审计scope中保留。

发现开放invocation或锁时先检查进程，不能重复启动、删除锁绕过保护或改写冻结源代码。100个B冻结源码及30份数据集已再次校验。必须修复报告/界面时，优先使用独立报告脚本，不能修改learner依赖后继续混用同一协议。

## Workbench

`http://127.0.0.1:8091/`现使用独立只读入口`python -m uvicorn scripts.execution_delivery_workbench:app --host 127.0.0.1 --port 8091`。PID在`.runtime/execution-preview.pid`。页面保留A的四层漏斗、Runtime归因、VerificationReceipt与执行Trace，增加连续test保留能力及退步跳转、B进度、B查询Trace和完整矩阵后的联合验收。使用“刷新证据”读取最新结果。

页面没有实验启动、发布、学习或部署端点。CPU Boundary指标与真实Agent指标独立展示。前端HTML及新报告入口未改变任何冻结研究Python依赖。

浏览器QA：`results/active-evolution/v1.1/development/workbench-qa-AB-v1/`，包含desktop/mobile/trace/acquisition截图和browser.json。已验证1440/390宽度、无溢出/JS错误、A退步跳转及B查询Trace。原A-only QA保留。完整研究代码回归为277通过、1跳过；新增界面相关5项测试通过，包含审计未完成状态及路径限制。
