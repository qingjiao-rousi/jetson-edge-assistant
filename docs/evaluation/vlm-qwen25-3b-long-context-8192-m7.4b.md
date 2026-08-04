# M7.4B Qwen2.5-VL-3B 8192 合成长手册单图事实

日期：2026-07-30。固定 `Qwen2.5-VL-3B-Instruct Q4_K_M`、`Q8_0 mmproj`、测试图片与 Runtime 完成一次 8192 context 合成长手册加单图验证。进程 exit code 为 `0`，全部容量、Runtime、vision、JSON 和事实正确性成功门通过。证据目录为 `benchmark-results/vlm-long-context/20260730-044757-968503-0400/`。

## Fixture 与 Tokenizer

fixture 由 `scripts/generate_vlm_long_context_fixture.py` 以 92 个 filler blocks 确定性生成，大小 `34994 bytes`，SHA-256 为 `69f658cbce2ade01e8bc20d73b4a801910ae3368d20e7d8acdafb9588df1fc90`。内容完全合成，不含真实客户、现场、操作员或设备信息；三个事实标记各出现一次，其位置比例分别约为开头 `0.0107`、中点 `0.4986`、末尾 `0.9871`。fixture 未披露 publisher。

现有构建目录中的 `llama-tokenize` target 已单独构建。binary 大小为 `29040 bytes`，SHA-256 为 `1012999431de6d4f778759f7e6464e7f9578b3a8fe2f620dbf8af3aa563b2b03`；Runtime commit 为 `19cc26967140407efe34006a355ab445b35b16ac`。正式校准以 `--file` 读取 fixture，tokenizer exit code 为 `0`，直接报告 `6334` raw tokens。该 tokenizer 调用只加载 vocab，不是 inference attempt。

最终 `llama-mtmd-cli` 直接报告 `6735` prompt tokens，位于要求的 6000–7000 区间；本次日志直接报告其中的 image tokens 为 `391`。长度判定没有使用字符数估算。

## 固定执行与加载

完整命令保存在证据目录的 `inference-command.txt`。固定参数为 context `8192`、batch `512`、ubatch `512`、GPU layers `99`、Flash Attention `on`、temperature `0`、seed `424242` 和最大新 token `128`；使用 `--file`、`--offline`、`--no-warmup` 和单张固定图片，不使用 chat mode 或远程模型参数。

| 项目 | 本次事实 |
| --- | --- |
| 主模型 | SHA-256 校验通过；加载成功；37/37 layers offload 到 CUDA0 |
| mmproj | SHA-256 校验通过；加载成功；519 tensors；CLIP 使用 CUDA0 |
| Context / batch / ubatch | `8192 / 512 / 512`，均由 CLI 日志确认 |
| Flash Attention | `enabled` |
| 图片处理 | 解码、vision preprocess、vision encode 和 embedding 注入成功 |
| Image grid / tokens | `23 x 17` / `391`，token 数直接来自本次日志 |
| Prompt / output | `6735 / 41` tokens；output token 使用 llama perf eval runs |
| Exit / finish / failure | `0` / `eog` / `null` |
| Attempts | tokenizer `1` 次，不计推理；inference `1` 次；retry `0` |

KV allocation 为 `288.00 MiB`、`8192 cells`、`36 layers`，其中 K `(f16)` 为 `144.00 MiB`，V `(f16)` 为 `144.00 MiB`。日志未发现 OOM、CUDA error、context overflow 或崩溃。

## JSON 正确性

stdout 去除首尾空白后整体通过 JSON 解析，没有提取 code fence 或修复文本。对象恰好包含四个要求的 key，自动检查结果如下：

```json
{
  "publisher": "The New York Times",
  "start_code": "A17",
  "middle_torque_nm": 42,
  "reset_seconds": 7
}
```

publisher 来自固定图片，fixture 自身不包含 `The New York Times`。start code 为严格字符串 `A17`，torque 与 reset duration 分别为整数 `42` 和 `7`。

## Timing 与 Telemetry

| 指标 | 本次值 |
| --- | ---: |
| CLI load time | `31304.48 ms` |
| Vision preprocess | `null`；CLI 未独立计时，不倒推 |
| Vision encode | `2782 ms` |
| Image embedding decode/injection | `32 ms` |
| Prompt eval | `29223.41 ms` |
| Decode | `5695.88 ms` |
| CLI total | `37033.86 ms` |
| Wall-clock | `38499 ms`，由 `date +%s%N` 测量 |
| tegrastats samples | `151` |
| Peak UMA used | `10789 MB / 30697 MB` |
| Peak GR3D | `99%` |
| Peak temperature | `57.125 C` |
| Peak `VDD_CPU_CV` | `2677 mW` |
| Peak `VDD_GPU_SOC` | `7268 mW` |
| Peak `VIN_SYS_5V0` | `6562 mW` |

所有 timing 和 telemetry 都是本次单次执行的直接日志值。它们不与 M7.4A 计算性能提升或退化比例。

## 结论边界

这只是一次合成长手册与单图联合输入测试，不是 RAG，不是实际多轮 session，也不是生产手册质量评测。它不形成平均性能、稳定性、长稳或部署结论。没有运行 16384 或 32768，没有接入 Agent、RAG 或多 session。
