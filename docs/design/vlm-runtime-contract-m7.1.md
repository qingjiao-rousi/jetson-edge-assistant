# VLM Runtime Contract（M7.1 设计）

这是自有 Runtime Adapter 的接口草案，不声称已实现。Adapter 隔离 `mtmd`/`omni` 的实验性 API；上游能力边界以 `docs/design/vlm-m7.1-audit.md` 为准。

## 数据模型

```text
ImageInput {
  id: string                 // 请求内唯一；用于 metrics/KV 关联
  bytes: byte[]              // 原始编码图片，Adapter 不接受任意路径
  mime: image/jpeg|image/png|image/webp
  width?: uint32             // 解码后校验值，不信任调用方
  height?: uint32
}

GenerateRequest {
  request_id: string
  prompt: string
  images: ImageInput[]       // 0..1（M7.1）；多图保留为后续版本能力
  max_new_tokens: uint32
  stream: bool
  timeout_ms: uint64
  cancel: CancellationToken
}
```

M7.1 policy：单图、JPEG/PNG/WebP、原始 bytes <= 10 MiB、解码后宽高各 <= 4096、像素数 <= 16 Mpix；空/损坏/超限在视觉编码前拒绝。预处理统一解码为 RGB uint8，保持长宽比缩放到模型允许范围，记录原始和目标尺寸；不得把本地路径直接暴露给上层。

## 生命周期与并发

`initialize(config)` 校验主模型和 mmproj 的路径/hash/metadata，加载 LLM 一次，再创建一个常驻 vision/mmproj context；`shutdown()` 先取消 in-flight 请求、等待 worker、释放 vision context，最后释放 LLM。mmproj 与主模型版本绑定，不能跨模型复用。单 context 只允许 1 个 in-flight generate；第二个请求返回 `RESOURCE_EXHAUSTED`，不在 Adapter 内隐式排队。

请求步骤固定为：validate → preprocess → vision encode → tokenize/image-marker injection → LLM prefill → decode/stream。上游 mtmd 的注入事实是 `mtmd_tokenize` + `mtmd_helper_eval_chunks`（`tools/mtmd/mtmd-cli.cpp:243-270`）；Adapter 必须从 chunk/image token API 读取实际 image token 数，不能估算。

## 结果、指标和错误

响应包括 `request_id`、文本片段/最终文本、`finish_reason`、`image_tokens` 和 metrics。至少记录：`preprocess_ms`、`vision_encode_ms`、`prefill_ms`、`first_token_ms`（Adapter 入口到首 token）、`decode_ms`、`total_ms`、`prompt_tokens`、`generated_tokens`、`ttft_ms`/`tpot_ms`（服务层定义，不能与 CLI timing 混称）、峰值内存/GPU telemetry（若可用）。

稳定错误码：`INVALID_ARGUMENT`（格式/大小/数量）、`IMAGE_DECODE_FAILED`、`MODEL_NOT_FOUND`、`HASH_MISMATCH`、`MMPROJ_LOAD_FAILED`、`VISION_ENCODE_FAILED`、`CONTEXT_EXCEEDED`、`RESOURCE_EXHAUSTED`、`DEADLINE_EXCEEDED`、`CANCELLED`、`BACKEND_UNAVAILABLE`、`INTERNAL`。错误响应必须包含 request_id、阶段和可诊断 message，不回显原始图片 bytes。

超时覆盖整个请求；到期后设置 cancel、停止在当前安全边界、回收 context 状态并返回 `DEADLINE_EXCEEDED`。显式取消返回 `CANCELLED`；客户端断连按取消处理。上游 `break_event`/Ctrl-C 只能作为 Adapter 的实现机制，不能直接成为公开错误语义（omni server 的复用逻辑见 `tools/server/server-omni.cpp:387-404`）。

## 流式语义

`stream=true` 时先发送一个 metadata/event（request_id、image_tokens、阶段计时可在完成后补发），随后发送有序 text delta，最后发送 terminal event（finish_reason、all metrics）。首 token 计时从 Adapter 接受请求开始；vision encode 和 prefill 不产生文本 delta。取消/超时发送一个 terminal error 后关闭流，不能发送“成功完成”。

## 责任分界

上游负责：GGUF 加载、mmproj/VPM encode、chunk/token 注入、LLM decode、omni 的 SSE/线程原语。Adapter 负责：bytes 输入与安全限制、格式/像素校验、模型资产门禁、单 context admission、请求 ID、超时/取消、统一错误码、指标时钟和流式协议。未验证能力：本地目标 `--help`、真实 VLM asset、格式兼容集合、动态 image token 上限、Jetson vision latency/TTFT/TPOT、断连取消。

M7.1 明确不定义音频/APM、TTS、RAG、Agent、多 context 并发和实时视频接口。
