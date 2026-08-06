# Qwen3 Q4_K_M/Q8_0 离线质量对比评测

## 方法与样本

这是一次**离线 AI 辅助盲评**，`scorer=ai_assisted`，不是人工评审。只读取 `benchmark-results/qwen3-quant-kv/20260728T033622Z/records.jsonl` 与 `benchmark-results/qwen3-quant-kv/20260728T035104Z/records.jsonl` 中 `phase=measured` 且 `valid=true` 的记录；排除 preconditioning。每个模型 15 条，S/L/G 各 5 条。

评分阶段只使用匿名 `candidate_a` 和 `candidate_b`，完整文本、prompt_id、attempts、SHA-256 和机械检查在 [blind-samples.jsonl](/home/nvidia/Desktop/llm/vlmllm-main/benchmark-results/qwen3-quant-kv/quality-review-20260728/blind-samples.jsonl) 中；评分在 [score.jsonl](/home/nvidia/Desktop/llm/vlmllm-main/benchmark-results/qwen3-quant-kv/quality-review-20260728/score.jsonl) 中。评分完成后才映射 `candidate_a=Q4_K_M`、`candidate_b=Q8_0`。

同一模型/同一 prompt 的 5 次输出逐字节相同，因此盲样本按 6 个唯一文本保存，每条保留 `attempts=[1,2,3,4,5]` 和 `sample_count=5`；汇总仍按 15 个有效 measured 样本加权，不将确定性重复伪装为独立语义证据。

## 机械比较

| Prompt | Q4 SHA-256 | Q8 SHA-256 | 两模型相同 | output tokens | 机械观察 |
|---|---|---|---:|---:|---|
| S | `146145e9…459a8` | `6e4cd508…fb6d` | 否 | 32 | 无空输出/乱码；具体温度和建议没有输入依据。 |
| L | `f7701a3a…5744` | `6f3f6796…a1d1` | 否 | 32 | 无空输出/乱码；两者在句中截断，Q8 可见文本更完整地复述了 nominal/stable/55°C。 |
| G | `f1a7e31f…0a3e2` | `6f532847…6e0a` | 否 | 256 | 无空输出/乱码；两者均在未完成句子处截断，并编造未给定的设备数值。 |

所有 30 条输出均为 `finish_reason=length`。这只记录输出上限/截断限制，不能直接等同于质量差；可见文本覆盖不足、格式断裂或无依据事实才反映在相应评分维度。

## AI 辅助评分

每个维度 0--5：relevance、factual_consistency、completeness、actionability、format_compliance、safety。相同文本获得相同评分；本次不存在跨模型完全相同文本。

| Prompt | 模型 | n | Relevance | Factual | Completeness | Actionability | Format | Safety | 总分 / 30 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S | Q4_K_M | 5 | 3 | 1 | 3 | 1 | 4 | 2 | 14 |
| S | Q8_0 | 5 | 3 | 1 | 3 | 1 | 4 | 2 | 14 |
| L | Q4_K_M | 5 | 3 | 4 | 1 | 1 | 4 | 4 | 17 |
| L | Q8_0 | 5 | 3 | 5 | 1 | 1 | 3 | 4 | 17 |
| G | Q4_K_M | 5 | 4 | 1 | 2 | 1 | 4 | 2 | 14 |
| G | Q8_0 | 5 | 4 | 1 | 2 | 1 | 4 | 2 | 14 |
| Overall | Q4_K_M | 15 | 3.33 | 2.00 | 2.00 | 1.00 | 4.00 | 2.67 | 15.00 |
| Overall | Q8_0 | 15 | 3.33 | 2.33 | 2.00 | 1.00 | 3.67 | 2.67 | 15.00 |

S 的两者均提供要求的状态字段，但都编造温度，并给出无依据建议。L 的 Q8 可见部分更准确复述固定日志，Q4 的格式略完整；两者都在行动建议前结束。G 的两者有编号结构，但都编造系统、温度、内存或利用率事实，且未完成验证与修复部分。每条评分的简短理由和不确定性在 `score.jsonl`。

## 结论与边界

质量结论为**并列/无法区分**：S/L/G 总分均为 Q4=14/17/14、Q8=14/17/14；L 中的维度差异不足以建立质量排名。这个质量结果不改变 `manifests/quantization-deployment-baseline-v1.json` 的独立工程性能排序：Q4_K_M 是端侧部署优先候选，Q8_0 是高精度对照/质量优先候选。

本评测只有 S/L/G 三类固定 prompt、没有独立人工评分、没有通用知识/事实问答/真实设备故障数据集，且所有输出均受 `finish_reason=length` 限制。因此不能据此声称 Q4 或 Q8 在所有任务上质量更高。最终部署选择仍必须同时考虑质量、Decode、启动时间、功耗、内存和 OOM 风险。

机器可读汇总见 [qwen3-q4-q8-quality-evaluation-20260728.json](/home/nvidia/Desktop/llm/vlmllm-main/docs/evaluation/qwen3-q4-q8-quality-evaluation-20260728.json)。
