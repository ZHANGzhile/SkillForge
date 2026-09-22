# SkillForge 本地运行、恢复与交付手册

适用范围：Windows 本地单GPU、单工作台worker、合成业务数据库。所有命令从项目根目录运行。当前正式模型是固定Qwen3-4B基座加main-v2适配器；不能把GGUF权重替代为可训练基座。

## 先看状态，避免启动两份GPU任务

```powershell
Get-Content .runtime/training-pipeline.json
Get-Content .runtime/research-finish.json
Get-Content configs/training-runs.json
```

`at`是Unix秒，持续更新表示协调进程有心跳；`progress`反映子进程已落盘的任务或训练更新。模型正在处理一个长任务时，任务数可能数分钟不变；先检查日志和GPU状态，不要只因任务数未变就重复启动。

主流水线先运行smoke/SFT/DPO，再串行执行三组validation、冻结模型、三组test及去Gate消融。完成的训练阶段会审核配置、语料、源码和适配器哈希，审核通过后复用，不重新训练。

第二个协调器等待主流水线完成，取得同一GPU锁后执行预声明稳定性子集，再生成研究报告。它等待期间不加载模型。

完整交付协调器`python -m scripts.run_release_delivery`进一步等待研究完成，再按configs/deployment-selection.json的预声明validation规则选择SFT/DPO、串行部署、验收HTTP和浏览器、运行源码回归并打包。选择不读取test成绩。状态在`.runtime/release-delivery.json`，逐阶段日志在`results/release-logs/<时间戳>`。当前已有后台协调器时不要重复启动。

## 启动工作台

双击根目录`启动项目.cmd`，访问`http://127.0.0.1:8080`。活跃评测期间只启动工作台，真实推理提交被暂停，历史、Skill和报告仍可查看。

只恢复网页服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_project.ps1 -DashboardOnly
```

状态接口：`/api/v1/health`、`/api/v1/training`。任务接口：`/api/v1/runs`；完整API结构见`/docs`。

工作台数据保存在`results/workbench/jobs.sqlite`；每个运行的业务数据库、请求和轨迹在`results/workbench/runs/<run-id>`。不要删除该目录来“修复”显示问题，否则会丢失审计证据。

## 从失败处恢复主评测

确认没有仍活跃的原协调进程及GPU子进程后执行：

```powershell
.\.venv-train\Scripts\python -u -m scripts.run_training_pipeline
```

必须用模块启动形式`-m scripts.*`；`python scripts/evaluate_trained_student.py`可能使跨scripts包导入失败。

若子进程报错，主状态为failed，日志路径包含在message中。常见处理：

| 情况 | 检查与恢复 |
|---|---|
| Python模块导入失败 | 确认根目录、正确venv、使用-m；不重训已完成权重 |
| CUDA/显存错误 | 停止本项目外占用GPU的推理前先核对进程归属；保留基础设施失败文件，恢复相同协议 |
| resume身份不匹配 | 比较配置、语料、模型和代码；不要编辑identity.json绕过检查 |
| checkpoint损坏 | 保留现场，恢复已验证的前一个checkpoint并建立明确版本；不要拼接不一致优化器状态 |
| evaluation.json存在但任务文件缺失 | 不当作完成；恢复审核会拒绝，定位具体缺失文件 |
| JSON动作格式错误 | 这是模型能力/接口失败，保留轨迹；不能用脚本补答案 |
| 某个任务达到16步仍未结束 | 记录max_steps_exceeded，不因想提高成绩而改变冻结预算 |

所有改变执行语义、提示、模型、Runtime源码的修复，都可能要求新的评测版本。只修改文档、额外报告脚本或不影响执行语义的启动方式，不修改已完成训练身份。

## 恢复稳定性与报告

```powershell
.\.venv\Scripts\python -u -m scripts.finish_research_evaluation
```

如果主流水线已经failed，先处理主故障再启动。重复子集固定在`configs/stability.json`，不能看test成绩后换成容易成功的任务。主test记录为第1次，新增第2/3次均使用独立环境。

单独重建文档与图表：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-report.txt
.\.venv\Scripts\python -m scripts.write_research_report
```

没有完整comparison.json时，报告明确标记后训练评测未完成，只绘制已有真实基线和训练曲线。产物包括Markdown、来源SHA-256、PNG与SVG。

## 切换到正式私有Student

全部主评测、稳定性和发布证据审核通过后：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/deploy_trained_project.ps1 -Stage SFT
```

脚本在8002启动单worker HF Student，核对服务实际模型和adapter哈希，在8080绑定工作台。上面的命令是手动指定SFT的示例；自动交付使用预声明validation策略选择SFT或DPO，选择证据在评测根目录的deployment-selection.json。两者均不根据test选优。不同模型已占用8002时，脚本拒绝无归属地终止服务。

工作台若仍有queued/running任务，不应在任务进行中切换模型。服务退出后原running任务标记interrupted；重试生成新运行和新业务环境，已经提交的历史写入不会被伪称撤销。

成功部署写入机器本地的`configs/deployment.local.json`。以后双击启动项目会恢复该部署。此文件不进入源码发布包；新机器首次部署需要显式选择阶段。

## 真实服务验收

部署成功仅说明服务可连接，必须继续实际业务验收：

```powershell
.\.venv\Scripts\python -m scripts.accept_trained_workbench --output results/workbench-acceptance/trained-sft-v1
```

输出目录必须是新目录。验收通过真实HTTP调用Student，不允许工程脚本fallback；检查三类正常任务、正确拒绝、转人工、自定义部分退款、提交幂等、实际模型身份、轨迹一致性和下载数据库完整性。失败案例保存后按实际结果报告，不能删除再冒充第一次通过。

这是功能性验收，不作为另一组独立泛化成绩。浏览器布局、刷新恢复和运行历史还需浏览器实测；已有旧Ollama网页验收不替代新HF服务验收。

## 生成交付包

```powershell
.\.venv\Scripts\python -m scripts.package_project --check-only
.\.venv\Scripts\python -m scripts.package_project --output release/SkillForge.zip
```

只有正式权重、父checkpoint谱系、同协议验证/test、稳定性记录及源码独立回归通过后才允许打包。目标文件不得已存在。ZIP会逐文件回读校验SHA-256；不把“文件写出”当作归档校验完成。

包含源码、配置、数据、适配器、研究文档与原始评测证据；不包含venv、机器本地服务配置和8GB基座模型。基座下载与训练依赖复现见TRAINING.md。CPU CI和Docker配置存在，但当前没有远端CI或容器实跑验收，不对外宣称已通过。

## 恢复边界

当前系统的幂等保障覆盖本地单SQLite事务；不等价于真实支付系统的分布式exactly-once。当前服务是localhost研究工作台，未配置生产认证和多租户隔离。不要将它直接绑定公网并接入真实客户或支付数据。
