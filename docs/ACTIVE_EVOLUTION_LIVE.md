# Active Self-Evolution v1 实施进度

更新时间：2026-10-02（Europe/Paris）。当前：四方法控制器、学习进程隔离和数据准备已接通；正式实验未开始。

## 当前完成内容

- P0 基础：配置草案、原有10,699个跟踪文件SHA-256清单、六世界可执行性变化见证、真实模型开发成本测量与缩减清单。
- P1 基础：严格EvidenceView、manifest成员检查、有限schema与八种类型受限运算符、最多双条件AND、确定性gap聚类、有限假设生成、H_other、log-space belief、可复算/去重/失配检查。终态诊断与主Boundary输入隔离。
- P2 基础：EIG、成本/风险评分、固定排序、预算/停止、预算内收敛率与截断平均查询数统计。
- P3 基础：独立隐藏子进程、SQLite backup clone、固定程序探针、工具业务guard、原库不变与故障队列隔离检查。
- P4 开发原型：四方法EvolutionController、事务式增量BeliefJournal、逐查询检查点、边界验证、独立immutable Registry、发布后新实例执行。学习参数接入配置；No Adaptation不查询，Passive按预定流交互并报告全部交互成本，仅从新失败学习。
- 数据准备：dataset-v3六世界×五种子共30个不可变数据包、10,044条任务，绑定真实冻结父Skill。CPU探索/验证覆盖公开状态组合；模型层单独声明8个代表场景及4个稳定锚点。模板、对象、请求及实例身份跨split隔离，语义状态域有意共享。数据生成不等于正式实验冻结。
- 学习进程：只接收公开候选与seed/explore证据，验证器持有私有任务与探针；拒绝私有文件、oracle导入、网络与子进程访问。这是防误读的Python协作式审计，不是对抗恶意原生代码的操作系统沙箱。
- 验证准入：绑定父Skill、数据manifest、验证器代码和逐案例探针，重算计数、校验哈希；H0保留父版本，不发布成“新能力”。放宽规则受旧策略中未变化的安全底线约束。
- Retention与只读敏感性：逐任务配对统计、固定证据路径的0.90/0.95/0.99重加权已实现；正式连续epoch结果仍待完成。
- 冻结程序执行：Evaluator探针与发布后执行复用父Skill的原DSL、输入绑定和后置条件；仅替换边界gate。强制适用性探针可绕过旧Skill gate，始终保留环境业务guard。旧工程简化探针仅作为兼容入口保留。

## 已运行验证

1. 新增覆盖四方法、进程访问边界、真实父版本、配置、逐案例审计、数据覆盖、Retention、原子写入及冻结DSL执行的检查。独立源码副本完整回归 **191 passed、1 skipped**，回执见RESULTS记录。副本不含data/results/.runtime/本地部署配置。
2. 原有10,699文件重新SHA审核通过，没有修改旧代码、历史报告或实验产物。
3. W1工程闭环：2条seed、8次主动查询，12条validation与6条stable_validation，候选获准。发布后新实例检查及恢复重跑通过。
4. 六个独立旧策略真实模型成本任务完成；原main-v3 SFT adapter身份一致。
5. 新增顶层模块会改变旧工作台的代码身份。确认没有queued/running任务后，仅刷新了工作台API进程；模型服务、权重与部署配置未替换，worker恢复健康。回执为development/workbench-refresh.json。
6. protocol-v5：W3/W6各四方法、开发seed=701、每个学习方法最多4次查询。No Adaptation为UNCHANGED，其余均INCONCLUSIVE；没有适应成功或方法优势可报告。8组恢复重跑通过，104条探针文件内容及修改时间完全不变。
7. protocol-v5六条学习轨迹完成三档只读敏感性分析，没有新增查询或读取test。W6 Active在0.90/0.95下有一步最优候选排序变化，三档均未收敛。
8. 检查点及Registry改为先完整写入、flush/fsync，再同目录原子发布且不覆盖竞争写入；中断和并发竞争有专门回归。
9. coverage-smoke-v1采用完整CPU开发规模：W3 Active 7次查询通过，Passive/Random各20次未收敛；W6三种学习方法均未收敛。W3在DSL接线后独立重复仍7次通过，加载Registry后4个全新实例执行符合候选规则。详细限制见RESULTS。

工程闭环的世界、特征域与任务结构是人工声明的；它证明组件接线与证据流，不证明主动学习效率优于随机，也不代表主项目失败被修复。

## 成本门槛

原草案合计3,672条真实任务，小样本P95外推约43.23小时。第一版缩减至732条但模型覆盖不足。当前W3/W5/W6、一个预定种子、独立8类代表场景，model_validation=8，形成872条基础任务、88条全局重试预留，旧smoke外推约11.30小时/1,230万tokens。实际新世界上下文长度可能更高，需要新Runtime smoke后再次复核，当前正式入口保持锁定。

## 接下来必须完成的工作

1. 新模型Runtime实测确认当前代表场景方案能否满足12小时/2,000万tokens门槛。当前11.30小时仍依赖旧策略成本样本，不能最终冻结。
2. 多gap调度、跨epoch协议；Passive开发流来自预定控制任务，尚非真实模型自然交互流。
3. 扩展其余世界开发接线检查、正式运行身份冻结、独立离线重放。当前验证器可从缓存探针哈希和逐案例记录复算，不等于已在独立环境重执行全部实验。
4. 新规则模型Runtime/Policy view、模型独立准入、Cost Gate最终冻结。现有main-v3服务系统提示包含旧规则，不能直接用于新世界正式协议。
5. 六世界×五种子×四组CPU实验、限额真实模型双评测、正式Retention及连续epoch。
6. Evolution工作台页面与浏览器验收。实验Boundary发布不代表主Agent已激活更新。

P8 Continual QLoRA不属于本轮v1必须验收范围。此记录是阶段交付，不将基础模块测试通过写成P0–P7全部完成。

## 运行入口

```powershell
.\.venv\Scripts\python.exe -m scripts.run_active_evolution --engineering
.\.venv\Scripts\python.exe -m scripts.run_active_evolution_protocol --output results/active-evolution/v1/development/protocol-next --worlds W3 W6
.\.venv\Scripts\python.exe -m scripts.prepare_active_evolution_data --output results/active-evolution/v1/preparation/dataset-next
.\.venv\Scripts\python.exe -m scripts.prepare_active_evolution --audit
.\.venv\Scripts\python.exe -m scripts.check_active_evolution
```

旧纵向入口不加`--engineering`会明确拒绝正式运行。工程输出绑定代码/配置；有实质变更后使用新`--output`目录，不覆盖已有结果。旧vertical-slice-v1、protocol-v3/v4/v5已保留对应源码快照；上面的旧纵向命令也需追加新输出目录，不能用当前源码冒充原运行身份。

本轮遇到的Windows命名管道限制通过子进程临时文件通信解决；SQLite context manager不自动关闭连接造成的文件占用已改用显式close。Belief快照的tuple/list序列化不一致也已修复，并有恢复测试覆盖。
