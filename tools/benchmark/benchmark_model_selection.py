#!/usr/bin/env python3
"""运行冻结的 M3 四模型 llama-cli 对比，并保存可追溯的原始证据。

执行路径：

1. ``main()`` 读取模型、Prompt 和 manifest 配置。
2. ``validate()`` 检查 Git、Runtime、CLI、模型 hash、CUDA、功耗和遥测工具。
3. 每个模型先执行一次独立 preconditioning;该过程不参与统计。
4. 对每个固定 Prompt 重复运行，直到得到指定数量的有效记录或达到最大尝试数。
5. 每次运行由 ``run_once()`` 写入独立目录,保存命令、stdout、stderr、tegrastats。
6. ``runs.jsonl`` 保存完整身份信息；``blind-review.jsonl`` 不含模型名，供人工盲评。

结果目录示意：

    benchmark-results/model-selection/<run_id>/
      config.json                  # 本次运行的冻结输入和来源链
      validation.json              # 启动前门禁结果
      runs.jsonl                   # 每次执行的完整记录
      blind-review.jsonl           # 不含模型身份的评分输入
      blind-review-map.json        # response_id 到模型身份的私有映射
      candidates/<candidate>/<prompt>/attempt-XX/
        command.json stdout.log stderr.log tegrastats.log

该脚本只记录 llama-cli 自报的 Prompt/Decode timing 和进程 wall time。
由于每个 CLI 进程都重新加载模型,wall_time_ms 不是 TTFT 或 TPOT。

正式模式拒绝 dirty 工作树，防止结果无法关联到确定的代码、模型和配置版本。
``--validate-only``、``--print-commands`` 与 ``--dry-run`` 不启动模型推理。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "third_party/llama.cpp-omni"
# 这三份文件共同冻结“测试什么、用什么模型、结果应包含什么”。
SELECTION_CONFIG = ROOT / "tools/benchmark/configs/model-selection-v1.json"
PROMPTS_CONFIG = ROOT / "tools/benchmark/configs/model-selection-prompts-v1.json"
MANIFEST = ROOT / "manifests/model-selection.json"
DEFAULT_OUTPUT = ROOT / "benchmark-results/model-selection"
OFFLOAD_RE = re.compile(r"offloaded\s+(\d+)\s*/\s*(\d+)\s+layers\s+to\s+GPU", re.I)
# Match the complete llama.cpp timing payload, not a substring: ``eval time``
# must never consume the ``prompt eval time`` line.
PROMPT_TIMING_RE = re.compile(r"^.*?\|\s*prompt eval time\s*=\s*([0-9.]+) ms\s*/\s*([0-9]+) tokens\s*\([^\r\n]*?,\s*([0-9.]+) tokens per second\)\s*$", re.I | re.M)
DECODE_TIMING_RE = re.compile(r"^.*?\|\s+eval time\s*=\s*([0-9.]+) ms\s*/\s*([0-9]+) (?:tokens|runs)\s*\([^\r\n]*?,\s*([0-9.]+) tokens per second\)\s*$", re.I | re.M)
TOTAL_TIMING_RE = re.compile(r"^.*?\|\s*total time\s*=\s*([0-9.]+) ms\s*/\s*[0-9]+ tokens\s*$", re.I | re.M)
TIMING_LINE_RE = re.compile(r"^\[\s*Prompt:.*\]\s*$", re.M)
CUDA_ERROR_RE = re.compile(r"(?:cuda|cublas|nvmap|nvrm|memory manager).*(?:error|failed|not supported)|failed to initialize CUDA", re.I)
FATAL_RE = re.compile(r"out of memory|\boom\b|failed to load|unsupported model|error.*(?:gguf|tokenizer|chat template|template)|(?:gguf|tokenizer|chat template|template).*error", re.I)
THINK_RE = re.compile(r"<think>\s*(?P<body>[\s\S]*?)\s*</think>|\[Start thinking\](?P<alt>[\s\S]*?)\[End thinking\]", re.I)


def sha256_file(path: Path) -> str:
    """以固定块大小计算文件 SHA-256。

    模型 GGUF 较大,不能整体读入内存。该函数同时用于权重、CLI 和脚本本身，
    让每条结果都能回溯到实际参与运行的二进制和输入文件。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """读取项目的 JSON 配置文件。

    配置文件在启动时一次性加载；后续命令构造和记录字段均基于该内存快照，
    避免运行中重新读取文件造成前后参数不一致。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    """生成用于 run_id 的 UTC 时间字符串，避免本地时区影响结果目录命名。"""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def git_value(path: Path, *args: str) -> str | None:
    """在指定仓库执行只读 git 查询，失败时返回 None。

    门禁不应因 Git 命令的 stderr 文本而猜测状态；调用方根据 None 或实际值
    决定是否阻断正式 benchmark。
    """
    result = subprocess.run(["git", "-C", str(path), *args], check=False, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def command_environment(binary: Path) -> dict[str, str]:
    """构造 llama-cli 子进程环境，优先加载本次构建目录中的动态库。

    Runtime 是共享库构建。显式把 binary 所在目录置于 LD_LIBRARY_PATH 前端，
    与冻结的 Qwen2.5 基线保持一致，避免意外链接到系统中另一份 libllama。
    """
    env = os.environ.copy()
    current = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = str(binary.parent) if not current else f"{binary.parent}:{current}"
    return env


def read_metadata(path: Path) -> dict[str, Any]:
    """从 GGUF 中读取本轮门禁必需的有限 metadata。

    不读取完整 token 列表或 chat template 正文，原因是它们很大且会把不必要的
    模型内容写进评测证据。这里仅确认架构、量化类别、tokenizer 和 template 存在性。
    """
    sys.path.insert(0, str(RUNTIME / "gguf-py"))
    from gguf import GGUFReader  # type: ignore

    reader = GGUFReader(str(path), "r")
    result: dict[str, Any] = {}
    for key in ("general.architecture", "general.file_type", "tokenizer.ggml.model", "tokenizer.chat_template"):
        field = reader.get_field(key)
        if field is None:
            result[key] = None
        elif key == "tokenizer.chat_template":
            result[key] = {"present": True, "content_recorded": False}
        else:
            value = field.contents()
            result[key] = value.item() if hasattr(value, "item") else value
    return result


def candidate_assets(config: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    """验证候选 GGUF 是否仍与冻结配置一致。

    返回值按 candidate_id 组织，既保存所有原始检查字段，也提供 ``failures``。
    ``validate()`` 使用 failures 决定是否阻断；保留明细可让后续报告说明是路径、
    hash、架构还是 tokenizer 门禁失败，而不是只给出笼统的“模型无效”。
    """
    # 先验证磁盘上的权重仍是协议中登记的那一份，再允许进入 GPU 推理。
    checks: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        expected = config["candidates"][candidate_id]
        path = ROOT / expected["model"]
        item: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            item["size_bytes"] = path.stat().st_size
            item["size_matches"] = item["size_bytes"] == expected["size_bytes"]
            item["sha256"] = sha256_file(path)
            item["sha256_matches"] = item["sha256"] == expected["sha256"]
            try:
                metadata = read_metadata(path)
                item["metadata"] = metadata
                item["architecture_matches"] = metadata["general.architecture"] == expected["architecture"]
                item["q4_k_m"] = metadata["general.file_type"] == 15
                item["tokenizer_present"] = metadata["tokenizer.ggml.model"] is not None
                item["chat_template_present"] = bool(metadata["tokenizer.chat_template"])
            except Exception as exc:  # Persist parser errors as an auditable hard gate.
                item["metadata_error"] = str(exc)
        required = ("exists", "size_matches", "sha256_matches", "architecture_matches", "q4_k_m", "tokenizer_present", "chat_template_present")
        item["failures"] = [name for name in required if item.get(name) is not True]
        if item.get("metadata_error"):
            item["failures"].append("metadata_error")
        checks[candidate_id] = item
    return checks


def cli_probe(binary: Path, required: list[str]) -> dict[str, Any]:
    """确认当前 llama-cli 可执行、支持协议参数，并能枚举目标 GPU。

    ``--help`` 是参数能力的实际来源，避免根据普通 llama.cpp 猜测 fork 的选项。
    ``--list-devices`` 只做设备探测，不加载模型；正式模式要求它列出 CUDA0: Orin。
    """
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return {"error": "llama-cli missing or not executable", "required_options_missing": required}
    env = command_environment(binary)
    help_result = subprocess.run([str(binary), "--help"], check=False, capture_output=True, text=True, env=env)
    devices_result = subprocess.run([str(binary), "--list-devices"], check=False, capture_output=True, text=True, env=env)
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    device_text = f"{devices_result.stdout}\n{devices_result.stderr}"
    return {
        "help_exit_code": help_result.returncode,
        "list_devices_exit_code": devices_result.returncode,
        "required_options_missing": [option for option in required if option not in help_text],
        "cuda0_orin": bool(re.search(r"CUDA0\s*:\s*Orin", device_text, re.I)),
        "devices_output": device_text.strip(),
        "ld_library_path": env["LD_LIBRARY_PATH"],
    }


def power_mode() -> dict[str, Any]:
    """读取 Jetson 当前 nvpmodel 状态，并检查是否为协议固定的 30W 模式。

    功耗模式会显著影响时钟和吞吐，因此不允许在未知模式下混入正式结果。
    保留原始输出而非只保存布尔值，方便审计具体平台状态。
    """
    result = subprocess.run(["nvpmodel", "-q"], check=False, capture_output=True, text=True)
    output = f"{result.stdout}\n{result.stderr}".strip()
    return {"exit_code": result.returncode, "output": output, "matches_mode_30w_id_2": bool(re.search(r"NV Power Mode:\s*MODE_30W\s*\n\s*2\b", output))}


def validate(config: dict[str, Any], manifest: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    """执行正式运行前的全部硬门禁，返回可序列化的验证报告。

    门禁覆盖四层：

    - 项目版本：必须有 HEAD 且工作树干净；
    - Runtime 版本:branch 和 commit 必须匹配协议；
    - 可执行环境:CLI hash、参数、CUDA0、功耗模式、tegrastats;
    - 模型资产:每个候选的路径、大小、hash、架构和 GGUF metadata。

    本函数不启动模型。任何 failures 都会让正式模式在 ``main()`` 中以退出码 2 停止。
    """
    # 正式 benchmark 的可复现性依赖完整的版本链；任一门禁失败都会阻止运行。
    binary = ROOT / config["cli"]
    project_commit = git_value(ROOT, "rev-parse", "HEAD")
    project_dirty = bool(git_value(ROOT, "status", "--porcelain", "--untracked-files=all"))
    probe = cli_probe(binary, config["required_cli_options"])
    assets = candidate_assets(config, candidate_ids)
    power = power_mode()
    failures: list[str] = []
    if project_commit is None:
        failures.append("project_has_no_head")
    if project_dirty:
        failures.append("project_worktree_dirty")
    if git_value(RUNTIME, "rev-parse", "--abbrev-ref", "HEAD") != config["runtime_branch"]:
        failures.append("runtime_branch")
    if git_value(RUNTIME, "rev-parse", "HEAD") != config["runtime_commit"]:
        failures.append("runtime_commit")
    if not binary.is_file() or sha256_file(binary) != config["cli_sha256"]:
        failures.append("cli_sha256")
    if manifest.get("runtime", {}).get("branch") != config["runtime_branch"] or manifest.get("runtime", {}).get("commit") != config["runtime_commit"]:
        failures.append("manifest_runtime_identity")
    if manifest.get("cli", {}).get("sha256") != config["cli_sha256"]:
        failures.append("manifest_cli_sha256")
    if probe.get("help_exit_code") != 0 or probe.get("required_options_missing"):
        failures.append("required_cli_options")
    if not probe.get("cuda0_orin"):
        failures.append("cuda0_orin")
    if not power["matches_mode_30w_id_2"]:
        failures.append("power_mode")
    if shutil.which("tegrastats") is None:
        failures.append("tegrastats")
    for candidate_id, asset in assets.items():
        if asset["failures"]:
            failures.append(f"asset:{candidate_id}:{','.join(asset['failures'])}")
    return {
        "valid": not failures,
        "failures": failures,
        "project_git": {"commit": project_commit, "branch": git_value(ROOT, "rev-parse", "--abbrev-ref", "HEAD"), "dirty": project_dirty},
        "runtime": {"branch": git_value(RUNTIME, "rev-parse", "--abbrev-ref", "HEAD"), "commit": git_value(RUNTIME, "rev-parse", "HEAD")},
        "cli": {"path": str(binary), "sha256": sha256_file(binary) if binary.is_file() else None, "probe": probe},
        "power_mode": power,
        "assets": assets,
    }


def command_for(config: dict[str, Any], candidate_id: str, prompt: str, n_predict: int) -> list[str]:
    """为一个候选模型和一个固定 Prompt 构造完整 llama-cli argv。

    所有模型共享 common_args,保证 context、batch、GPU layers、sampling 等条件一致。
    仅模型路径、Prompt 和模型专属参数不同；目前 Qwen3 专属参数为
    ``--reasoning off``，以避免 reasoning token 破坏横向可比性。
    """
    # 从同一份公共参数复制命令，只替换本次 Prompt 和最大生成 token 数。
    candidate = config["candidates"][candidate_id]
    common = list(config["common_args"])
    index = common.index("--n-predict")
    common[index + 1] = str(n_predict)
    return [str(ROOT / config["cli"]), "--model", str(ROOT / candidate["model"]), "--prompt", prompt, *common, *candidate.get("extra_args", [])]


def extract_response(stdout: str, prompt: str) -> str:
    """从 llama-cli simple-io stdout 中分离模型回答。

    CLI 输出包含启动 banner、可用命令、``> <prompt>`` 回显、模型回答、timing 和
    ``Exiting...``。评分只应看到回答，因此以最后一次 Prompt 回显为起点，并剥离
    timing 与退出标记。使用最后一次匹配是为了兼容未来可能出现的重复 Prompt 输出。
    """
    # simple-io 的 stdout 同时包含 banner、Prompt 回显、回答和 timing；
    # 盲评与自动检查只能使用模型实际生成的回答区间。
    marker = f"> {prompt}"
    index = stdout.rfind(marker)
    answer = stdout[index + len(marker):] if index >= 0 else stdout
    answer = answer.lstrip("\r\n")
    answer = TIMING_LINE_RE.split(answer, maxsplit=1)[0]
    answer = re.split(r"^Exiting\.\.\.\s*$", answer, maxsplit=1, flags=re.M)[0]
    return answer.strip()


def runtime_metrics(stderr: str) -> dict[str, Any]:
    """解析 llama-cli stderr 中自报的 Prompt、Decode 和 total timing。

    字段缺失时保持 None,而不是填零或估算。这里的指标由 llama.cpp 报告，
    与外层 ``wall_time_ms`` 的进程级测量不同，两者在结果中故意分开保存。
    """
    # 这些是 llama-cli 自报的运行时指标，不把进程墙钟时间伪装成 TTFT/TPOT。
    metrics: dict[str, Any] = {"runtime_prompt_eval_ms": None, "runtime_prompt_tokens": None, "runtime_prompt_tokens_per_second": None, "runtime_decode_eval_ms": None, "runtime_decode_tokens": None, "runtime_decode_tokens_per_second": None, "runtime_total_ms": None}
    if match := PROMPT_TIMING_RE.search(stderr):
        metrics.update({"runtime_prompt_eval_ms": float(match.group(1)), "runtime_prompt_tokens": int(match.group(2)), "runtime_prompt_tokens_per_second": float(match.group(3))})
    if match := DECODE_TIMING_RE.search(stderr):
        metrics.update({"runtime_decode_eval_ms": float(match.group(1)), "runtime_decode_tokens": int(match.group(2)), "runtime_decode_tokens_per_second": float(match.group(3))})
    if match := TOTAL_TIMING_RE.search(stderr):
        metrics["runtime_total_ms"] = float(match.group(1))
    return metrics


def telemetry_peaks(path: Path) -> dict[str, int | None]:
    """从一条运行对应的 tegrastats 原始日志计算资源峰值。

    ``peak_vdd_gpu_soc_mw`` 是 GPU/SOC rail 功耗，不等价于整机功耗。温度保留为
    采样到的最高值；如果日志缺字段则返回 None，不将缺失误认为零。
    """
    # 原始 tegrastats 日志保留在单次运行目录；这里仅计算便于横向比较的峰值。
    values: dict[str, list[int]] = {"peak_ram_mb": [], "peak_gr3d_percent": [], "peak_gpu_temp_c": [], "peak_tj_temp_c": [], "peak_vdd_gpu_soc_mw": []}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            patterns = {
                "peak_ram_mb": r"\bRAM\s+(\d+)/",
                "peak_gr3d_percent": r"\bGR3D_FREQ\s+(\d+)%",
                "peak_gpu_temp_c": r"\bGPU@([0-9]+(?:\.[0-9]+)?)C",
                "peak_tj_temp_c": r"\bTJ@([0-9]+(?:\.[0-9]+)?)C",
                "peak_vdd_gpu_soc_mw": r"\bVDD_GPU_SOC\s+(\d+)mW",
            }
            for key, pattern in patterns.items():
                if match := re.search(pattern, line):
                    values[key].append(round(float(match.group(1))))
    return {key: max(samples) if samples else None for key, samples in values.items()}


def automatic_checks(prompt_id: str, response: str, metrics: dict[str, Any], n_predict: int) -> dict[str, Any]:
    """执行协议中无需人工判断的输出检查。

    J-05/J-10 检查 JSON 可解析性,J-09 检查严格 READY,J-03 检查四步格式。
    ``suspected_n_predict_truncation`` 只是风险标记：当 decode token 数达到上限且
    回答没有常见结尾符号时提示人工复核，不能单独断言模型输出被截断。
    """
    # 这些检查是可机械验证的协议项；技术正确性仍留给后续盲评。
    json_valid: bool | None = None
    if prompt_id in {"J-05", "J-10"}:
        try:
            json.loads(response)
            json_valid = True
        except json.JSONDecodeError:
            json_valid = False
    step_lines = re.findall(r"(?m)^\s*(?:[0-9]+[.)、]|第[一二三四五六七八九十]+步)", response)
    return {
        "json_valid": json_valid,
        "exact_ready_match": response == "READY" if prompt_id == "J-09" else None,
        "exact_four_steps": len(step_lines) == 4 if prompt_id == "J-03" else None,
        "suspected_n_predict_truncation": metrics.get("runtime_decode_tokens") is not None and metrics["runtime_decode_tokens"] >= n_predict and not re.search(r"[。.!?}\]）)]$", response),
    }


def output_details(stdout: str, stderr: str, prompt: str, candidate_id: str, n_predict: int) -> dict[str, Any]:
    """把单次 CLI 原始输出归一化为可写入 JSONL 的结果字段。

    此处同时解析回答 hash、实际 GPU offload 行、已知错误、Qwen3 thinking 标签和
    llama.cpp timing。调用方会在获得真实 Prompt ID 后重新计算 automatic_checks,
    因为本函数只负责与 Prompt 文本无关的日志归一化。
    """
    # 将原始 CLI 日志归一为“回答、GPU offload、错误、timing”四类可审计字段。
    response = extract_response(stdout, prompt)
    combined = f"{stdout}\n{stderr}"
    offloads = [{"offloaded": int(match.group(1)), "total": int(match.group(2))} for match in OFFLOAD_RE.finditer(combined)]
    thinking = [(match.group("body") or match.group("alt") or "").strip() for match in THINK_RE.finditer(response)]
    metrics = runtime_metrics(stderr)
    return {
        "response_text": response,
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "output_complete": bool(response) and bool(re.search(r"^Exiting\.\.\.\s*$", stdout, re.M)),
        "offload_matches": offloads,
        "offload_all_layers": bool(offloads) and any(item["offloaded"] == item["total"] for item in offloads),
        "error_lines": [line.strip() for line in combined.splitlines() if CUDA_ERROR_RE.search(line) or FATAL_RE.search(line)],
        "qwen3_reasoning_nonempty": candidate_id == "qwen3" and any(thinking),
        "qwen3_empty_reasoning_tags": candidate_id == "qwen3" and bool(thinking) and all(not body for body in thinking),
        "automatic_checks": automatic_checks("", response, metrics, n_predict),
        **metrics,
    }


def run_once(config: dict[str, Any], provenance: dict[str, Any], candidate_id: str, prompt: dict[str, Any], phase: str, attempt: int, directory: Path, n_predict: int) -> dict[str, Any]:
    """执行一个独立 llama-cli 进程并返回一条完整运行记录。

    ``phase`` 为 preconditioning 或 measured;二者使用相同 Runtime 路径，
    但仅 measured 记录进入正式比较。每次尝试拥有独立产物目录，即使发生失败或
    重试也不会覆盖证据。finally 块只终止本函数启动的 tegrastats 子进程。
    """
    # 每次尝试都在独立目录运行，避免 stdout、stderr、遥测数据被后续尝试覆盖。
    directory.mkdir(parents=True, exist_ok=False)
    command = command_for(config, candidate_id, prompt["text"], n_predict)
    (directory / "command.json").write_text(json.dumps({"argv": command}, indent=2) + "\n", encoding="utf-8")
    stdout_path, stderr_path, telemetry_path = directory / "stdout.log", directory / "stderr.log", directory / "tegrastats.log"
    # tegrastats 只在当前 CLI 子进程生命周期内运行，并在 finally 中被定向停止。
    telemetry_stream = telemetry_path.open("w", encoding="utf-8")
    telemetry = subprocess.Popen([str(shutil.which("tegrastats")), "--interval", str(config["tegrastats_interval_ms"])], stdout=telemetry_stream, stderr=subprocess.STDOUT, text=True)
    started = time.monotonic_ns()
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(command, check=False, stdout=stdout, stderr=stderr, text=True, env=command_environment(Path(command[0])))
        exit_code = completed.returncode
    finally:
        if telemetry.poll() is None:
            telemetry.terminate()
            try:
                telemetry.wait(timeout=5)
            except subprocess.TimeoutExpired:
                telemetry.kill()
                telemetry.wait(timeout=5)
        telemetry_stream.close()
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    details = output_details(stdout, stderr, prompt["text"], candidate_id, n_predict)
    details["automatic_checks"] = automatic_checks(prompt["id"], details["response_text"], details, n_predict)
    # 有效运行只表示 Runtime 执行成功；JSON、READY 等质量规则单独记录，不能混淆。
    valid = exit_code == 0 and details["output_complete"] and details["offload_all_layers"] and not details["error_lines"] and (candidate_id != "qwen3" or not details["qwen3_reasoning_nonempty"])
    return {
        "schema_version": 1, "run_id": provenance["run_id"], "candidate_id": candidate_id, "prompt_id": prompt["id"], "phase": phase, "attempt": attempt, "valid": valid, "exit_code": exit_code,
        "project_git": provenance["project_git"], "runtime_commit": provenance["runtime_commit"], "runtime_branch": provenance["runtime_branch"], "cli_sha256": provenance["cli_sha256"], "model_sha256": provenance["model_sha256"][candidate_id], "script_sha256": provenance["script_sha256"], "selection_config_sha256": provenance["selection_config_sha256"], "prompts_config_sha256": provenance["prompts_config_sha256"], "manifest_sha256": provenance["manifest_sha256"],
        "wall_time_ms": round((time.monotonic_ns() - started) / 1_000_000, 3), "artifacts": {"command": str((directory / "command.json").relative_to(ROOT)), "stdout": str(stdout_path.relative_to(ROOT)), "stderr": str(stderr_path.relative_to(ROOT)), "telemetry": str(telemetry_path.relative_to(ROOT))},
        **details, **telemetry_peaks(telemetry_path),
    }


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    """以追加方式写入一条 JSONL 记录。

    每次运行立即落盘，避免长批量任务中断时丢失此前已完成的尝试记录。
    ``sort_keys`` 让同类记录的字段顺序稳定，便于 diff 和后处理。
    """
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    """解析命令行、执行门禁，并调度完整的候选模型比较。

    返回码约定:0 表示当前模式正常完成;1 表示已启动运行但 preconditioning
    失败;2 表示启动前门禁或参数校验失败。正式模式只在所有门禁通过后创建 run_dir。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--print-commands", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--candidate", choices=["qwen25", "qwen3", "phi35", "llama32"])
    parser.add_argument("--prompt-id")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--preconditioning-runs", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config, prompts, manifest = load_json(SELECTION_CONFIG), load_json(PROMPTS_CONFIG), load_json(MANIFEST)
    candidate_ids = [args.candidate] if args.candidate else list(config["candidates"])
    prompt_list = [item for item in prompts["prompts"] if not args.prompt_id or item["id"] == args.prompt_id]
    if not prompt_list:
        parser.error("--prompt-id is not in tools/benchmark/configs/model-selection-prompts-v1.json")
    if args.runs < 1 or args.preconditioning_runs < 1 or args.max_attempts < args.runs:
        parser.error("--runs and --preconditioning-runs must be positive; --max-attempts must be >= --runs")
    # validate-only / print-commands / dry-run 也复用同一门禁，避免正式运行和预检查口径不同。
    validation = validate(config, manifest, candidate_ids)
    plan = {"candidates": candidate_ids, "prompts": [item["id"] for item in prompt_list], "preconditioning_processes": len(candidate_ids) * args.preconditioning_runs, "required_measured_processes": len(candidate_ids) * len(prompt_list) * args.runs, "maximum_measured_processes": len(candidate_ids) * len(prompt_list) * args.max_attempts}
    if args.validate_only:
        print(json.dumps(validation, indent=2, ensure_ascii=False))
        return 0 if validation["valid"] else 2
    if args.print_commands:
        print(json.dumps({"validation": validation, "commands": {candidate: {prompt["id"]: command_for(config, candidate, prompt["text"], prompts["n_predict"]) for prompt in prompt_list} for candidate in candidate_ids}}, indent=2, ensure_ascii=False))
        return 0 if validation["valid"] else 2
    if args.dry_run:
        print(json.dumps({"validation": validation, "plan": plan, "note": "dry-run starts no model or telemetry process"}, indent=2, ensure_ascii=False))
        return 0 if validation["valid"] else 2
    if not validation["valid"]:
        print(json.dumps(validation, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    # run_id 同时进入目录、JSONL 和盲评匿名 ID，便于从评分回溯原始日志。
    run_id = f"model-selection-v1-{utc_now()}-{os.getpid()}"
    run_dir = args.output_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    provenance = {"run_id": run_id, "project_git": validation["project_git"], "runtime_commit": validation["runtime"]["commit"], "runtime_branch": validation["runtime"]["branch"], "cli_sha256": validation["cli"]["sha256"], "model_sha256": {key: value["sha256"] for key, value in validation["assets"].items()}, "script_sha256": sha256_file(Path(__file__).resolve()), "selection_config_sha256": sha256_file(SELECTION_CONFIG), "prompts_config_sha256": sha256_file(PROMPTS_CONFIG), "manifest_sha256": sha256_file(MANIFEST)}
    (run_dir / "config.json").write_text(json.dumps({"run_id": run_id, "provenance": provenance, "validation": validation, "plan": plan, "n_predict": prompts["n_predict"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    records_path, blind_path, map_path = run_dir / "runs.jsonl", run_dir / "blind-review.jsonl", run_dir / "blind-review-map.json"
    blind_map: dict[str, Any] = {}
    # 外层固定候选模型，内层固定 Prompt；因此不同模型的输入与运行次数完全一致。
    for candidate_id in candidate_ids:
        precondition = next(item for item in prompts["prompts"] if item["id"] == "J-09")
        for attempt in range(1, args.preconditioning_runs + 1):
            record = run_once(config, provenance, candidate_id, precondition, "preconditioning", attempt, run_dir / "candidates" / candidate_id / "preconditioning" / f"attempt-{attempt:02d}", prompts["n_predict"])
            append_jsonl(records_path, record)
            if not record["valid"]:
                print(f"preconditioning failed for {candidate_id}; stopping", file=sys.stderr)
                return 1
        # preconditioning 不计入评测数据。正式数据只累计 valid 运行，失败尝试会保留日志。
        for prompt in prompt_list:
            valid = 0
            for attempt in range(1, args.max_attempts + 1):
                record = run_once(config, provenance, candidate_id, prompt, "measured", attempt, run_dir / "candidates" / candidate_id / prompt["id"] / f"attempt-{attempt:02d}", prompts["n_predict"])
                if record["valid"]:
                    valid += 1
                    response_id = hashlib.sha256(f"{run_id}:{candidate_id}:{prompt['id']}:{attempt}".encode()).hexdigest()[:16]
                    # blind-review 不包含 candidate_id；模型身份仅保存在不交给评分者的映射文件中。
                    blind = {"response_id": response_id, "prompt_id": prompt["id"], "response_text": record["response_text"], "response_sha256": record["response_sha256"], "scorer_a": None, "scorer_b": None, "disagreement": None, "final_score": None, "notes": None}
                    append_jsonl(blind_path, blind)
                    blind_map[response_id] = {"candidate_id": candidate_id, "prompt_id": prompt["id"], "attempt": attempt, "response_sha256": record["response_sha256"]}
                append_jsonl(records_path, record)
                if valid >= args.runs:
                    break
            if valid < args.runs:
                print(f"{candidate_id} {prompt['id']} has {valid}/{args.runs} valid runs", file=sys.stderr)
    map_path.write_text(json.dumps(blind_map, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"artifacts: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
