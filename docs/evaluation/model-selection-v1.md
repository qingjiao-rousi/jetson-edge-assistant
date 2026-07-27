# M1 文本指令模型第一轮选型协议（v1）

## 1. 目标和范围

本协议冻结阶段一的第一轮文本指令模型筛选：在同一 Jetson、同一 `llama-cli`、同一 Q4_K_M GGUF 和同一业务输入下，从 4 个 3B--4B 级候选中选出一个暂定主模型和一个备选模型。本轮仅使用文本单轮指令，不使用 RAG、工具调用、图片或音频；第一轮结论不替代后续 DirectBackend 复测。

状态只能使用：**已确认**、**未发现**、**待确认**。本文的“Runtime 支持”表示固定源码中存在从 GGUF 架构识别到模型实现的代码路径；运行时加载、CUDA offload 与生成结果另以预检归档为准。

## 2. 固定软硬件基线

| 项目 | 值 | 状态 / 证据 |
| --- | --- | --- |
| 主项目正式基线 | `9b63aad86f5befc2d1b35e1cbd162e27b4cc0a5c` | 已确认，正式 config/summary 记录的 commit；本审计时工作树 `HEAD=f9e6389...`，未切换版本 |
| Runtime | `jetson-runtime-dev@19cc26967140407efe34006a355ab445b35b16ac` | 已确认，`manifests/runtime.json` |
| CLI | `llama-cli`，version `259 (19cc269)` | 已确认，`docs/baselines/qwen2.5-3b-q4_k_m/validate-only.json` |
| 硬件与系统 | Jetson AGX Orin 32GB、Ubuntu 22.04.5、L4T R36.4.7、CUDA 12.6.68、aarch64 | 已确认，`manifests/environment.json` |
| CUDA 构建 | Release、SM 87、`GGML_CUDA=ON`、Flash Attention on、NCCL off | 已确认，`manifests/build.json` |
| 功耗模式 | `MODE_30W`，ID 2 | 已确认；正式 benchmark 后查询，非脚本开始时采样，见 telemetry |
| incumbent | Qwen2.5-3B-Instruct Q4_K_M | 已确认；`models/qwen2.5-3b-instruct-q4_k_m.gguf`，SHA-256 见 `manifests/model.json` |
| 正式参考 run | `qwen25-20260723T122143Z-75564` | 已确认；只作为参数和工程基线，不作为跨模型质量结论 |

## 3. 候选准入条件

1. 必须是 3B--4B 级的纯文本 instruction 模型，第一轮权重必须为 GGUF `Q4_K_M`；不得以不同量化等级的结果比较模型能力。
2. 固定 Runtime commit 必须有实际架构枚举、`general.architecture` 名称映射、模型创建分派及图构建实现。架构不支持即淘汰。
3. 最终决定前，模型身份、权重来源、许可证、不可变 revision、GGUF 文件名/大小和 SHA-256 均必须可验证；没有证据时保持“待确认”，不推测 Hugging Face `main`、LFS OID 或 license。
4. 每个实际 GGUF 必须在测前记录有限 metadata：architecture、name、file type、量化版本、tokenizer 类型、chat template 是否存在，以及文件 SHA-256；不得打印完整 token 列表或完整 template。
5. 报告语言覆盖中文、英文和中英混合；语言能力由固定任务实测，不把厂商宣传当结论。

## 4. 候选模型审计表

