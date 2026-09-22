# 本地 Student 硬件检查

检查日期：2026-09-10。只读检查，尚未安装服务或下载权重。

- CPU：AMD Ryzen 9 7900X，12核。
- NVIDIA GPU：RTX 5070，12227 MiB显存；检查时占用约1318 MiB。
- 系统可见物理内存：95.1 GiB，检查时可用约69.8 GiB。
- 磁盘：C盘空闲约313 GB，D盘约284 GB。
- 未在 PATH 找到 Ollama；wsl.exe、docker.exe 存在。WSL分发列表查询被权限拒绝，不能据此认定未安装WSL。

判断：硬件具备本地小型量化 Student 推理的条件。建议先使用Windows原生推理服务和约4B量化模型进行接口与上下文测试；具体速度和上下文上限需实测。训练所需显存不同，不能由推理可运行直接推出QLoRA/SFT/DPO必然可运行。

官方资料：
- https://docs.ollama.com/gpu （列出RTX 5070）
- https://docs.ollama.com/windows （Windows原生运行）
- https://ollama.com/library/qwen3:4b （候选模型）

检查方法：nvidia-smi读取显卡；Windows GlobalMemoryStatusEx读取内存；注册表只读查询CPU名称。CIM查询被沙箱拒绝，已通过这些只读接口获取所需信息。
