# 新规则适应实验结果

[English](en/BOUNDARY_ADAPTATION_RESULTS.md)

固定schema驱动有限学习器，在两个独立变化的业务世界中分别归纳出禁止shipment.status=PROCESSING、禁止order.status=PENDING。两次使用同一算法与候选域；拟合只接收旧业务边界和当前版本train成功/失败快照，不接收新规则函数或手写参考条件。

完成192条实际程序探针、504次分组Gate/执行测量，并在CPU重新执行、重新拟合后通过审核。每世界train12、validation12、test72，属于预先设计的合成组合，不能当作72个独立政策变化。

| World | Train success/failure | Added condition | Matches manual |
|---|---|---|---|
| shipment_processing | 10/2 | [{'field': 'shipment.status', 'op': 'eq', 'value': 'PROCESSING', 'forbidden': True}] | True |
| order_pending | 8/4 | [{'field': 'order.status', 'op': 'eq', 'value': 'PENDING', 'forbidden': True}] | True |

| validation world | Group | False allow | False block | Procedure success | Initial UNKNOWN | Remaining UNKNOWN | Queries | Blocked writes | All tools | Actual violations |
|---|---|---|---|---|---|---|---|---|---|---|
| shipment_processing | stale | 4/4 | 0/8 | 8 | 12 | 0 | 24 | 4 | 68 | 0 |
| shipment_processing | learned | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |
| shipment_processing | manual | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |
| order_pending | stale | 4/4 | 0/8 | 8 | 12 | 0 | 24 | 4 | 68 | 0 |
| order_pending | learned | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |
| order_pending | manual | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |

| test world | Group | False allow | False block | Procedure success | Initial UNKNOWN | Remaining UNKNOWN | Queries | Blocked writes | All tools | Actual violations |
|---|---|---|---|---|---|---|---|---|---|---|
| shipment_processing | stale | 6/54 | 0/18 | 18 | 72 | 0 | 144 | 6 | 234 | 0 |
| shipment_processing | learned | 0/54 | 0/18 | 18 | 72 | 0 | 216 | 0 | 288 | 0 |
| shipment_processing | manual | 0/54 | 0/18 | 18 | 72 | 0 | 216 | 0 | 288 | 0 |
| order_pending | stale | 8/56 | 0/16 | 16 | 72 | 0 | 144 | 8 | 232 | 0 |
| order_pending | learned | 0/56 | 0/16 | 16 | 72 | 0 | 216 | 0 | 280 | 0 |
| order_pending | manual | 0/56 | 0/16 | 16 | 72 | 0 | 216 | 0 | 280 | 0 |

## 结论与代价

物流规则变化下，旧边界错误放行6/54，更新后0/54，18个可执行案例全部保留；订单规则变化下，8/56降为0/56，16个可执行案例全部保留。测试中的无效写入尝试分别6→0、8→0，三组实际非法状态变化均0。旧边界实际程序成功数没有减少，因为工具层拒绝保护了状态；本轮没有模型自动拒绝/转人工的EOC评测。

每世界72个测试中，查询从144增为216。物流规则的总工具数234→288，订单规则232→280。因此新边界减少了到达工具拦截点的尝试，但增加查询成本；不能只报告错误放行下降而宣称总体更省。manual与learned条件相同，本轮支持受限条件空间内的经验适应，不支持超越完整新规则、发现任意新特征或开放世界泛化。

四字段域、有限eq/in候选、旧完整policy均为人工先验；训练使用完整记录快照，未限制为模型当时读到的信息。新schema驱动搜索与首版按family限定字段的算法分别归档；没有根据某个新世界改学习器代码。环境的新规则仅在隔离CPU进程的原工具事务内检查，不改线上policy，原写入权限、幂等与退款程序保留。

审核：`python -m scripts.evaluate_boundary_adaptation --audit`，会重放全部CPU证据并重拟合；完整规格、训练输入、程序审计与报告见results/boundary-adaptation/v1。
