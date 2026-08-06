import hashlib
import io
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
from app.audio.voice_gateway import AudioGatewayError, HalfDuplexGateway, TextDemoGateway, float_samples_to_pcm, load_config, normalize_spoken_text, tts_text


class AudioGatewayM11Test(unittest.TestCase):
    def artifact(self, directory, name):
        path = directory / name
        path.write_bytes(b"local-model")
        return {"path": str(path.relative_to(ROOT)), "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "language": "zh", "sample_rate": 16000, "license": "Apache-2.0"}

    def test_config_requires_pinned_local_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            directory = pathlib.Path(temp)
            config = {"schema_version": 1, "milestone": "M11-PROTOTYPE", "sample_rate": 16000, "tts_sample_rate": 8000, "channels": 1, "input_device": None, "output_device": None, "asr_model": self.artifact(directory, "asr"), "vad_model": self.artifact(directory, "vad"), "tts_model": {**self.artifact(directory, "tts"), "sample_rate": 8000}, "agent_command": ["python3", "scripts/run_agent.py", "--jsonl"], "session_id": "voice-session", "max_record_seconds": 15, "silence_timeout_seconds": 2}
            path = directory / "config.json"; path.write_text(json.dumps(config), encoding="utf-8")
            loaded = load_config(path)
            self.assertEqual(loaded["sample_rate"], 16000)
            config["asr_model"]["sha256"] = "0" * 64
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(AudioGatewayError): load_config(path)

    def test_half_duplex_turn_orders_record_agent_tts_play(self):
        events = []
        class Audio:
            def record(self, *_): events.append("record"); return b"pcm"
            def play(self, *_): events.append("play")
        class Asr:
            def transcribe(self, _): events.append("asr"); return "故障是什么"
        class Agent:
            def answer(self, *_): events.append("agent"); return {"status": "OK", "answer": "故障说明。[S1]", "citations": [{"id": "S1"}]}
        class Tts:
            def synthesize(self, _): events.append("tts"); return b"audio"
        config = {"sample_rate": 16000, "tts_sample_rate": 8000, "session_id": "voice-session", "max_record_seconds": 15, "silence_timeout_seconds": 2}
        result = HalfDuplexGateway(config, Agent(), Audio(), Asr(), Tts()).run_turn("r1")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(events, ["record", "asr", "agent", "tts", "play"])

    def test_text_demo_skips_microphone_and_reuses_agent_response(self):
        events = []
        class Audio:
            def play(self, pcm, rate): events.append(("play", pcm, rate))
        class Agent:
            def answer(self, request_id, session_id, query):
                events.append(("agent", request_id, session_id, query))
                return {"status": "OK", "answer": "BX-9 的出口压力是 18 MPa。[S1]", "citations": [{"id": "S1"}]}
        class Tts:
            def synthesize(self, answer): events.append(("tts", answer)); return b"pcm"
        config = {"session_id": "voice-session", "tts_sample_rate": 8000}
        result = TextDemoGateway(config, Agent(), Audio(), Tts()).run_turn("text-r1", "BX-9 的出口压力是多少？")
        self.assertEqual(result["answer"], "BX-9 的出口压力是 18 MPa。[S1]")
        self.assertEqual(result["citations"], [{"id": "S1"}])
        self.assertEqual(result["spoken_text"], "该设备的出口压力是十八兆帕。")
        self.assertEqual([event[0] for event in events], ["agent", "tts", "play"])
        self.assertEqual(events[1][1], "该设备的出口压力是十八兆帕。")

    def test_text_demo_does_not_play_agent_error(self):
        class Agent:
            def answer(self, *_): return {"status": "CITATION_FORMAT_ERROR", "answer": None, "citations": []}
        class Audio:
            def play(self, *_): self.fail("play must not run")
        class Tts:
            def synthesize(self, _): self.fail("tts must not run")
        result = TextDemoGateway({"session_id": "voice-session", "tts_sample_rate": 8000}, Agent(), Audio(), Tts()).run_turn("text-r2", "问题")
        self.assertEqual(result["status"], "CITATION_FORMAT_ERROR")

    def test_tts_text_and_pcm_conversion(self):
        self.assertEqual(tts_text("答案。[S1] [S2]"), "答案。")
        self.assertEqual(float_samples_to_pcm([-1.0, 0.0, 1.0]), b"\x00\x80\x00\x00\xff\x7f")

    def test_spoken_text_normalizes_citations_codes_numbers_and_units(self):
        answer = "BX-9 的出口压力是 18 MPa。[S1] E42，15 to 65 degrees Celsius，250 operating hours。[S12]"
        self.assertEqual(normalize_spoken_text(answer), "该设备的出口压力是十八兆帕。故障代码四十二，十五到六十五摄氏度，二百五十运行小时。")
        self.assertNotIn("[S", normalize_spoken_text(answer))

    def test_empty_spoken_text_does_not_synthesize_or_play(self):
        class Agent:
            def answer(self, *_): return {"status": "OK", "answer": "[S1]", "citations": [{"id": "S1"}]}
        class Audio:
            def play(self, *_): self.fail("play must not run")
        class Tts:
            def synthesize(self, _): self.fail("tts must not run")
        result = TextDemoGateway({"session_id": "voice-session", "tts_sample_rate": 8000}, Agent(), Audio(), Tts()).run_turn("text-r3", "问题")
        self.assertEqual((result["status"], result["spoken_text"]), ("TTS_TEXT_ERROR", ""))


if __name__ == "__main__": unittest.main()
