# M10.2-B Agent JSONL 评估

状态：`DONE`（有界原型）。入口为 `python3 scripts/agent_m10_2.py --jsonl`，进程只初始化一次 embedding provider、ReadOnlyTools 和 SessionStore，并逐行输出独立 JSON 响应。

契约测试覆盖：同一 session 连续请求轮次为 1、2；不同 session 历史隔离；reset 后重新从 1 开始；第 9 个 session 被拒绝；重复 request_id、unknown op、空 session_id、超长 query 被拒绝；无证据时模型调用次数为 0；模型不输出 `[S1]` 等引用时返回 `CITATION_FORMAT_ERROR`；JSONL 输入输出一一对应。

回答提示明确要求只依据 `Manual evidence`，每个事实句末尾使用 ASCII `[S<n>]`，中文回答也保留该标记，且不输出 Markdown 代码块。首次答案不合规时以相同 evidence 最多重试一次；两次都失败不写入 session，并返回 `retry_count` 和 `citation_failure_reason`。引用索引必须对应本次 retrieval 的 citations，不能引用不存在或另一 session 的证据。

固定边界：最多 8 个 session、每 session 最近 20 轮、单次最多 3 个 Agent 步骤、query 最多 4096 字符、session_id 最多 128 字符。工具白名单仅为 `search_manuals`、`read_manual`、`lookup_fault_code`，并记录 request_id、session_id、op、plan、tool_audit、session_turns、status 和耗时；不记录完整手册或 prompt。

这是进程内有界 session 原型，不代表 Runtime 层多 session KV，也不支持持久化、LRU/TTL、跨进程共享或生产鉴权。
