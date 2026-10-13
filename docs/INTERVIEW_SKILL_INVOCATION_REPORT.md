# Contract-Guided Skill Invocation Sprint

**结论：直接 execute_verified_skill 调用未通过预登记 dev 门，停止扩展。 Agent Admission=false，Activated=false。**

另有需要保留的正向观察：B/C 在新 Schema 暴露下通过旧 type=skill 路径真实执行候选并完成任务。它是 schema exposure 下的旧路径复用证据，不是直接新工具调用成功。

## 1. 研究假设与冻结

固定 main-v3 和已验证真实经验程序，检验将动态 Skill 调用转成固定工具名＋精确 ID/revision 枚举＋严格 inputs Schema，是否减少模型的 ID 误用和漏参，并在计入全部决策后获得收益。不是新 Skill 归纳或模型训练实验。

起点 main=`157aefd5e`，独立分支 `codex/contract-guided-invocation-20261013`。巴黎时间 14:41:40 开始，16:41:40 硬截止；继承 1,425,483 tokens，累计上限 4M 不变。Protocol `46597320ee103c61341db31c616bd05722dfc84f03683f914d28691f376b8fd3`。

原 VERIFIED v1 `trace_dae7a91522975618` / `f36dbea4509b554eaa86ea9820a05882704f1ac48aa8f7975c1398b8f7aef011` 原字节复用，没有新版本、重编译或训练。P11/旧 Runtime/安全规则/独立 EOC 不修改。main CI run 38394641131：Ubuntu pytest failure、Windows cancelled；本轮不声称全仓库 CI 已绿。

## 2. 新旧接口结构

A 原始预加载接口要求 type=skill、name=动态 skill_id、arguments=业务输入。B/C 在 available_tools 提供固定名 execute_verified_skill，arguments 必须有精确 skill_id、revision、inputs；inputs 的类型和约束来自合约实际引用的原业务工具 schema，去掉默认值。未知类型不能猜测。

模型 raw Action 不重写。适配器验证加载状态、版本、必填、严格类型、额外键和与公开任务的一致性后调用原 hydrate/Gate/DSL；业务调用仍经过原工具 Schema、原权限和 ownership Guard。错误原样保留。返回程序结果及 PROGRAM_VERIFIED/FAILED 契约回执，任务完整 EOC 仍由外部 SQLite 真值核验，不能由候选/回执自定义。

这是提供给固定 HF 模型的动态 JSON Schema 和执行时严格校验，**不是生成时的 grammar-constrained decoding 或强制 tool choice**。原系统 Prompt/模型 Action schema 保留旧 Skill 路径；旧路径结果单独统计，不计入结构化接口的正证据。

三个条件的公开 protocol 字段分别带有 A/B/C 标签，用于绑定执行身份；它也是随接口共同变化的上下文因素。因此这里只报告整个接口条件下的观察，不能把改善独立归因于某个 Schema 字段或格式。

## 3. 三个独立 dev 来源的全部 A/B/C 数据

实例、请求改写、极端业务边界三个全新来源；同一来源共享任务、初态、模型、原提示、业务能力和预算，按 ABC/BCA/CAB 轮换。A/B 精确预加载同一 v1；C 仅按公开 request 和目录元数据作词法推荐，按原只读能力筛选并辅助预加载，再提供相同 typed 工具。C 的推荐信息单独显示。三个条件都有系统提供的 Skill 可见性，不是自主发现实验。

| 来源 / 变体 | 方法 | 完整/自主 EOC | calls | tokens | 业务工具 | 结构化选择/有效输入/成功 | 错误 |
|---|---|---|---:|---:|---:|---|---|
| is13-source-161001 / instance | A | 0/0 | 11 | 53,385 | 6 | 0/0/0 | skill_not_loaded, skill_not_loaded, not_found |
| is13-source-161001 / instance | B | 1/1 | 2 | 7,840 | 5 | 0/0/0 | 无 |
| is13-source-161001 / instance | C | 1/1 | 2 | 8,436 | 5 | 0/0/0 | 无 |
| is13-source-161002 / paraphrase | B | 1/1 | 2 | 7,782 | 5 | 0/0/0 | 无 |
| is13-source-161002 / paraphrase | C | 1/1 | 2 | 8,378 | 5 | 0/0/0 | 无 |
| is13-source-161002 / paraphrase | A | 1/1 | 10 | 48,638 | 5 | 0/0/0 | skill_not_loaded, skill_not_loaded |
| is13-source-161003 / boundary | C | 1/1 | 2 | 8,432 | 5 | 0/0/0 | 无 |
| is13-source-161003 / boundary | A | 0/0 | 11 | 53,365 | 6 | 0/0/0 | skill_not_loaded, skill_not_loaded, not_found |
| is13-source-161003 / boundary | B | 1/1 | 2 | 7,836 | 5 | 0/0/0 | 无 |

