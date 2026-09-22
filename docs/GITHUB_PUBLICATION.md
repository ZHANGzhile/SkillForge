# GitHub 归档与复现

本次发布保存现有研究快照，不表示产品验收已全部通过。研究结果与限制见[量化结果](QUANTITATIVE_RESULTS.md)，私有Student实际服务验收为4/6。

2026-09-22已上传至[ZHANGzhile/SkillForge](https://github.com/ZHANGzhile/SkillForge)私有仓库main分支。独立远程clone核验8,651个原始产物、2,694,303,932字节全部一致，Git LFS fsck通过；初次推送的Windows/Linux CI均通过。详见[发布校验回执](../results/github-publication.json)。

## 上传内容

- 源码、测试、CI配置、运行与训练脚本、中文技术文档和图表。
- data目录的冻结数据集，以及results目录的实验结果、完整轨迹、成功与失败记录、训练日志、适配器、优化器检查点、工作台历史数据库。
- `artifacts-manifest.json`逐文件记录data/results的字节数与SHA-256，可用于下载后核对；瞬时worker锁和SQLite WAL/SHM不属于持久结果。

权重、PyTorch检查点和SQLite文件使用Git LFS；JSON/JSONL/CSV原始证据保留在Git中。`.gitattributes`禁用自动换行转换，以保留已有审计文件的字节哈希。

不上传本机venv、node_modules、运行进程/PID/缓存目录、凭据、机器专用模型和部署配置。8GB第三方Qwen基座保存在.runtime中，不重复分发；官方revision及下载校验流程见[训练说明](TRAINING.md)。项目实际训练生成的适配器与检查点均上传。

## 完整下载

安装Git与Git LFS后：

```powershell
git lfs install
git clone https://github.com/ZHANGzhile/SkillForge.git
cd SkillForge
git lfs pull
git lfs fsck
```

私有仓库需要先登录有权限的GitHub账号。完整权重应通过Git LFS拉取，不应把LFS指针文本当作模型文件。

只查看代码时可在clone前设置`GIT_LFS_SKIP_SMUDGE=1`，随后需要权重时再执行`git lfs pull`。CPU CI不下载训练权重；运行训练/推理另外需要CUDA环境和官方基座。

## 后续同步

```powershell
git status
git add .
git commit -m "Describe the actual change"
git push
```

首次发布完成后的远程地址、提交号与传输核验结果以交付消息及`results/github-publication.json`为准。不得把GitHub归档成功等同于退款能力修复或产品验收通过。
