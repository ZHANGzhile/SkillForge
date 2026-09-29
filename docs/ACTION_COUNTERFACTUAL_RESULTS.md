# 已观察复用点的动作级反事实结果

[English](en/ACTION_COUNTERFACTUAL_RESULTS.md)

已完成15对上下文、30条分支；排除0个源调用点。分叉前原context、完整SQLite dump、剩余故障队列及执行位置一致，之后由同一固定HTTP模型真实续跑。

| Arm | Qualified / contexts | Actual violation rate | Real continuation calls | Continuation tokens | Post-fork tool calls |
|---|---:|---:|---:|---:|---:|
| skill | 15/15 | 0.0 | 15 | 51895 | 67 |
| primitive | 15/15 | 0.0 | 30 | 96925 | 35 |

改善0例，退步0例；以primitive成功的15个上下文为分母，observed-reuse counterfactual NTR为 **0.00%**。总体population causal NTR仍为 **null**。

只强制分叉处一个动作，之后模型自主决策。两臂保留同样的Skill候选和Gate，primitive臂后续仍可选Skill；不是全程禁用Skill。前缀重放和强制动作不计模型调用，表中的模型调用/token是真实续跑成本，工具计数从分叉处开始并包含强制动作的内部工具。不是从任务起点全自主执行的成本对照。

Runtime对工具的原始发起者归因包含强制动作，不能把其中实验控制的写入称作模型自己产生的违规意图。实际违规仍按状态审核；强制/重放次数和实际模型输入单独保存。

筛选扫描全部真实Skill调用，不按源结局筛选；但实际这批调用所在原轨迹均成功。覆盖只限已提供、已选择、有只读前缀及续跑预算的Skill使用点，不能推广到错误复用、未被选择的Skill或全部78个任务。每臂一次确定性续跑，不提供总体置信保证。

源test已被查看，本轮不训练、不改prompt、不选部署、不声称修复原10个失败。旧B0/B3系统消融的NTR字段不改写。报告先重放分叉、核对所有分支与连续状态链，再重算配对结果。

## 逐上下文对照

| Context | Family | Skill qualified | Primitive qualified | Skill helped | Skill harmed |
|---|---|---|---|---|---|
| task-03c8ef59f7cd559a2f21-step-1 | refund | True | True | False | False |
| task-06da994cb33949d6206b-step-1 | refund | True | True | False | False |
| task-147a6e31f40d0fba9ffe-step-1 | refund | True | True | False | False |
| task-17797662d3be0172a49d-step-0 | cancel_order | True | True | False | False |
| task-55d4f0846622abd82658-step-0 | modify_address | True | True | False | False |
| task-72278120f75f07e021b2-step-0 | cancel_order | True | True | False | False |
| task-7469b338d31ded16ab22-step-0 | refund | True | True | False | False |
| task-8adfc6c3be2cd3c9c90c-step-0 | modify_address | True | True | False | False |
| task-8ff77e727147e3534311-step-1 | refund | True | True | False | False |
| task-9609260cae1b8fe0bb03-step-1 | refund | True | True | False | False |
| task-97ac26a1819903763fed-step-1 | refund | True | True | False | False |
| task-c64c115fa2701e1968f7-step-0 | refund | True | True | False | False |
| task-d10c77657f8f07645997-step-0 | cancel_order | True | True | False | False |
| task-e73a807ded9b20205dda-step-0 | cancel_order | True | True | False | False |
| task-fd2f28d7bab0dd15dab8-step-0 | refund | True | True | False | False |