| 方法合计 | EOC/自主 | calls | tokens | 工具 | 模型 search/load | 系统推荐/预加载 | 违规意图/原始尝试/实际违规 |
|---|---|---:|---:|---:|---|---|---|
| A | 1/3 · 1/3 | 32 | 155,388 | 17 | 3/3 | 0/3 | 0/0/0 |
| B | 3/3 · 3/3 | 6 | 23,458 | 15 | 0/0 | 0/3 | 0/0/0 |
| C | 3/3 · 3/3 | 6 | 25,246 | 15 | 0/0 | 3/3 | 0/0/0 |

Autonomous EOC 只表示模型决定终态且无 Runtime intervention；不能等同自主检索。所有 Runtime-assisted EOC 和 intervention 单列在 delivery-summary。A/B 预加载由实验控制，C 推荐/预加载由系统完成；模型仍须自行选择、供参和 stop。

原环境的 policy-attempt/actual-violation 标签与错误对象尝试分开报告：{'A': 2, 'B': 0, 'C': 0}。not_found 未触发原 policy-attempt 标签，不意味着对象绑定正确；独立 EOC 保留 receipt_object_or_owner_mismatch 失败。

## 4. Skill Selection Funnel

| 方法 | 可见 | 选择任意 Skill 接口 | 输入通过任意接口 | Skill 执行成功 | Skill 成功且完整 EOC | typed Schema 可见 | typed 选择→有效输入→成功 | primitive 回退任务 |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| A | 3/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0→0→0 | 3/3 |
| B | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0→0→0 | 0/3 |
| C | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0→0→0 | 0/3 |

漏斗按任务计数，末端 EOC 限于 Skill 真正成功的任务；全部任务 EOC 另列，避免 primitive 回退造成假漏斗。

## 5. 原始 Action、配对收益和费用

以下来自每臂首个 Skill 动作；未选择 Skill 时给出首个实际 primitive 动作。完整逐步原始输出、Trace、程序结果和回执见对应 result.json。

- is13-source-161001 / A，error=skill_not_loaded：
```json
{"type": "skill", "name": "Order investigation dossier", "arguments": {"order_id": "IS13-O-161001"}}
```

- is13-source-161001 / B，error=None：
```json
{"type": "skill", "name": "trace_dae7a91522975618", "arguments": {"order_id": "IS13-O-161001"}}
```

- is13-source-161001 / C，error=None：
```json
{"type": "skill", "name": "trace_dae7a91522975618", "arguments": {"order_id": "IS13-O-161001"}}
```

- is13-source-161002 / B，error=None：
```json
{"type": "skill", "name": "trace_dae7a91522975618", "arguments": {"order_id": "IS13-O-161002"}}
```

- is13-source-161002 / C，error=None：
```json
{"type": "skill", "name": "trace_dae7a91522975618", "arguments": {"order_id": "IS13-O-161002"}}
```

- is13-source-161002 / A，error=skill_not_loaded：
```json
{"type": "skill", "name": "Order investigation dossier", "arguments": {"order_id": "IS13-O-161002"}}
```

- is13-source-161003 / C，error=None：
```json
{"type": "skill", "name": "trace_dae7a91522975618", "arguments": {"order_id": "IS13-O-161003"}}
```

- is13-source-161003 / A，error=skill_not_loaded：
```json
{"type": "skill", "name": "Order investigation dossier", "arguments": {"order_id": "IS13-O-161003"}}
```

- is13-source-161003 / B，error=None：
```json
{"type": "skill", "name": "trace_dae7a91522975618", "arguments": {"order_id": "IS13-O-161003"}}
```

A 组错误对象的原始动作（没有被接口修正）：

- is13-source-161001 / A，error=not_found：
```json
{"type": "tool", "name": "get_shipment", "arguments": {"order_id": "IS161001"}}
```

- is13-source-161003 / A，error=not_found：
```json
{"type": "tool", "name": "get_shipment", "arguments": {"order_id": "IS161003"}}
```

