# Qwen3 DirectBackend chat-template 决策（M5.1a）

状态：**B. 已确认：公开 API 不能等价实现，M5.2 必须引入明确的 template-rendering 适配层。**

审计对象是冻结 fork `third_party/llama.cpp-omni` 的
`19cc26967140407efe34006a355ab445b35b16ac`，以及部署实物
`models/Qwen3-4B-Q4_K_M.gguf`（设计基线见
`docs/design/direct-backend-m5.1.md:7-20`）。本次只离线读取了 GGUF
metadata；没有初始化 libllama、创建 context 或启动模型。

## 结论

Qwen3 GGUF 的默认 Jinja 模板把 `enable_thinking is false` 显式渲染为：

```text
<|im_start|>assistant\n<think>\n\n</think>\n\n
```

而公开 `llama_chat_apply_template()` 既没有 template-variable 参数，也明确不是
Jinja renderer。对该模板，它的实现会按 `<|im_start|>` 启发式识别为
`chatml`，只输出：

```text
<|im_start|>assistant\n
```

两者字节不同，且前者的空 `<think>...</think>` prefill 是 Qwen3
`--reasoning off` 的目标输入语义，不能省略。因此不需要 Jetson 推理验证即可确认：
只调用公开 libllama API 的 DirectBackend **无法**稳定复现这一语义。另见第 3 节：
当前构建的 `llama-cli` 来自 `tools/cli` target，而不是旧的 `tools/main` target；
不能把 `tools/cli` 的 common/Jinja 能力误写成公开 libllama C API 能力。

这不是对 `llama_chat_apply_template()` 的负面推断，而是由其声明和实现共同
确定的限制：C API 只接收 `tmpl/chat/n_msg/add_ass/buf/length`
（`third_party/llama.cpp-omni/include/llama.h:1167-1186`）；实现也只把消息的
`role`、`content` 转给预定义格式器（`third_party/llama.cpp-omni/src/llama.cpp:467-495`）。

## 1. 冻结 Qwen3 GGUF metadata

离线命令：

```bash
python3 third_party/llama.cpp-omni/gguf-py/gguf/scripts/gguf_dump.py \
  models/Qwen3-4B-Q4_K_M.gguf
```

结果为 28 个 KV，`general.architecture = qwen3`，且仅存在一个模板键
`tokenizer.chat_template`；不存在 `tokenizer.chat_template.*` 和
`tokenizer.chat_templates`，所以可用 template 名称集合只有默认项（无命名变体）。
GGUF 二进制键本身没有可引用的文本行号；键名和命名变体的规范常量见
`third_party/llama.cpp-omni/gguf-py/gguf/constants.py:268-270`，该离线 dump
的输出将默认键列为第 29 个 KV。

默认模板的实际尾部条件为：

```jinja
{%- if add_generation_prompt %}
    {{- '<|im_start|>assistant\n' }}
    {%- if enable_thinking is defined and enable_thinking is false %}
        {{- '<think>\n\n</think>\n\n' }}
    {%- endif %}
{%- endif %}
```

因此 reasoning 开关存在，名字为 `enable_thinking`；默认未定义/非 false
时不附加空 think block，false 时附加。模板还使用 `tools`、
`messages`、`add_generation_prompt`、`bos_token`、`eos_token` 等 Jinja
上下文，不能把它安全降格为仅 role/content 的通用 ChatML。GGUF writer 对
`default` 和命名变体如何写入这些键的代码也可见
`third_party/llama.cpp-omni/gguf-py/gguf/gguf_writer.py:1084-1110`。

## 2. 公开 C API：签名、语义与变量能力

`llama_model_chat_template(model, NULL)` 是公开 API 获取默认模板的方式，
其注释也定义了 `NULL` 表示默认项（`third_party/llama.cpp-omni/include/llama.h:607-609`）。

公开渲染 API 为：

```c
int32_t llama_chat_apply_template(
    const char * tmpl, const struct llama_chat_message * chat,
    size_t n_msg, bool add_ass, char * buf, int32_t length);
```

完整声明、输出缓冲/返回长度语义在
`third_party/llama.cpp-omni/include/llama.h:1167-1186`。尤其 `:1169` 明确：
它“不使用 jinja parser”，只支持预定义模板列表。该签名没有 context/kwargs
对象，因而不支持 `enable_thinking` 或任何 template variables。

实现进一步确认该限制：先通过字符串启发式 `llm_chat_detect_template()`
分类，不认识就返回 `-1`（`third_party/llama.cpp-omni/src/llama.cpp:474-488`）；
`<|im_start|>` 会直接分类为 `LLM_CHAT_TEMPLATE_CHATML`
（`third_party/llama.cpp-omni/src/llama-chat.cpp:96-104`）；该分支只逐条输出
role/content，并在 `add_ass` 时追加 assistant 开头
（`third_party/llama.cpp-omni/src/llama-chat.cpp:250-257`）。它不会读取、解释或
绑定 GGUF 模板中 `enable_thinking` 条件。

`llama_chat_builtin_templates()` 仅枚举内置模板名（声明在
`third_party/llama.cpp-omni/include/llama.h:1185-1186`）；该能力同样没有变量绑定
入口，不能补足上述差异。

## 3. CLI 的 `--reasoning off` 实际路径（非公开 API）

