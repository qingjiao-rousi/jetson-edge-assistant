# M11 本地半双工语音闭环

状态：`M11-PROTOTYPE`。

`scripts/audio_gateway_m11.py` 实现固定顺序：PortAudio 录制 16 kHz 单声道 int16 PCM，sherpa-onnx VAD 检测一句话结束，本地 sherpa-onnx ASR 转写，调用现有 `scripts/agent_m10_2.py --jsonl`，再以本地 sherpa-onnx TTS 生成 PCM 并通过 PortAudio 播放。播放完成后才进入下一轮录音，因此这是半双工。

每个 ASR/VAD/TTS 模型都必须在配置中声明本地相对路径、文件大小、SHA-256、语言、采样率和许可证；启动时校验，不执行联网下载。Agent 进程只启动一次，网关不复制 Agent、RAG 或引用校验逻辑。

## 无麦克风演示

使用 `--text` 可只执行一轮 `文本问题 -> M10.2 Agent JSONL -> 本地 VITS TTS -> PortAudio 播放`，不创建输入流、VAD 或 ASR：

```bash
python3 scripts/audio_gateway_m11.py \
  --config configs/audio-gateway-m11.json \
  --text "BX-9 的出口压力是多少？"
```

该模式继续使用 Agent 返回的引用门禁结果；非 `OK` 回答不会送入 TTS 或播放。

## 仅供播报的规范化

终端 JSON 的 `answer` 和 `citations` 永远保持 Agent 原始输出。网关只为 TTS 生成 `spoken_text`：移除 `[S1]` 等控制标记，将 `18 MPa`、摄氏度范围和运行小时转换为中文可读形式；`BX-9` 在明确上下文中转换为“该设备”，`E42` 转换为“故障代码四十二”。无法安全解释的 ASCII 片段从 `spoken_text` 移除，不伪造含义。若结果为空，返回 `TTS_TEXT_ERROR`，不合成也不播放。

不包含真正全双工、AEC、打断、Streaming TTS、音视频同步、多路音频、持久化会话或 Runtime 层多 session KV。