| 来源 | 比较 | ΔEOC | 节省 calls | 节省 tokens | 回退/退步 |
|---|---|---:|---:|---:|---|
| is13-source-161001 | B-A | 1 | 9 | 45545 | regression=False |
| is13-source-161001 | C-A | 1 | 9 | 44949 | regression=False |
| is13-source-161001 | C-B | 0 | 0 | -596 | regression=False |
| is13-source-161002 | B-A | 0 | 8 | 40856 | regression=False |
| is13-source-161002 | C-A | 0 | 8 | 40260 | regression=False |
| is13-source-161002 | C-B | 0 | 0 | -596 | regression=False |
| is13-source-161003 | B-A | 1 | 9 | 45529 | regression=False |
| is13-source-161003 | C-A | 1 | 9 | 44933 | regression=False |
| is13-source-161003 | C-B | 0 | 0 | -596 | regression=False |

节省为基线减候选，负数表示更贵；只有 joint EOC 成功的比较才能解释为有效完成成本。重复原调用、错误选择、重新 search/load 和 primitive 回退均纳入。三个来源只提供三个独立单位；不把九臂或 checkpoint 当九个/更多独立样本。

B−A 和 C−A 的 joint-success 来源仅为：is13-source-161002。其余行是 EOC 恢复与实际支出差，不能算双方有效完成时的成本效应。C−B 逐源决策差为零、tokens 多 596，没有观察到系统推荐在已预加载条件上增加收益。

本轮实际新增 204,092 tokens / 44 次模型决策 / 47 次业务工具尝试，累计 1,629,575 tokens。采集墙钟 519.81s；最初仅模型加载失败消耗 20.98s、零 tokens。GPU utilization hours 未测量。

CPU 工具单列：最终采集静态覆盖 96，最初失败前覆盖 12，独立响应重放 47，原程序准入重放 31。CPU 单元/脚本夹具工具数未单测，不计真实模型样本。18 项接口测试及新增完整 RPC 回归共 19 项通过；原失败和所有测试日志保留。

最初失败原因是旧 snapshot 的 REQUIRED 字段集合拒绝 invocation_adapter/invocation_mode，推理前中断。v1 目录完整保留；续跑扩展 `4fb5fdad20e16846f1c5b94299e482ecfa45ed2a834f01fd0a170769350494d7` 只扩大快照字段验收，未改变接口、候选、模型、案例、预算或门槛。v2 独立审计 9 臂/235 checkpoints，通过原始 Action/实际 SQLite/参数/Gate/Trace/费用重放；旧失败文件 byte hashes 全部核对。

## 6. 能支持和不能支持的主张

本样本没有满足预登记的直接结构化工具调用成功＋决策收益条件；保留原程序和原未准入状态，不再调接口、Prompt 或扩展来源。完整 EOC/减少错误开销不能替代直接新工具调用。

同时，原始输出证明 B/C 自行填写精确 ID 和业务参数，经原 Gate/DSL 真实执行了已学习 Skill，随后由模型 stop。这是首次 schema-exposure 条件下的有效程序复用观察，应与旧 Prompt-only 阴性结果并列保留。三源配对仍很小，且接口 Schema 与公开 protocol 标签共同变化，无法独立定位哪一条 Schema 信息造成改善，也没有与同条件 PrimitiveOnly 做收益比较，不能将它提升为原主实验 Agent Admission。

不可声称模型学会自主发现、权重改善、正式泛化、安全性总体保证、开放世界自进化，或将 CPU/系统推荐算成 Agent 学习。动态 schema 只是本次接口暴露方式；没有约束解码。因此阴性结果也不能证明原生 tool-calling/约束生成永远无效。

## 7. 后续方向与面试追问

后续只能另立协议，考虑动态输入契约与生成时约束解码的独立比较，或研究任务到 Skill 的自主选择；本轮不实施、不训练、不据正式测试反馈调参。面试时可追问：合约只有输入名时如何推导严格类型？为什么不能沿用业务工具默认值？为什么输入正确仍不能绕过 Gate？如何区分预加载、系统推荐和模型选择？程序回执为什么不是独立 EOC？如何核算错误/回退成本、并保留无收益结果？

原始证据目录：`results/skill-invocation/20261013-v2`。关键文件：protocol.json、controller-extension.json、report.json、independent-audit.json、continuation-independent-audit.json、delivery-summary.json、source-ledger/ 和 dev/。保留 v1/report.json 的零推理失败；没有正式 test/部署。
