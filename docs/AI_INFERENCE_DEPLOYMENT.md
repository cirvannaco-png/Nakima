# Hugging Face inference and deployment controls

## Current implementation

Nakima already uses a multi-stage Python 3.12 Dockerfile. The runtime image installs the system `git` executable required by GitPython, runs as the non-root `nakima` user, uses one Uvicorn worker, and exposes `/health`. CI now smoke-tests those properties against the final built image, rather than checking only the GitHub Actions runner.

The Hugging Face adapter is opt-in. It is selected with `DEFAULT_AI_PROVIDER=huggingface` and requires a private/protected OpenAI-compatible endpoint, its bearer token, and an evaluated model. The adapter fails closed if credentials are absent and no fallback is configured. A fallback is only used when `HUGGINGFACE_FALLBACK_PROVIDER` is explicitly set.

## Endpoint setup gate

Before creating an endpoint:

1. Select a model only after the evaluation protocol in [../benchmarks/README.md](../benchmarks/README.md) has been run on a frozen, reviewed corpus.
2. Pin the model repository revision and the serving image/engine version.
3. Choose a private endpoint where possible; otherwise use a protected endpoint with token authentication. Never expose an unauthenticated public endpoint to repository content.
4. Keep `HUGGINGFACE_API_TOKEN`, GitHub App private key, webhook secret, database credentials, and model-provider tokens in the host's secret manager. Never commit them or place them in build arguments.
5. Set a strict request timeout, prompt character ceiling and completion-token ceiling. These are safety limits, not a complete dollar cap.
6. Set provider-side billing alerts and replica limits; use scale-to-zero or pause when appropriate. Hugging Face Inference Endpoints are billed by compute runtime and hardware, not solely by generated tokens.
7. Send only authorized, secret-redacted source excerpts. Treat repository content as untrusted input and model output as untrusted advice.
8. Run CI, unit tests, static analysis, container scanning, integration tests and a demo webhook test before enabling production events.

## Reproducibility status

The runtime image's Git and non-root properties are checked by CI. A fully reproducible release still requires resolving and committing a complete dependency lock with hashes and pinning immutable base-image digests (the current requirements use minimum-version ranges and the Dockerfile uses mutable base tags plus package-index updates). Do not describe a deployment as fully reproducible until those artifacts exist and the same lock/image digest can be rebuilt successfully.

## Production release gates

- CI passes on the exact candidate commit, including the final-container smoke test.
- The real endpoint passes authentication, timeout, oversized-prompt, provider-failure and fallback tests.
- Model results meet the precision/recall/false-positive gates documented in the benchmark protocol.
- Retrieval snippets are repository-relative, size-bounded, exclude generated/vendor directories, and do not escape the checked-out repository.
- Database readiness is verified separately from liveness; migrations and durable background-job recovery are tested.
- Webhook signatures, replay/idempotency handling, rate limits, secret redaction, and emergency disable behavior are tested.
- No model output can merge code, deploy, or authorize a write without the existing validation and human approval gates.
- Deploy only after the licensing/hosting authorization and operational owner are confirmed.

## Current limitations

No Hugging Face Inference Endpoint has been created, no endpoint token has been configured for Nakima, and no real model scores are claimed. The connected Hugging Face account currently authenticates without a Pro subscription; dedicated endpoint creation requires billing setup. The benchmark harness also needs an independently adjudicated defect corpus. These are explicit release blockers, not successful checks.