| 候选 | 定位 | 预期 GGUF 架构 | Runtime 支持 | 本地权重/metadata | 来源、许可证、不可变 revision、精确文件名/大小 | 特别限制 |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen2.5-3B-Instruct（incumbent） | 中文、中英混合的当前基准 | `qwen2` | 已确认 | 已确认：`models/qwen2.5-3b-instruct-q4_k_m.gguf`；`general.architecture=qwen2`、file type 15、量化版本 2、`tokenizer.ggml.model=gpt2`、chat template 存在 | 已确认：`Qwen/Qwen2.5-3B-Instruct-GGUF@cc1e68eea5f05f88f41a6de1fc73110178f23715`；文件 `qwen2.5-3b-instruct-q4_k_m.gguf`，`2104932768` bytes，SHA-256 `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`，Xet hash `5ae0c201348e276d543a1e5c0e053370e32415774095c677319f62b302b1620a`；Qwen Research License Agreement | 已确认加载、CUDA 全层 offload（37/37）和完整生成；仅限非商业研究/评估，商业使用待确认 Alibaba Cloud 单独许可 |
| Qwen3-4B（仅 Instruct，non-thinking） | 新一代 Qwen 对照，中文/英文/混合 | `qwen3` | 已确认 | 已确认：`models/Qwen3-4B-Q4_K_M.gguf`，file type 15、量化版本 2、chat template 存在；metadata name 为 `Qwen3 4B Instruct Awq` | 已确认：`Qwen/Qwen3-4B-GGUF@a9a60d009fa7ff9606305047c2bf77ac25dbec49`；文件 `Qwen3-4B-Q4_K_M.gguf`，`2497280256` bytes，SHA-256/LFS OID `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`；Apache-2.0 | 已确认加载、CUDA 全层 offload（37/37）和完整生成；`--reasoning off` 已确认生效且无非空 thinking 内容 |
| Phi-3.5-mini-instruct（3.8B 级） | 英文技术问答对照 | `phi3` | 已确认 | 已确认：`models/Phi-3.5-mini-instruct-Q4_K_M.gguf`；`general.architecture=phi3`、file type 15、量化版本 2、`tokenizer.ggml.model=llama`、chat template 存在 | 已确认：基础模型 `microsoft/Phi-3.5-mini-instruct@2fe192450127e6a83f7441aef6e3ca586c338b77`，Microsoft MIT License；GGUF `bartowski/Phi-3.5-mini-instruct-GGUF@b1693692c4758ac83f0d0e65aff9b4f945f29941`，文件 `Phi-3.5-mini-instruct-Q4_K_M.gguf`，`2393232672` bytes，SHA-256/Xet OID `e4165e3a71af97f1b4820da61079826d8752a2088e313af0c7d346796c38eff5` | 已确认加载、CUDA 全层 offload（33/33）和完整生成；**质量预检警告**：J-09 的 `READY` 后附加解释，未通过 exact-one-word，不影响 Runtime PASS |
| Llama-3.2-3B-Instruct | 英文技术问答与短指令对照 | `llama` | 已确认 | 已确认：`models/Llama-3.2-3B-Instruct-Q4_K_M.gguf`；`general.architecture=llama`、name `Llama 3.2 3B Instruct`、file type 15、量化版本 2、`general.license=llama3.2`、chat template 存在 | 已确认：基础模型 `meta-llama/Llama-3.2-3B-Instruct@0cb88a4f764b7a12671c53f0838cd831a0843b95`，Llama 3.2 Community License；GGUF 转换者/发布者 `forkjoin-ai`，repo `forkjoin-ai/llama-3.2-3b-instruct-gguf@8ba7b537e9c91208bcb364b214317bbd810d55ae`，文件 `Llama-3.2-3B-Instruct-Q4_K_M.gguf`，`2019377696` bytes，SHA-256 `6c1a2b41161032677be168d354123594c0e6e67d2b9227c84f296ad037c728ff`，Xet hash `631388935f3017b4b663e122a218ea37d00c47737a505d36edaf2530fddcbe0c` | 已确认加载、CUDA 全层 offload（29/29）和完整生成；第三方 README 的 Apache-2.0 标记不作为基础权重许可证 |

四个本地 GGUF 的 metadata 均使用 Runtime 自带 `gguf-py` 读取有限字段；未显示 template 正文或 tokenizer tokens。宿主机有效预检 [`model-preflight-20260727.md`](preflight/model-preflight-20260727.md) 已确认四个模型均能加载、全层 CUDA offload 并生成完整非空文本；Qwen3 的 non-thinking 行为已确认。该预检不是正式质量或性能 benchmark。

## 5. Runtime 源码支持证据

下列引用均来自 `third_party/llama.cpp-omni@19cc269`，不是对普通 llama.cpp 的推断。

