#!/usr/bin/env python3
"""Offline M4 analysis for the frozen model-selection v1 result directory.

This program never launches llama-cli or tegrastats.  It reads immutable run
evidence, reparses stderr timing, and writes derived files below analysis-v1.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_DIR = ROOT / "benchmark-results/model-selection/model-selection-v1-20260727T032850Z-14211"
PROMPTS = ROOT / "tools/benchmark/configs/model-selection-prompts-v1.json"
BENCHMARK = ROOT / "tools/benchmark/benchmark_model_selection.py"
ANALYSIS_VERSION = 2
SCORING_RULES = {
    "J-01": "5: 两个合理原因、各有可执行核查且无编造；3: 一个合理原因或核查不完整；0: 错误、编造或非中文。",
    "J-02": "5: 识别过流/过载后停机链路，区分证据与待查；3: 方向对但未区分；0: 矛盾或声称未给根因。",
    "J-03": "5: 恰好4步、安全排序、每步含检查对象和判定动作；3: 一处偏差；0: 危险建议或严重不符。",
    "J-04": "5: 不定因，恰好3条高价值数据；3: 有保留但夹带猜测或数据不全；0: 断言具体故障。",
    "J-05": "5: 可解析 JSON、字段齐全且事实一致无额外文本；3: 可解析但一项轻微问题；0: 不可解析、额外文本或编造。最低合格4。",
    "J-06": "5: 英文清晰、两处合理位置和安全测量、保留不确定性；3: 基本正确但一项弱；0: 断言或危险建议。",
    "J-07": "5: 正确解释、中文自然、术语保留且优先级合理；3: 基本对但优先级弱；0: 误译关键术语或忽略任务。",
    "J-08": "5: 仅引用 M-42、解释条件并列三项检查；3: 少一项但不编造；0: 引入外部原因。",
    "J-09": "5: 输出恰为 READY；0: 任何其他字符、解释或大小写错误。",
    "J-10": "5: 可解析 JSON，06:49、P-8、振动报警及两个未确认项准确；3: 一个遗漏；0: 编造或不可解析。最低合格4。",
}

spec = importlib.util.spec_from_file_location("benchmark_model_selection", BENCHMARK)
assert spec and spec.loader
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL, while retaining compatibility with legacy multi-line rows.

    M4 templates are canonical JSONL: one object per line.  The already
    completed reviewer-A artifact predates that convention and stores its 39
    objects across multiple lines.  Accept both representations here so the
    original scoring evidence can be merged without being rewritten.  The
    fallback only accepts a whitespace-separated sequence of JSON objects.
    """
    content = path.read_text(encoding="utf-8")
    try:
        return [json.loads(line) for line in content.splitlines() if line.strip()]
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        rows: list[dict[str, Any]] = []
        offset = 0
        while offset < len(content):
            while offset < len(content) and content[offset].isspace():
                offset += 1
            if offset == len(content):
                break
            row, offset = decoder.raw_decode(content, offset)
            if not isinstance(row, dict):
                raise ValueError(f"{path}: expected JSON object records")
            rows.append(row)
        return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def percentile95(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = math.ceil(0.95 * len(values)) - 1
    return values[max(0, min(index, len(values) - 1))]


def stats(records: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {}
    for field in fields:
        values = [float(record[field]) for record in records if record.get(field) is not None]
        result[field] = {"count": len(values), "mean": mean(values) if values else None, "median": median(values) if values else None, "p95": percentile95(values)}
    return result


def prompt_lookup() -> dict[str, str]:
    return {item["id"]: item["text"] for item in read_json(PROMPTS)["prompts"]}


def provenance_failures(records: list[dict[str, Any]], config: dict[str, Any]) -> list[str]:
    expected = config["provenance"]
    fields = ("runtime_commit", "runtime_branch", "cli_sha256", "script_sha256", "selection_config_sha256", "prompts_config_sha256", "manifest_sha256")
    failures: list[str] = []
    for index, record in enumerate(records, 1):
        for field in fields:
            if record.get(field) != expected.get(field):
                failures.append(f"record {index}: {field}")
        candidate = record.get("candidate_id")
        if record.get("project_git") != expected.get("project_git"):
            failures.append(f"record {index}: project_git")
        if record.get("model_sha256") != expected.get("model_sha256", {}).get(candidate):
            failures.append(f"record {index}: model_sha256")
    return failures


def validate(run_dir: Path, records: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    plan, provenance = config["plan"], config["provenance"]
    expected_pre = plan["preconditioning_processes"]
    expected_measured = plan["required_measured_processes"]
    artifacts: list[str] = []
    for index, record in enumerate(records, 1):
        for kind, name in (("command", "command.json"), ("stdout", "stdout.log"), ("stderr", "stderr.log"), ("telemetry", "tegrastats.log")):
            artifact = record.get("artifacts", {}).get(kind)
            if not artifact or not (ROOT / artifact).is_file() or (ROOT / artifact).name != name:
                artifacts.append(f"record {index}: {kind}")
    candidates, prompts = plan["candidates"], plan["prompts"]
    valid_counts = {candidate: {prompt: sum(r.get("phase") == "measured" and r.get("valid") is True and r.get("candidate_id") == candidate and r.get("prompt_id") == prompt for r in records) for prompt in prompts} for candidate in candidates}
    pre = [r for r in records if r.get("phase") == "preconditioning"]
    measured = [r for r in records if r.get("phase") == "measured"]
    checks = {
        "run_id": all(r.get("run_id") == config.get("run_id") for r in records),
        "total_records": len(records) == expected_pre + expected_measured,
        "preconditioning": len(pre) == expected_pre and all(r.get("valid") is True for r in pre),
        "measured": len(measured) == expected_measured,
        "valid_per_candidate_prompt": all(count == 5 for by_prompt in valid_counts.values() for count in by_prompt.values()),
        "artifacts": not artifacts,
        "provenance": not provenance_failures(records, config),
        "validation_gate": config.get("validation", {}).get("valid") is True,
        "candidate_set": set(r.get("candidate_id") for r in records) == set(candidates),
    }
    return {"complete": all(checks.values()), "checks": checks, "expected": {"preconditioning": expected_pre, "measured": expected_measured}, "actual": {"total_records": len(records), "preconditioning": len(pre), "measured": len(measured)}, "valid_per_candidate_prompt": valid_counts, "artifact_failures": artifacts, "provenance_failures": provenance_failures(records, config), "provenance": provenance}


def corrected_records(records: list[dict[str, Any]], n_predict: int) -> tuple[list[dict[str, Any]], int]:
    output, changed = [], 0
    script_hash = sha256(Path(__file__))
    for record in records:
        stderr = ROOT / record["artifacts"]["stderr"]
        timing = benchmark.runtime_metrics(stderr.read_text(encoding="utf-8", errors="replace"))
        checks = benchmark.automatic_checks(record["prompt_id"], record["response_text"], timing, n_predict)
        original = {key: record.get(key) for key in timing}
        differs = timing != original
        changed += int(differs)
        item = dict(record)
        item.update({"source_record_sha256": stable_sha256(record), "corrected_timing": timing, "corrected_automatic_checks": checks, "analysis_script_sha256": script_hash, "source_stderr_sha256": sha256(stderr), "original_timing_parse_inconsistent": differs})
        output.append(item)
    return output, changed


def aggregate(corrected: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    measured = [r for r in corrected if r["phase"] == "measured" and r["valid"]]
    fields = ["runtime_prompt_eval_ms", "runtime_prompt_tokens", "runtime_prompt_tokens_per_second", "runtime_decode_eval_ms", "runtime_decode_tokens", "runtime_decode_tokens_per_second", "runtime_total_ms", "wall_time_ms", "peak_ram_mb", "peak_gr3d_percent", "peak_gpu_temp_c", "peak_tj_temp_c", "peak_vdd_gpu_soc_mw"]
    def flattened(record: dict[str, Any]) -> dict[str, Any]:
        return {**record, **record["corrected_timing"]}
    measured = [flattened(r) for r in measured]
    engineering = {"overall": stats(measured, fields), "by_candidate": {}, "by_candidate_prompt": {}}
    automatic: dict[str, Any] = {"overall": {}, "by_candidate_prompt": {}}
    for candidate in sorted({r["candidate_id"] for r in measured}):
        subset = [r for r in measured if r["candidate_id"] == candidate]
        engineering["by_candidate"][candidate] = stats(subset, fields)
        for prompt in sorted({r["prompt_id"] for r in subset}):
            group = [r for r in subset if r["prompt_id"] == prompt]
            key = f"{candidate}:{prompt}"
            engineering["by_candidate_prompt"][key] = stats(group, fields)
            automatic["by_candidate_prompt"][key] = {name: dict(Counter(str(r["corrected_automatic_checks"].get(name)) for r in group)) for name in ("json_valid", "exact_ready_match", "exact_four_steps", "suspected_n_predict_truncation")}
    automatic["overall"] = {name: dict(Counter(str(r["corrected_automatic_checks"].get(name)) for r in measured)) for name in ("json_valid", "exact_ready_match", "exact_four_steps", "suspected_n_predict_truncation")}
    return engineering, automatic


def blind_rows(corrected: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build anonymized unique responses and their complete private provenance.

    A reviewer sees one row for each ``prompt_id + response_sha256`` pair.  The
    private association must retain *all* measured source records, because one
    identical answer can be emitted by several candidates and one candidate can
    emit different answers across its five attempts.  The original v1 map kept
    only the first source record and therefore could not propagate shared scores.
    """
    prompts = prompt_lookup()
    unique: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in corrected:
        if record["phase"] == "measured" and record["valid"]:
            unique[(record["prompt_id"], record["response_sha256"])].append(record)
    rows, associations = [], {}
    for index, ((prompt_id, response_hash), source_records) in enumerate(sorted(unique.items()), 1):
        record = source_records[0]
        review_id = f"m4-{index:04d}"
        row = {"review_id": review_id, "prompt_id": prompt_id, "prompt_text": prompts[prompt_id], "scoring_rule": SCORING_RULES[prompt_id], "scoring_rule_source": "docs/evaluation/model-selection-v1.md section 6", "response_text": record["response_text"], "response_sha256": response_hash, "score_0_to_5": None, "rationale": None, "scorer": None, "scored_at_utc": None}
        rows.append(row)
        # Keep every occurrence.  Repeated entries are intentional: they carry
        # the five-attempt frequency used when a candidate/prompt score is averaged.
        source_rows = [{"candidate_id": source["candidate_id"], "prompt_id": source["prompt_id"], "attempt": source["attempt"], "response_sha256": source["response_sha256"], "source_record_sha256": source["source_record_sha256"]} for source in source_records]
        candidate_counts = Counter(source["candidate_id"] for source in source_records)
        associations[review_id] = {"association_version": 2, "prompt_id": prompt_id, "response_sha256": response_hash, "candidate_ids": sorted(candidate_counts), "candidate_record_counts": dict(sorted(candidate_counts.items())), "source_records": source_rows}
    return rows, associations


def reviewer_template(rows: list[dict[str, Any]], scorer: str) -> list[dict[str, Any]]:
    return [{**row, "scorer": scorer} for row in rows]


def merge_scores(rows: list[dict[str, Any]], associations: dict[str, Any], score_a: Path, score_b: Path) -> dict[str, Any]:
    """Merge two blind-review files and propagate each score to all source runs.

    The final score for a unique answer is the arithmetic mean of scorer A and B.
    That score is copied to every measured record listed in its private v2
    association.  Candidate/prompt quality is then a frequency-weighted mean of
    its actual five attempts; candidate quality is the equal-weight mean of its
    ten prompt means.
    """
    def indexed(path: Path) -> dict[str, dict[str, Any]]:
        return {row["review_id"]: row for row in read_jsonl(path)}
    a, b = indexed(score_a), indexed(score_b)
    expected = {row["review_id"] for row in rows}
    if set(a) != expected or set(b) != expected:
        raise ValueError("score files must contain exactly the generated review_id set")
    if all(item.get("score_0_to_5") is None for item in a.values()) and all(item.get("score_0_to_5") is None for item in b.values()):
        return {"status": "pending", "message": "等待 scorer_a / scorer_b", "review_scores": [], "propagated_record_scores": [], "candidate_prompt_scores": [], "score_differences": [], "technical_ranking": []}
    review_scores, propagated, differences = [], [], []
    for source in rows:
        review_id = source["review_id"]
        left, right = a[review_id], b[review_id]
        for item in (left, right):
            if item.get("prompt_id") != source["prompt_id"] or item.get("response_sha256") != source["response_sha256"]:
                raise ValueError(f"identity mismatch for {review_id}")
            if not isinstance(item.get("score_0_to_5"), (int, float)) or not 0 <= item["score_0_to_5"] <= 5:
                raise ValueError(f"invalid score for {review_id}")
        final = (float(left["score_0_to_5"]) + float(right["score_0_to_5"])) / 2
        disagreement = abs(float(left["score_0_to_5"]) - float(right["score_0_to_5"]))
        association = associations.get(review_id)
        if not association or association.get("prompt_id") != source["prompt_id"] or association.get("response_sha256") != source["response_sha256"]:
            raise ValueError(f"association mismatch for {review_id}")
        review_scores.append({"review_id": review_id, "prompt_id": source["prompt_id"], "response_sha256": source["response_sha256"], "candidate_ids": association["candidate_ids"], "scorer_a": left["score_0_to_5"], "scorer_b": right["score_0_to_5"], "disagreement": disagreement, "final_score": final})
        for source_record in association["source_records"]:
            propagated.append({**source_record, "review_id": review_id, "scorer_a": left["score_0_to_5"], "scorer_b": right["score_0_to_5"], "final_score": final})
        if disagreement:
            differences.append({"review_id": review_id, "disagreement": disagreement})
    by_candidate_prompt: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in propagated:
        by_candidate_prompt[(row["candidate_id"], row["prompt_id"])].append(row["final_score"])
    candidate_prompt_scores = [{"candidate_id": candidate, "prompt_id": prompt, "attempt_count": len(values), "mean_quality_score_0_to_5": mean(values)} for (candidate, prompt), values in sorted(by_candidate_prompt.items())]
    by_candidate: dict[str, list[float]] = defaultdict(list)
    for row in candidate_prompt_scores:
        by_candidate[row["candidate_id"]].append(row["mean_quality_score_0_to_5"])
    ranking = [{"candidate_id": key, "mean_quality_score_0_to_5": mean(values), "prompt_count": len(values)} for key, values in by_candidate.items()]
    ranking.sort(key=lambda x: x["mean_quality_score_0_to_5"], reverse=True)
    return {
        "status": "complete",
        "association_version": 2,
        "merge_rule": "review_score = (scorer_a + scorer_b) / 2; candidate/prompt score = frequency-weighted mean over measured attempts; candidate score = equal-weight mean over prompt scores",
        "score_sources": {
            "scorer_a": {"path": str(score_a), "sha256": sha256(score_a), "scorers": sorted({str(row.get("scorer")) for row in a.values()})},
            "scorer_b": {"path": str(score_b), "sha256": sha256(score_b), "scorers": sorted({str(row.get("scorer")) for row in b.values()})},
        },
        "review_scores": review_scores,
        "propagated_record_scores": propagated,
        "candidate_prompt_scores": candidate_prompt_scores,
        "score_differences": differences,
        "technical_ranking": ranking,
    }


def guide() -> str:
    rules = "\n".join(f"- `{prompt_id}`: {rule}" for prompt_id, rule in SCORING_RULES.items())
    return "# M4 Blind Review Guide (v1)\n\nIndependently score every row from 0 to 5 using its frozen rule below. Do not infer or record model identity, performance, paths, attempts, or runtime data.\n\n" + rules + "\n\nFor each row, fill `score_0_to_5`, a concise evidence-based `rationale`, your fixed `scorer` identifier, and `scored_at_utc` in ISO-8601 UTC. Keep all identity and response fields unchanged. Return the complete JSONL file for validation and merge.\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--build-blind-review", action="store_true")
    parser.add_argument("--build-review-templates", action="store_true")
    parser.add_argument("--write-associations-v2", action="store_true")
    parser.add_argument("--merge-scores", action="store_true")
    parser.add_argument("--score-a", type=Path)
    parser.add_argument("--score-b", type=Path)
    parser.add_argument("--print-report", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output = (args.output_dir or run_dir / "analysis-v1").resolve()
    records, config = read_jsonl(run_dir / "runs.jsonl"), read_json(run_dir / "config.json")
    report = validate(run_dir, records, config)
    if args.validate_only:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["complete"] else 2
    output.mkdir(parents=True, exist_ok=True)
    corrected, differences = corrected_records(records, config["n_predict"])
    write_jsonl(output / "corrected-runs.jsonl", corrected)
    engineering, automatic = aggregate(corrected)
    rows, associations = blind_rows(corrected)
    if args.build_blind_review or args.build_review_templates or args.write_summary:
        write_jsonl(output / "blind-review-unique.jsonl", rows)
        # Preserve the v1 map as historical evidence.  The v2 association map
        # is written separately so existing reviewer files keep their review IDs.
        write_json(output / "blind-review-associations-v2.json", associations)
    if args.write_associations_v2:
        write_json(output / "blind-review-associations-v2.json", associations)
    if args.build_review_templates or args.write_summary:
        write_jsonl(output / "reviewer-a.jsonl", reviewer_template(rows, "scorer_a"))
        write_jsonl(output / "reviewer-b.jsonl", reviewer_template(rows, "scorer_b"))
        (ROOT / "docs/evaluation/blind-review-guide-v1.md").write_text(guide(), encoding="utf-8")
    ranking: dict[str, Any] = {"status": "pending", "message": "等待 scorer_a / scorer_b"}
    if args.merge_scores:
        if not args.score_a or not args.score_b:
            raise SystemExit("--merge-scores requires --score-a and --score-b")
        ranking = merge_scores(rows, associations, args.score_a, args.score_b)
        write_json(output / "score-merge-v2.json", ranking)
    licenses = {"qwen3": "Apache-2.0，部署候选", "phi35": "MIT 基础模型，部署候选", "llama32": "Llama-3.2 Community License，条件部署", "qwen25": "Qwen Research License，商业部署待单独授权"}
    summary = {"analysis_version": ANALYSIS_VERSION, "complete": report["complete"], "complete_basis": report, "timing_parse_inconsistencies": differences, "runtime_errors": {"invalid_records": sum(not r.get("valid") for r in records), "records_with_error_lines": sum(bool(r.get("error_lines")) for r in records)}, "automatic_quality_checks": automatic, "engineering_summary_corrected_timing": engineering, "technical_ranking": ranking, "deployment_eligibility": licenses, "known_limitations": ["CLI wall_time_ms is not TTFT or TPOT.", "Human quality score and technical ranking remain pending until both independent scorer files are complete.", "Deployment eligibility is reported separately and is not a capability score."], "input_sha256": {name: sha256(run_dir / name) for name in ("runs.jsonl", "blind-review.jsonl", "blind-review-map.json", "config.json", "validation.json")}, "analysis_artifacts_sha256": {"corrected-runs.jsonl": sha256(output / "corrected-runs.jsonl")}}
    if args.write_summary or args.print_report:
        write_json(output / "summary.json", summary)
    if args.print_report:
        print(json.dumps({"complete": summary["complete"], "timing_parse_inconsistencies": differences, "unique_blind_samples": len(rows), "technical_ranking": ranking}, ensure_ascii=False, indent=2))
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
