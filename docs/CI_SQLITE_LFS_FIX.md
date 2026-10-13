# 最终交付 CI 修复：SQLite LFS 指针与真实对象

2026-10-13。修复提交 `1719a4d3a1ace63b63d9f4e975a85c87162774cf`。只改 CI 配置并增加只读夹具检查；未改测试、审计器、安全规则或冻结实验字节。

## 根因与实测

`tests/test_boundary_auditor_v2.py` 使用 `results/skill-evolution/v1.3/formal-P11-v1/agent/physical/9` 的真实 checkpoint。`.gitattributes` 将 `*.sqlite` 存为 Git LFS；原 `actions/checkout@v4` 未设置 LFS，因此没有取得数据库对象。审计将文件实际 SHA-256 与 checkpoint 清单对比，正确拒绝指针。

以 checkpoint 0 的 `environment.sqlite` 为例：

| 对象 | 大小 | SHA-256 |
|---|---:|---|
| Git 中 LFS pointer | 130 bytes | `723d8a55a56e48b34a346efec6c6d7adf49dc9947ca34810b72e9e868b3887f4` |
| 实际 SQLite | 77,824 bytes | `ccd2cc92636b79343f2aeb067dc7398009a10c21859d84bdcb0a2df4ae7d27eb` |
| checkpoint 预期 | 77,824 bytes | 与实际 SQLite 完全相同 |

pointer 的内容是版本行、`oid sha256:<上述真实数据库 hash>` 和 `size 77824`，不是损坏的 SQLite。该 arm 的 17 个 checkpoint 数据库均为上述 hash；live.sqlite 同为 77,824 bytes，hash 为 `b698b58679692c309c86eae5ad9ee65183298e27ce650a6c78960ef73d35c3a6`。

完整实测见 [lfs-diagnosis.json](../results/final-delivery/20261013/lfs-diagnosis.json)。本地原失败测试严格执行为 2 passed，没有修改或跳过测试。

## 修复

[tests.yml](../.github/workflows/tests.yml) 启用 `lfs: true`，通过 Git 配置环境给 checkout 的 LFS fetch 设置本 CPU 夹具目录的 include。当前 CPU 测试对历史原始 SQLite 的依赖只有该 arm；其余合成夹具在各自临时目录生成。没有下载真实模型权重，也没有删掉其他数据。将来若测试新增历史数据库依赖，应显式扩大下载范围，不能跳过审计。

[verify_ci_sqlite.py](../scripts/verify_ci_sqlite.py) 对全部 18 个数据库检查 SQLite header、Git LFS OID、size 和 checkpoint database_sha256；任一不符即使 CI 失败。原审计继续独立重放原始失败 Action、费用、每个 checkpoint 和最终 SQL。`.gitattributes` 保持原样。

矩阵设置 `fail-fast: false`，避免 Ubuntu 失败使 Windows 无结果；每个平台上传 JUnit XML。原 checkout 的 `lfs` 默认 false 见 [actions/checkout 官方说明](https://github.com/actions/checkout)，筛选规则见 [Git LFS 官方配置](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-config.adoc)。

## 验证与记录边界

- [修复后的双平台 CI](https://github.com/ZHANGzhile/SkillForge/actions/runs/38434043025)：平台结果分别记录，不用本地通过代替远端 Windows。
- [Ubuntu 原始日志摘要](../results/final-delivery/20261013/ci-ubuntu.json)：536 passed / 1 skipped；SQLite 夹具核验通过。
- [Windows 原始日志摘要](../results/final-delivery/20261013/ci-windows.json)：536 passed / 1 skipped；SQLite 夹具核验通过。双平台运行均为 completed / success，见 [GitHub jobs 与 JUnit artifacts 凭据](../results/final-delivery/20261013/ci-run.json)。
- 本地首次全量：520 passed / 16 failed / 1 skipped，失败来自 Windows 长临时路径的文件创建，不是审计降级。改用全新短临时目录后，原完整套件为 536 passed / 1 skipped；失败日志与成功 JUnit 都保留。
- [所有历史结果完整性](../results/final-delivery/20261013/integrity.json)：111,816 个已跟踪文件、12,758,072,861 bytes 对照 Git blob/LFS OID，missing/mismatch/unhydrated 均为 0；P11 的 370 个冻结源码无变化。

本轮没有新增模型调用、tokens、学习或 Prompt 变体。最终双平台结果以冻结状态总结和 GitHub 对应运行的 jobs 为准。
