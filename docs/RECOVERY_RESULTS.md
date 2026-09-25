# main-v3 恢复训练结果

本报告审核逐任务检查点后生成；模型仅按validation准入，未按新实例test选优。

| 模型 | 新实例test EOC | 固定候选决策 | Skill调用 | 模型违规尝试 | 实际违规 |
|---|---:|---:|---:|---:|---:|
| DPO-reference | 57/78 | 45/48 | 13 | 2.6% | 0.0% |
| SFT | 68/78 | 44/48 | 15 | 0.0% | 0.0% |

新实例沿用已知生成器、任务族与结构；不能作为开放域或未知结构泛化证明。旧main-v2报告独立保留，旧test已被查看，不能重新当作首次独立测试。

SFT语料由355增至1,267个样本，两轮训练的更新次数也增加；本实验未隔离数据内容与计算量因素。DPO-reference使用原main-v2权重，本轮候选为重新训练的SFT。

实际产品验收另见工作台结果；研究评测完成不等于HTTP和浏览器验收通过。

## 验证与成本

新SFT validation为69/69；验证token loss为0.013850。模型在新test之前通过预声明准入。

| 指标 | 旧DPO | 新SFT |
|---|---:|---:|
| 平均LLM调用 | 3.45 | 2.37 |
| 平均工具调用 | 5.94 | 4.79 |
| 平均token | 10411.59 | 6653.26 |
| 本机平均延迟(ms) | 24042.70 | 15402.84 |

## 新实例分任务族结果

| 任务族 | 旧DPO EOC | 新SFT EOC |
|---|---:|---:|
| cancel_order | 13/15 | 15/15 |
| composite | 0/9 | 3/9 |
| modify_address | 28/30 | 27/30 |
| refund | 10/18 | 17/18 |
| shipment_investigation | 3/3 | 3/3 |
| ticket | 3/3 | 3/3 |

逐任务配对：13例从失败转成功，2例从成功转失败；净提升14.1个百分点。单训练种子、单次greedy测试，未声称统计显著性。

## 保留的失败

| task ID | 任务族 | 结局 | 不满足的契约 |
|---|---|---|---|
| task-0f2e6230e33cbbc84a33 | composite | refused | unexpected_outcome, expected:order.status |
| task-5eeef59f4f18bb33e25a | composite | refused | unexpected_outcome |
| task-b60ecc538d8e070a8d9f | modify_address | refused | unexpected_outcome |
| task-b95460321498eca119e7 | composite | refused | unexpected_outcome |
| task-c17a09f971df0bd1b5df | composite | refused | unexpected_outcome |
| task-d3ead9a40567953f871c | modify_address | refused | unexpected_outcome |
| task-d478c779bf7872d3b65c | modify_address | refused | unexpected_outcome |
| task-d60cfa170ca38357da3f | refund | max_steps_exceeded | unexpected_outcome |
| task-dbf30af1850d882777b0 | composite | refused | unexpected_outcome, expected:order.status |
| task-f68475e6f8b33f36a3e7 | composite | refused | unexpected_outcome, expected:order.status |

固定候选决策45/48降为44/48，地址任务28/30降为27/30；总体系统收益不代表所有子能力提高。causal NTR仍为null，不能将全部收益归因于Skill复用。
