# Contract-Guided Skill Invocation：预登记实施方案

2026-10-13，独立分支 `codex/contract-guided-invocation-20261013`。开始 14:41:40 巴黎时间，硬截止 16:41:40（12:41:40–14:41:40 UTC）。到时停止新增开发，交付现有证据。最新 main=`157aefd5e`；P11 和 Closeout 已阅读。GitHub Actions run 38394641131：Ubuntu pytest failure，Windows cancelled；这是继承的 CI 状态，不声称本轮修复全仓库 CI。

1. **冻结**：复用原六条真实轨迹生成的 VERIFIED v1，原 revision、DSL、模型权重、原 CatalogModel 系统提示、Gate、业务权限、独立 EOC 全不变。不追加 Prompt、重编译或训练；新源码、来源、协议及结果置于独立目录。
2. **适配器**：从 loaded VERIFIED 合约的 inputs 和 DSL 中实际引用的原业务工具 input schemas 推导严格字段类型/长度等约束；不携带默认值，无法推导则拒绝。动态 `execute_verified_skill` 要求精确 skill_id、revision、完整 inputs，额外键、缺失、类型错误、未加载、冲突版本及与公开任务不一致的绑定均拒绝。新工具是虚拟调用接口，不增加业务工具权限；有效动作由原 hydrate/Gate/execute 执行。模型 raw Action 不重写；返回程序结果和契约验证回执，任务 EOC 仍由外部独立核验。
3. **Trace**：保留每次原始 Action、上下文、判参、Gate、程序内工具及结果/故障、验证回执、预算和 SQLite checkpoint。模型显式选择、提供输入和决定 stop；没有自动补参、ID 修正或终态代决策。只扩展执行契约的虚拟调用入口，复用原 Runtime 函数代码，不重构原文件；本 dev 适配器不宣称支持 checkpoint resume。
4. **CPU 先行**：正确输入、缺失/错误类型/多余输入、未加载、错误/冲突 revision、业务 Gate 拒绝、工具故障、原权限、原 A 接口、公开推荐隔离。所有新增测试通过后才启动真实模型。
5. **九臂 dev**：三个全新来源（实例、请求改写、极端边界），每源 A/B/C；同模型、原提示、目录、任务、初态、能力与预算，顺序轮换 ABC/BCA/CAB。A 原精确预加载 v1 与旧接口；B 相同预加载与新 typed 接口；C 仅用 request 文本和公开目录元数据作词法推荐、按原能力筛选后辅助预加载，再给同一 typed 接口。C 的系统 search/preload 单列，不能称模型自主发现。三组均有预加载，不评估完全自主 discovery。
6. **预算/停止**：沿用每臂 12 decisions、65,536 tokens、search/load 各三，以及原累计 4M tokens 上限；继承 1,425,483 tokens，不重置。新截止早于旧总截止。无真实结构化执行或无调用成本改善即停止，不追加变体。保守正 dev 标准为九臂全部 EOC/安全、B 三源均结构化成功、每源相对 A 至少省一次模型决策。额外报告 C−A/C−B 和 token 成本；即使正 dev 也只保存探索性证据，不变更 Program/Agent Admission 或部署。
7. **交付**：独立审计重放原模型输出、SQL/checkpoints、费用和漏斗，生成 `INTERVIEW_SKILL_INVOCATION_REPORT.md`。失败和 primitive 回退完整保留，不把 CPU scripted 测试或系统辅助推荐当成模型自主技能学习。
