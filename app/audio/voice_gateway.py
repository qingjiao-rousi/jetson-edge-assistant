#!/usr/bin/env python3
"""M11 half-duplex local audio -> Agent -> audio gateway."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
MILESTONE = "M11-PROTOTYPE"
CITATION_MARKER = re.compile(r"\s*\[S[1-9][0-9]*\]\s*")
SPEECH_SENTENCE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")


class AudioGatewayError(ValueError):
    pass


def _spoken_number(value: str) -> str:
    if "." in value:
        whole, fraction = value.split(".", 1)
        return _spoken_number(whole) + "点" + "".join("零一二三四五六七八九"[int(digit)] for digit in fraction)
    number = int(value)
    if number == 0:
        return "零"
    digits, units = "零一二三四五六七八九", ("", "十", "百", "千")
    pieces, pending_zero = [], False
    source = str(number)
    for index, char in enumerate(source):
        digit = int(char)
        unit = units[len(source) - index - 1]
        if digit == 0:
            pending_zero = bool(pieces)
        else:
            if pending_zero:
                pieces.append("零")
            pieces.append(digits[digit] + unit)
            pending_zero = False
    result = "".join(pieces)
    return result[1:] if result.startswith("一十") else result


def normalize_spoken_text(answer: str) -> str:
    """Create VITS-only Mandarin text while preserving the original Agent payload."""
    if not isinstance(answer, str):
        return ""
    spoken = CITATION_MARKER.sub("", answer)
    spoken = re.sub(r"\b(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+degrees?\s+Celsius\b",
                    lambda m: f"{_spoken_number(m.group(1))}到{_spoken_number(m.group(2))}摄氏度", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\b(\d+(?:\.\d+)?)\s+MPa\b", lambda m: _spoken_number(m.group(1)) + "兆帕", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\b(\d+(?:\.\d+)?)\s+operating\s+hours?\b", lambda m: _spoken_number(m.group(1)) + "运行小时", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"BX-9", "该设备", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\bE(\d{2,4})\b", lambda m: "故障代码" + _spoken_number(m.group(1)), spoken, flags=re.IGNORECASE)
    # Do not invent a pronunciation for unsupported ASCII identifiers.
    spoken = re.sub(r"[A-Za-z][A-Za-z0-9._/-]*", "", spoken)
    # VITS lexicons do not assign pronunciations to bracket glyphs; they add no spoken meaning.
    spoken = re.sub(r"[()（）\[\]{}<>]", "", spoken)
    spoken = re.sub(r"\s+", "", spoken)
    return spoken


def speech_chunks(text: str, maximum_characters: int = 48) -> list[str]:
    """Split completed text for sequential TTS playback; this is not streaming TTS."""
    if not isinstance(text, str) or maximum_characters < 1:
        return []
    chunks: list[str] = []
    for sentence in SPEECH_SENTENCE.findall(text):
        remaining = sentence.strip()
        while len(remaining) > maximum_characters:
            boundary = remaining.rfind("，", 0, maximum_characters + 1)
            split_at = boundary + 1 if boundary >= 0 else maximum_characters
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:]
        if remaining:
            chunks.append(remaining)
    return chunks


def tts_text(answer: str) -> str:
    """Compatibility wrapper that rejects an answer with no safe speakable content."""
    spoken = normalize_spoken_text(answer)
    if not spoken:
        raise AudioGatewayError("answer has no speakable text")
    return spoken


def float_samples_to_pcm(samples: Any) -> bytes:
    pcm = array.array("h")
    for sample in samples:
        value = max(-1.0, min(1.0, float(sample)))
        pcm.append(max(-32768, min(32767, round(value * 32768))))
    return pcm.tobytes()


def _repo_file(value: str) -> pathlib.Path:
    path = pathlib.PurePosixPath(value)
    if not isinstance(value, str) or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise AudioGatewayError("model path must be repository-relative")
    return (ROOT / path).resolve()


def validate_model_spec(spec: dict, name: str, sample_rate: int) -> dict:
    required = {"path", "size_bytes", "sha256", "language", "sample_rate", "license"}
    if not isinstance(spec, dict) or not required.issubset(spec):
        raise AudioGatewayError(f"{name} must specify path, size_bytes, sha256, language, sample_rate and license")
    if not isinstance(spec["size_bytes"], int) or spec["size_bytes"] < 1:
        raise AudioGatewayError(f"{name}.size_bytes is invalid")
    if not isinstance(spec["sha256"], str) or len(spec["sha256"]) != 64 or any(c not in "0123456789abcdefABCDEF" for c in spec["sha256"]):
        raise AudioGatewayError(f"{name}.sha256 is invalid")
    if spec["sample_rate"] != sample_rate or not all(isinstance(spec[k], str) and spec[k].strip() for k in ("language", "license")):
        raise AudioGatewayError(f"{name} language/license/sample_rate is invalid")
    path = _repo_file(spec["path"])
    if not path.is_file():
        raise AudioGatewayError(f"{name} artifact is missing: {spec['path']}")
    if path.stat().st_size != spec["size_bytes"]:
        raise AudioGatewayError(f"{name} artifact size mismatch")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest.lower() != spec["sha256"].lower():
        raise AudioGatewayError(f"{name} artifact sha256 mismatch")
    return {**spec, "path": str(path)}


def load_config(path: str | pathlib.Path) -> dict:
    config_path = _repo_file(str(path)) if not isinstance(path, pathlib.Path) or not path.is_absolute() else path
    config = json.loads(config_path.read_text(encoding="utf-8"))
    required = {"schema_version", "milestone", "sample_rate", "tts_sample_rate", "channels", "input_device", "output_device", "asr_model", "vad_model", "tts_model", "session_id", "max_record_seconds", "silence_timeout_seconds"}
    if set(config) != required or config["schema_version"] != 1 or config["milestone"] != MILESTONE:
        raise AudioGatewayError("invalid M11 config")
    if config["sample_rate"] != 16000 or config["channels"] != 1:
        raise AudioGatewayError("M11 audio contract requires 16 kHz mono")
    if not isinstance(config["session_id"], str) or not config["session_id"] or len(config["session_id"]) > 128:
        raise AudioGatewayError("invalid voice session_id")
    if config["tts_sample_rate"] != 8000:
        raise AudioGatewayError("M11 VITS playback requires 8 kHz output")
    for key in ("max_record_seconds", "silence_timeout_seconds"):
        if not isinstance(config[key], (int, float)) or config[key] <= 0:
            raise AudioGatewayError(f"invalid {key}")
    config = dict(config)
    config["asr_model"] = validate_model_spec(config["asr_model"], "asr_model", 16000)
    config["vad_model"] = validate_model_spec(config["vad_model"], "vad_model", 16000)
    config["tts_model"] = validate_model_spec(config["tts_model"], "tts_model", config["tts_sample_rate"])
    return config


class AgentClient:
    def __init__(self, command: list[str], popen=subprocess.Popen):
        self.process = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        if self.process.stdin is None or self.process.stdout is None:
            raise AudioGatewayError("agent pipes unavailable")
        self._input, self._output = self.process.stdin, self.process.stdout

    def answer(self, request_id: str, session_id: str, query: str) -> dict:
        self._input.write(json.dumps({"request_id": request_id, "op": "answer", "session_id": session_id, "query": query}, ensure_ascii=False) + "\n")
        self._input.flush()
        line = self._output.readline()
        if not line:
            raise AudioGatewayError("agent exited without response")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise AudioGatewayError("invalid agent response")
        return response

    def close(self):
        if self.process.stdin: self.process.stdin.close()
        self.process.terminate()
        self.process.wait(timeout=5)


class InProcessAgentClient:
    """Adapter for the existing Agent application; no JSONL subprocess is started."""

    def __init__(self, application: Any):
        self.application = application

    def answer(self, request_id: str, session_id: str, query: str) -> dict:
        return self.application.handle({"request_id": request_id, "op": "answer", "session_id": session_id, "query": query})

    def request(self, payload: dict) -> dict:
        return self.application.handle(payload)

    def close(self) -> None:
        return None


@dataclass
class HalfDuplexGateway:
    config: dict
    agent: Any
    audio: Any
    asr: Any
    tts: Any
    speak: bool = True

    def run_turn(self, request_id: str) -> dict:
        samples = self.audio.record(self.config["max_record_seconds"], self.config["silence_timeout_seconds"])
        text = self.asr.transcribe(samples)
        if not text.strip():
            return {"status": "EMPTY_ASR", "text": "", "answer": None, "spoken_text": None}
        response = self.agent.answer(request_id, self.config["session_id"], text)
        if response.get("status") != "OK":
            return {"status": response.get("status", "AGENT_ERROR"), "text": text, "answer": response.get("answer"), "citations": response.get("citations", []), "spoken_text": None}
        if not self.speak:
            return {"status": "OK", "text": text, "answer": response["answer"], "citations": response.get("citations", []), "spoken_text": None}
        spoken = normalize_spoken_text(response["answer"])
        if not spoken:
            return {"status": "TTS_TEXT_ERROR", "text": text, "answer": response["answer"], "citations": response.get("citations", []), "spoken_text": ""}
        pcm = self.tts.synthesize(spoken)
        self.audio.play(pcm, self.config["tts_sample_rate"])
        return {"status": "OK", "text": text, "answer": response["answer"], "citations": response.get("citations", []), "spoken_text": spoken}


@dataclass
class TextDemoGateway:
    """Keyboard demo: Agent and local TTS only, with no microphone path."""
    config: dict
    agent: Any
    audio: Any
    tts: Any

    def run_turn(self, request_id: str, text: str) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise AudioGatewayError("--text must be non-empty")
        response = self.agent.answer(request_id, self.config["session_id"], text)
        if response.get("status") != "OK":
            return {"status": response.get("status", "AGENT_ERROR"), "text": text, "answer": response.get("answer"), "citations": response.get("citations", []), "spoken_text": None}
        spoken = normalize_spoken_text(response["answer"])
        if not spoken:
            return {"status": "TTS_TEXT_ERROR", "text": text, "answer": response["answer"], "citations": response.get("citations", []), "spoken_text": ""}
        pcm = self.tts.synthesize(spoken)
        self.audio.play(pcm, self.config["tts_sample_rate"])
        return {"status": "OK", "text": text, "answer": response["answer"], "citations": response.get("citations", []), "spoken_text": spoken}


def build_tts_backends(config: dict):
    try:
        import sounddevice as sd
        import sherpa_onnx
    except ImportError as error:
        raise AudioGatewayError("M11 requires local sounddevice/PortAudio and sherpa-onnx packages") from error
    class PlaybackAudio:
        def play(self, pcm, sample_rate):
            with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16", device=config["output_device"]) as stream:
                stream.write(pcm)

    try:
        tts_dir = pathlib.Path(config["tts_model"]["path"]).parent
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=config["tts_model"]["path"],
            lexicon=str(tts_dir / "lexicon.txt"),
            tokens=str(tts_dir / "tokens.txt"),
            data_dir=str(tts_dir),
        )
        tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=2),
            rule_fars=str(tts_dir / "rule.far"),
        ))
    except (AttributeError, TypeError, RuntimeError) as error:
        raise AudioGatewayError(f"unsupported local sherpa-onnx TTS configuration: {error}") from error

    class Tts:
        def synthesize(self, text):
            result = tts.generate(text)
            return float_samples_to_pcm(result.samples)

    return PlaybackAudio(), Tts(), sherpa_onnx, sd


def check_output_device(config: dict) -> None:
    try:
        import sounddevice as sd
        sd.query_devices(config["output_device"], kind="output")
    except (ImportError, ValueError, OSError) as error:
        raise AudioGatewayError(f"output device is unavailable: {error}") from error


def check_input_device(config: dict) -> None:
    try:
        import sounddevice as sd
        sd.query_devices(config["input_device"], kind="input")
    except (ImportError, ValueError, OSError) as error:
        raise AudioGatewayError(f"input device is unavailable: {error}") from error


def build_asr_backends(config: dict):
    try:
        import sounddevice as sd
        import sherpa_onnx
    except ImportError as error:
        raise AudioGatewayError("M11 requires local sounddevice/PortAudio and sherpa-onnx packages") from error

    class PortAudio:
        def record(self, max_seconds, silence_timeout):
            frames = []
            last_speech = None
            with sd.RawInputStream(samplerate=config["sample_rate"], channels=1, dtype="int16", device=config["input_device"], blocksize=512) as stream:
                deadline = time.monotonic() + max_seconds
                while time.monotonic() < deadline:
                    data, _ = stream.read(512)
                    chunk = bytes(data); frames.append(chunk)
                    try:
                        samples = array.array("h", chunk)
                        vad.accept_waveform([sample / 32768.0 for sample in samples])
                        if getattr(vad, "is_speech_detected", lambda: True)():
                            last_speech = time.monotonic()
                        if last_speech is not None and time.monotonic() - last_speech >= silence_timeout:
                            break
                    except (AttributeError, TypeError):
                        pass
            return b"".join(frames)

    # Keep construction local and explicit; no model download or network fallback exists.
    try:
        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.sample_rate = config["sample_rate"]
        vad_config.silero_vad.model = config["vad_model"]["path"]
        vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
        asr_dir = pathlib.Path(config["asr_model"]["path"]).parent
        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(asr_dir / "tokens.txt"),
            encoder=str(asr_dir / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(asr_dir / "decoder-epoch-99-avg-1.int8.onnx"),
            joiner=str(asr_dir / "joiner-epoch-99-avg-1.int8.onnx"),
            num_threads=2,
            enable_endpoint_detection=True,
        )
    except (AttributeError, TypeError, RuntimeError) as error:
        raise AudioGatewayError(f"unsupported local sherpa-onnx model configuration: {error}") from error

    class VadAsr:
        def transcribe(self, pcm):
            samples = array.array("h"); samples.frombytes(pcm)
            stream = recognizer.create_stream()
            stream.accept_waveform(config["sample_rate"], [sample / 32768.0 for sample in samples])
            stream.input_finished()
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            return recognizer.get_result_all(stream).text

    return PortAudio(), VadAsr()


def build_backends(config: dict):
    recorder, asr = build_asr_backends(config)
    playback, tts, _, _ = build_tts_backends(config)

    class Audio:
        def record(self, max_seconds, silence_timeout):
            return recorder.record(max_seconds, silence_timeout)

        def play(self, pcm, sample_rate):
            playback.play(pcm, sample_rate)

    return Audio(), asr, tts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/voice-gateway.json")
    parser.add_argument("--assistant-config", default="configs/assistant.json", help="provides the canonical Agent command")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--text", help="run one keyboard text -> Agent -> TTS playback demo")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        from app.assistant.application import load_config as load_assistant_config
        agent = AgentClient(load_assistant_config(args.assistant_config)["agent_command"])
        try:
            if args.text is not None:
                audio, tts, _, _ = build_tts_backends(config)
                result = TextDemoGateway(config, agent, audio, tts).run_turn(f"m11-text-{time.time_ns()}", args.text)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            else:
                audio, asr, tts = build_backends(config)
                gateway = HalfDuplexGateway(config, agent, audio, asr, tts)
                counter = 0
                while True:
                    counter += 1
                    result = gateway.run_turn(f"m11-audio-{time.time_ns()}-{counter}")
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    if args.once: break
        finally:
            agent.close()
        return 0
    except (AudioGatewayError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