| 审计项 | 证据与结论 |
| --- | --- |
| 架构枚举与名称映射 | [`src/llama-arch.h:15`](../../third_party/llama.cpp-omni/src/llama-arch.h:15)、[`:38`](../../third_party/llama.cpp-omni/src/llama-arch.h:38)、[`:41`](../../third_party/llama.cpp-omni/src/llama-arch.h:41)、[`:49`](../../third_party/llama.cpp-omni/src/llama-arch.h:49) 声明 `llama`、`qwen2`、`qwen3`、`phi3`；[`src/llama-arch.cpp:11`](../../third_party/llama.cpp-omni/src/llama-arch.cpp:11)、[`34`](../../third_party/llama.cpp-omni/src/llama-arch.cpp:34)、[`37`](../../third_party/llama.cpp-omni/src/llama-arch.cpp:37)、[`45`](../../third_party/llama.cpp-omni/src/llama-arch.cpp:45) 映射相应字符串。 |
| GGUF 识别与加载 | `general.architecture` 的 key 名在 [`src/llama-arch.cpp:144`](../../third_party/llama.cpp-omni/src/llama-arch.cpp:144)；loader 从 GGUF 读取并调用 `llm_arch_from_string()` 在 [`src/llama-model-loader.cpp:546`](../../third_party/llama.cpp-omni/src/llama-model-loader.cpp:546) 和 [`:552`](../../third_party/llama.cpp-omni/src/llama-model-loader.cpp:552)；未知架构被拒绝见 [`src/llama-model.cpp:313`](../../third_party/llama.cpp-omni/src/llama-model.cpp:313)。 |
| 模型加载路径 | `llama_model_load()` 构造 loader、创建模型并准备设备，见 [`src/llama.cpp:276`](../../third_party/llama.cpp-omni/src/llama.cpp:276) 至 [`:287`](../../third_party/llama.cpp-omni/src/llama.cpp:287)。 |
| 模型分派 | `llama`、`qwen2`、`qwen3`、`phi3` 分别在 [`src/llama-model.cpp:40`](../../third_party/llama.cpp-omni/src/llama-model.cpp:40)、[`:86`](../../third_party/llama.cpp-omni/src/llama-model.cpp:86)、[`:100`](../../third_party/llama.cpp-omni/src/llama-model.cpp:100)、[`:110`](../../third_party/llama.cpp-omni/src/llama-model.cpp:110) 进入专有 model class。 |
| 图构建/模型实现 | Qwen2 载入 tensor 和建图：[`src/models/qwen2.cpp:18`](../../third_party/llama.cpp-omni/src/models/qwen2.cpp:18)、[`:48`](../../third_party/llama.cpp-omni/src/models/qwen2.cpp:48)；Qwen3：[`src/models/qwen3.cpp:14`](../../third_party/llama.cpp-omni/src/models/qwen3.cpp:14)、[`:48`](../../third_party/llama.cpp-omni/src/models/qwen3.cpp:48)；Phi3：[`src/models/phi3.cpp:27`](../../third_party/llama.cpp-omni/src/models/phi3.cpp:27)、[`:59`](../../third_party/llama.cpp-omni/src/models/phi3.cpp:59)（含 SWA 分支）；Llama：[`src/models/llama.cpp:34`](../../third_party/llama.cpp-omni/src/models/llama.cpp:34)、[`:94`](../../third_party/llama.cpp-omni/src/models/llama.cpp:94)。 |
| tokenizer 与 chat template | tokenizer 由各 GGUF 自己提供并在加载后供 sampler 使用（[`common/sampling.cpp:187`](../../third_party/llama.cpp-omni/common/sampling.cpp:187)）；CLI 将消息应用 chat template（[`tools/cli/cli.cpp:206`](../../third_party/llama.cpp-omni/tools/cli/cli.cpp:206) 至 [`:222`](../../third_party/llama.cpp-omni/tools/cli/cli.cpp:222)）。默认 template 来自模型 metadata 的 CLI 选项说明在 [`common/arg.cpp:3204`](../../third_party/llama.cpp-omni/common/arg.cpp:3204)。模板输入包含 `enable_thinking`，见 [`common/chat.cpp:837`](../../third_party/llama.cpp-omni/common/chat.cpp:837) 至 [`:844`](../../third_party/llama.cpp-omni/common/chat.cpp:844)。 |
| sampling | 固定参数 `seed`、temperature、top-k、top-p、min-p、repeat penalty 分别由 CLI 参数解析，见 [`common/arg.cpp:1613`](../../third_party/llama.cpp-omni/common/arg.cpp:1613)、[`:1634`](../../third_party/llama.cpp-omni/common/arg.cpp:1634)、[`:1643`](../../third_party/llama.cpp-omni/common/arg.cpp:1643)、[`:1651`](../../third_party/llama.cpp-omni/common/arg.cpp:1651)、[`:1659`](../../third_party/llama.cpp-omni/common/arg.cpp:1659)、[`:1709`](../../third_party/llama.cpp-omni/common/arg.cpp:1709)；common sampler 建立 chain 在 [`common/sampling.cpp:187`](../../third_party/llama.cpp-omni/common/sampling.cpp:187) 至 [`:198`](../../third_party/llama.cpp-omni/common/sampling.cpp:198)。 |
| Qwen3 thinking 审计 | Runtime 明确提供 `--reasoning on|off|auto`，并把它传入 template 的 `enable_thinking`，见 [`common/arg.cpp:3171`](../../third_party/llama.cpp-omni/common/arg.cpp:3171) 至 [`:3181`](../../third_party/llama.cpp-omni/common/arg.cpp:3181)。CLI 也有 reasoning-budget sampler 路径，见 [`tools/cli/cli.cpp:100`](../../third_party/llama.cpp-omni/tools/cli/cli.cpp:100) 至 [`:115`](../../third_party/llama.cpp-omni/tools/cli/cli.cpp:115)。本轮必须强制 off 并在预检中保存实际 CLI 解析日志；若 template 不支持或不遵从，Qwen3 不参加公平排名。 |
| CUDA backend | `GGML_USE_CUDA` 时注册通用 CUDA backend，见 [`ggml/src/ggml-backend-reg.cpp:115`](../../third_party/llama.cpp-omni/ggml/src/ggml-backend-reg.cpp:115) 至 [`:118`](../../third_party/llama.cpp-omni/ggml/src/ggml-backend-reg.cpp:118)；`llama_supports_gpu_offload()` 查询 GPU backend，见 [`src/llama.cpp:73`](../../third_party/llama.cpp-omni/src/llama.cpp:73) 至 [`:79`](../../third_party/llama.cpp-omni/src/llama.cpp:79)，CUDA backend 初始化在 [`ggml-cuda.cu:5687`](../../third_party/llama.cpp-omni/ggml/src/ggml-cuda/ggml-cuda.cu:5687)。未发现这四个架构的模型专用 CUDA backend 分支；实际全层 offload 仍须逐模型实测。 |

