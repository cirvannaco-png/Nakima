#!/usr/bin/env python3
"""Evaluate an OpenAI-compatible Hugging Face endpoint against labeled JSONL cases.

Each JSONL record:
{
  "case_id": "repo-bug-001",
  "repository": "owner/repo",
  "commit": "immutable-commit-sha",
  "language": "python",
  "file": "src/module.py",
  "code": "source excerpt with line numbers relative to the excerpt",
  "expected_findings": [{"file":"src/module.py","line":12,"rule":"null-dereference"}],
  "clean_control": false
}

Ground truth must be manually reviewed and frozen before comparing models. The
script reports evidence-based location matches, false positives on clean controls,
latency percentiles, and errors. It never treats model self-reported confidence as
ground truth and never changes repositories or opens PRs.
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * q))]


def parse_findings(content):
    # Models sometimes wrap JSON in a Markdown fence. Reject malformed output
    # rather than silently converting an unparseable response into zero findings.
    text = content.strip()
    if text.startswith(chr(96) * 3):
        lines = text.splitlines()
        if lines and lines[0].startswith(chr(96) * 3):
            lines = lines[1:]
        if lines and lines[-1].strip() == chr(96) * 3:
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    value = json.loads(text)
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise ValueError("model output must be JSON with a findings array")
    return findings


def match_findings(predicted, expected):
    """Greedy one-to-one match by file and line ±3; rule must match if provided."""
    unmatched = list(expected)
    tp = fp = 0
    for pred in predicted:
        file_name = pred.get("file")
        line = pred.get("line")
        rule = str(pred.get("rule", "")).strip().lower()
        match_index = None
        for index, exp in enumerate(unmatched):
            if file_name != exp.get("file"):
                continue
            try:
                if abs(int(line) - int(exp.get("line"))) > 3:
                    continue
            except (TypeError, ValueError):
                continue
            expected_rule = str(exp.get("rule", "")).strip().lower()
            if expected_rule and rule and rule != expected_rule:
                continue
            match_index = index
            break
        if match_index is None:
            fp += 1
        else:
            tp += 1
            unmatched.pop(match_index)
    return tp, fp, len(unmatched)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, help="Ground-truth JSONL file")
    parser.add_argument("--output", default="benchmark-results.json")
    parser.add_argument("--model", default=os.getenv("HUGGINGFACE_MODEL", "Qwen/Qwen2.5-Coder-7B-Instruct"))
    parser.add_argument("--endpoint", default=os.getenv("HUGGINGFACE_ENDPOINT_URL"))
    parser.add_argument("--token", default=os.getenv("HUGGINGFACE_API_TOKEN"))
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()
    if not args.endpoint or not args.token:
        parser.error("set HUGGINGFACE_ENDPOINT_URL and HUGGINGFACE_API_TOKEN")
    if args.max_tokens < 1 or args.max_tokens > 2048:
        parser.error("--max-tokens must be between 1 and 2048 for a bounded benchmark")

    cases = [json.loads(line) for line in Path(args.cases).read_text().splitlines() if line.strip()]
    if not cases:
        parser.error("cases file is empty")

    results = []
    latencies = []
    errors = 0
    tp = fp = fn = 0
    clean_fp = 0
    with httpx.Client(
        timeout=httpx.Timeout(args.timeout, connect=min(10, args.timeout)), follow_redirects=False
    ) as client:
        for case in cases:
            prompt = (
                "Review this repository code for actionable defects only. "
                "Do not invent findings. Return only JSON: "
                '{"findings":[{"file":"relative/path","line":1,"rule":"short-rule",'
                '"evidence":"specific code evidence","impact":"concrete impact"}]}.\n'
                f"Repository: {case['repository']}\nCommit: {case['commit']}\n"
                f"Language: {case.get('language', 'unknown')}\n"
                f"File: {case['file']}\nCode:\n{case['code']}"
            )
            started = time.perf_counter()
            try:
                response = client.post(
                    args.endpoint.rstrip("/") + "/v1/chat/completions",
                    headers={"Authorization": "Bearer " + args.token, "Content-Type": "application/json"},
                    json={
                        "model": args.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                        "max_tokens": args.max_tokens,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                predicted = parse_findings(content)
                elapsed_ms = (time.perf_counter() - started) * 1000
                latencies.append(elapsed_ms)
                case_tp, case_fp, case_fn = match_findings(predicted, case.get("expected_findings", []))
                tp += case_tp
                fp += case_fp
                fn += case_fn
                if case.get("clean_control"):
                    clean_fp += len(predicted)
                results.append(
                    {
                        "case_id": case["case_id"],
                        "status": "ok",
                        "latency_ms": round(elapsed_ms, 2),
                        "tp": case_tp,
                        "fp": case_fp,
                        "fn": case_fn,
                        "predicted_count": len(predicted),
                    }
                )
            except Exception as exc:
                errors += 1
                results.append({"case_id": case.get("case_id"), "status": "error", "error_type": type(exc).__name__})

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    summary = {
        "model": args.model,
        "endpoint_host": args.endpoint.split("/")[2] if "://" in args.endpoint else "redacted",
        "cases_total": len(cases),
        "cases_succeeded": len(cases) - errors,
        "errors": errors,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": (2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        "false_positives_on_clean_controls": clean_fp,
        "latency_ms_p50": percentile(latencies, 0.50),
        "latency_ms_p95": percentile(latencies, 0.95),
        "ground_truth_warning": "Metrics are meaningful only for independently reviewed, representative cases.",
        "results": results,
    }
    Path(args.output).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
