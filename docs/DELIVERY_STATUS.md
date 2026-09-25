# 本地研究项目交付验收

2026-09-25 23:50:13

main-v3 SFT通过validation准入，完成新实例双评测；原六项真实HTTP功能验收与浏览器签收通过。研究效果与局限见[恢复训练报告](RECOVERY_RESULTS.md)，原main-v2成绩和失败记录完整保留。

真实验收目录：`results\workbench-acceptance\recovery-sft-20260925-154703`；adapter SHA-256：`f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b`。

ZIP逐文件核验完成以.runtime/recovery-delivery.json的completed状态为准。本地合成领域验收不代表生产部署或所有任务成功。


最终归档已实际完成：`release/SkillForge-recovery-20260925-234934.zip`，518,113,488字节、2,855文件，逐文件SHA-256核验通过。ZIP SHA-256：`b8aea6e1169d38e21fe5b30845c7a6f7ab900c8c9ad763e77dcf8a448905c6d0`。回执：`results/recovery-release.json`。

最终源码独立回归102 passed、1 skipped；两个上游弃用提示。23:51重新通过启动入口部署相同adapter，HTTP服务健康、worker活跃；保存的真实验收经重新审核后保留，未重新生成或替换功能样例。
