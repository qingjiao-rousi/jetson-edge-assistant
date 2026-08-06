# M12 终端交互界面

状态：`M12-PROTOTYPE`。

`scripts/chat_console_m12.py` 是一个仅使用 Python 标准库的交互式终端。启动后在进程内长驻一个 `python3 scripts/agent_m10_2.py --jsonl` 子进程，固定一个 session，并由 UI 生成唯一 `request_id`、发送 JSONL、解析响应。用户只看到 `你：`、`助手：` 和必要的模式或错误简讯，不看到 JSON、request_id、citations 数组或 tool audit。

默认模式是 `manual`，普通输入发送 `op=answer`，保留回答正文中的 `[S1]` 引用。`/mode general` 显式切换到一般解释模式并发送 `op=explain`，显示一次“非设备手册结论”提示。支持 `/mode manual`、`/mode general`、`/reset` 和 `/quit`；reset 使用同一 session 调用 Agent reset，quit 关闭子进程。

`NO_EVIDENCE`、`GENERAL_EXPLANATION_REJECTED` 和 `CITATION_FORMAT_ERROR` 会转换为简短友好提示。该 UI 不改变 Agent、RAG 或 Runtime 契约，不提供生产鉴权或安全认证能力。

每次 Agent 成功返回回答后，终端追加 `助手：回答结束。`，便于在模型响应较慢或文本较长时确认本轮已经完成。M12 Console 本身是文本 UI，不包含录音、TTS 或扬声器播放；语音闭环仍由独立的 `scripts/audio_gateway_m11.py` 提供。
