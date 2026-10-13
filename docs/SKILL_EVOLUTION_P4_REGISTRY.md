# P4：版本目录与原始 Agent 证据接入（2026-10-12）

本批补齐不可变注册/目录快照、废弃和祖先回滚，以及原始 Agent 证据到配对统计门的适配器。真实结果仍为 **NO_USEFUL_CANDIDATE，0 个新 Skill**。目录操作只生成选择快照，没有改动正在服务的目录，没有新 Agent 准入或隔离激活。

前批静态/动态验证和统计方法见 [P4 治理说明](SKILL_EVOLUTION_P4_GOVERNANCE.md)。本批 [工程报告](../results/skill-evolution/v1.2/development/p4-registry-20261012/report.json)与[独立审计](../results/skill-evolution/v1.2/development/p4-registry-20261012/evidence-audits/74ea582059366dcc35155060d0a3db67d52cd7c95ce4e3d7da585038ede23183.json)均已保存。

## 不可变目录管理

`skillforge/skill_evolution/registry.py` 使用内容寻址的 registrations/snapshots，不修改 legacy revision-v1、Catalog 或旧结果。所有操作显式返回新 snapshot ID，没有可悄悄覆盖的 latest 指针。

| 操作 | 约束与证据 |
|---|---|
| Legacy import | 精确绑定现有 VERIFIED Catalog，保留旧来源范围，不算本批程序/Agent 准入 |
| Program registration | 独立重放正式程序准入回执；重新审计真实 learn、机会筛选与 TraceCompiler；候选必须匹配，不接受工程/合成候选冒充 |
| Publication | CANDIDATE → VERIFIED 生成新的 Catalog revision hash，原候选字节不变；注册同时绑定提案与发布版本 |
| Revision | 保持精确父版本、program lane 与 Boundary 不变；父版本必须 VERIFIED；精确/潜在重复暂时均阻止直接注册 |
| Retain parent | 新快照保留同一 Catalog hash，并保存零候选原因、来源和父快照 |
| Deprecate | 在新快照移除指定精确版本，重新检查依赖；旧快照不变 |
| Rollback | 只能选当前父链上的既有祖先；新快照记录当前父与回滚目标，不改写任一祖先 |

每个选中 Skill 只允许一个 VERIFIED 版本，依赖闭包须完整。当前程序注册仅支持已有的直线只读 lane；组合、metadata publication 与 Boundary publication 尚无正式入口。

`provenance.py` 在注册之前重新验证 P2 原始集合、固定 adapter 声明、历史 controller 费用、每条轨迹的动作/工具因果关系，以及筛选和编译结果。候选 hash 自洽不等于来源可信。注册入口存在，但由于真实候选为零，**正式成功注册分支尚未用真实候选实测**；本批实际验证的是 legacy import、零更新和工程拒绝路径。

## 原始 Agent 证据

`agent_evidence.py` 在 CPU 上用已保存的原始模型响应重放 Runtime；不加载权重、不重新生成响应。

- 核对受支持的 Runtime/工具/验证器源码、任务、完整模型设置与公共提示、精确目录与执行预算。
- 原始响应重新解析为 Action，必须与已保存动作相同；每步上下文和 messages 必须由此前实际工具观察重建。
- 在独立 SQLite 环境重放动作、search/load/Gate/Skill/工具路径，逐个比较 durable checkpoint、工具回执、完整数据库、对象/RNG/fault 状态与最终结果。
- 重算 controller 的每次推理前批准、累计 token 预留/结算及最终费用，保留原模型费用和此次 CPU 重放费用的区别。
- 独立 workflow EOC 与 Safety 重算；分别报告 autonomous EOC、Runtime-assisted EOC 和 intervention counts。

