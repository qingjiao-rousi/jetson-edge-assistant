# 模型替换边界与操作清单

EdgeOmni 的模型路径和校验元数据是配置化的，但当前实现不能笼统称为“任意 GGUF 即插即用”。替换成本取决于替换的是量化文件、VLM 家族还是 RAG embedding。

## 替换分级

| 替换类型 | 当前难度 | 需要改什么 | 必须重新验证什么 |
| --- | --- | --- | --- |
| 同一 Qwen2.5-VL 发布中的 Q4/Q8 主模型 | 低到中 | 新建完整 `assistant-<variant>.json`，更新 main GGUF 路径、大小、SHA-256，并声明与 MMProj 的配对 | `assistant` preflight、真实加载、chat template、37/37 offload、文本/单图冒烟、性能/内存 |
| 同一模型的新 GGUF revision | 中 | 除上述字段外，记录 repository/revision/license；重新确认 MMProj 是否仍兼容 | 完整回归，旧结果不得沿用 |
| 另一个受固定上游支持的 VLM 家族 | 中到高 | 可能需修改 `MtmdBackend` 的资产绑定、默认 marker/template 和输入适配；上游必须支持该 architecture/vision projector | 构建、加载、template、图像 tokenization、输出、取消/超时、资源与质量 |
| 文本模型（不用图像） | 中 | 当前 service host 固定实例化 `MtmdBackend`；需要新增明确 backend/profile 选择，不能只删 MMProj 字段 | 文本 API、KV reuse、模板、采样与错误合同 |
| RAG embedding 模型 | 高 | 更新 `configs/embedding.json` 的 binary/model/dimension/pooling/template/hash，并重建一个**新** SQLite index 合同 | embedding fingerprint、维度、索引 metadata、全新 dev/eval；不能消费 R2.5 holdout |

## 为什么还不是任意模型即插即用

1. `runtime/tools/vlm_service_host.cpp` 要求 main model 与 MMProj 的路径、大小和 SHA-256 全部存在，并固定创建 `MtmdBackend`。
2. `runtime/src/mtmd_backend.cpp` 当前资产 ID/绑定名仍包含 Qwen2.5-VL Q4/MMProj Q8 的具体名称；虽然校验器本身是通用结构，backend 的 profile 还没有完全数据驱动。
3. 模型必须被固定的 `llama.cpp-omni` commit 识别，带可用默认 chat template，并能由该版本 `mtmd` 初始化 vision support。
4. embedding 的 dimension、normalization、pooling、query/document template 会进入 fingerprint 和 SQLite metadata。换 embedding 后旧索引不能继续冒充兼容索引。
5. `DirectBackend` benchmark 路径另外只接受两个冻结 Qwen3 benchmark hash，不是通用 VLM 替换入口；EdgeOmni VLM 对照应通过完整 Assistant/Runtime config 启动。

## 推荐操作

不要覆盖 `configs/assistant.json`。为每个候选量化保存独立合同，例如：

```text
configs/assistant-q4.json
configs/assistant-q8.json
```

每份合同都要完整记录 model 和 MMProj 的 path、size、SHA-256，以及相同或有意调整的 context/batch/ubatch/GPU layers。然后分别执行：

```bash
# Run from the repository root.

python3 scripts/verify_local_assets.py --root . \
  --config configs/assistant-q4.json --profile assistant
python3 scripts/run_local_assistant.py --config configs/assistant-q4.json

python3 scripts/verify_local_assets.py --root . \
  --config configs/assistant-q8.json --profile assistant
python3 scripts/run_local_assistant.py --config configs/assistant-q8.json
```

当前仓库只固定提供 Q4 主模型合同。Q8 对照资产的真实大小、SHA-256 和 MMProj 配对在写入新合同前必须从本地获准资产中取得；不能复制 Q4 hash 或凭文件名猜测。

## 可进一步改进

要把“易替换”提升为可展示的工程能力，建议在 P1 增加 `runtime.profile`/`backend` 和通用 `asset_id`/`binding_id` 配置，提供 `assistant-q4.example.json`、`assistant-q8.example.json`，再增加 model matrix 测试。完成前，对外准确表述应是：**配置化替换已审计资产；跨模型家族需要适配和重新验证。**
