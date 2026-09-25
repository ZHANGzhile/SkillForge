# SkillForge

将 Tool-Use 轨迹转化为带适用边界、可执行、可验证的技能，并研究这些轨迹是否能改善模型的动作决策。

目标是完整的 Skill 学习研究项目，包含执行、技能学习、真实 Student、QLoRA SFT、DPO 和训练后独立评测。当前已有**正式研究工作台、持久化执行服务、三类冻结 Skill、216 个隔离任务、真实模型 B0–B3基线、正式SFT/DPO权重、训练后双评测与稳定性结果**。研究评测完成；真实私有工作台验收4/6，整体交付尚未通过。

2026-09-19核验：同协议78个test任务，Base/SFT/DPO合格率分别44.9%/73.1%/70.5%，固定候选决策准确率8.3%/91.7%/91.7%，实际违规均为0；复合任务均0/9。真实HF DPO网页服务的HTTP验收在两个退款案例失败，后续签收和最终ZIP未完成。详见[量化结果](docs/QUANTITATIVE_RESULTS.md)、[研究报告](docs/RESEARCH_REPORT.md)与[面试复盘](docs/PROJECT_INTERVIEW_TRACE.md)。

GitHub：<https://github.com/ZHANGzhile/SkillForge>。完整实验结果、训练适配器与检查点随仓库归档；首次clone后执行`git lfs pull`。上传范围和复现方法见[GitHub归档说明](docs/GITHUB_PUBLICATION.md)。

2026-09-25实施更新：针对退款循环与写后漏验证，已构建只来自train的恢复课程，SFT样本由355增至1,267，并启动独立main-v3训练。新实例测试集在训练前冻结；候选须先达到validation准入条件，再自动执行新实例双评测、原六项真实HTTP验收、浏览器签收和ZIP校验。**新模型效果尚未得出，原4/6失败记录保留。** 已通过102项源码独立回归（1项跳过）及训练期间桌面/手机页面检查。方案与复现入口见[恢复训练说明](docs/RECOVERY_V1.md)，实时进度见[训练进度](docs/TRAINING_LIVE.md)。

本机双击根目录 **启动项目.cmd**，打开 **http://127.0.0.1:8080**。工作台提供数据集 / 自定义任务、实时轨迹、运行历史、Skill 契约、真实实验报告、取消 / 隔离重试及轨迹 / 数据库下载。原演示保留在 `/skill-demo`，工程接线检查位于 `/engineering`。

已完成真实自由 Action 对照：B0 **35/78**、B1 **45/78**、B2 **38/78**、B3 **37/78**、去 Gate **38/78**；各组实际 Skill 调用为 0，尚未验证执行复用收益。另一个明确受限的 Skill 目录协议在 27 个 validation 场景通过，不能与前述自由协议混算。详见 `docs/REAL_EVAL_REPORT.md` 和 `docs/SKILL_DEMO_ACCEPTANCE.md`。

## 快速开始（PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m skillforge.cli demo
.\.venv\Scripts\python -m uvicorn skillforge.api:app --host 127.0.0.1 --port 8080
```

如果环境设置了 `PIP_NO_INDEX=1`，安装前可在当前 PowerShell 会话设置 `$env:PIP_NO_INDEX='0'`。需要网络可以访问软件源。

浏览器打开 `http://127.0.0.1:8080` 使用正式工作台；`/docs` 查看 API。`/api/v1/runs` 接受冻结任务 ID 或完整 Task / Expected Outcome Contract。任务不是从自由文本猜测期望结果；自定义任务可编辑请求、参数、初始业务状态和预期结局。

任务及事件持久化在 `results/workbench/jobs.sqlite`；每个 run 拥有独立的业务 SQLite 和轨迹。取消等待当前模型请求返回，在下一次动作 / 工具执行前生效；已提交 mutation 不回滚。服务中断后，已排队任务恢复执行，原运行中任务标记 `interrupted`，必须通过显式隔离重试生成新 run。提交时支持 `Idempotency-Key`，同键异参返回 409。模型配置或代码发生变化后，原排队任务拒绝无记录地切换版本。

服务使用一个 worker；不要配置多个 Uvicorn worker。支持环境变量 `SKILLFORGE_JOB_ROOT`、`SKILLFORGE_DATASET`、`SKILLFORGE_BUNDLE`。默认数据集和冻结包为本机已验收产物；全新机器先按下文生成数据、采集 train 轨迹并 prepare 冻结包。应用绑定 localhost，用于单用户本地合成环境研究。原 `/tasks`、`/benchmark/run` 为旧兼容入口，其 BackgroundTasks 不具备新队列的恢复语义。

