# 新规则适应：固定有限学习器预声明

本轮独立于边界表达实验，不请求GPU、不训练模型、不修改旧核心或线上policy。研究对象是受限条件空间中的归纳与验证，不声称发现任意新特征或通用规则。

固定程序：旧退款Skill的inputs/procedure/postconditions/ID不变。固定先验：旧完整人工业务边界，以及四个已有可观察字段的有限取值域（风险、支付、订单、物流）；包含对退款旧规则无关的订单和物流字段。新学习器在这些字段上枚举eq/in条件、保留全部当前版本正例、贪心排除最多负例、平局eq优先再按内容hash排序，最多2条，规则变化后不修改算法或候选空间。与首版限定refund字段的学习器分开标识，不把新增字段搜索能力归给旧算法。

预声明两个相互独立世界：旧退款policy额外禁止shipment.status=PROCESSING；旧退款policy额外禁止order.status=PENDING。两世界都从旧边界出发，不叠加规则。环境事务内二次policy check执行新规则；权限、幂等、写入事务保持旧实现。仅CPU实验进程临时替换Environment模块引用的eligibility函数，退出后恢复，不修改文件或运行中GPU服务。

每个世界同一预定组合分割：LOW/MEDIUM × CAPTURED × 全部3订单状态 × 全部4物流状态中，按配置列表的订单索引+物流索引之和偶数分train、奇数分validation，各12。此划分使训练正例包含多个允许的订单/物流值，避免一个偶然常量与禁止条件不可区分；两世界使用相同划分。test为LOW/MEDIUM/HIGH × PARTIALLY_REFUNDED/FAILED × 全部3订单状态 × 全部4物流状态，共72。金额为合法固定请求1700，部分退款初始1200，余额足够。两个世界的ID/版本独立；test的组合与train/validation隔离，不宣称业务状态语义未知。

正负标签来自新policy下真实执行固定程序的成败；只有business_rule_rejected算业务负例，其他失败单列excluded。保存完整SQLite初态、前后状态链及工具审计。学习仅接收当前policy版本的train快照特征/参数/标签和旧边界，不接收新规则函数、world名称、手写参考条件、validation/test标签。不混入旧版本已过期的正例。

对照：stale旧边界；learned从新train成功/失败精化；manual知道完整新规则的手写参考。三个组都使用同一新环境、相同Gate与程序。先用全观察统计错误放行/错误拦截，再从空观察hydrate并按Gate决定是否尝试程序，报告UNKNOWN、查询数、程序执行成功、被工具拒绝写入及实际非法状态变化。这里的完成是程序结果，不是模型选择正确refusal/escalation的EOC。

全部validation/test均报告，不按结果重选条件；不将同规则下多个组合当作72个独立真实业务政策证据，不制造置信区间。支持的最强结论为：在明确人工特征域中，固定学习器能利用新版本执行反例更新边界，并迁移到未参与拟合的组合。两个世界代表两种合成政策变化，不代表真实业务总体。不做自动部署。

执行前冻结规格/生成数据/学习器/环境实验代码/旧bundle与核心hash；`python -m scripts.evaluate_boundary_adaptation --freeze`，然后`--run`；`--audit`重新执行全部CPU探针、重新拟合条件并重算指标。UUID值和延迟仅在语义重放比较中规范化，原始证据完整保存。
