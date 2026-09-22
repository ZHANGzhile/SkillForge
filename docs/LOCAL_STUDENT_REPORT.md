# 本地 Student 实测报告

日期：2026-09-10。Ollama v0.34.0，Qwen3 4B Q4_K_M，RTX 5070。模型名skillforge-qwen3-4b，16K上下文，单并发，temperature=0，seed=42，最大输出512。

服务运行于127.0.0.1:11434，项目使用显式Qwen3 raw适配器。37/37层加载到GPU；API报告size_vram=5,098,103,111字节，约4.75GiB。此结果只验证推理，不代表训练已通过。

## 集成与业务结果

最终接口验收：`results/local-student-smoke-accepted/model_smoke.json`，compatible=true。

最终真实运行：`results/local-student/9354139e-ad4f-4a02-b140-06d8dfe41c37`。目录包含配置、5个任务完整轨迹、统计、GPU驻留及服务版本/模型摘要/适配代码哈希。仅使用train分区，未用test调试，engineering_only=false。

| 案例 | 预期 | 实际与问题 |
|---|---|---|
| 可修改地址 | 完成并验证 | 修改后未读取验证，失败 |
| 已发货地址修改 | 拒绝 | 尝试修改被拦截，随后转人工，结局不符 |
| 可取消订单 | 完成取消 | 未执行即stop，失败 |
| 可退款 | 完成退款 | 未执行即stop，失败 |
| 高风险退款 | 转人工 | 结局符合，但此前发生被拦截的退款违规尝试 |

Expected Outcome满足率20%；违规尝试40%；实际违规0%；平均2.4次模型决策、1.8次工具调用、4370.8个总token、1.63秒/任务。唯一结局合格案例不是全程正确决策；同时满足结局与无违规尝试为0/5。五例只用于集成与诊断，不代表完整泛化或B0–B3结果。

## 遇到的问题与处理

下载慢：分段续传，运行库和权重并行下载；完整ZIP按官方SHA-256校验成功，临时CLI与完整包CLI哈希一致。

聊天适配：默认模板路径首次返回错误结构；自定义模板试验后，服务实际可能采用内嵌Jinja，生成被归入思考字段，最终Action为空。扩大到2048输出仍未解决。最终撤销模板覆盖，显式渲染Qwen3提示并通过raw生成接口消费最终JSON，不读取或依赖思考内容。失败smoke和所有中间轨迹均保留，不混入最终验收。

软件回归：45 passed，2个已有Starlette/anyio弃用警告。

## 下一步

1. 固定已验收的模型与适配配置，在train检查并改进状态读取、mutation后验证、stop/refuse/escalate决策；记录新旧提示版本，保留当前基线。
2. 收集真实成功与失败轨迹，加上business policy构建Skill边界；证据不足时不能用脚本轨迹充数。
3. 用validation选择并冻结Skill，再执行真实B0–B3及Full System/Decision-level双评测。
4. 完成上述对照及SFT action-level、DPO same-context数据审计后，再考虑正式训练。

启动方法见LOCAL_STUDENT.md；源文档：[Ollama Modelfile](https://docs.ollama.com/modelfile)。实际运行配置以保存的服务快照为准。