选项解析把 `--reasoning off` 设为 `enable_reasoning = 0`，并将
`default_template_kwargs["enable_thinking"]` 写成字符串 JSON `"false"`
（`third_party/llama.cpp-omni/common/arg.cpp:3171-3187`；字段定义在
`third_party/llama.cpp-omni/common/common.h:620-635`）。这是 `common`/CLI
参数状态，**不是** `include/llama.h` 所声明的 libllama C API。

当前构建产物的来源由 `third_party/llama.cpp-omni/tools/cli/CMakeLists.txt:1-20`
确认：`llama-cli` 链接 `llama-cli-impl`，实现位于 `tools/cli/cli.cpp`。
`tools/cli/cli.cpp:202-223` 在 `format_chat()` 中设置
`inputs.use_jinja`、`inputs.add_generation_prompt` 和 `inputs.enable_thinking`，
随后调用 common 模板管线。`inputs.enable_thinking` 的 false 分支位于
`third_party/llama.cpp-omni/tools/cli/cli.cpp:219`。

在 Jinja 路径中，`inputs.enable_thinking` 被传入 renderer 参数
（`third_party/llama.cpp-omni/common/chat.cpp:2342-2358`），随后作为
`enable_thinking` 注入并执行模板（`third_party/llama.cpp-omni/common/chat.cpp:831-880`）。
因此，当前 `llama-cli` 的源码可以确认 common/Jinja renderer 会接收
`enable_thinking=false`；旧 `tools/main` 路径的调用点不代表当前构建产物。

`--reasoning off` 到 renderer 布尔值的已确认实现位于 server/common 管线：
server-context 计算 `params_base.enable_reasoning != 0 &&
template_supports_thinking`，所以 off（0）得到 `enable_thinking=false`
（`third_party/llama.cpp-omni/tools/server/server-context.cpp:1208-1223`）。该行同时
明确此条件是 Jinja + template-support 检测；不是公开 C API 行为。随后 CLI chat
renderer 接收该值的赋值可见
`third_party/llama.cpp-omni/tools/cli/cli.cpp:202-223`，并由 common Jinja renderer
注入为全局变量（`third_party/llama.cpp-omni/common/chat.cpp:2342-2358,831-880`）。

因此，所要求的 non-thinking 模板语义来自 server/common 的 Jinja 渲染器，而不是
C API 的 `llama_chat_apply_template()`。当前 `llama-cli` 的 common 路径已由源码和
宿主机预检分别确认；这不意味着 DirectBackend 可以调用该内部 renderer。无论以
目标 Qwen3 template 语义还是已确认的 server/common 行为为基准，都不能把 common
能力或 CLI 的 `default_template_kwargs` 误描述为 DirectBackend 可调用的公开接口。

## 4. DirectBackend 可复用与不可复用的边界

| 项目 | 仅公开 libllama API 的状态 |
| --- | --- |
| 从模型取得默认模板文本 | 可复用：`llama_model_chat_template(model, NULL)`。 |
| 将标准 role/content 消息格式化为 ChatML 近似 prompt | 可复用：`llama_chat_apply_template()` 的 ChatML 分支。 |
| 缓冲区长度查询、扩容和生成 prompt | 可复用：该 API 的返回长度约定。 |
| 渲染 Qwen3 原始 Jinja | 不可复用：C API 明确不使用 Jinja。 |
| 向模板传 `enable_thinking=false` | 不可复用：公开签名没有变量/kwargs 参数。 |
| Qwen3 `--reasoning off` 空 think prefill | 不可复用：ChatML 分支只追加 assistant header，实际 Qwen3 模板另追加空 think block。 |
| `common_chat_templates_apply*`、Minja、CLI kwargs | 不可作为 DirectBackend 的公开 libllama 依赖；它们属于内部 common 层。 |

## 5. 不依赖内部 common API 的稳定路径

存在稳定路径，但它必须是 M5.2 的明确 **ChatTemplateRenderer** 适配层，而非
将 C API 的近似格式伪称为等价。该层应：

1. 以固定 Qwen3 GGUF metadata 模板为输入契约，保存模板 SHA-256/原始文本
   fingerprint；模型模板变化时拒绝运行或要求重新审计。
2. 使用自有或独立、版本锁定的 Jinja-compatible renderer，显式传入
   `messages`、`tools`、`add_generation_prompt`、`bos_token`、`eos_token` 和
   布尔 `enable_thinking=false`。不得链接或调用 `common_chat_templates_*`。
3. 在 renderer 单测中以最少的 system/user、历史 assistant、tool 和
   generation-prompt fixture 锁定与冻结模板的逐字节输出；其中无 tool 的 user
   generation fixture 必须以空 `<think>\n\n</think>\n\n` 结尾。
4. 只把 renderer 的 UTF-8 prompt 交给公开 `llama_tokenize`/decode/sampling
   API；模型推理生命周期仍完全使用公开 libllama。

这条路径不依赖内部 common API，且把模板兼容性从隐式行为变成可审计契约。

## M5.2 模型策略

选择：**增加独立 ChatTemplateRenderer，并直接实现 Qwen3 DirectBackend。**

不建议先以 Qwen2.5 替代：本审计已确认 Qwen3 的差异，不存在需要 Jetson
运行才能作出的等价性判断；以 Qwen2.5 骨架延期只会留下未经解决的模板边界。
M5.2 的进入条件是 renderer 的离线逐字节模板测试通过；之后才可进行已有
设计所列的、显式标记的 Jetson integration。
