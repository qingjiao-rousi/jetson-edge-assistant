# M8.1 Application VLM Diagnosis API

The EdgeOmni application boundary is `RuntimeService`. M8.1 adds `POST /v1/diagnose/image`, accepting only `prompt`, exactly one `images` item (`id`, `mime`, `data_base64`), optional `request_id`, and optional `stream`. It normalizes into the existing `GenerateRequest` and uses the M7.5C shared base64 transport, `ImageInput` contract, validator, asset gate, RuntimeService, and MtmdBackend. It introduces no second image parser or asset verifier.

Example uses a placeholder only:
```json
{"request_id":"example","prompt":"Describe the panel.","images":[{"id":"example.png","mime":"image/png","data_base64":"AA=="}],"stream":true}
```

SSE remains `metadata -> token* -> terminal`; response terminal fields expose request ID, finish reason, error, image tokens, and measurement status. Client-side format/image-gate failures map to 400. Runtime asset, CUDA, model, and internal failures remain service-side errors. No response logs or echoes base64, raw bytes, or local paths.

M7.5C-R is the lower Adapter service's single three-image smoke evidence. M8.1 is offline API-contract validation only, makes no performance, stability, concurrency, or deployment conclusion, and does not load a model. 8192 is the development default; metadata context 128000 is not a Jetson deployable-length claim.