## 6. 固定业务任务集

所有输入按模型自身 GGUF chat template 使用 `--conversation --single-turn`。下面的文本逐字冻结；除在结果记录中填入模型 ID 外不得改写。除 J-05 外均不使用 grammar 强制 JSON，以便测量模型本身的结构化遵循；J-05 同时记录“裸输出”与“JSON 可解析性”。每项 0--5 分，按表中规则判定。

| ID | 完整 Prompt | 目的 | 通过条件 / 评分规则 |
| --- | --- | --- | --- |
| J-01 | `你是工业设备维护助手。离心泵运行 20 分钟后轴承温度从 58°C 升至 92°C，振动从 3.1 mm/s 升至 7.8 mm/s。请用中文给出最可能的两个原因，并分别说明一项现场核查。不要虚构已经测得的数据。` | 中文设备故障问答 | 5：两个原因均合理、各有可执行核查且无编造；3：一个合理原因或核查不完整；0：错误结论、编造数据或未中文作答。 |
| J-02 | `设备日志如下：\n[10:00:01] MOTOR_A current=18.2A temp=71C\n[10:00:05] MOTOR_A current=25.9A temp=78C alarm=OVERLOAD\n[10:00:08] VFD_A fault=OC\n[10:00:12] MOTOR_A stopped\n请定位最直接的故障链路，区分“日志直接支持”和“仍需检查”的内容，中文回答。` | 给定日志的故障定位 | 5：识别过流/过载后停机链路，明确证据与待查项；3：定位方向对但未区分证据；0：与日志矛盾或声称未给出的根因。 |
| J-03 | `一台 380V 三相风机启动后 30 秒跳闸。请给出恰好 4 步、按安全优先顺序排列的排查建议。每一步必须包含“检查对象”和“判定动作”，不要给出带电拆线建议。` | 分步骤排查与短指令遵循 | 5：恰好 4 步、顺序安全、每步含两要素；3：主要合理但数量或要素有一处偏差；0：危险建议或严重不符合。 |
| J-04 | `只知道“空压机压力波动”，没有压力曲线、阀门状态、排气温度或报警码。请回答：目前能确认什么、不能确认什么、下一步最需要哪 3 条数据。不要猜测具体故障。` | 信息不足时的不确定性 | 5：明确不能定因，列出恰好 3 条高价值数据；3：有保留但夹带猜测/数据不完整；0：断言具体故障。 |
| J-05 | `仅输出一个 JSON 对象，不要 Markdown，不要解释。根据以下事实生成字段：device_id、severity、evidence、next_action。事实：设备 ID 为 P-17；报警为 HIGH_TEMP；记录温度 91°C；尚未确认根因。severity 只能是 low、medium、high；evidence 必须是字符串数组。` | 严格 JSON 输出 | 5：可解析 JSON、字段齐全、值与事实一致且无额外文本；3：可解析但一个轻微值/类型问题；0：无法解析、额外前后缀或编造根因。最低合格为 4。 |
| J-06 | `You are given this fact: a 24 VDC sensor supply measures 23.9 V at the cabinet and 18.1 V at the field sensor while the sensor is connected. Give two likely fault locations and one safe measurement for each. Do not claim a failed component is confirmed.` | 英文技术问答 | 5：英文清晰、两处合理位置和安全测量、保留不确定性；3：基本正确但一项弱；0：断言或危险建议。 |
| J-07 | `请解释这句话中的术语并给出排查优先级：PLC shows a watchdog timeout after the HMI recipe download，现场同时报告“通信偶发中断”。用中文回答，但保留 PLC、watchdog、HMI、recipe 等英文术语。` | 中英混合术语 | 5：正确解释、中文自然、术语保留且有合理优先级；3：解释基本对但优先级弱；0：误译关键术语或忽略任务。 |
| J-08 | `仅依据以下上下文回答问题。\n上下文：维修手册片段 M-42：当液位开关 LS-2 持续为低位且泵 P-2 已停止时，控制器会禁止自动重启；推荐先检查液位、LS-2 接线和输入指示灯。\n问题：控制器为什么可能禁止 P-2 自动重启？下一步检查什么？如果上下文没有给出原因，请明确说“上下文未提供”。` | 有上下文且避免编造 | 5：只引用 M-42 信息、解释禁止条件并列出三项检查；3：少一项但不编造；0：引入外部故障原因。 |
| J-09 | `Answer with exactly one word: READY` | 简短指令遵循 | 5：输出恰为 `READY`；0：任何其他字符、空白解释或大小写错误。 |
| J-10 | `从以下交接记录中提取 JSON，字段必须为 alarm_time、device、confirmed_event、not_confirmed。\n记录：06:40 P-8 启动；06:47 操作员报告异响；06:49 PLC 报警 VIB_HIGH；06:50 P-8 停机；07:05 尚未完成轴承检查；07:10 未发现电机温度报警。\n只依据记录，alarm_time 使用 HH:MM，not_confirmed 为字符串数组。` | 较长输入的信息提取 | 5：可解析 JSON，`06:49`、`P-8`、振动高报警与未完成轴承检查/无温度报警均准确；3：一个遗漏；0：编造或不可解析。最低合格为 4。 |

