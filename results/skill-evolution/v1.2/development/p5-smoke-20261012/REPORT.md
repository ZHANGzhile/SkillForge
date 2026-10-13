# P5 A/B/C 开发成本 smoke（2026-10-12）

六臂真实 main-v3 执行完成，独立原始证据审计通过。**6/6 EOC、6 autonomous、0 assisted、零 Safety 事件**。两个开发来源组，不能当作六个独立样本或正式研究结论。

| 方法 | 目录 | EOC | 模型调用 | tokens | 模型来源工具调用 |
|---|---|---:|---:|---:|---:|
| A | 空目录，保留相同原始工具与检索接口 | 2/2 | 7 | 22,959 | 5 |
| B | 冻结历史静态目录 | 2/2 | 7 | 22,966 | 5 |
| C | P4 实际 RETAIN_PARENT 目录 | 2/2 | 7 | 22,966 | 5 |

B/C 内容完全相同，两个任务的 C−B EOC / calls / tokens 差均为 0。各臂均走 primitive，search/load/Skill 使用均为 0。真实新候选为 0，不能声明新 Skill 复用或演化收益。

增量 **21 calls / 68,891 tokens / 174.8481 秒采集墙钟**；共享累计 **606,187 / 668,390 tokens，2,079.6725 / 2,626.7213 秒**。剩余 **62,203 tokens / 547.0488 秒**。GPU 小时未实测。

模型工具调用 15 次，静态覆盖 CPU 调用另 12 次，独立审计 CPU 重放另 15 次。审计没有新增模型费用。所有臂 No-History 检查通过；当前任务历史保留，跨任务 learn/经验记忆不进入上下文。没有独立 No-History 消融效应。

P5 定向测试 14 passed；[全量预检](../preflight-20261012-P5-smoke/preflight.json)为 **425 passed / 1 skipped / 2 upstream warnings**，正式冻结资产与固定 adapter 核验通过。初始化日志读取线程的一次 UTF-8 解码异常保留在 stderr；主任务正常完成，根因未定位。

模型 Worker 已退出，GPU 租约已释放，无后台模型任务。没有训练、新程序/Agent 准入、激活或部署。

## 原始证据与三轮草案

- [原始汇总](report.json)
- [独立审计](evidence-audits/7cb0ec1d7f4f67b68d8a28bc7c43a593083132881647ab5f6c5ece7e36ec13de.json)
- [三轮草案](../p5-draft-20261012/draft.json)及[审计绑定](../p5-draft-20261012/binding.json)
- [实现、范围与下一步](../../../../../docs/SKILL_EVOLUTION_P5_COST_SMOKE.md)

草案未冻结、未登记执行，真实三轮完成数为 0。最多 120 次模型执行，按本次实测加两倍余量，规划 2,755,920 tokens / 6,994 秒墙钟；逐臂硬上限合计 7,864,320 tokens。正式研究预算未登记。

下一步补齐正式 Agent 准入回执与隔离激活控制器，登记累计研究预算、来源/实体账本及明确支持范围，再冻结三轮协议。当前仅支持两个直线只读目标，不声称 Structural / Compositional 迁移或 Agent 授权拒绝 EOC 已验证。

## 身份

```text
protocol: 3d9150481bdd856faca1d745bc190bcfca64ad2518a644a5a731405466c0f446
report: abdb29cd90603aaf1931a8015c82f54b1622970a53516b128f7ed6649a965bd1
main-v3: f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b
B/C catalog: d3c1564a3116c531adadda04a5ddb92319e43bb8c807f8857a8b750c11386daa
draft: 7b59ea321c9608f6fe5a237fd075430f176e8c56eb7a7471d78e5038761f9ed3
```
