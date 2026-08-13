"""M12 application assembly and bounded startup preflight checks."""
from __future__ import annotations

import json
import base64
import pathlib
import sqlite3
import stat
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
import uuid

from app.agent.service import AgentApplication as CoreAgentApplication, build_application
from app.audio import voice_gateway
from app.qa import manual_qa

ROOT = pathlib.Path(__file__).resolve().parents[2]
MILESTONE = "M12-PROTOTYPE"
MAX_DIAGNOSIS_IMAGE_BYTES = 10 * 1024 * 1024
DIAGNOSIS_ENDPOINT = "/v1/diagnose/image"
DEFAULT_IMAGE_PROMPT = "请描述图像中可见的设备状态、告警和需要人工确认的点。不要假设不可见信息。"


class AssistantConfigError(ValueError):
    pass


class AssistantPreflightError(RuntimeError):
    pass


class AssistantImageError(RuntimeError):
    pass


def repo_path(value: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise AssistantConfigError("path must be a non-empty repository-relative string")
    pure = pathlib.PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise AssistantConfigError("path must be repository-relative without '..'")
    path = (ROOT / pure).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise AssistantConfigError("path is outside the repository") from error
    if not path.is_file():
        raise AssistantConfigError(f"referenced file is missing: {value}")
    return path


def load_config(path: str | pathlib.Path = "configs/assistant.json") -> dict:
    config_path = repo_path(str(path)) if not pathlib.Path(path).is_absolute() else pathlib.Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssistantConfigError(f"invalid assistant config: {error}") from error
    required = {"schema_version", "milestone", "runtime", "rag", "modules", "agent_command"}
    if not isinstance(config, dict) or set(config) != required or config.get("schema_version") != 2 or config.get("milestone") != MILESTONE:
        raise AssistantConfigError("invalid M12 assistant config")
    modules = config["modules"]
    if not isinstance(modules, dict) or set(modules) != {"manual_qa_config", "voice_gateway_config"}:
        raise AssistantConfigError("modules must name the manual QA and voice configs")
    manual_path = repo_path(modules["manual_qa_config"])
    voice_path = repo_path(modules["voice_gateway_config"])
    runtime = config["runtime"]
    runtime_keys = {"base_url", "ready_endpoint", "chat_endpoint", "host", "port", "executable", "model", "mmproj", "context_tokens", "batch_tokens", "ubatch_tokens", "gpu_layers", "prefix_reuse"}
    if not isinstance(runtime, dict) or set(runtime) != runtime_keys:
        raise AssistantConfigError("runtime has an invalid launch contract")
    base, ready, chat = runtime.get("base_url"), runtime.get("ready_endpoint"), runtime.get("chat_endpoint")
    if not isinstance(base, str) or not base.startswith(("http://", "https://")) or base.rstrip("/") != base:
        raise AssistantConfigError("runtime.base_url must be an HTTP(S) URL without a trailing slash")
    if not isinstance(ready, str) or not ready.startswith("/") or "://" in ready or "?" in ready or "#" in ready:
        raise AssistantConfigError("runtime.ready_endpoint must be an absolute endpoint path")
    if not isinstance(chat, str) or not chat.startswith("/") or "://" in chat or "?" in chat or "#" in chat:
        raise AssistantConfigError("runtime.chat_endpoint must be an absolute endpoint path")
    if runtime["host"] != "127.0.0.1" or not isinstance(runtime["port"], int) or not 1 <= runtime["port"] <= 65535:
        raise AssistantConfigError("Runtime must bind a valid 127.0.0.1 port")
    if base != f"http://{runtime['host']}:{runtime['port']}":
        raise AssistantConfigError("runtime.base_url must match runtime.host and runtime.port")
    executable = runtime["executable"]
    executable_path = pathlib.PurePosixPath(executable) if isinstance(executable, str) else None
    if not executable_path or executable_path.is_absolute() or ".." in executable_path.parts or executable_path.as_posix() != executable:
        raise AssistantConfigError("runtime.executable must be repository-relative")
    for name in ("model", "mmproj"):
        spec = runtime[name]
        if not isinstance(spec, dict) or set(spec) != {"path", "size_bytes", "sha256"}:
            raise AssistantConfigError(f"runtime.{name} must define path, size_bytes and sha256")
        if (not isinstance(spec["size_bytes"], int) or spec["size_bytes"] < 1 or not isinstance(spec["sha256"], str) or
                len(spec["sha256"]) != 64 or any(char not in "0123456789abcdefABCDEF" for char in spec["sha256"])):
            raise AssistantConfigError(f"runtime.{name} asset metadata is invalid")
        # Model files are intentionally not required while only loading configuration.
        if not isinstance(spec["path"], str) or pathlib.PurePosixPath(spec["path"]).is_absolute() or ".." in pathlib.PurePosixPath(spec["path"]).parts:
            raise AssistantConfigError(f"runtime.{name}.path must be repository-relative")
    if not all(isinstance(runtime[key], int) and runtime[key] > 0 for key in ("context_tokens", "batch_tokens", "ubatch_tokens", "gpu_layers")):
        raise AssistantConfigError("runtime numeric settings must be positive integers")
    if runtime["prefix_reuse"] not in {"disabled", "single_hot_text"}:
        raise AssistantConfigError("runtime.prefix_reuse must be disabled or single_hot_text")
    rag = config["rag"]
    if not isinstance(rag, dict) or set(rag) != {"database"} or not isinstance(rag["database"], str):
        raise AssistantConfigError("rag must contain the shared database path")
    if pathlib.PurePosixPath(rag["database"]).is_absolute() or ".." in pathlib.PurePosixPath(rag["database"]).parts:
        raise AssistantConfigError("rag.database must be repository-relative")
    command = config["agent_command"]
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise AssistantConfigError("agent_command must be a non-empty argv list")
    manual = manual_qa.load_config(manual_path)
    manual = manual_qa.bind_runtime(manual, rag["database"], base + chat)
    return {**config, "_manual_path": manual_path, "_voice_path": voice_path, "_manual": manual}


def check_runtime(config: dict, urlopen: Callable[..., Any] = urllib.request.urlopen) -> None:
    url = config["runtime"]["base_url"] + config["runtime"]["ready_endpoint"]
    try:
        with urlopen(url, timeout=5) as response:
            if getattr(response, "status", None) != 200:
                raise AssistantPreflightError(f"Runtime readiness failed at {url}: HTTP {getattr(response, 'status', 'unknown')}")
            body = json.loads(response.read().decode("utf-8"))
    except AssistantPreflightError:
        raise
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AssistantPreflightError(f"Runtime readiness failed at {url}: {error}") from error
    if not isinstance(body, dict) or body.get("ready") is not True:
        raise AssistantPreflightError(f"Runtime readiness failed at {url}: ready is not true")


def check_rag(config: dict) -> None:
    database = manual_qa.repo_path(config["_manual"]["database"])
    if not database.is_file() or not database.stat().st_size or not database.exists():
        raise AssistantPreflightError(f"RAG SQLite database is missing or empty: {config['_manual']['database']}")
    if not database.stat().st_mode & 0o444:
        raise AssistantPreflightError(f"RAG SQLite database is not readable: {config['_manual']['database']}")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA schema_version").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise AssistantPreflightError(f"RAG SQLite database cannot be opened read-only: {error}") from error


def check_tts(config: dict, return_backends: bool = False) -> dict | tuple[dict, Any, Any]:
    try:
        voice = voice_gateway.load_config(config["_voice_path"])
        playback, tts, _, _ = voice_gateway.build_tts_backends(voice)
        voice_gateway.check_output_device(voice)
    except (voice_gateway.AudioGatewayError, OSError, ValueError) as error:
        raise AssistantPreflightError(f"TTS/output preflight failed: {error}") from error
    return (voice, playback, tts) if return_backends else voice


def check_listen(config: dict) -> dict:
    try:
        voice = voice_gateway.load_config(config["_voice_path"])
        voice_gateway.build_asr_backends(voice)
        voice_gateway.check_input_device(voice)
    except (voice_gateway.AudioGatewayError, OSError, ValueError) as error:
        raise AssistantPreflightError(f"ASR/VAD/input preflight failed: {error}") from error
    return voice


def _image_path(value: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise AssistantImageError("图片路径必须是非空的仓库内相对路径")
    pure = pathlib.PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise AssistantImageError("图片路径必须是仓库内相对 POSIX 路径，且不能包含 '..'")
    path = (ROOT / pure).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise AssistantImageError("图片符号链接不能逃出仓库") from error
    try:
        mode = path.stat().st_mode
    except OSError as error:
        raise AssistantImageError(f"图片文件无法读取：{value}") from error
    if not stat.S_ISREG(mode):
        raise AssistantImageError(f"图片不是普通文件：{value}")
    return path


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise AssistantImageError("图片格式不受支持：仅支持 PNG、JPEG 或 WebP")


def _read_image(value: str) -> tuple[str, bytes]:
    path = _image_path(value)
    try:
        if path.stat().st_size > MAX_DIAGNOSIS_IMAGE_BYTES:
            raise AssistantImageError("图片超过 10 MiB 大小限制")
        data = path.read_bytes()
    except AssistantImageError:
        raise
    except OSError as error:
        raise AssistantImageError(f"图片读取失败：{value}") from error
    if len(data) > MAX_DIAGNOSIS_IMAGE_BYTES:
        raise AssistantImageError("图片超过 10 MiB 大小限制")
    return _image_mime(data), data


def _http_error_message(body: bytes, status: int) -> str:
    try:
        parsed = json.loads(body.decode("utf-8"))
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return f"HTTP {status}"


@dataclass
class AssistantApplication:
    config: dict
    agent: CoreAgentApplication

    @classmethod
    def create(cls, config_path: str | pathlib.Path = "configs/assistant.json", provider: Any = None) -> "AssistantApplication":
        config = load_config(config_path)
        manual = config["_manual"]
        retrieval = json.loads(manual_qa.repo_path(manual["retrieval_config"]).read_text(encoding="utf-8"))
        provider = provider or manual_qa.provider_from_config(
            manual_qa.load_embedding_config(manual_qa.repo_path(manual["embedding_config"]))
        )
        return cls(config, build_application(manual, retrieval, provider))

    def preflight_text(self, urlopen: Callable[..., Any] = urllib.request.urlopen) -> None:
        check_runtime(self.config, urlopen)
        check_rag(self.config)

    def diagnose_image(self, image_path: str, prompt: str | None, request_id: str | None = None,
                       urlopen: Callable[..., Any] = urllib.request.urlopen) -> dict:
        request_id = request_id or f"m12-image-{time.time_ns()}-{uuid.uuid4().hex}"
        if not isinstance(request_id, str):
            raise AssistantImageError("图像诊断 request_id 无效")
        question = (prompt or DEFAULT_IMAGE_PROMPT).strip()
        if not question:
            question = DEFAULT_IMAGE_PROMPT
        mime, data = _read_image(image_path)
        payload = {
            "request_id": request_id,
            "prompt": question,
            "stream": False,
            "images": [{"id": image_path, "mime": mime, "data_base64": base64.b64encode(data).decode("ascii")}],
        }
        endpoint = self.config["runtime"]["base_url"] + DIAGNOSIS_ENDPOINT
        request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=120) as response:
                status = getattr(response, "status", 200)
                body = response.read()
        except urllib.error.HTTPError as error:
            raise AssistantImageError(f"Runtime 图像诊断失败：{_http_error_message(error.read(), error.code)}") from error
        except (OSError, urllib.error.URLError) as error:
            raise AssistantImageError(f"无法连接 Runtime 图像诊断接口：{error}") from error
        if status < 200 or status >= 300:
            raise AssistantImageError(f"Runtime 图像诊断失败：{_http_error_message(body, status)}")
        try:
            response = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssistantImageError("Runtime 返回了无效的图像诊断 JSON") from error
        if not isinstance(response, dict):
            raise AssistantImageError("Runtime 返回了无效的图像诊断结果")
        if isinstance(response.get("error"), dict):
            message = response["error"].get("message") or response["error"].get("code") or "未知错误"
            raise AssistantImageError(f"Runtime 图像诊断失败：{message}")
        if not isinstance(response.get("text"), str):
            raise AssistantImageError("Runtime 图像诊断结果缺少文本")
        return response


def run_console(config_path: str | pathlib.Path = "configs/assistant.json", session_id: str | None = None,
                speak: bool = False) -> None:
    """Run the unified local console with lazy audio setup."""
    from app.audio.voice_gateway import HalfDuplexGateway, InProcessAgentClient, normalize_spoken_text, speech_chunks
    from app.ui.chat_console import ChatConsole

    config = load_config(config_path)
    check_runtime(config)
    check_rag(config)
    application = AssistantApplication.create(config_path)
    agent = InProcessAgentClient(application.agent)
    audio_state: dict[str, Any] = {}

    def ensure_tts() -> tuple[dict, Any, Any]:
        if "tts" not in audio_state:
            voice, playback, tts = check_tts(config, return_backends=True)
            audio_state["tts"] = (voice, playback, tts)
        return audio_state["tts"]

    def play_answer(answer: str) -> None:
        voice, playback, tts = ensure_tts()
        spoken = normalize_spoken_text(answer)
        for chunk in speech_chunks(spoken):
            playback.play(tts.synthesize(chunk), voice["tts_sample_rate"])

    def listen(request_id: str) -> dict:
        if "listen" not in audio_state:
            voice = check_listen(config)
            recorder, asr = voice_gateway.build_asr_backends(voice)
            audio_state["listen"] = (voice, recorder, asr)
        voice, recorder, asr = audio_state["listen"]
        turn_config = dict(voice, session_id=console.session_id)
        if console.speak:
            _, playback, tts = ensure_tts()
            class Audio:
                def record(self, *args): return recorder.record(*args)
                def play(self, *args): return playback.play(*args)
            audio = Audio()
        else:
            audio, tts = recorder, None
        return HalfDuplexGateway(turn_config, agent, audio, asr, tts, speak=console.speak).run_turn(request_id)

    # Move the VITS and output-device cold start before the first answer without requiring TTS.
    if speak:
        try:
            ensure_tts()
        except AssistantPreflightError:
            pass
    console = ChatConsole(agent, session_id=session_id, speaker=play_answer, listener=listen, speak=speak,
                          image_diagnoser=application.diagnose_image)
    console.run()
