# M7.4B 合成长手册单图验证设计

日期：2026-07-30。M7.4B 使用固定 Qwen2.5-VL-3B Q4_K_M、Q8_0 mmproj、测试图片和 8192 context，验证一次合成长手册与单图联合输入。它不修改 M7.3/M7.4A 证据、M7.4A runner/config 或 Runtime 源码。

## 确定性 Fixture

`scripts/generate_vlm_long_context_fixture.py` 仅根据整数 `filler_blocks` 生成 ASCII 文本。填充段落描述虚构训练设备，明确不包含客户、现场、操作员或真实设备信息。三个唯一权威事实分别位于开头、中点和末尾：`start_code = A17`、`middle_torque_nm = 42`、`reset_seconds = 7`。

末尾要求模型只输出包含 `publisher`、`start_code`、`middle_torque_nm` 和 `reset_seconds` 四个 key 的 JSON。fixture 不出现预期 publisher 名称；publisher 必须来自固定图片。

## Tokenizer 校准

现有 build 的 `llama-tokenize` target 单独构建，不重新配置 CMake。runner 在真实推理前对候选 fixture 执行：

```text
llama-tokenize --model <local-gguf> --file <fixture> --ids --show-count --log-disable
```

长度选择只依据 `Total number of tokens`，不使用字符数估算。配置把 raw tokenizer 目标放在 6200–6400。M7.4A 的固定短 prompt raw count 为 14，CLI prompt count 为 415，实际 image tokens 为 391，说明当前 chat template 与 marker 另有 10 tokens 固定开销；该证据只用于把候选放在区间内部。M7.4B 的最终成功门仍以本次 `llama-mtmd-cli` 直接报告的 6000–7000 prompt tokens 为准。

Tokenizer 只加载 vocab 并输出 token IDs/count，不计为 inference attempt。最终证据保存 tokenizer binary 身份、Runtime commit、模型 SHA-256、fixture SHA-256、raw token count、命令、stdout、stderr 和完整校准历史。

## 单次执行门

runner 默认和 `--dry-run` 都不启动 subprocess；只有 `--execute` 才执行预检、tokenizer 校准和一次模型推理。预检严格校验 Runtime commit/cleanliness、两个 binary、模型、mmproj、图片和四个 M7.4A 只读 reference 文件的大小与 SHA-256，并拒绝 `ldd` 的 `not found`。

推理命令固定使用 `--file fixture.txt`、`--ctx-size 8192`、batch/ubatch `512`、GPU layers `99`、Flash Attention `on`、temperature `0`、seed `424242`、predict `128`、mmproj offload、offline 和 no-warmup。外部 `timeout` 限制执行时间，`date +%s%N` 测量 wall-clock，tegrastats 记录 UMA、GR3D、温度和功耗；不使用 `/usr/bin/time`，不自动下载，不 warmup，不重试。

每次执行使用 `benchmark-results/vlm-long-context/<timestamp>/` 新目录并以 `exist_ok=False` 创建。推理启动后的任何结果都保留 command、stdout、stderr、telemetry、process status 和 result，不修改 prompt 或参数进行第二次尝试。

## 正确性与边界

stdout 去除首尾空白后必须整体通过 JSON 解析，不能从 Markdown fence 或其他文本中提取对象。对象必须恰好包含四个指定 key；publisher 字符串必须包含 `The New York Times`，start code 必须严格为字符串 `A17`，两个数值必须是非布尔整数 `42` 与 `7`。解析失败或任一事实错误归类为 `quality_gate_failed`，原始 stdout 保持不变。

成功还要求 CLI 直接报告 6000–7000 prompt tokens、直接报告 image tokens、37/37 CUDA offload、mmproj CUDA、完整 vision 路径、非空输出、有效 tegrastats 样本，且没有 OOM、CUDA error、context overflow 或崩溃。

这是单次合成长手册测试，不是 RAG，不是实际多轮 session，也不是生产手册质量评测。结果不形成平均性能、稳定性或部署结论，不与 M7.4A 计算性能提升比例；16384 和 32768 不执行。
