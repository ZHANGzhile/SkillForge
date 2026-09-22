# 本地 Student 运行指南

2026-09-10：本机部署与GPU集成验收完成。业务小批结果1/5，详见LOCAL_STUDENT_REPORT.md。

## 项目内文件

- `.runtime/ollama/ollama.exe`：官方 Ollama v0.34.0 Windows 独立服务。
- `.runtime/models/`：本项目使用的模型权重。
- `models/Modelfile.qwen3-4b`：Qwen3 4B 的16K上下文、512输出token配置。
- `configs/ollama.json`：本机API、模型名称、固定seed、显式Qwen3 raw适配器。
- `configs/model.local.json`：本地激活配置，不提交Git。

## 启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_student.ps1
```

服务仅监听127.0.0.1:11434。启动脚本的环境变量只影响当前进程及子进程，不改系统PATH。

项目当前使用`ollama_qwen3_raw`适配器访问`/api/generate`，在客户端渲染Qwen3 ChatML并预填空思考结束标记，绕过本版本聊天模板/思考解析问题。`reasoning_effort`仅供通用OpenAI路径使用；raw路径不发送该参数。不得直接将此适配器用于其他模型系列。配置中的`/v1`是服务基址约定，适配器会换成实际native路径。

模型首次准备（服务启动之后）：

```powershell
.\.venv\Scripts\python scripts/pull_student.py
.\.runtime\ollama\ollama.exe create skillforge-qwen3-4b -f models/Modelfile.qwen3-4b
Copy-Item configs/ollama.json configs/model.local.json
.\.venv\Scripts\python -m skillforge.cli model-smoke
.\.venv\Scripts\python scripts/student_validation.py
```

小批验证只使用实验数据集train分区中的5个案例，输出标记B0-real-train-smoke。未使用脚本策略代替模型，也不在test上调试提示词。输出目录保存任务状态、工具调用、配置和GPU驻留信息。

启动不等于效果验收：要分别确认API能够返回有效Action、模型驻留GPU、任务是否满足Expected Outcome Contract。实际失败也保留。

## 来源

- https://github.com/ollama/ollama/releases/tag/v0.34.0
- https://docs.ollama.com/windows
- https://ollama.com/library/qwen3:4b
- https://docs.ollama.com/api/openai-compatibility

官方安装包SHA-256：`a7dd1b174f39d3d1b8a25d4cbc86045d0e190b17187bfdcbe2f2ee3b5a11470e`。
