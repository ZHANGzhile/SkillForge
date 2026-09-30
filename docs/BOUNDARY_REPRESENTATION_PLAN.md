# 退款边界表达对照：预声明

本轮研究已观察到的B退款拒绝，属于事后诊断。旧分数、核心、模型、实际执行契约、工具policy、Gate补查和预算保持冻结。实验显示层不写回Registry、不决定动作，也不是新的Agent。

两臂都执行原B契约。original原样显示；allowlist_view仅在已观察payment.status为CAPTURED、PARTIALLY_REFUNDED或FAILED时，把显示契约中禁止FAILED的条件替换成首个前置条件payment.status in [CAPTURED, PARTIALLY_REFUNDED]。其余字段、Skill ID、程序、参数、观测和提示相同。缺失或域外支付状态（包括REFUNDED）保留原文。转换含条件位置与算子表达变化，因此不能归因于某一个单词或算子。

显示与执行分离：实际Gate、hydrate和executor一律读取原B。有限枚举覆盖域内、域外、缺失支付状态，LOW/MEDIUM/HIGH/缺失风险，合法/超额/零额/缺失金额及缺失余额，检查显示前后在当前观察上的三态状态一致。UNKNOWN缺失字段与reason的解释顺序不作为语义等价标准；执行路径不会使用显示版Gate。

固定实验量：原边界test全部8个退款场景，两臂每场景3次，共48次完整任务；其中原B首步确实提供Skill的全部4个上下文，两臂各原样请求10次，共80次决策，共128项。上下文按是否提供Skill选择，不按模型任务成败选择。全部负向场景也在完整任务中保留。不复用历史执行充当本轮对照，不将重复次数当作独立场景数。

两臂和两种请求按固定seed/key哈希交错串行执行，输入、顺序、代码、源证据及服务身份在首个请求前冻结。逐项原子检查点，恢复先审核；基础设施失败停止留档，模型非法输出保留。保存Runtime原context以及真正发送模型的完整JSON字符串，避免只记录干预前输入。

完整任务的初始SQLite与Gate补查后的首步context必须跨臂逐字一致；动作变化后的历史自然分叉，环境生成的交易UUID也可能不同，不能宣称完整多步轨迹全程都是同一输入。原样首步重放才严格固定输入的其余内容。

主要输出为原退款退步场景的首动作频数与完整EOC；同时报告全部4个可用输入的动作频数、全部8场景的逐次EOC/正常任务通过/禁止场景结局、被拦截写入、Skill使用、UNKNOWN查询和模型/工具成本。只解释本合成样本的表示干预效果，不另造显著性阈值、不替换旧联合门槛、不直接部署。如果改善，只支持进一步验证表示敏感性；没有改善则保留负结果。底层同输入波动与从经验学习新规则仍属独立问题。

执行：`python -m scripts.evaluate_boundary_representation --freeze`，`--run`，`--audit`。完整后`python -m scripts.report_boundary_representation`生成中英文报告。方案与代码冻结后不根据部分成绩修改；实时记录见BOUNDARY_REPRESENTATION_LIVE.md。