## 7. 固定运行参数

参数优先继承正式 incumbent config `docs/baselines/qwen2.5-3b-q4_k_m/benchmark-config-qwen25-20260723.json` 和脚本 `scripts/benchmark_qwen25.py`。实际执行时为每个模型新建结果目录，不修改该脚本。

| 项目 | 固定值 |
| --- | --- |
| 权重 | 每模型 Q4_K_M GGUF；同一模型不同量化另行报告 |
| context / batch / ubatch | `4096 / 2048 / 512` |
| GPU | `--gpu-layers 99 --device CUDA0 --split-mode none --main-gpu 0 --fit off` |
| CPU / 内存加载 | `--threads 8 --threads-batch 8 --mmap` |
| 生成 | `--n-predict 128 --seed 424242 --temp 0.0 --top-k 1 --top-p 1.0 --min-p 0.0 --repeat-penalty 1.0` |
| 对话/计时 | `--conversation --single-turn --simple-io --no-display-prompt --no-warmup --show-timings --verbose`，Flash Attention on |
| Qwen3 专项 | 显式 `--reasoning off`；预检必须确认其生效，不能留 `auto` |
| preconditioning | 每模型 1 个独立 `llama-cli` 进程；不是被测进程内 warmup |
| 有效运行 | 每个模型、每个 Prompt 5 次有效运行；失败不计入，最多 8 次尝试；每次单独启动/停止 `tegrastats`，1000 ms 间隔 |
| 可比性 | 同一散热与 `MODE_30W`（ID 2）、同一 Runtime/CLI、同一参数和任务顺序；运行开始和结束记录功耗模式。模型 template 由 GGUF metadata 提供，但不得手工替换以提高某一候选得分。 |

