# Active Self-Evolution v1 正式交付

2026-10-03。正式验证流程、证据审核和Evolution Trace已完成，**研究假设未通过完整验收，未激活新的Agent bundle**。Continual QLoRA未实施，仍属v1.1。

## 完成范围与结论

| 阶段 | 完成情况 | 正式结论 |
|---|---|---|
| 新世界Runtime与版本化Policy view | learner/Agent只接收公开任务、旧公开规则及学习patch；固定main-v3 | gold判定在独立评测端；隔离为协作式Python访问防护 |
| 新Runtime成本门槛与冻结 | v3 smoke通过；73份源码、30组数据manifest冻结 | 最终协议哈希见下方；前两轮失败smoke保留 |
| CPU 6×5×4矩阵 | 120/120；19,200条held-out记录审核通过 | Active收敛86.7%对Random 3.3%，RMQ 8.033对20；但2次false allow使安全门槛失败 |
| 连续policy epoch | W3→W5、seed1701；8/8组合 | Active连续两次获准更新；新世界均80/80，无stable负迁移 |
| 固定SFT真实Agent双评测 | 20/20配对；300次唯一执行 | 四个Active更新提案均引入正常任务退步，被独立准入拒绝；最终test保留H0，无更新收益 |
| Workbench Evolution Trace | 主工作台入口、逐query证据、版本链、完整结果 | 桌面/手机真实浏览器验收通过；只读，不调用模型或发布Skill |

实际资源：1,335,942 tokens；任务耗时41.30分钟，含模型进程启动和关闭共41.90分钟，无基础设施重试，低于12小时/20M限制。缓存只复用完全相同的任务/bundle/model身份。

四个Active提案在Decision validation均由7/8提高到8/8，但出现缺少写后读回或执行错误，正常任务退步不可被其他样例的改善抵消。拒绝提案不进入正式test：独立层有效bundle的New-world EOC仍为12/24、Stable EOC 9/24、Decision 20/24。CPU发现正确边界不等于完整Agent已学会可靠执行。

## 使用页面

双击项目根目录的`启动 Evolution.cmd`，或运行：

```powershell
.\.venv-train\Scripts\python.exe -m scripts.start_active_evolution_workbench
```

打开 <http://127.0.0.1:8080/evolution>。工作台首页也有Evolution入口。启动器复用固定main-v3，保持原部署配置与历史签收文件不变；实验bundle未获准激活，主工作台任务执行仍使用原部署。

仅查看证据、不启动模型或任务队列：

```powershell
.\.venv-train\Scripts\python.exe -m scripts.start_active_evolution_workbench --preview
```

只读预览为 <http://127.0.0.1:8081/evolution>。当正式GPU评测占用设备时，完整工作台启动器会要求使用预览；不会抢占实验。

## 审核入口

- 完整表格与解释：[DELIVERY.md](../results/active-evolution/v1/formal-v1/DELIVERY.md)。
- 协议：[protocol.json](../results/active-evolution/v1/formal-v1/protocol.json)，哈希`de3eae4b913556249d5d761b636b88dac87038f833a22825f62c899f6c9de60e`。
- CPU：[cpu-report.json](../results/active-evolution/v1/formal-v1/cpu-report.json)、[独立审核](../results/active-evolution/v1/formal-v1/independent-audit.json)。
- 连续父链：[continuous-report.json](../results/active-evolution/v1/formal-v1/continuous-report.json)、`continuous/<epoch>/<method>/lineage.json`。
- Agent：[model-report.json](../results/active-evolution/v1/formal-v1/model-report.json)、`model-layer/**/activation.json`和哈希绑定的原始cache。
- 交付审核：[delivery-audit.json](../results/active-evolution/v1/formal-v1/delivery-audit.json)、[最终签收](../results/active-evolution/v1/formal-v1/delivery-signoff.json)。
- 页面验收：[browser.json](../results/active-evolution/v1/formal-v1/workbench/browser.json)，同目录保存截图。

只读复核可运行`python -m scripts.audit_active_evolution_formal`与`python -m scripts.audit_active_evolution_delivery`，不会新增查询或推理。正式协议和产物不可覆盖；不能通过修改已冻结代码、过滤失败或重跑能力失败来改善已报告结果。

这些结论限于声明的六世界、有限假设空间及模型层代表场景。Workbench展示的是可追溯的研究证据；实验流程交付完成与研究假设通过是两个不同结论。
