# 决策提示实验 v1（2026-09-27）

本实验针对已观察到的组合边界错误、退款数值判断和循环读取，测试一次预先固定的提示整理。它不声称重新学会Skill，也不更换权重。原Skill/Gate、工具、verifier和所有已发布结果保持冻结。

实现只读取模型context中已经可见的状态，将既有规则按权限/故障、高风险优先、复合后续分支、写后验证排序；可见整数支付字段齐全时计算剩余额度。它不读取Task.expected、隐藏数据库状态、旧test答案，不调用模型或工具，不选择或替换最终Action。模型仍自主输出自由Action，Tool仍执行二次policy check。新增提示的token计入成本。

固定参数见configs/decision-guidance.json。先完成原69例validation与固定候选决策探针；准入要求69例EOC全部合格、模型违规尝试0、实际违规0、决策至少41例正确。不尝试多个提示后按test挑选。未通过则记录拒绝并停止后续test，不改门槛。

在首个模型请求前冻结seed=20260927的独立实例数据，核对与原数据及上轮恢复数据的task/order/instance ID不重叠。只有validation准入后才评测新test的control/guided两组，各78例Full System与Decision-level探针，均使用同一固定权重HTTP服务。已知结构、旧validation及从旧失败得到的设计动机均明确披露；这不是未知业务泛化实验，也不输出same-context causal NTR。

每一步同时保存Runtime原始context和实际发送给模型的model_input_context；重算提示并核对完整模型输入。保存身份、连续工具状态链、任务与配置hash，网络/GPU故障独立记录，不进入模型失败分母。支持检查点恢复；只复用审核通过的记录，不重跑已完成案例挑选结果。不得并行启动本实验的两个协调器。

新目录沿用三分区文件格式，其中新train/validation文件仅随生成器冻结，本轮不使用它们训练或准入。准入仍使用原validation；冻结文件不等于已经运行新test。

运行：`.venv/Scripts/python -m scripts.evaluate_decision_guidance --resume`。进度见docs/DECISION_GUIDANCE_LIVE.md及results/decision-guidance/v1/progress.json。本实验不自动替换生产工作台的当前已签收配置。