## 运行结果

`demo` 每次创建独立目录，终端返回 `pipeline_summary.json` 的绝对路径。目录包括：

- 训练分区的成功轨迹和刻意失败的工程轨迹；
- 地址 Skill 及正例、反例、边界验证明细；
- B0–B3 四条执行路径的接线测试；
- 固定候选 Skill/refuse/escalate 决策测试；
- 经 action-level 筛选的 SFT 工程样例；
- 每次运行的配置、逐任务 JSONL、完整工具审计和 errors.csv。

这些结果均带 `engineering_only: true`。脚本策略只验证工程行为，不用于声称 Memory、Skill、SFT 或 DPO 提升了模型能力。当前 smoke tasks 在分区间共享模板，不能用来证明结构泛化。

## 连接真实 Student

```powershell
$env:SKILLFORGE_MODEL_URL='http://localhost:8001/v1'
$env:SKILLFORGE_MODEL_NAME='实际模型名称'
$env:SKILLFORGE_API_KEY='local'
.\.venv\Scripts\python -m skillforge.cli model-smoke
.\.venv\Scripts\python -m skillforge.cli benchmark
```

`.env.example` 为配置示例；程序读取进程环境变量，不自动加载 `.env`。smoke 只确认 OpenAI-compatible chat endpoint 和 JSON Action 能力，不代表完成 vLLM adapter、许可证、GPU 或训练兼容性验证。模型客户端绕开系统 HTTP 代理，适用于本地/直连 endpoint；代理部署需要额外配置。

工程测试单独运行：`python -m skillforge.cli benchmark --scripted`。不传 `--scripted` 才使用真实模型。

## 已实现的关键约束

- 有限 DSL：call/assert/finish，最多 12 节点，白名单工具，无任意代码。
- 三态 Gate 无 I/O；Runtime 按固定映射补齐状态，成本包含 Gate 和 Skill 内部调用。
- SQLite 事务内权限与 policy 复检，写工具幂等键，同键异参拒绝，提交后响应丢失可安全重试。
- Expected Outcome Contract 分别约束 completed/refused/escalated，检查状态与必要证据。
- 分开记录模型违规尝试、实际违规及未知适用性；没有反事实实验时因果 NTR 为 null。
- Compiler 强制 train 数据、多个成功轨迹与失败轨迹，并与集中式 policy 合成边界；条件保存来源。
- Skill validation 仅接受 validation；Memory/SFT/DPO 不接受 test 数据。
- Skill metadata 中的 validation 统计不进入模型候选上下文。
- Registry 版本不可变；验证生成新版本。最小实现为文件式 Registry。

## 当前领域范围与限制

8 类实体已建表，但字段为纵向闭环所需最小集；开发版使用标准库 sqlite3，尚未迁移 SQLAlchemy/PostgreSQL。每订单一笔支付、一条物流；地址有效性是合成环境的长度规则。取消已付款订单不自动退款。

Compiler 支持地址、取消和退款的受限归纳，校验成功轨迹的读取/写入/复核顺序；只有业务失败反例用于边界学习，超时本身不会产生禁止条件。已支持最多两轮的领域契约修订，尚无开放域 LLM 合成、递归 Skill composition 或 embedding 检索。复合任务目前由 Runtime 决策选择 primitive 操作；Raw Memory 使用词项相似度和任务族排序。

## 隔离实验（第二轮新增）

独立于旧 smoke suite，默认生成 **216 个任务：69 train、69 validation、78 test**。实例、订单和模板内容跨分区隔离；三分支组合仅出现在 test。清单包含文件哈希，读取时重新验证内容和隔离约束。

```powershell
.\.venv\Scripts\python -m skillforge.cli dataset --output data/experiment-v1 --instances 3
$collected = .\.venv\Scripts\python -m skillforge.cli collect --dataset data/experiment-v1 --output results/sources --scripted --failure-fixtures | ConvertFrom-Json
.\.venv\Scripts\python -m skillforge.cli prepare --dataset data/experiment-v1 --source $collected.source_path --output results/frozen --scripted
.\.venv\Scripts\python -m skillforge.cli compare --dataset data/experiment-v1 --bundle results/frozen/frozen.json --output results/comparisons --scripted --ablation --repeats 3
```

