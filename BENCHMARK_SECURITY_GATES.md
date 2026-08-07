# Security Gate Benchmark

`tests/benchmark_security_gates.py` is a **ground-truth correctness benchmark**
for the Security Gate, not a fuzzy quality score. Every case has a known right
answer (*this input must block* / *this input must not block*), so the only
acceptable result is **100%**: any failure is a real regression in either

- **detection** — a threat class that stopped blocking, or
- **precision** — clean input that started blocking and would jam every future
  PR pipeline run.

## What it covers

It exercises the real detection layer (`SecretScanner`, `ConfigSecurityScanner`,
`VirusScanner` with a mocked, EICAR-aware clamd) through the real decision layer
(`RiskScorer`, `security_gate_should_block` from `orchestrator/workflow.py`) end
to end against a scratch repository on disk.

| Case | Expected | Why |
|---|---|---|
| `aws_access_key_committed` | block | AKIA-prefixed key is a critical finding |
| `private_key_committed` | block | Raw PEM private key block is critical |
| `malware_via_eicar` | block | Virus findings are hardcoded critical in `security/nsil.py` |
| `clean_repository` | pass | No findings must never block |
| `only_medium_findings` | pass | Generic 20+ char `api_key` assignment is medium |
| `only_high_findings` | pass | A Slack token alone is high, not critical |
| `dockerfile_missing_user_only` | pass | `dockerfile_no_user` is medium |

## Running it

```bash
# readable report table
pytest tests/benchmark_security_gates.py -v -s

# it is also collected by the normal suite, so CI runs it on every PR
pytest --cov=. --cov-fail-under=80
```

## Adding cases

Append a `GateCase` to `CASES` for every new threat class, and for every
"this must never block" regression that shows up in practice. That list *is*
the benchmark — the test functions just execute it.

## Out of scope (verify by hand)

- NSIL persistence/reconciliation — covered by `tests/test_security_nsil.py`.
- The CI-level `bandit` / `safety` / Trivy jobs in `.github/workflows/` — these
  are shell commands in someone else's tool, not Python this repo can benchmark.
  To verify Trivy by hand, drop the EICAR test string into a file in a scratch
  branch and confirm the workflow job fails:

  ```bash
  printf 'X5O!P%%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > eicar.txt
  ```
