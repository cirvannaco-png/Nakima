# Nakima Deploy Agent

Sixth agent in the Nakima pipeline. Sits after Docker-sandbox build/test,
before the code goes live, wired into the same human-approval-gate pattern
you already use for accepted roadmap items.

## Structure

```
deploy_agent/
  models.py           # DeployConfig, DeployPlan, DeployRun, DeployStatus, RiskLevel, etc.
  adapter.py           # DeployAdapter ABC — the contract every platform implements
  secrets_store.py     # Fernet-encrypted credential storage (InMemory backend for now)
  orchestrator.py        # DeployAgent — validate -> plan -> approval gate -> execute -> status
  sources/
    github_source.py     # REAL, LIVE-TESTED data flow: repo -> local artifact via git clone
  adapters/
    vercel.py             # REAL — file-hash upload + deployment API, mock-verified
    netlify.py             # REAL — zip-upload deploy API, mock-verified
    supabase.py             # REAL — Management API (migrations + edge functions), mock-verified
    huggingface.py           # REAL — huggingface_hub SDK calls, import-verified only
    gce.py                   # REAL — google-cloud-compute SDK calls, import-verified only
    gcp.py                    # REAL — google-cloud-run SDK calls, import-verified only
tests/
  test_github_source_live.py   # LIVE tests against real github.com — actually clones a real repo
  test_vercel_adapter.py        # mocked HTTP tests verifying real request construction
  test_netlify_adapter.py        # same
  test_supabase_adapter.py        # same
example_usage.py                  # runnable demo: real repo clone -> attempted real deploy call
```

## Honest verification status

Three tiers, and it matters which one each adapter is in:

1. **Live-tested against the real service** — `GitHubRepoSource`. This
   sandbox can reach github.com, so `fetch_artifact()` was run against
   `octocat/Hello-World` for real: real clone, real resolved commit SHA,
   real cleanup, real error path with a bad ref, real token-redaction check.
   See `tests/test_github_source_live.py`.

2. **Mock-verified request construction** — Vercel, Netlify, Supabase.
   This sandbox's outbound network is allowlisted and does not include
   `api.vercel.com` / `api.netlify.com` / `api.supabase.com` (confirmed:
   these return `403` with `x-deny-reason: host_not_allowed` from the
   egress proxy, not from the real platform). So these were verified with
   `requests_mock` instead — real headers, real endpoint URLs, real payload
   shapes, and for Vercel specifically, a test that recomputes the sha1 of
   the actual bytes sent and confirms it matches the `x-vercel-digest`
   header. This proves the *logic* is correct without proving the *live
   endpoint* behaves as documented — verify against a real account before
   trusting it with production traffic.

3. **Import-verified only** — Hugging Face, GCE, GCP. These use official
   SDKs (`huggingface_hub`, `google-cloud-compute`, `google-cloud-run`)
   which import and construct correctly in this environment, and the code
   is written against each SDK's real documented method signatures. But
   none of it has run against a live endpoint or been exercised with mocks
   here — these need your real credentials to validate properly.

**Bottom line: nothing in here is a stub anymore** — every adapter makes
real API/SDK calls with real payload construction. But tier 3 in particular
should be treated as "written correctly, not yet proven" until you run it
against real infrastructure once.

## The data flow (what changed)

Before: `DeployConfig.artifact_path` was a string you typed by hand.
Now: `GitHubRepoSource.fetch_artifact(owner, repo, ref)` clones the actual
repo and returns a `FetchResult` whose `.local_path` becomes
`artifact_path` — see `example_usage.py` for this wired end-to-end. This is
the seam where Nakima's build/sandbox pipeline plugs in for real: once
NEIS + sandbox produce a validated build, this is what pulls it (or a
specific commit of it) into the deploy step.

## Before this touches anything real

1. Replace `InMemorySecretsBackend` with a Postgres-backed one (same
   interface — `save/load/mark_used/delete`).
2. Generate the master key once (`SecretsStore.generate_master_key()`) and
   set it as `NAKIMA_DEPLOY_SECRETS_KEY` in Render — never commit it.
3. Get real credentials for one platform and run its adapter against a real
   (ideally throwaway/staging) project first — start with Netlify or
   Vercel, since those are mock-verified and the most likely to just work.
4. For Hugging Face / GCE / GCP: budget time for a first real run to catch
   whatever the SDKs' actual runtime behavior doesn't match the docs on —
   this is normal for SDK-based integrations and expected, not a sign
   something's wrong with the approach.
5. Wire `approval_callback` to your real approval mechanism instead of the
   console stub.
6. `pip install -r requirements.txt` (or `requirements-dev.txt` to also run
   the test suite — `pytest tests/`).

## Adding a new platform

Implement `DeployAdapter`'s five methods, register it in
`adapters/__init__.py`'s `ADAPTER_REGISTRY`, done.