## 8. 指标定义

| 类别 | 指标 | 定义 |
| --- | --- | --- |
| 质量 | 中文技术问答、故障定位、步骤建议、指令遵循、JSON 有效性、不确定性、中英文与中英混合、上下文忠实度、明显幻觉 | 来自 J-01--J-10 的固定人工/程序评分；幻觉是与输入事实矛盾或将未给出的内容说成已确认。 |
| 工程 | 模型加载成功、有效运行成功率 | 成功加载并产生完整输出的有效次数 / 尝试次数；分别保留错误文本与退出码。 |
| 工程 | Prompt / Decode tokens/s，Prompt / Decode 时间 | 只记录 llama.cpp 自报的 timing 字段及其原始 stderr。 |
| 工程 | CLI wall time | 独立 `llama-cli` 进程从启动到退出的墙钟时间，含启动和加载；**不得称为 TTFT 或 TPOT**。 |
| 工程 | 峰值 RAM、GR3D、GPU/TJ 温度、VDD_GPU_SOC | 每运行的 `tegrastats` 原始采样和峰值；`VDD_GPU_SOC` 是 rail，不等同整机功耗。 |

未测量字段必须留空并标为“待确认”，不得估算。第一轮 CLI 不输出真实 TTFT、TPOT、服务 Prefill 或 Decode 分段；它们属于第二轮 DirectBackend 指标。

## 9. 评分规则

总分 100，业务质量 70 分、工程表现 30 分。先应用硬性淘汰条件，再在未淘汰者中按总分排序。

| 维度 | 分值 | 固定计算 |
| --- | ---: | --- |
| 中文技术与故障定位 | 25 | J-01、J-02，各 0--5；J-03 安全步骤 0--5；J-08 上下文忠实度 0--5；另由 J-01/J-02 的技术准确性复核 0--5。 |
| 指令与结构化输出 | 20 | J-03 0--5、J-05 0--5、J-09 0--5、J-10 0--5。 |
| 不确定性与幻觉控制 | 15 | J-04 0--5；J-01/J-02/J-06/J-08 中每出现一次明显幻觉扣 2 分，最低 0；无明显幻觉为 5；评审完整性 0--5。 |
| 英文与中英混合 | 10 | J-06、J-07 各 0--5。 |
| 稳定性与可运行性 | 15 | 5/5 有效运行且无加载/CUDA/OOM/不完整输出 15；4/5 10；其余先按硬淘汰处理。 |
| 工程效率 | 15 | Prompt tokens/s 5、Decode tokens/s 5、峰值 RAM 3、峰值 GR3D/GPU/TJ/VDD_GPU_SOC 2；仅在同一任务、同一运行条件、同一统计口径下以未淘汰模型的相对排序赋分。 |

两名人工评分者应先在不显示模型名称的输出副本上独立按 J-01--J-10 打分，再揭示模型名称、记录分歧和一致结论。评分表版本、Prompt ID、运行 ID、输出 SHA-256、每人分数、判据引用和分歧处理必须一并保存。模型名称、速度或初次结果出现后不得修改 Prompt、权重、通过线、权重或评分规则；任何协议变更只能新建 v2 并令 v1 结果不可混合。

## 10. 硬性淘汰条件

以下任一项即淘汰，不以总分补偿：

1. 当前 Runtime 未发现对应架构支持，或 metadata 的架构不是已审计目标。
2. GGUF 无法解析、加载或生成完整输出；包括 tokenizer/template 错误。
3. 最终决策时模型身份、转换来源、许可证、不可变 revision 或文件完整性仍待确认。
4. 固定任务中出现 OOM、CUDA 错误、非零退出、空输出或截断/不完整输出。
5. J-05 或 J-10 的平均分低于 4/5，或 J-02 故障定位低于 3/5，或 J-03 出现危险带电拆线建议。
6. Qwen3 未确认 non-thinking mode 生效、输出仍含 reasoning 路径，或其 metadata/转换身份仍待确认。

