# M11 评估记录

M11 最小闭环的验收对象是本地音频契约和顺序状态机，而不是新增检索算法：`record -> VAD endpoint -> ASR -> M10.2 Agent citation answer -> TTS -> playback -> record`。

Python 契约测试覆盖模型 artifact 的 size/SHA-256 校验、16 kHz 单声道配置，以及录音、ASR、Agent、TTS、播放的严格半双工顺序。真实设备验收需要提供配置中指定的 sherpa-onnx 中文 ASR/VAD/TTS 本地模型和可用 PortAudio 设备；默认仓库不携带模型，也不允许运行时下载。

无麦克风演示路径覆盖 `--text`：它不会调用录音、VAD 或 ASR；只将键盘问题交给现有 Agent JSONL，收到 `OK` 且带 Agent citations 的回答后生成本地 VITS PCM 并播放。Agent 返回 `CITATION_FORMAT_ERROR`、`NO_EVIDENCE` 等非成功状态时，不执行 TTS/播放。

M11 还验证 TTS-only `spoken_text`：citation 标记会移除，设备型号、故障码、数字和常用工程单位会转为中文播报；原始 `answer`/`citations` 不变。规范化为空或 Agent 非 `OK` 时，TTS 和播放均不会执行。

限制：单一固定 voice session；不支持全双工、AEC、用户打断、流式 TTS、音视频同步、多路音频、持久化或生产鉴权；不代表 Runtime 层多 session KV。
