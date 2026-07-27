# M5.2 Qwen3 DirectBackend 最小文本闭环

状态：DONE（CPU 编译与单元测试）；Qwen3 集成运行：`BLOCKED_SANDBOX`。

## 实现范围

- 自有 `runtime/` C++17 工程，未修改 `third_party/llama.cpp-omni`。
- `ChatTemplateRenderer` 只支持 Qwen3 的 `system`、`user`、`assistant` 文本消息；
  generation prompt 固定渲染 `enable_thinking=false` 的
  `<think>\n\n</think>\n\n` prefill。
- Renderer 以冻结 GGUF `tokenizer.chat_template` 的 SHA-256
  `57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361` 为版本门禁。
  此值由离线 GGUF metadata 读取所得；审计依据见
  `docs/design/qwen3-direct-template-decision.md:45-68`。
- `DirectBackend` 是单模型、单 context、单请求串行实现；不含 HTTP/SSE、VLM、RAG、
  Agent、Docker、systemd、多 session、流式 callback、Cancel、TTFT 或 TPOT。

## 上游 API 对照

| DirectBackend 操作 | 实际公开 libllama API | 上游依据 |
| --- | --- | --- |
| backend 生命周期 | `llama_backend_init`, `llama_backend_free` | `include/llama.h:447-453` |
| 模型/上下文 RAII | `llama_model_load_from_file`, `llama_model_free`, `llama_init_from_model`, `llama_free` | `include/llama.h:482-520` |
| template fingerprint 读取 | `llama_model_chat_template(model, NULL)` | `include/llama.h:607-609` |
| tokenizer | `llama_model_get_vocab`, two-pass `llama_tokenize` | `include/llama.h:554,1118-1133` |
| prefill/decode | `llama_batch_init/free`, `llama_decode` | `include/llama.h:917-956` |
| sampler | chain + `top_k/top_p/min_p/temp/dist`, `llama_sampler_sample` | `include/llama.h:1284-1329,1476-1486` |
| output/stop | `llama_token_to_piece`, `llama_vocab_is_eog` | `include/llama.h:1061-1065,1135-1146` |
| context reset | `llama_memory_clear(llama_get_memory(ctx), false)` | `include/llama.h:550-552,702-706` |

没有调用 `common_chat_templates_*`、`tools/cli`、`tools/main` 或 CLI 子进程。
`llama_chat_apply_template` 未用于 Qwen3 rendering，因为公开 API 不接受 template
variables 且不使用 Jinja；该决策见
`docs/design/qwen3-direct-template-decision.md:72-100`。

## CMake

冻结构建中上游 target 名为 `llama`（`third_party/llama.cpp-omni/src/CMakeLists.txt:11-55`），
实际 artifact 为 `third_party/llama.cpp-omni/build-jetson-release/bin/libllama.so`。
其 build-tree `llama-config.cmake` 指向安装前缀，不能作为可重定位 package 使用；
因此自有 CMake 将该实际 shared library 和对应公开 include/ggml include 导入为
`edgeomni_llama`，不猜测 CUDA 或手工链接 `ggml-cuda`。

```bash
cmake -S . -B build-runtime -DEDGEOMNI_BUILD_TESTS=ON
cmake --build build-runtime --parallel 2
ctest --test-dir build-runtime --output-on-failure
```

配置日志确认了实际 include 和 library：

```text
EdgeOmni frozen llama include: .../third_party/llama.cpp-omni/include
EdgeOmni frozen llama library: .../build-jetson-release/bin/libllama.so
```

## 测试结果

`edgeomni_runtime_unit_test`：PASS。

- ChatTemplateRenderer golden：单 user、system + user、多轮 user/assistant、
  不添加 generation prompt、tool role 拒绝、template fingerprint mismatch、SHA-256
  test vector。
- FakeBackend contract：initialize/shutdown、重复 initialize、模型不存在、hash 不匹配、
  context reset、连续请求、context 超限、非法空请求。
- `git diff --check`：PASS。
- C++：`edgeomni_runtime`、`edgeomni_fake_backend`、unit test 和可选
  `edgeomni_qwen3_integration_test` 均已成功编译和链接。

## 集成运行

集成二进制的构建命令：

```bash
cmake -S . -B build-runtime -DEDGEOMNI_BUILD_TESTS=ON -DEDGEOMNI_BUILD_INTEGRATION=ON
cmake --build build-runtime --parallel 2
./build-runtime/runtime/edgeomni_qwen3_integration_test
```

本次没有执行最后一行：当前运行环境没有 `/dev/nvidia*`，`nvidia-smi -L` 报告无法与
driver 通信。这是 `BLOCKED_SANDBOX`，不构成 GPU 硬件或 Jetson 配置故障结论。通过条件为：
初始化成功，单请求返回 `code=kOk`、非空 `finish_reason`，且打印 prompt/generated token
计数；模型加载只发生一次。

## 已知限制与 M5.3

- 模板 renderer 是冻结 Qwen3 文本模板的受控子集；tools、图片、多模态和未知 role
  明确报错，不提供降级格式。
- 模型 SHA 值作为固定 RuntimeConfig 门禁；完整模型文件 hash 在冻结 deployment
  manifest 中已记录，M5.2 未重新计算 2.5 GiB 文件 hash。
- 只有 `generate_text` 同步调用，没有 token callback、取消或性能指标。
- M5.3 应在不改变模板门禁的前提下增加：token 流式 callback、CPU abort callback 的
  cancel contract、CUDA cancel 延迟限制说明、TTFT/TPOT 与结构化 metrics；服务层仍应
  在这些 Runtime contract 稳定后再开始。
