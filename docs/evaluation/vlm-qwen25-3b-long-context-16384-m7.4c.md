# M7.4C Qwen2.5-VL-3B 16384 合成长手册事实

日期：2026-07-30。M7.4C 的唯一一次 16384 context 执行状态为 `FAILED`，证据目录为 `benchmark-results/vlm-long-context-16384/20260730-052012-814635-0400/`。没有重试。

本地资产、Runtime commit 和四个 M7.4B 只读参考文件均通过 size/SHA-256 校验。M7.4C fixture 完全合成，大小 `73703 bytes`，SHA-256 为 `4ddfe0e50411670bffefa87b2715df90a43ef4c99502f9dd6257978820eecdef`。`llama-tokenize` 直接报告 `13301` raw tokens，处于 12600–14100 校准区间；该调用不计为 inference attempt。

模型命令已实际启动一次。日志直接确认 context/batch/ubatch 为 `16384 / 512 / 512`，并创建 `576.00 MiB` F16/F16 KV Cache（K/V 各 `288.00 MiB`）。图片解码、vision preprocess、vision encode、embedding 注入完成，image grid 为 `23 x 17`，image tokens 为 `391`。但 stderr 直接记录 `ggml_cuda_init: failed to initialize CUDA: unknown error`，所有记录的 KV layer 均为 CPU，未出现 37/37 CUDA offload 或 mmproj CUDA 证据。

运行在进入 prompt eval、decode 和输出前中断，runner 没有获得 child exit code。因而 prompt/output tokens、CLI total、wall-clock、finish reason 和 JSON 正确性均为 `null` 或不可评估。tegrastats 有 532 个有效样本，峰值 UMA 为 `14239 / 30697 MB`，但这不是 GPU 成功、性能或容量结论。

该失败不证明 16384 OOM，也不证明 16384 可用；它只证明在本次环境中 CUDA 初始化失败且一次启动未完成。未运行 32768，也没有修改参数进行第二次尝试。