这证明保存的响应、动作、工具效果、checkpoint 和账单互相一致，**不是对生成过程的硬件证明**。token 数来自已结算 worker/controller 记录，未从解码文本重新推算完整生成 tokens。真实采集来源与共享预算仍由原采集审计负责；不完整/中断、未知费用、写入或故障轨迹不在本批 Agent 重放支持范围。

## 配对门接入与边界

`declare_evidence_protocol` 固定完整 validation 案例与 stable 分区、同模型/Runtime/提示/源码/限制、两份 Catalog、同初始数据库/授权身份和共同累计预算。`audit_paired_files` 从两个不同原始目录重放轨迹，重新建立配对计数，再送入原 source-group 统计门；`audit_paired_report` 再次从原始文件重算整个报告。

train/dev/test 不能进入 Agent admission validation；source_group、task 与实体必须由来源账本预先拥有。stable_validation 不增加 primary 样本。费用按预声明的任务顺序、baseline 然后 candidate 累计，不允许为每臂重置预算。两臂需完整保存相同的 collector checkpoint/admission 格式。

这里完成了 **raw evidence → audited pair → statistical gate**，但没有实现 P5 正式配对采集控制器、正式 Agent admission receipt 或 activation controller。所有返回仍明确 `agent_admitted=false`、`isolated_activated=false`、`deployed=false`。单独提交计数、重算报告 hash、统计门通过或程序 VERIFIED，均不能激活目录。

## 本批实际结果

原六条真实 train 轨迹完整动作重放通过：**6/6 EOC、6 autonomous、0 assisted**，原费用为 **21 次模型调用 / 68,906 tokens**。独立重算筛选和编译仍为零机会/零候选，没有补造有利轨迹或降低门槛。

快照链为 `LEGACY_IMPORT → RETAIN_PARENT → engineering DEPRECATED → engineering ROLLBACK`。保留和恢复目录 hash 均为 `d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa`。工程分支的废弃/回滚不代表真实业务废弃或部署操作；历史静态程序仍按原来源导入。

基线快照/注册原始字节核对通过。工程程序回执被正式注册入口拒绝，真实 train 被 validation 协议拒绝。本批执行 15 次 CPU 重放工具调用，独立事后审计再执行 15 次；新增真实模型调用/tokens 均为 **0**。共享真实模型累计仍为 **537,296 tokens / 1,904.82 秒采集墙钟**，CPU 测试与重放另计。

本批定向测试 21 项通过。全量独立源码副本 **411 passed / 1 skipped / 2 upstream warnings**（69.72 秒），正式 A/B 的 86/100 个冻结源码、历史文件保护及固定 main-v3 adapter 核验均通过。[独立预检](../results/skill-evolution/v1.2/development/preflight-20261012-P4-registry/preflight.json)。

## 复核与下一步

```powershell
.venv/Scripts/python.exe -m scripts.verify_skill_evolution_registry --compiler-run results/skill-evolution/v1.2/development/p3-trace-screen-20261012 --output <fresh-output>
.venv/Scripts/python.exe -m scripts.verify_skill_evolution_registry --run results/skill-evolution/v1.2/development/p4-registry-20261012
.venv/Scripts/python.exe -m pytest tests/test_skill_evolution_registry.py tests/test_skill_evolution_agent_evidence.py -q
```

旧工程/真实模型结果使用各自注册的源码；新增 auditor 模块不追写旧 Runtime 身份。重放入口拒绝执行器或 auditor 与声明版本不符；需要旧版本时使用归档源码。日志仍为单控制器实现，不声称支持多写者事务。

下一步实现 P5 同后端 A/B/C 与 No-History 的采集控制器、共享累计费用和三轮父链；在新成本 smoke 后冻结正式 protocol，并补 Agent admission/isolated activation 入口。真实新 Skill 的正式程序/Agent 验收等待符合原效益门槛的 learn 证据；若三轮均无更新，也应完整报告并保留父目录。返回值绑定、写入验证、组合和 RevisionPlanner 仍未完成；Workbench 新版尚未扩展。
