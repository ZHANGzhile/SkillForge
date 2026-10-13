# Interview Sprint 后续：程序不变，验证引用与发现接口

2026-10-13，用户要求继续完成原 Sprint 闭环。原 [零收益报告](INTERVIEW_SPRINT_RESULTS.md)、所有 formal 数据与源码、失败/拒绝路径完整保留；本文件与新结果目录不回写原结论。

预算沿用 **09:06:38 UTC 起、16:06:38 UTC 截止** 的七小时上限，以及累计 4M tokens；已消费 **1,042,947 tokens**，不恢复或重置。P11 与上一轮模型均已结束，GPU 无实验租约。

根据此前独立 **dev** 可见性诊断，固定 main-v3 五次混淆展示名称和执行 ID；没有使用原 validation/test 反馈挑选程序。原程序来自六条真实轨迹，本次不重新计算或声称第二个新 Skill。

单一 metadata 修订将 name 设置为原 skill_id，version 增加到 2、parent_revision 指向旧 VERIFIED 版本。逐项验证 procedure/inputs/postconditions/policy/boundary 不变；既有治理识别为 metadata_revision，语义指纹相等。保留描述以支持自然检索。程序准入通过等价证明继承，另跑八个独立 CPU Positive/Boundary/Negative/Fault 检查，不伪造一个“重新编译的 v2 候选”。

严格预声明三个阶段，不为结果继续搜索新变体：

1. **Metadata dev**：三个全新 dev 来源，旧名称 v1/精确名称 v2 同权重、原提示/Runtime、同一任务预加载配对。三例都必须真实正确执行 Skill、EOC 通过、每例至少省一次决策，且无违规。
2. **Discovery dev**：通过前项后，在另三个新 dev 来源上运行 PrimitiveOnly/StaticLibrary/ExperienceEvolution。唯一预声明的共用提示补充要求模型先搜索一次、排除写程序、复制精确执行 ID；三组相同提示、模型、Runtime、工具、初态、预算。Runtime 不代搜索/加载，不映射别名，不改模型动作。C 三例都必须自主 search→load→成功 Skill、EOC 通过，每例较 B 至少省一次决策；九臂均安全成功。
3. **新独立冻结与对照**：两项 dev 门通过后冻结新 protocol，沿用六主要来源、两旧只读保留来源、零退步/安全门、至少一次调用收益的原 Agent 准入规则；测试为九新实例/改写/边界/拒绝来源加两旧只读来源，各三方法，共 57 臂。来源提前独立声明，不将 dev 转成 formal，不反馈测试。自动激活/部署关闭。

后续结果仅能解释为**一条明确共用检索指令下，真实学习程序的复用表现**，不能称作原提示下自然自发检索成功，也不能回填上一轮收益。任何成功均与 Runtime-assisted/model-autonomous、错误引用、全部成本和回退分别统计；小样本仅探索性描述，不宣称显著性。

实现位于新 `skillforge/interview_reference/` 和 `scripts/run_interview_reference.py`，避免向原已冻结包追加源码。现有模型权重、EOC、原 Opportunity 门槛、原 DSL/Guard 均保留；无 SFT/DPO/RL。

当前里程碑：新 CPU 契约 **4 passed**。这只是 metadata/严格引用/无 Runtime 自动检索的工程验证，真实模型收益待验证。

## 完成状态

三个新 dev 来源/六真实臂及 224 checkpoint 已完成并独立审计。名称对齐后 ID 三例正确，但三例均以空 arguments 调用，被严格绑定检查拒绝；正确 Skill 执行 0，dev 门未通过。按预声明停止后续新提示与 formal 扩展，保留失败 RevisionMemory 和父目录。新增 220,722 tokens，累计 1,263,669；没有重置预算。详细结果见 [引用/绑定失败报告](INTERVIEW_REFERENCE_RESULTS.md)。
