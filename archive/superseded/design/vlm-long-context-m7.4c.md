# M7.4C 16384 Context 合成长手册验证设计

日期：2026-07-30。M7.4C 是 M7.4B 之后的独立 16384 context 验证协议，不修改 M7.3、M7.4A 或 M7.4B 的脚本、fixture、配置和证据。它仍使用固定 Qwen2.5-VL-3B Q4_K_M、Q8_0 mmproj 和固定图片；不下载资产、不修改 Runtime 源码、不执行 RAG、Agent 或真实多 session。

## Fixture 和长度门

`scripts/generate_vlm_long_context_fixture_m7_4c.py` 是独立版本化 generator。它只生成 ASCII 合成手册，三个唯一事实仍分布在开头、中点和末尾，且不出现图片 publisher。`llama-tokenize --file` 直接校准 raw tokens，目标区间为 12600–14100；最终模型命令必须直接报告 13000–14500 prompt tokens。字符数不用于判断长度。

## 单次执行门

`scripts/run_vlm_long_context_m7_4c.py` 默认 dry-run，只有 `--execute` 执行。预检校验本地 binary、模型、mmproj、图片、Runtime commit/cleanliness，以及 M7.4B 的结果、配置、runner 和评估 JSON 的 size/SHA-256。执行参数固定为 context `16384`、batch/ubatch `512`、GPU layers `99`、Flash Attention `on`、temperature `0`、seed `424242`、predict `128`、`--file`、`--offline`、`--no-warmup` 和 mmproj offload。

Tokenizer 调用不算 inference attempt。模型最多启动一次，不自动下载、不 warmup、不改参数重试。必须保留 command、stdout、stderr、tegrastats 和状态文件；32768 仍未执行且不承诺部署。

## 成功门与边界

成功要求 CLI 直接确认 `16384 / 512 / 512`、直接报告 image tokens、13k–14.5k prompt tokens、37/37 CUDA offload、mmproj CUDA、图像解码/视觉编码/embedding 注入、有效 telemetry、非空严格 JSON 与四项事实正确，并且无 CUDA/OOM/context overflow/崩溃。任一缺失均不是成功。

这是单次合成长手册和单图输入测试，不是 RAG、生产手册质量评测或真实多轮 session。无论成功或失败，都不形成平均性能、稳定性、长稳或部署结论。
