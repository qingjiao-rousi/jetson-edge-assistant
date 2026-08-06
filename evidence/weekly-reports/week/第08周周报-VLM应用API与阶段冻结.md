# 第08周周报：VLM 应用 API 与阶段冻结

日期：2026-08-04。第 8 周在既有单常驻 VLM Runtime 上完成应用单图诊断 API、离线路由契约、失败审计和一次修复后的真实 HTTP/SSE 单图冒烟。原工业故障辅助主线不变，本周工作是 VLM 图片能力在应用入口的纵向完善。

## 本周完成

- 新增 `POST /v1/diagnose/image`，仅接受 prompt、可选 request ID、可选 stream 和一个 `{id,mime,data_base64}` 图片；禁止路径、URL、data URI、多图和未知字段。
- 复用 M7.5 已有 RuntimeService、ImageInput、图片门禁、资产 verifier、MtmdBackend 和 SSE，不建立第二套模型服务。
- FakeBackend 真实 loopback 测试验证请求规范化、单次 backend 调用、图片数据不泄漏及 `metadata -> token* -> terminal`。
- M8.2-D 定位首轮应用请求在 parser 前置门禁失败：`max_new_tokens` 被规范化为 signed JSON integer，而共享 parser 要求 unsigned；历史真实 inference 数修正为 0，但历史目录保持不变。
- runner 增加 HTTP status/reason/headers、脱敏 body、异常类型、阶段、耗时和 response bytes 取证；inference 只根据 backend token/terminal 直接证据计数。
- M8.2-R 只启动一次 service、只发一个请求、无重试，完成修复后的真实应用链路。

## M8.2-R 事实

| 项目 | 结果 |
| --- | --- |
| HTTP | 200 |
| SSE | 1 metadata、67 token、1 done，顺序通过 |
| Backend | `generate_text` 已调用，inference run 1 |
| Tokens | image 391、prompt 415、output 67 |
| 输出门 | 包含 `The New York Times` |
| CUDA | `CUDA0: Orin`，37/37 layers offload |
| Context/KV | 8192；288 MiB |
| Adapter timing | model ready 6220 ms；preprocess 11 ms；prefill 4709 ms；TTFT 4899 ms；decode 9205 ms；total 13940 ms |
| mtmd 日志 | vision encode 2947 ms；embedding decode 54 ms |
| Telemetry | 80 样本；UMA 9483/30697 MiB；GR3D 99%；57.281 C |
| 清理 | service exit 0；tegrastats 已停止 |

本轮账本：当前 service start 1、application request attempt 1、inference 1、retry 0；连同失败的 M8.2，累计 application attempt 2、累计真实 inference 1。

## 阶段边界

- 8192 继续作为开发默认 context；16384 仅保留既有 recovery 实验事实；32768 未执行且禁用。
- `qwen2vl.context_length=128000` 是模型 metadata，不是 Jetson 可部署长度结论。
- M7.5C-R 是底层单常驻服务三图顺序冒烟；M8.2-R 是应用路由单图恢复冒烟。二者都不是平均性能、长稳、并发或生产部署结论。
- 本周未接入 RAG、工具、Agent、多 session、音频、Docker 或 systemd，未修改 Runtime submodule，也未提交 git commit。

## 第8周验收

- [x] 单图输入和固定资产绑定；
- [x] image token、vision/embedding 原始日志和 Runtime metrics 分源记录；
- [x] HTTP JSON 与 SSE 应用入口；
- [x] 图片安全门禁和敏感数据不泄漏测试；
- [x] parser 失败根因审计与真实 loopback 回归；
- [x] 修复后 8192 应用 API 真实单图闭环；
- [x] 历史证据、attempt 语义和阶段限制明确冻结。

第 8 周正式关闭。下一步按原计划进入第 9 周单 VLM RAG，先完成离线文档、chunk、索引、引用和 FakeBackend 契约，不直接扩大到 Agent 或生产部署。
