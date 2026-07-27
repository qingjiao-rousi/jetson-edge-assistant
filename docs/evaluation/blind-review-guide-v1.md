# M4 Blind Review Guide (v1)

Independently score every row from 0 to 5 using its frozen rule below. Do not infer or record model identity, performance, paths, attempts, or runtime data.

- `J-01`: 5: 两个合理原因、各有可执行核查且无编造；3: 一个合理原因或核查不完整；0: 错误、编造或非中文。
- `J-02`: 5: 识别过流/过载后停机链路，区分证据与待查；3: 方向对但未区分；0: 矛盾或声称未给根因。
- `J-03`: 5: 恰好4步、安全排序、每步含检查对象和判定动作；3: 一处偏差；0: 危险建议或严重不符。
- `J-04`: 5: 不定因，恰好3条高价值数据；3: 有保留但夹带猜测或数据不全；0: 断言具体故障。
- `J-05`: 5: 可解析 JSON、字段齐全且事实一致无额外文本；3: 可解析但一项轻微问题；0: 不可解析、额外文本或编造。最低合格4。
- `J-06`: 5: 英文清晰、两处合理位置和安全测量、保留不确定性；3: 基本正确但一项弱；0: 断言或危险建议。
- `J-07`: 5: 正确解释、中文自然、术语保留且优先级合理；3: 基本对但优先级弱；0: 误译关键术语或忽略任务。
- `J-08`: 5: 仅引用 M-42、解释条件并列三项检查；3: 少一项但不编造；0: 引入外部原因。
- `J-09`: 5: 输出恰为 READY；0: 任何其他字符、解释或大小写错误。
- `J-10`: 5: 可解析 JSON，06:49、P-8、振动报警及两个未确认项准确；3: 一个遗漏；0: 编造或不可解析。最低合格4。

For each row, fill `score_0_to_5`, a concise evidence-based `rationale`, your fixed `scorer` identifier, and `scored_at_utc` in ISO-8601 UTC. Keep all identity and response fields unchanged. Return the complete JSONL file for validation and merge.
