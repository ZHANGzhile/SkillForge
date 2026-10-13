# Sprint 补充协议：公开接口说明能否解除参数绑定失败

2026-10-13。原 Sprint 和 metadata dev 的失败均保留。本次是另行预登记的探索性补充，不重启已停止的旧协议。唯一程序仍来自原六条真实训练轨迹；沿用 metadata v2 的精确 ID 名称和原有五读 DSL，不生成第二个候选。

根据前轮独立 dev 发现的空 arguments 错误，预先声明唯一一个共用系统提示变体：先检索一次；复制精确 ID/revision；按加载结果的 required inputs 从公开 parameters 逐键绑定。三组收到完全相同提示，Runtime/Guard/权限/模型权重不变，不自动搜索、加载、补参、纠正 ID 或终止任务。此条件下的复用属于明确接口说明下的 Agent 行为，不能回填原提示的自主发现结果。

先使用三个全新 dev 来源（新实例、请求改写、极端业务边界），每源 PrimitiveOnly / StaticLibrary / ExperienceEvolution 三臂。全部九臂须独立 EOC 成功、安全；C 的三个来源须由模型实际 search→load→成功执行 Skill，每例较 B 至少节省一次决策。任一失败则停止本协议，不追加提示变体、不使用正式来源、不放宽门槛。

仅 dev 全通过时，另行冻结六主要＋两旧保留 validation 来源，以及九主要＋两旧保留 held-out 来源。三组同权重、提示、Runtime、初态和预算，方法顺序轮换，统计单位为 source group。沿用原至少一次决策收益、六主要来源、零退步/安全门。所有开销包含检索/加载/错误/回退。实验规模探索性，不宣称显著性；不自动生产激活。

候选在任何推理前通过新独立 Positive / Boundary / Negative / Fault 各二沙箱和重放。来源账本与既有所有 Sprint 来源检查不重叠；源文件快照、计划 hash、旧失败 hash、模型原始输出和 SQLite/checkpoint 全保留，独立审计后报告准入。

预算沿用 09:06:38 UTC 起、16:06:38 UTC 截止，累计上限 4M tokens。已消费 1,263,669 tokens / 422 次决策 / 75 个真实臂，不清零。第四小时无候选停止规则已由约第 25 分钟的真实候选满足。GPU 串行租约，P11 完结且无租约后运行。不新增训练或修改历史 formal 文件。
