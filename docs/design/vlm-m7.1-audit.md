# M7.1 VLM 图片输入能力审计

审计日期：2026-07-28。仅读取工作区源码、已有构建目录、`--help` 可用性和本地资产；没有运行模型、构建新目标、下载或修改 `third_party/llama.cpp-omni`。

## 结论摘要

| 目标 | 工作区可执行文件/Help | 实际能力结论 |
|---|---|---|
| `llama-mtmd-cli` | MISSING；CMake 目标存在于 `tools/mtmd/CMakeLists.txt:111-117` | 可验证的实验性图片/音频 CLI；`--mmproj` 必需，`--image` 可重复，多图按顺序注入 |
| `llama-omni-cli` | MISSING；CMake 目标存在于 `tools/omni/CMakeLists.txt:98-105` | MiniCPM-o Omni 专用；`--vision`/`--audio`/`--omni`，图片由 `stream_prefill` 处理，伴随 APM/TTS 设计 |
| `llama-omni-server` | MISSING；CMake 目标存在于 `tools/server/CMakeLists.txt:38-51` | HTTP/SSE Omni server；常驻 `omni_context`，但请求模型是单共享 context，`n_parallel` 强制为 1 |
| `llama-server` | 未将图片路径接入本轮自有契约；通用 server 源码存在，但没有可执行产物 | 不作为 M7.1 VLM 后端结论 |

构建目录 `third_party/llama.cpp-omni/build-jetson-release/bin/` 当前只有 `llama-cli`、`libmtmd.so`、`libomni.so` 等，未发现上述三个 executable；因此不存在可如实引用的本地 `--help` 输出。

## mtmd 图片路径

- 帮助字符串明确要求 `-m --mmproj`，并声明 `--image`、`--audio` 可选，见 `tools/mtmd/mtmd-cli.cpp:40-48`；入口拒绝缺失 `--mmproj`，见 `:292-295`。
- `mtmd_context_params` 将 GPU、warmup、动态 `image_min_tokens/image_max_tokens` 传给 `mtmd_init_from_file`，见 `tools/mtmd/mtmd-cli.cpp:136-155`；C API 的视觉/音频能力查询见 `tools/mtmd/mtmd.h:84-129`。
- 文件图片通过 `mtmd_helper_bitmap_init_from_file` 读入 bitmap，见 `tools/mtmd/mtmd-cli.cpp:168-175`；单轮遍历 `params.image`，在 prompt 中按图片数插入 marker，然后将所有 bitmap 交给 `mtmd_tokenize`，见 `:343-362` 和 `:243-249`。
- tokenized chunks 由 `mtmd_helper_eval_chunks` 写入 llama KV/context，见 `:257-270`。图像 token 数可从 `mtmd_image_tokens_get_n_tokens` 获取，见 `tools/mtmd/mtmd.h:182-189`；动态分辨率上下限是参数，不是固定项目策略。
- 音频与图片在同一 `mtmd_input_chunk_type` 枚举中并列（TEXT/IMAGE/AUDIO），见 `tools/mtmd/mtmd.h:54-58`；CLI chat 命令也分别暴露 `/image` 和 `/audio`，见 `mtmd-cli.cpp:368-375`。因此音频属于 libmtmd 同一路径，但不纳入 M7。
- Ctrl-C 仅通过全局生成标志停止采样，见 `mtmd-cli.cpp:30-65`、`:178-209`；这不是自有 Runtime 的可取消请求语义。

## omni 图片路径

- `llama-omni-cli` 参数包括 `--vision`、`--audio`、`--omni`、vision backend 和 batch encode，见 `tools/omni/omni-cli.cpp:54-74`、`:239-280`。它默认按 MiniCPM-o 目录推导 VPM/APM 路径，见 `:145-160`，并在 `omni_init` 时同时配置 `vpm_model/apm_model`，见 `:358-370`、`:400-405`。
- VPM API 明确区分图片解码、预处理、单张/批量 encode，并可报告 output token 数，见 `tools/omni/vision.h:96-113`。`vision_image_f32_batch` 记录 overview 加 slices，见 `:44-70`；这不是 mmproj API，而是 omni 自有 VPM 模块。
- `stream_prefill` 接收音频文件、图片文件、slice 数和文本，见 `tools/omni/omni.h:507-514`；服务器 `/v1/stream/prefill` 将 `img_path_prefix` 直接传入，见 `tools/server/server-omni.cpp:209-247`。
- server 先在 `/v1/stream/omni_init` 加载并持有 `omni_context`，见 `server-omni.cpp:138-206`；`/v1/stream/decode` 支持 SSE，见 `:250-343`。这是常驻模型和流式文本输出的源码证据，但不是验证过的 Jetson 性能结论。
- server 将默认 `n_parallel` 收敛为 1，见 `server-omni.cpp:98-103`；全局 `octx_mutex` 包住初始化、prefill、decode，见 `:181-203`、`:222-240`、`:278-304`。M7.1 以单 context 单 in-flight request 为边界。
- 关闭 session 设置 `break_event`、清队列并调用 `omni_prepare_for_reuse`，见 `server-omni.cpp:387-404`；这可作为 Adapter 取消/复用的上游事实，但 HTTP 断连取消仍未验证。

## 未验证与边界

未发现可执行目标，故未验证实际 `--help`、图片解码格式集合、最大字节/分辨率、VLM 模型兼容矩阵、vision encode 实测耗时、first-token/TTFT/TPOT 或流式稳定性。`models/` 中只有文本 GGUF；VLM 主模型、mmproj、APM、TTS、token2wav 均标记 MISSING，详见 `manifests/vlm-assets-v1.json`。

本轮不纳入音频业务、RAG、Agent、实时视频、TTS 联调或模型下载。

## 多 context 与候选模型补充

`4096` 仅定义为冒烟基线，不是业务上限。`llama-omni-cli` 将 `n_ctx` 默认设为 4096，但接受 `-c/--ctx-size`，见 `third_party/llama.cpp-omni/tools/omni/omni-cli.cpp:64-65`、`:254-256`，并写入 `params.n_ctx`，见 `:369-370`。最终可用上限仍由每个模型 GGUF metadata、训练配置、KV 分配和实际 OOM/延迟测试共同决定。

统一 context 矩阵：

| context | 定义 | 状态 |
|---|---|---|
| 4096 | 加载、单图输入和最小功能基线 | 待实测 |
| 8192 | 第一版默认业务候选 | 待实测 |
| 16384 | 长手册、多轮对话和图片说明 | 待实测 |
| 32768 | 容量风险验证，不承诺部署 | 待实测 |

有效预算统一按 `image_tokens + image_text_tokens + manual_text_tokens + history_tokens + output_reservation <= n_ctx` 计算。mtmd 的图像 token 数由 `mtmd_image_tokens_get_n_tokens()` 提供，见 `third_party/llama.cpp-omni/tools/mtmd/mtmd.h:182-189`；Qwen-VL 类模型还使用 M-RoPE 位置，见 `mtmd.cpp:198-214`，因此不能用固定的“每图 N token”替代实测值。

候选和每个 context 档的后续测试资格详见 `docs/design/vlm-context-model-matrix-m7.1.md`。7～8B 仅表示参数规模和能力候选，不表示更长 context；本地没有这些 VLM 主模型或 mmproj，metadata、revision、许可证、大小和 hash 均未冻结。