## 11. 第一轮执行流程

1. 对每个待测文件执行只读身份门禁：文件 SHA-256、有限 GGUF metadata、架构、Q4_K_M、chat template 存在性、来源/许可证/revision 证据。
2. 核验主项目、Runtime、CLI、build manifest、`MODE_30W` ID 2 和可用磁盘空间；保存命令和环境记录。
3. 逐模型运行一次独立 preconditioning；随后按同一 J-01--J-10 顺序，各 5 次有效运行并采集 stdout、stderr、timing 和 telemetry。Qwen3 先保存 `--reasoning off` 的预检证据。
4. 先自动校验 JSON、exact-match、退出码、输出完整性和 metrics，再进行盲评。
5. 记录总分、硬淘汰与原始证据，选一名暂定主模型和一名备选。第一轮只筛选 `llama-cli` 路径，不能宣称 DirectBackend 已验证。

## 12. 第二轮复测流程

第 5--6 周在 DirectBackend 中仅复测第一轮前两名：用相同任务与同一 Q4_K_M 权重测量真实 TTFT、TPOT、Prefill、Decode、内存和稳定性。然后仅对最终主模型比较 Q4_K_M、Q8_0 与 KV Cache 配置。多模型 Q4_K_M 比较与同一模型量化/KV 比较必须分开报告，不得混为“模型能力”结论。

## 13. 结果记录格式

每个模型一份 `model-card.json`、每次运行一行 JSONL、每 Prompt 一份盲评表，至少包含：

```text
run_id, candidate_id, model_path, model_sha256, gguf_architecture,
source_repo, source_revision, license, runtime_commit, cli_version,
power_mode, prompt_id, prompt_sha256, command, preconditioning_run_id,
attempt, valid, exit_code, output_sha256, output_complete,
runtime_prompt_eval_ms, runtime_prompt_tokens_per_second,
runtime_decode_eval_ms, runtime_decode_tokens_per_second, runtime_total_ms,
cli_wall_time_ms, peak_ram_mb, peak_gr3d_percent, peak_gpu_temp_c,
peak_tj_temp_c, peak_vdd_gpu_soc_mw, scorer_a, scorer_b, final_score,
hard_elimination, notes
```

TTFT、TPOT、Prefill、DirectBackend Decode 字段在第一轮保持空值并标“待确认”。

## 14. 当前待确认项

| 项目 | 状态 | 所需证据 |
| --- | --- | --- |
| Qwen2.5 的商业使用授权 | 待确认 | Qwen Research License 仅授予非商业研究/评估用途；商业使用前须获得 Alibaba Cloud 单独许可。 |
| Qwen3 non-thinking template 行为 | 已确认 | 宿主机 run `20260727T014900Z` 接受 `--reasoning off`、生成最终回答且未见非空 thinking 内容；见预检归档。 |
| 四个候选的 Jetson 加载、CUDA offload 与生成 | 已确认 | 宿主机 run `20260727T014800Z`：Qwen2.5 37/37、Qwen3 37/37、Phi-3.5 33/33、Llama-3.2 29/29，均 exit 0。性能与固定 10 Prompt 质量仍待确认。 |

上述远端固定 revision、文件名、大小、SHA-256/Xet 或 LFS identity 与许可证来自本地保留的相应模型页/许可证证据及本地 SHA-256 比对；不得将 `main` 用作 revision。已完成一次宿主机短预检；尚未执行本协议的正式 10 Prompt 比较。

## 15. 下一步获取模型的顺序

1. 不再获取新模型：四个 Q4_K_M 候选已完成身份、来源、固定 revision、文件完整性和许可证记录。
2. 预检已确认 Qwen3 `--reasoning off` 的 non-thinking 行为；若后续环境或 GGUF 改变，须重新预检，不通过则不得进入公平排名。
3. 四个候选的加载/CUDA/完整输出预检已通过；任何 Runtime、CLI 或权重 hash 改变后都须重新执行，失败按第 10 节淘汰。
4. 由人工确认后执行第一轮固定 Prompt 筛选；不得把预检或第一轮结果表述为 DirectBackend 验证。
