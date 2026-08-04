# M7.5A VLM Runtime Adapter Contract 落地

日期：2026-07-30。M7.5A 将 M7.1 的 VLM contract 落到 EdgeOmni C++ Runtime 的数据结构、纯内存图片门禁和资产校验组件，但不连接 mtmd、不加载 GGUF/mmproj、不运行推理，也不修改上游 Runtime submodule 或 M7.3/M7.4 证据。只读参考为 `docs/design/vlm-runtime-contract-m7.1.md`、`manifests/vlm-assets-v1.json`、M7.4B 8192 JSON 与 M7.4C-R 16384 JSON。

## Contract 和兼容性

`ImageInput` 包含 request-local ID、encoded bytes、MIME 和可选调用方声明尺寸；不包含本地文件路径。`GenerateRequest.images` 限制为 0..1，`GenerateResponse` 增加 `image_tokens`，`RuntimeMetrics` 增加 image preprocess、vision encode、image embedding、TTFT 和 TPOT 的零值字段。既有 `RuntimeBackend::generate_text`、文本错误码和文本字段均未重命名。

本轮的 `DirectBackend` 是 Qwen3 文本 backend；收到非空 `images` 立即返回既有 `INVALID_ARGUMENT`，不会加载模型。FakeBackend 的既有文本路径未改变。HTTP service 不接收 base64 图片，`images` 继续因未知字段被拒绝；它仅在既有 metrics JSON 中追加零值 vision/image 字段和 response 的零值 `image_tokens`。

## 图片门禁

`vlm_input_validator` 只接受 JPEG、PNG 和 WebP encoded bytes，限制单图、非空、最多 10 MiB。未来 mtmd decoder 必须提供 `DecodedImageInfo`；validator 只用该解码尺寸检查宽/高最大 4096 与像素最大 16 MiPixel，计算使用 `uint64_t` 和溢出前检查。调用方声明尺寸不参与安全判断，错误消息不回显原始 bytes。

## 资产门禁

`vlm_asset_verifier` 对主模型和 mmproj 逐个执行 regular-file、精确 size 和流式 SHA-256 校验。它还要求显式 binding ID 的主模型/MMproj asset ID 分别匹配配置的两个 spec，因而不能将“expected hash 出现在 allow-list”替代实际 pair binding。该组件不调用 llama 或 mtmd。

## Context 与边界

配置固定默认开发 context 为 8192；16384 仅保留一次 M7.4C-R recovery 冒烟事实；32768 禁用。8192 与 16384 都不构成稳定性或部署结论。M7.5A 排除 HTTP 图片上传、RAG、Agent、多图、多 session、音频和全部模型/推理执行；mtmd backend 接入留给下一阶段。
