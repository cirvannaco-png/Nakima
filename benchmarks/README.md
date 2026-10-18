# Nakima code-model evaluation

## Candidate shortlist (not a ranking)

1. `Qwen/Qwen2.5-Coder-7B-Instruct` — baseline candidate with an Apache-2.0 model card; suitable for initial endpoint sizing and controlled evaluation.
2. `Qwen/Qwen2.5-Coder-14B-Instruct` — mid-sized candidate; compare quality gains against latency and hardware cost.
3. `Qwen/Qwen2.5-Coder-32B-Instruct` — higher-capacity candidate; evaluate only if measured quality justifies the added runtime cost.

All three model cards currently declare Apache-2.0. Pin the exact Hub revision used for every benchmark and deployment.

Model card: https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct

No model is approved for production based on its published coding benchmark alone. Defect detection, repository-specific precision, and false-positive rate must be measured on Nakima's own frozen corpus.

## Corpus protocol

Build a versioned JSONL corpus with:
- at least 3 representative repositories across the languages Nakima claims to support;
- immutable commit SHAs and file excerpts captured from those commits;
- independently adjudicated defect locations/rules and clean-control files;
- both known real defects (from issue-linked fixes) and clean controls;
- no train/test leakage: repositories or time periods held out from prompt tuning;
- expected findings reviewed by two engineers for high-severity examples.

Do not upload private source code or secrets to a public endpoint. Use only repositories whose owners authorize external inference. Redact credentials and personal data before inference.

## Run

Use a private/protected OpenAI-compatible Hugging Face Inference Endpoint and set secrets outside source control:

```bash
export HUGGINGFACE_ENDPOINT_URL='https://<private-endpoint-host>'
export HUGGINGFACE_API_TOKEN='…'
python scripts/benchmark_defect_detection.py --cases benchmarks/defect_cases.jsonl --model Qwen/Qwen2.5-Coder-7B-Instruct --output benchmark-results.json
```

The JSONL case format and scoring implementation are documented in the script. It reports precision, recall, F1, false positives on clean controls, error count, and p50/p95 latency. Location matches are one-to-one and tolerate a ±3 line offset. Rule labels must match when both sides provide them.

## Release gates

- precision ≥ 0.85 on held-out cases;
- recall ≥ 0.80 for high-severity defects;
- clean-control false-positive rate ≤ 0.10;
- no credentials or private code in logs/artifacts;
- p95 latency within the agreed product SLO;
- all proposed fixes pass repository tests and security scans;
- no model-only finding can trigger a merge, deploy, or autonomous write.

Record model ID, immutable model revision, endpoint hardware, quantization, prompt version, corpus commit, and exact script revision with every run. Keep raw outputs in access-controlled storage; do not commit private source snippets or tokens.

## Current status

The harness is implementation-ready, but no scores are claimed until an authenticated endpoint and labeled corpus are available. Hugging Face Inference Endpoints require billing setup and are billed by compute runtime; configure minimum/maximum replicas, scale-to-zero, and billing alerts before deployment.
