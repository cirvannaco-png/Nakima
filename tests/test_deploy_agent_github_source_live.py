"""
Live integration test against a real public GitHub repo. Unlike the other
adapter tests (which mock HTTP), this one genuinely hits github.com — it's
the one piece of the deploy pipeline's data flow we can fully verify
end-to-end in this environment. Skips (doesn't fail) if network is
unavailable, so it doesn't break CI runs without internet access.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deploy_agent.sources.github_source import GitHubRepoSource, GitCommandError


def _network_available() -> bool:
    import subprocess
    result = subprocess.run(
        ["git", "ls-remote", "https://github.com/octocat/Hello-World.git", "HEAD"],
        capture_output=True, timeout=15,
    )
    return result.returncode == 0


@pytest.mark.skipif(not _network_available(), reason="No network access to github.com")
def test_fetch_real_public_repo():
    src = GitHubRepoSource()
    result = src.fetch_artifact("octocat", "Hello-World", "master")
    try:
        assert os.path.isdir(result.local_path)
        assert len(result.resolved_sha) == 40  # full git SHA
        assert os.path.exists(os.path.join(result.local_path, "README"))
    finally:
        src.cleanup(result.local_path)
    assert not os.path.exists(result.local_path)


@pytest.mark.skipif(not _network_available(), reason="No network access to github.com")
def test_fetch_nonexistent_ref_raises_clear_error():
    src = GitHubRepoSource()
    with pytest.raises(GitCommandError):
        src.fetch_artifact("octocat", "Hello-World", "this-branch-does-not-exist-xyz")


@pytest.mark.skipif(not _network_available(), reason="No network access to github.com")
def test_token_never_appears_in_error_on_failure():
    src = GitHubRepoSource(token="super_secret_value_12345")
    try:
        src.fetch_artifact("octocat", "Hello-World", "nonexistent-branch-abc")
    except GitCommandError as e:
        assert "super_secret_value_12345" not in str(e)
        assert "super_secret_value_12345" not in str(e.command)
