#!/usr/bin/env python3
"""M7.5B one-shot process supervisor. It never retries a model launch."""
import argparse, hashlib, json, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""): digest.update(chunk)
    return digest.hexdigest()
def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--runner", required=True); parser.add_argument("--output", required=True); args = parser.parse_args()
    output = pathlib.Path(args.output); output.mkdir(parents=True, exist_ok=False)
    model = ROOT / "models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"; mmproj = ROOT / "models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"; image = ROOT / "third_party/llama.cpp-omni/tools/mtmd/test-1.jpeg"; runner = pathlib.Path(args.runner)
    command = [str(runner), str(model), str(mmproj), str(image)]
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    provenance = {"runner": {"path": str(runner), "size_bytes": runner.stat().st_size, "sha256": sha256(runner)}, "model": {"size_bytes": model.stat().st_size, "sha256": sha256(model)}, "mmproj": {"size_bytes": mmproj.stat().st_size, "sha256": sha256(mmproj)}, "image": {"size_bytes": image.stat().st_size, "sha256": sha256(image)}}
    (output / "asset-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    telemetry_path = output / "tegrastats.log"
    with telemetry_path.open("w") as telemetry:
        telemetry_process = subprocess.Popen(["/usr/bin/tegrastats", "--interval", "250"], stdout=telemetry, stderr=subprocess.STDOUT, text=True)
        started = time.monotonic()
        try:
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=900)
            timed_out = False
        except subprocess.TimeoutExpired as error:
            run = subprocess.CompletedProcess(command, 124, error.stdout or "", error.stderr or "")
            timed_out = True
        finally:
            telemetry_process.terminate()
            try: telemetry_process.wait(timeout=10)
            except subprocess.TimeoutExpired: telemetry_process.kill(); telemetry_process.wait()
    wall_ms = round((time.monotonic() - started) * 1000)
    (output / "stdout.log").write_text(run.stdout); (output / "stderr.log").write_text(run.stderr)
    payload = {"status": "TIMEOUT" if timed_out else ("SUCCESS" if run.returncode == 0 else "FAILED"), "child_exit_code": run.returncode, "tegrastats_stopped": telemetry_process.poll() is not None, "wall_clock_ms": wall_ms, "adapter_result": json.loads(run.stdout.splitlines()[-1]) if run.stdout.splitlines() else None}
    (output / "result.json").write_text(json.dumps(payload, indent=2) + "\n")
    return run.returncode
if __name__ == "__main__": sys.exit(main())
