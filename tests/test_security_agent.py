"""Regression test for the audit_dependencies sandbox bug: the original
code re-installed `safety` at runtime inside a network_disabled=True
container (safety is already baked into Dockerfile.sandbox), so the
install always failed before `safety check` ever ran. This asserts the
fixed call shape: no redundant install command, and network explicitly
re-enabled for this one trusted, non-code-executing scan.
"""

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("GITHUB_TOKEN", "ghp-test")
os.environ.setdefault("DEFAULT_AI_PROVIDER", "github")

from agents.base import AgentRequest  # noqa: E402
from agents.security_agent import SecurityAgent  # noqa: E402


async def test_audit_dependencies_no_requirements_file(tmp_path):
    agent = SecurityAgent()
    resp = await agent.execute(AgentRequest(action="audit_dependencies", context={"repo_dir": str(tmp_path)}))
    assert resp.success is True
    assert resp.result["vulnerabilities"] == []
    assert resp.result["note"] == "no requirements.txt found"


async def test_audit_dependencies_runs_safety_directly_with_network_enabled(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.0.0\n")

    fake_result = {
        "success": True,
        "logs": '[["requests", "<2.31.0", "2.0.0", "CVE-FAKE"]]',
        "command": "safety check --json",
    }

    with patch("agents.security_agent.SandboxExecutor") as MockExecutor:
        instance = MockExecutor.return_value
        instance.run_build = AsyncMock(return_value=fake_result)

        agent = SecurityAgent()
        resp = await agent.execute(AgentRequest(action="audit_dependencies", context={"repo_dir": str(tmp_path)}))

    # The bug: a "pip install safety" command was prepended, which always
    # failed under the sandbox's default network_disabled=True. The fix:
    # exactly one command (safety is already in the image), and network
    # explicitly re-enabled for this call.
    instance.run_build.assert_awaited_once_with(tmp_path, ["safety check --json"], network_disabled=False)
    assert resp.success is True
    assert resp.result["vulnerabilities"] == [
        {"package": "requests", "installed": "2.0.0", "vulnerability": "CVE-FAKE"}
    ]
