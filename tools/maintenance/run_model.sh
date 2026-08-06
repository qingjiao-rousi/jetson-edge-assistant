#!/usr/bin/env bash
# Jetson 本地文本模型交互启动器。
#
# 这个脚本只负责把已经构建好的 llama-cli 和本地 GGUF 权重按固定开发参数
# 启动为交互式对话。
#
# 默认模型是第一阶段选型冻结的 Qwen3-4B Q4_K_M。其他三个已审计模型仍可
# 通过 --model 显式切换，方便功能对比或问题复现。

# -e：任一命令失败立即退出；-u：引用未定义变量即报错；pipefail：管道中任一
# 命令失败都算失败。三者可避免模型路径或运行时环境错误被静默忽略。
set -euo pipefail

# 无论用户从哪个目录调用脚本，都以脚本本身的位置反推项目根目录，避免依赖
# 当前工作目录。BASH_SOURCE 比 $0 更稳健，能够处理通过 source 或软链接调用。
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# 使用项目 submodule 中的固定构建产物，不调用系统可能存在的另一份 llama-cli。
CLI="$PROJECT_ROOT/third_party/llama.cpp-omni/build-jetson-release/bin/llama-cli"

# 以下是交互启动默认值。-1 表示 llama-cli 不预设生成 token 上限；用户可按
# Ctrl+C 随时中断当前生成或退出交互会话。
MODEL_ID="qwen3"
CTX_SIZE="4096"
N_PREDICT="-1"
EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: scripts/run_model.sh [options] [-- llama-cli-options...]

Start an interactive local GGUF chat. The default is the frozen Qwen3-4B
Q4_K_M baseline with CUDA offload and reasoning disabled.

Options:
  --model ID          qwen3 (default), qwen25, phi35, or llama32
  --ctx-size N        Context size; default: 4096
  --n-predict N       Maximum generated tokens; default: -1 (unlimited)
  -h, --help          Show this help and exit
  --                  Pass subsequent options directly to llama-cli

Examples:
  scripts/run_model.sh
  scripts/run_model.sh --model qwen25
  scripts/run_model.sh --ctx-size 8192 -- --temp 0.2
EOF
}

# 只解析启动器自己的少量参数。"--" 后的参数不再由本脚本解释，而是原样
# 追加给 llama-cli；这样可临时试验某个已知 llama-cli 参数而不改动脚本。
while (($#)); do
    case "$1" in
        --model)
            [[ $# -ge 2 ]] || { echo "--model requires an ID" >&2; exit 2; }
            MODEL_ID="$2"
            shift 2
            ;;
        --ctx-size)
            [[ $# -ge 2 ]] || { echo "--ctx-size requires a value" >&2; exit 2; }
            CTX_SIZE="$2"
            shift 2
            ;;
        --n-predict)
            [[ $# -ge 2 ]] || { echo "--n-predict requires a value" >&2; exit 2; }
            N_PREDICT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS=("$@")
            break
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

# 每个可选 ID 映射到项目中已完成来源、hash 和 CUDA 预检的具体 GGUF 文件。
# Qwen3 显式关闭 reasoning，和冻结选型协议保持一致，避免思考 token 混入回答。
case "$MODEL_ID" in
    qwen3)
        MODEL="$PROJECT_ROOT/models/Qwen3-4B-Q4_K_M.gguf"
        MODEL_ARGS=(--reasoning off)
        ;;
    qwen25)
        MODEL="$PROJECT_ROOT/models/qwen2.5-3b-instruct-q4_k_m.gguf"
        MODEL_ARGS=()
        ;;
    phi35)
        MODEL="$PROJECT_ROOT/models/Phi-3.5-mini-instruct-Q4_K_M.gguf"
        MODEL_ARGS=()
        ;;
    llama32)
        MODEL="$PROJECT_ROOT/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
        MODEL_ARGS=()
        ;;
    *)
        echo "Unsupported model ID: $MODEL_ID" >&2
        echo "Choose qwen3, qwen25, phi35, or llama32." >&2
        exit 2
        ;;
esac

# 在加载数 GB 权重前先给出明确错误。-x 确认二进制可执行，-f 仅确认权重存在，
# 不在日常启动时重算完整 SHA-256，以免每次启动额外扫描整个模型文件。
[[ -x "$CLI" ]] || { echo "llama-cli is missing or not executable: $CLI" >&2; exit 1; }
[[ -f "$MODEL" ]] || { echo "Model is missing: $MODEL" >&2; exit 1; }

# 当前 Runtime 以共享库构建。将二进制目录放到 LD_LIBRARY_PATH 最前端，确保
# llama-cli 优先加载同一次 Jetson 构建产生的 libllama/libggml，而不是系统中
# 可能版本不同的库；原有 LD_LIBRARY_PATH 仍被保留在其后。
export LD_LIBRARY_PATH="$(dirname -- "$CLI")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# 将固定开发参数组织为 Bash 数组，而不是拼接字符串。这样模型路径或用户追加
# 参数中即使包含空格也会作为一个完整 argv 元素传给 llama-cli。
ARGS=(
    --model "$MODEL"
    --ctx-size "$CTX_SIZE"

    # 与第一阶段模型选择一致的 batch/ubatch，供 prompt prefill 使用。
    --batch-size 2048
    --ubatch-size 512

    # 99 大于这四个候选的层数；实际效果是将全部可 offload 的层放到 CUDA0。
    --gpu-layers 99
    --device CUDA0
    --split-mode none
    --main-gpu 0

    # Jetson 开发基线使用 8 个 CPU 线程；CUDA 不能使用时仍可用于 CPU 侧工作。
    --threads 8
    --threads-batch 8
    --n-predict "$N_PREDICT"

    # 使用本项目已构建并审计的 CUDA Flash Attention、内存映射和 chat template。
    # --conversation 会让 llama-cli 进入交互式多轮对话；这里故意不加
    # --single-turn 或 --prompt，因此脚本只启动并等待用户在终端输入。
    --flash-attn on
    --fit off
    --mmap
    --conversation
    "${MODEL_ARGS[@]}"
)

# exec 以 llama-cli 替换当前 shell：Ctrl+C 会直接发送给模型进程，且脚本的退出
# 状态就是 llama-cli 的退出状态，不会留下额外的 Bash 父进程。
echo "Starting $MODEL_ID with CUDA0. Press Ctrl+C to stop."
exec "$CLI" "${ARGS[@]}" "${EXTRA_ARGS[@]}"
