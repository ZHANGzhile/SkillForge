# GitHub 归档与复现

本文件保留原main-v2快照及最新main-v3发布记录。main-v3真实HTTP验收6/6与浏览器签收通过，独立新实例测试68/78；原main-v2的4/6失败记录保持不变。详见[恢复结果与限制](RECOVERY_RESULTS.md)。

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

仓库当前公开可读；原9月22日快照上传时为私有。完整权重应通过Git LFS拉取，不应把LFS指针文本当作模型文件。

只查看代码时可在clone前设置`GIT_LFS_SKIP_SMUDGE=1`，随后需要权重时再执行`git lfs pull`。CPU CI不下载训练权重；运行训练/推理另外需要CUDA环境和官方基座。

## 后续同步

9月25日恢复训练分版本保留在main-v3；本轮先同步已完成的实现、冻结语料、新实例集、完成的GPU smoke和页面/回归证据。正式SFT仍在写入的检查点与日志待阶段完成后同步，不能将上传代码当作新模型训练成功。`artifacts-manifest.json`及原发布回执描述9月22日的初始快照，核对该快照应检出回执中的提交；后续文件更新不会回写历史回执。

```powershell
git status
git add .
git commit -m "Describe the actual change"
git push
```

首次发布完成后的远程地址、提交号与传输核验结果以交付消息及`results/github-publication.json`为准。不得把GitHub归档成功等同于退款能力修复或产品验收通过。


## main-v3完成后的归档

2026-09-25已完成main-v3训练、validation69/69、新实例test68/78、真实HTTP6/6与浏览器签收。正式adapter、最终及倒数checkpoint、全部新评测成功/失败记录和签收证据随最新提交上传；`results/recovery-artifacts.json`记录本次增量文件哈希。仓库当前为公开可读（API核验），不再需要权限读取公开源码；Git LFS仍用于大二进制。

原main-v2归档回执与其历史提交不改写。新交付ZIP的清单对应生成时快照；此后新增的发布说明和上传回执以GitHub最新提交为准。


## 2026-09-26公开发布核验

正式产物提交：`0afa9d094b79a98261211d009c0e489135386b65`。用户确认公开上传范围后，正式权重、检查点、全部新评测及验收记录已实际推送。两个清单共716文件、910,235,670字节已从GitHub独立下载并逐文件核对大小及SHA-256；Git LFS fsck通过。

[该提交Windows/Linux CI](https://github.com/ZHANGzhile/SkillForge/actions/runs/36196841618)全部通过。结构化回执：[results/recovery-github-publication.json](../results/recovery-github-publication.json)。`recovery-artifacts.json`中的pending说明反映本地快照制作时的状态；本次发布回执记录其后的公开上传及核验完成，不改写原清单。

独立校验时Git LFS下载一度连接建立但不返回文件内容；改为从GitHub公开媒体端点分段获取同一提交的6个大对象，每个分段核对Content-Range/长度，完整组装后核对原LFS SHA，再执行LFS完整性检查。没有使用本机训练文件替代下载校验。
