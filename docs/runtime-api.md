# Runtime HTTP API

`/v1/generate` 和 `/v1/chat` 接受相同的 Runtime 请求结构。下面只记录它们现有的 `sampling` 和 `stream` 合同；这不是生产服务或兼容性承诺。

## Sampling

`sampling` 是可选 JSON object。省略字段时，Runtime 使用以下默认值：

```json
{
  "seed": 424242,
  "top_k": 1,
  "top_p": 1.0,
  "min_p": 0.0,
  "temperature": 0.0
}
```

可发送全部或任意子集：

```json
{
  "sampling": {
    "seed": 424242,
    "top_k": 40,
    "top_p": 0.95,
    "min_p": 0.05,
    "temperature": 0.8
  },
  "stream": false
}
```

| Field | JSON type | Accepted values |
| --- | --- | --- |
| `seed` | integer | `0..4294967295` (`UINT32_MAX`) |
| `top_k` | integer | `0..100000` |
| `top_p` | number | finite, `(0, 1]` |
| `min_p` | number | finite, `[0, 1]` |
| `temperature` | number | finite, `[0, 10]` |
| `stream` | boolean | `true` or `false`; omitted means `false` |

`top_k <= 100000` 和 `temperature <= 10` 是 EdgeOmni HTTP API 的防御性输入边界，不是 `llama.cpp-omni` 规定的 sampler 上限。

## Errors

非法 JSON 产生 HTTP 400，响应包含 `{"error":{"code":"invalid_json",...}}`。已解析 JSON 的 `sampling` 或 `stream` 类型、整数范围、有限性或数值范围错误产生 HTTP 400，响应包含 `{"error":{"code":"invalid_argument",...}}`。
