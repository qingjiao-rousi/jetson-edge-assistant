# M10.1 KV Prefix Reuse Evaluation

状态：`DONE`。本报告记录单热文本 session 的 Jetson 实机验证，不代表多用户生产缓存。

## 固定配置

- 模型：`Qwen3-4B-Q4_K_M.gguf`
- SHA-256：`7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`
- Runtime：context `1024`、batch/ubatch `256/256`、GPU layers `99`、Flash Attention 开启
- Sampling：seed `424242`、top_k `1`、top_p `1`、min_p `0`、temperature `0`

## 实机结果

| 请求 | 输出 | 命中/Prompt | 实际 Prefill Token | Prefill | TTFT | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 冷 | `Ready.` | 0/18 | 18 | 179ms | 194ms | 421ms |
| 热 | `Ready.` | 17/18 | 1 | 0ms | 91ms | 267ms |
| Prefix 分叉 | `Stable.` | 8/18 | 10 | 16ms | 102ms | 379ms |

`cold_hot_output_equal=true`。热请求保留 17 个共同 Token，并重新计算最后一个 Prompt Token；分叉请求只复用公共 Token Prefix。

## 验收

- `build-runtime` CTest：5/5 通过；
- Python unittest：85/85 通过；
- `edgeomni_qwen3_integration_test`：通过，覆盖冷/热首 token 与完整输出一致、分叉、reset；
- `git diff --check`：通过。

## 边界

仅支持一个热文本 session。没有多 session、LRU、TTL、持久化、跨进程共享、图片/VLM KV、缓存池、并发 decode 或生产多用户隔离。M9.1B-R2.5 仍为 `PARTIAL`：其独立 holdout 的无答案拒绝率为 `0.50`，低于 `0.75`，不得重跑或用于调参。M9.2 的本地手册检索、citation 和本地模型带来源回答闭环已经完成，但仍是原型集成。
