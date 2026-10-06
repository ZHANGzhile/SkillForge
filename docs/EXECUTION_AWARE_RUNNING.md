# Execution-Aware v1.1-A：运行与续接

2026-10-06 最终状态：A、B 正式实验和独立审计均已完成。实验进程已结束；以下运行状态、session 和阶段数字保留为历史记录。A 连续稳定性出现 1 个退步，B 未证明 v2 优于原 Active，不能宣称完整研究验收通过。见[正式交付总结与网页预览](EXECUTION_AWARE_V1_1_DELIVERY.md)。

当前活动根目录：`results/active-evolution/v1.1/formal-A-v2`。

A已完成，当前运行阶段为B，见[正式B运行与续接](ACQUISITION_V2_RUNNING.md)。8091只读预览已切换到`scripts.execution_delivery_workbench:app`，同时显示A与B。

冻结hash：`c565643a4e87d9b71d1875778ab71c0a6a9956d1b6b3b7adeb421a2064c93fcc`。A源码、数据、模型设置、准入阈值均不得原地修改。B文件不参与A冻结，但B正式实验需在A完成后独立冻结。

## 当前进程

2026-10-05状态更新：以下A续跑已正常结束，`72b4dc3a119f4bff8ad355b6acd20fa3.final.json`为complete，恢复耗时2,309.34秒。1,608条执行及两个连续epoch全部完成，自动finalizer已生成正式REPORT和审计；不再启动A模型矩阵。下列session仅为历史追溯。

- 固定main-v3模型矩阵：`python -m scripts.resume_execution_after_sleep --run`，当前Codex终端session `17232`。
- 当前invocation：`72b4dc3a119f4bff8ad355b6acd20fa3`，开始记录位于`model-layer/invocations/`。
- 自动收尾：续跑包装器在runner退出后直接调用独立finalizer，无需额外等待进程。
- 只读预览：`http://127.0.0.1:8091/`，PID保存在`.runtime/execution-preview.pid`。

终端session仅在当前Codex会话中有效。先检查现有进程和invocation关闭记录；不要重复启动同一矩阵或相同输出目录。当前runner会在关闭时恢复其租用的8002模型服务与8080主Workbench；8091只读预览独立运行，不占用模型。

## 检查与产物

```powershell
.venv/Scripts/python.exe -m scripts.audit_execution_aware
```

此命令只读当前已落盘证据，在`formal-A-v2/audits/`新增带独立身份的审计回执。运行中报告明确标为incomplete，开放invocation的墙钟和正在执行的任务尚未结算。正式runner按冻结预算进行每次dispatch检查。

CPU正式矩阵已完成：9个独立单元、5个Belief Converged、5个Boundary Admitted；另外两个连续epoch的Boundary均准入。`cpu-report.json`为证据入口。

模型层按单元保存`activation.json`、`evaluation-freeze.json`、`report.json`，完整矩阵结束后保存`model-report.json`。自动收尾只有在完整且审计通过时写`REPORT.md`及`execution-attribution.json`；否则保存incomplete回执，不推算总体效果。最终审计还核对实际父Bundle lineage、Runtime干预计数、独立Decision和候选/有效Bundle区别。逐臂归因按变化/stable test拆分，包括新Bundle的自主/辅助EOC；不同effective Bundle之间的差异不归因为纯Runtime救援。

收尾进程在启动时固定报告器与审计器的源码hash；若等待期间修改这些文件，会拒绝生成带错误源码身份的报告。更新报告代码后应重启这个只读等待进程，不必重启模型实验。

## 2026-10-05 外部中断与恢复记录

原调用`b85dd828f58d4743af45f2376841e6f2`在183条完整cache后外部中断，没有正常退出记录。已通过主机进程表确认不存在原runner/worker；不是仅根据失效的终端session判断。原start保留，失效GPU租约已归档，原main-v3与Workbench服务恢复后重新进入正式租约。

恢复工具`recover_execution_interruption.py`根据冻结的串行调度顺序，确定最多一个未结算的FullSystem dispatch，对其保守预留`16 × 16384 = 262144` tokens并消耗一个基础设施失败额度；这不表示已观测到该请求实际消耗这么多tokens。墙钟按start文件时间至进程核验/服务恢复结束，再加60秒余量计2,074.28秒，包括停机间隔。资源总账在恢复点为1,662,186 tokens、3,584.22秒（含既有开发），没有重置预算。

