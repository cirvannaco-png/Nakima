"""
End-to-end example showing the real data flow: GitHub repo -> local artifact
-> deploy adapter. Run with: python example_usage.py

Part 1 (GitHubRepoSource) makes a real, live `git clone` against github.com
and will actually succeed here. Part 2 (the deploy call itself) makes a real
HTTP request to the target platform's API — that will fail in THIS sandbox
because outbound network here is allowlisted to a small set of domains that
doesn't include vercel.com/netlify.com/etc, and because the credentials
below are placeholders. Run Part 2 from an environment with real network
access and a real API token to see it actually deploy.
"""

import logging

from deploy_agent import (
    DeployAgent,
    DeployConfig,
    DeployPlan,
    GitHubRepoSource,
    InMemorySecretsBackend,
    SecretsStore,
)
from deploy_agent.adapters import ADAPTER_REGISTRY

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def console_approval_gate(plan: DeployPlan) -> bool:
    """Stand-in for your real approval flow (Slack, GitHub issue comment, etc.)."""
    print(f"\n--- APPROVAL REQUIRED ---\n{plan.summary}")
    print(f"Risk: {plan.risk.value} | Destructive: {plan.destructive} | Reversible: {plan.reversible}")
    for change in plan.changes:
        print(f"  - {change}")
    answer = input("Approve? [y/N] ").strip().lower()
    return answer == "y"


def main():
    # --- Part 1: real data flow from a repository ---
    # This actually clones a real repo — replace with your own Nakima-built
    # repo/ref once wired into the real pipeline (e.g. after NEIS + sandbox
    # build/test succeed on a roadmap item).
    print("=== Fetching real artifact from GitHub ===")
    source = GitHubRepoSource()  # set GITHUB_TOKEN env var for private repos / higher rate limit
    fetch_result = source.fetch_artifact(owner="octocat", repo="Hello-World", ref="master")
    print(f"Cloned {fetch_result.owner}/{fetch_result.repo}@{fetch_result.ref} "
          f"-> {fetch_result.local_path} (commit {fetch_result.resolved_sha[:12]})")

    # --- Part 2: secrets + agent construction ---
    import os
    from cryptography.fernet import Fernet
    os.environ.setdefault("NAKIMA_DEPLOY_SECRETS_KEY", Fernet.generate_key().decode())

    store = SecretsStore(backend=InMemorySecretsBackend())
    # Replace with real tokens to actually deploy — these placeholders will
    # fail validate()/execute() with a clean, typed auth error, which is the
    # correct behavior, not a bug.
    store.put("netlify", "default", {"api_token": "REPLACE_WITH_REAL_NETLIFY_TOKEN"})

    agent = DeployAgent(
        secrets_store=store,
        adapters=ADAPTER_REGISTRY,
        approval_callback=console_approval_gate,
        auto_approve_low_risk=False,  # flip True once you trust plan() classifications
    )

    # --- Part 3: deploy the real fetched artifact ---
    print("\n=== Attempting real deploy call (will fail without real network + real token) ===")
    netlify_config = DeployConfig(
        platform="netlify",
        project_ref="your-real-site-id",
        artifact_path=fetch_result.local_path,   # <-- the actual cloned repo, not a hardcoded path
        environment="production",
        roadmap_item_id="roadmap-042",
    )
    try:
        status = agent.run(netlify_config)
        print(f"Deploy result: {status.state.value} -> {status.live_url}")
    except Exception as exc:
        print(f"Expected in this sandbox (no network to netlify.com / placeholder token): {exc}")
    finally:
        source.cleanup(fetch_result.local_path)


if __name__ == "__main__":
    main()