`--failure-fixtures` 只允许用于显式脚本工程模式，故意执行错误动作以检查 verifier；不会伪装成模型产生的失败数据。实际模型链路配置 endpoint 后移除 `--scripted` 和 `--failure-fixtures`，重新 collect，并使用新的冻结输出目录。真实轨迹不足三个成功实例或缺少业务失败证据时，prepare 会报错；应继续采集真实训练案例，不能补入 test 数据。

`prepare` 将源轨迹绑定到 manifest 中的任务，核对原始状态、内容指纹和确定性 verdict。仅改 split 标签无法通过。B2 使用只从成功轨迹生成的 Naive Skill；B3 使用成功＋失败＋策略生成并通过 validation 的 Skill。B2 不受 validation 筛选影响。冻结包被篡改或来自其他数据集时，compare 拒绝运行。

`--ablation` 加入 B3-no-gate。结果包含 comparison.csv/json、A–E 分层统计、两类 Skill 的固定候选决策探针、每任务执行日志，以及多次重复全部成功的比例。`pass_all_repeats` 为描述性稳定性指标，不是 pass@k 或显著性检验。脚本比较仅验证框架，不能证明算法收益。

详见 `docs/EXPERIMENTS.md` 和 `docs/ROUND2_REPORT.md`。

## 退款与有界修订（第三轮新增）

`prepare` CLI 默认编译地址、取消、退款三类 Skill；可用 `--families modify_address cancel_order` 指定子集。旧的两类来源可能缺少退款失败证据，需要新目录重新 collect，不能覆盖旧冻结包。

退款 Gate 使用固定领域判断 `refund.amount_valid`：金额必须为正整数且不超过剩余额。它只计算已知观察和输入，不发起工具或模型调用。Executor 在 mutation 前计算并冻结预期累计退款额，再用 `get_payment` 的结果验证，避免把退款后的值再次相加。

候选验证失败时，prepare 最多执行两轮修订，并将全部历史写入冻结包。修订仅支持从 train＋policy 编译出的标准领域契约恢复边界或执行段；validation 用于选择修复段，不能提供训练轨迹。没有支持的修订、预算耗尽或持续基础设施故障时，候选最终标为 REJECTED。

单独验证/修订候选：

```powershell
.\.venv\Scripts\python -m skillforge.cli refine --dataset data/experiment-v1 --source PATH_TO_TRAIN_JSONL --candidate PATH_TO_CANDIDATE_JSON --output results/new-repair-run --scripted --max-refinements 2
```

每轮保存 `attempt-N.json`（契约、版本、反馈案例、变更段、源数据哈希），最终保存 `summary.json`；原始候选不修改。`--max-refinements 0` 只验证；超过2不允许。真实模型来源去掉 `--scripted`。

本轮报告见 `docs/ROUND3_REPORT.md`。

SFT/DPO已完成独立Windows CUDA环境中的正式NF4 QLoRA训练，权重在`results/training/main-v2/{sft,dpo}/adapter`。checkpoint恢复、私有Student接口和Base/SFT/DPO同协议双评测已实现；当前正在运行独立评测，不能提前宣称能力提升。原真实B0–B3先于正式训练完成。

运行进度查看`docs/TRAINING_LIVE.md`或工作台`/api/v1/training`；训练方法、来源边界和手工恢复命令见`docs/TRAINING.md`。已有后台流水线时勿再启动第二份GPU训练。

## 文档

- `docs/SKILL_DEMO_ACCEPTANCE.md`：可操作的真实模型Skill演示；双击根目录`启动演示.cmd`或访问http://127.0.0.1:8080/skill-demo。
- `docs/REAL_EVAL_REPORT.md`：首次完整真实五组结果；实际Skill调用为0，核心复用收益尚未验证。
- `docs/REAL_TRAIN_REPORT.md`：真实69任务采集、提示版本对照、三类Skill证据与冻结结果。
- `docs/LOCAL_STUDENT.md`：Ollama＋Qwen3 4B 本机服务启动与兼容性验证。
- `docs/DESIGN.md`：业务规则与已确认设计。
- `docs/PROGRESS.md`：实时阶段状态和验收记录。
- `docs/ISSUES.md`：困难、根因、解决方案及验证。

Docker 引擎启动后可执行 `docker compose up --build`。当前开发机尚未通过容器运行验收；CPU CI 配置已提供，但没有远端 CI 运行记录。
