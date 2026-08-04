# M7.5C VLM Service Image Contract

The HTTP request accepts an optional `images` array with at most one item. Every item has only `id`, `mime`, and standard base64 `data_base64`; data URIs, URLs, paths, unknown fields, malformed padding, and decoded payloads over 10 MiB are rejected before a large decoded buffer is retained. The HTTP layer never logs encoded image data.

For SSE, `metadata` is emitted before backend generation and therefore contains `image_tokens: null`: actual image tokens do not exist until the mtmd chunk path processes decoded bytes. The terminal response contains the direct mtmd image-token value. Image preprocess is measured by the Adapter; separate vision encode and embedding timing remain `not_measured` unless an upstream API exposes them directly. The fixture set is deterministic and synthetic; one sequence run would be a single fixed-input integration check, not a performance, stability, or deployment conclusion.
