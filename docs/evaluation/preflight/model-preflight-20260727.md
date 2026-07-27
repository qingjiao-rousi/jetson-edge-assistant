# M2 四模型 Jetson 运行时预检归档（2026-07-27）

## 结论

有效宿主机预检 `20260727T014800Z` 通过四个候选；这是一项加载、CUDA offload 和短文本生成门禁，不是正式性能或质量 benchmark。Qwen3 的单独复验 `20260727T014900Z` 也通过，确认 `--reasoning off` 的输出没有非空 thinking 内容。隔离沙箱记录 `20260727T015043Z` 为 `BLOCKED_SANDBOX`，不能覆盖宿主机结论。

| 候选 | 状态 | 退出码 | GPU offload | 生成 / 错误门禁 | 短指令质量预检 |
| --- | --- | ---: | --- | --- | --- |
| Qwen2.5-3B-Instruct Q4_K_M | PASS | 0 | 37/37 | 非空完整；未见 CUDA、OOM、GGUF、tokenizer 或 template 错误 | `READY`，exact match |
| Qwen3-4B Q4_K_M | PASS | 0 | 37/37 | 非空完整；未见上述错误 | `READY`，exact match；`--reasoning off` 无非空 thinking |
| Phi-3.5-mini-instruct Q4_K_M | PASS | 0 | 33/33 | 非空完整；未见上述错误 | **警告**：`READY` 后附加解释，Runtime PASS，`exact_ready_match=false` |
| Llama-3.2-3B-Instruct Q4_K_M | PASS | 0 | 29/29 | 非空完整；未见上述错误 | `READY`，exact match |

`wall_time_ms` 与 CLI 显示的 Prompt/Generation 速度仅是此短预检的原始日志内容，**不得**作为正式性能结论，也不得称为 TTFT 或 TPOT。

## 固定身份

| 项目 | 值 | 状态 |
| --- | --- | --- |
| 主项目运行时记录 | `f9e6389deec31d050a7651fc72a396df3a88ad3e`，`main`，dirty | 已确认（执行时） |
| Runtime | `jetson-runtime-dev@19cc26967140407efe34006a355ab445b35b16ac` | 已确认 |
| llama-cli | `third_party/llama.cpp-omni/build-jetson-release/bin/llama-cli` | 已确认 |
| CLI SHA-256 | `e71f2d2695a33b68ca4ce4d2ff2cdc796c46c54a131f55cd4293e7cfc8230335` | 已确认 |
| Jetson 功耗模式 | `MODE_30W`，ID `2` | 已确认 |
| 宿主机 CUDA probe | `CUDA0: Orin` 已列出 | 已确认 |

## 模型文件身份

| 候选 | 文件 | SHA-256 | GGUF architecture / file type | tokenizer / chat template |
| --- | --- | --- | --- | --- |
| Qwen2.5 | `models/qwen2.5-3b-instruct-q4_k_m.gguf` | `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d` | `qwen2` / `15` (Q4_K_M) | `gpt2` / 存在 |
| Qwen3 | `models/Qwen3-4B-Q4_K_M.gguf` | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | `qwen3` / `15` (Q4_K_M) | `gpt2` / 存在 |
| Phi-3.5 | `models/Phi-3.5-mini-instruct-Q4_K_M.gguf` | `e4165e3a71af97f1b4820da61079826d8752a2088e313af0c7d346796c38eff5` | `phi3` / `15` (Q4_K_M) | `llama` / 存在 |
| Llama-3.2 | `models/Llama-3.2-3B-Instruct-Q4_K_M.gguf` | `6c1a2b41161032677be168d354123594c0e6e67d2b9227c84f296ad037c728ff` | `llama` / `15` (Q4_K_M) | `gpt2` / 存在 |

仅记录有限 GGUF metadata；没有归档完整 tokenizer token 列表或 chat template 正文。

## 证据与限制

- 有效四模型运行：`benchmark-results/model-selection/preflight/20260727T014800Z/summary.json`，SHA-256 `0bb9bf22eaf989b8ee27a4f204a1220f507d8b360a4113c912d2d1fc777d889a`。
- Qwen3 复验：`benchmark-results/model-selection/preflight/20260727T014900Z/summary.json`，SHA-256 `21954e4f6454243deb47258fbb0cfd4b091e8016f4ece874b37490b6e87074de`。
- 沙箱记录：`benchmark-results/model-selection/preflight/20260727T015043Z/summary.json`，SHA-256 `1344f206435744bfe608a619c3cb202d3ec41dcbbf9b977bfa361b484b35e76c`。其中 `/dev/nvmap` 与 CUDA0 均不可见，状态仅为 `BLOCKED_SANDBOX`，不表示宿主机 GPU 故障。
- 预检脚本、配置与 manifest 的收口版本 SHA-256 分别为 `b463fa4c158a55837efb2c30b4d6923f9f8449255c66411ee9f397cb83cd1167`、`9c7f3d5ea02988515955751864f9968f747d9cee57758b50dae76252adc52dd8`、`a939a86f1dcd56d83f8791abe948e3a306b1f7d5f17310a72014d92d7f9042b4`。

## 归档的模型来源材料

| 归档文件 | 原始未跟踪路径 | 可确认的归属 | SHA-256 |
| --- | --- | --- | --- |
| `docs/evaluation/sources/qwen3-4b/README.md` | `md/README.md` | `Qwen/Qwen3-4B-GGUF` README；front matter 记录 `base_model: Qwen/Qwen3-4B` 与 Apache-2.0 | `f7b7cbdbeab2a25b55e92cf160c035287374253b13af7ea2d5178847f6f8537e` |
| `docs/evaluation/sources/qwen2.5-3b-instruct/LICENSE` | `md/LICENSE(1)` | Qwen2.5 的 Qwen Research License Agreement | `ef52482bb785733093dc9a2e8edd8e764c77d12d8e9d8f10a80c9b547d32d0f9` |

前者不是 Qwen3 权重文件本身，后者不是 Qwen2.5 GGUF metadata；它们仅作为来源和许可证证据归档。Qwen2.5 的商业使用授权仍为待确认，不能由该研究许可替代。

## 后续准入

四个模型通过 Runtime 门禁，可以进入第一轮固定 10 Prompt 比较；该许可仅限实验和筛选。正式比较前仍须维持 Qwen2.5 的商业授权待确认状态，并将 Phi 的 exact-one-word 偏差作为 J-09 质量评分事实，而非 Runtime 失败。
