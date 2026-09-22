# 执行设计 v1.1

## 权威与范围

本文件落实用户确认的设计。电商数据完全为本地合成数据。先贯通修改地址、取消、退款、物流调查、转人工和复合任务。正式训练在 B0–B3 后进行。单 Agent、单进程任务执行，不引入通用编排。

## 决策表

- 所有订单读写先校验 authenticated customer 与订单归属；身份来自执行上下文，不能由模型覆写。
- 修改地址：CONFIRMED + NOT_STARTED + 地址有效。PROCESSING 转人工；SHIPPED / DELIVERED 拒绝。
- 取消：CONFIRMED + NOT_STARTED；已取消视作已满足取消结果，不重复写。已扣款取消仅取消订单，不自动退款；退款需显式授权任务。
- 退款：CAPTURED / PARTIALLY_REFUNDED，金额正且不超剩余额；金额以整数最小货币单位表示。
- HIGH 风险写操作转人工。缺失状态、未知状态与策略冲突转人工。
- v1 每订单至多一笔 payment、一条 shipment；数据库唯一约束明确此限制。
- 写工具使用 request_id 作为幂等键，同键不同参数拒绝；事务内读取最新状态再次检查策略。模拟响应丢失发生在提交之后，用同键重试。

## Expected Outcome Contract

fixture 独立定义 allowed_outcomes（completed/refused/escalated）、期望状态、禁止改变字段。Verifier 检查终止结果、真实状态、执行审计与证据。拒绝和转人工并非普遍成功；只有符合当前任务的 contract 才匹配。全拒绝策略不能通过正常任务。

## Skill 语义

有限节点：call、assert、finish。条件为 field + op(eq/in) + value，不使用 eval。v1 顺序程序与条件失败出口，不支持循环、递归、自定义代码和 Skill 递归调用。输入引用采用 $input.field，观察引用采用 $state.field。只允许白名单工具。执行步数有上限。

Gate 只读输入和已知状态，返回三态及缺失字段，不执行 I/O、不调用模型。Runtime 可按固定映射补充 get_order/get_shipment/get_customer/validate_address 查询，统计全部成本。写工具始终独立再次校验。

## 学习与评测

Compiler 必须同时接收成功轨迹、失败轨迹和版本化 policy；每条边界保存来源。v1 先实现受限领域归纳，不声称具备开放域自动程序发现能力。

训练轨迹用于 Skill 编译；validation 用于验证/refinement；test 只用于冻结版本的最终评测。数据记录 split、template_id、seed、policy_version。B0–B3 同模型同任务配置；离线脚本策略只用于工程测试，不能作为 LLM baseline。

指标区分 attempted_policy_violation 与 actual_policy_violation；wrong_reuse_attempt_rate、wrong_reuse_associated_failure_rate；因果 NTR 无匹配反事实证据时标为 unavailable。Full System 和固定候选 Decision-level 分开输出。

## 第二轮实施补充

- 新增 experiment-v1 manifest 和冻结实验协议，具体定义见 EXPERIMENTS.md。
- 主 Compiler 支持地址/取消，成功轨迹要求读取在写入之前、复核在写入之后。失败轨迹只有实际业务拒绝/权限拒绝且与相应条件相关时提供边界证据。
- B2 为独立的 success-only Naive Skill，B3 才使用成功/失败/policy 与 validation。B3-no-gate 保持 VERIFIED 契约，仅去掉运行时 Gate。
- Gate 查询异常显式返回上下文；同任务同调用的耗尽预算不可通过换 step 重置。
- mutation 的 operation key 在整个任务内按工具及参数绑定，而非按模型 step 绑定。

## 第三轮实施补充

- 增加退款 Skill，固定谓词 refund.amount_valid 从 amount、captured_amount、refunded_amount 计算；不足信息保持 UNKNOWN。
- refund.expected_total 是执行前固定的累计退款目标，不引入通用算术表达式。退款后通过 get_payment 验证。
- 修订最多两轮，validation 只定位修复段，内容来自 train＋policy；原候选不变，每轮版本及失败反馈独立记录。
- Skill 执行的 result.error 中若重试耗尽，脚本策略转人工，避免重复选择同一个失败 Skill。