详细证据位于`formal-A-v2/recovery/b85dd828f58d4743af45f2376841e6f2/`及原invocation的final记录。183条完整缓存均复用；已确认新调用产生第184、185条结果，原未知请求在新隔离环境中按既定重试额度执行。未修改协议、阈值或模型权重。

恢复工具的默认命令只打印方案；`--apply`在核验无存活runner后保存保守记账、恢复服务并关闭原调用。若沙箱不能查看主机Python进程或创建不可变记录所需的本地硬链接，应使用已授权的主机权限执行核验，不能用空进程列表直接绕过保护。

## 中断后的恢复边界

1. 若现有模型进程仍在运行，继续观察，不重新启动。
2. 若invocation已有final记录，先检查status和基础设施失败记录。需要恢复时，原命令会按严格身份复用已完成缓存；恢复仍占同一个共享预算及冻结重试额度。
3. 若仅有start而没有final，runner会拒绝自动恢复。先核验已拥有的worker是否仍运行，并对这段资源使用进行保守核算；不能删除start记录绕过此保护。
4. Worker的执行checkpoint不能套用到新建的内存环境。新的隔离尝试使用新的worker输出目录，已完成任务通过身份缓存复用。当前实现不宣称生产环境端到端崩溃续跑。

## 2026-10-05 睡眠中断与有证据的计时修正

调用`1bdc3caed371406fb28ba95b7cc7e2c4`在1,293条完整缓存、9/9独立组完成后，在连续epoch 1遇到TimeoutError并因原始墙钟超限停止。Windows System的Kernel-Power 42及Power-Troubleshooter 1交叉证实：UTC 01:01:05至10:22:27系统处于睡眠，覆盖失败请求的异常等待。原始调用累计47,131.09秒（13.092小时），不是实际GPU运算时间。

用户要求“检查后找到问题解决，继续运行”后，新增显式基础设施计时修正，hash为`1a80e1c34e16fe0e5383bb310c8c269695a7f27214cb32447dff3fd5bbaf67b5`。证据及修正位于`formal-A-v2/recovery/sleep-20261005/`。仅扣除交叉验证睡眠区间减60秒余量，共33,622.16秒；恢复前修正账本13,508.93秒（3.752小时），tokens 6,602,261。原始start/final、失败预留和全部缓存不修改。原冻结墙钟预算确实被突破，报告必须披露这是修正后的续跑，不能声称原预算合规。

`resume_execution_after_sleep.py`通过显式Ledger子类仅调整prior_seconds，继续调用原冻结矩阵代码；不修改86个冻结源码、模型、数据、顺序、准入或估计量。扣除是总账的一次性修正，后续新调用时间照常增加。20M token、12小时修正后时间、原全局/逐任务重试上限均保留，两次失败的524,288 token预留不退款。续跑持有线程级Windows SYSTEM_REQUIRED，阻止自动空闲睡眠但不改变全局电源设置；手动睡眠仍可能发生，新睡眠不会自动获得扣除。

包装器持有`.runtime/execution-sleep-continuation.lock`，防止重复续跑；异常强制退出后需要先核验主机进程再处理遗留锁。不要再次使用未经修正的原models入口，否则原始账本会正确拒绝继续。每个新调用由不可变binding记录关联原protocol与修正hash；最终报告和8091页面同时显示原始及修正后的账本。

恢复验证：`source-check-2e2ae091e6f04f2d9891af6684e54e8a`为274通过、1跳过，10,699历史文件校验通过；另核验86个冻结源码。修正包括电源日志七位小数兼容、证据篡改/范围拒绝、一次性扣除、失败预留/重试和新时间预算保护测试。

模型父进程建议使用`.venv-train/Scripts/python.exe`，其具有GPU租约所需依赖；纯CPU/audit使用`.venv/Scripts/python.exe`。不重新估算或冻结当前A来迁就已观察结果。

开发资源账本已经包含四臂cost smoke；正式A的冻结prior为714,710 tokens、1,509.94秒。未来新协议不得再次把同一smoke重复相加。现有A使用冻结prior与模型层invocation/cache记录计费。

## 完成A之后

先解读完整A漏斗、effect及准入失败原因，再进入B的开发消融和独立冻结。保持20-query预算，保留原Active对照，H0 Challenge与disagreement/coverage候选分开；不得因A单个validation结果而提前声称正式有效。Continual SFT仍为条件性的v1.2。
