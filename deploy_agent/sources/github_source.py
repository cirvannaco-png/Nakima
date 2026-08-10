"""
GitHubRepoSource: the actual data flow from a repository into the deploy
pipeline. This is real, live-tested code — it runs an actual `git clone`
against github.com, which is what turns `DeployConfig.artifact_path` from a
manually-typed path into something populated automatically from the repo
Nakima just built.

Flow:
  GitHubRepoSource.fetch_artifact(owner, repo, ref)
    -> git clone --depth 1 --branch {ref} https://github.com/{owner}/{repo}.git
    -> resolve the checked-out commit SHA (for reproducibility/audit)
    -> return the local path, ready to hand to DeployConfig.artifact_path

Uses plain `git` via subprocess rather than the GitHub REST API on purpose:
the API has a 60 req/hr unauthenticated rate limit that's easy to exhaust
(confirmed live — see README), while `git clone` over HTTPS has no such
ceiling for public repos. The REST API is used only for the lightweight
`list_repo_files` path where a full clone would be wasteful, and that path
degrades gracefully (raises a clear, typed error) if rate-limited.

Private repos: pass a token; it's injected into the clone URL the same way
`https://x-access-token:{token}@github.com/...` works for GitHub Apps and PATs.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import requests

logger = logging.getLogger("nakima.deploy_agent.sources.github")

GITHUB_API = "https://api.github.com"


class GitHubSourceError(Exception):
    pass


class GitCommandError(GitHubSourceError):
    def __init__(self, command: list[str], returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git command failed ({returncode}): {' '.join(command)}\n{stderr}")


@dataclass
class FetchResult:
    local_path: str
    resolved_sha: str
    owner: str
    repo: str
    ref: str


class GitHubRepoSource:
    def __init__(self, token: str | None = None):
        """`token`: a GitHub PAT (or GitHub App installation token) with repo
        access. Required for private repos; optional for public ones."""
        self._token = token or os.environ.get("GITHUB_TOKEN")

    def _clone_url(self, owner: str, repo: str) -> str:
        """Return a credential-free URL.

        Authentication is supplied through GIT_HTTP_EXTRAHEADER in
        fetch_artifact(). Keeping the token out of argv prevents it from
        appearing in process listings, command errors, or audit logs.
        """
        return f"https://github.com/{owner}/{repo}.git"

    def fetch_artifact(self, owner: str, repo: str, ref: str = "main", dest_dir: str | None = None) -> FetchResult:
        """Shallow-clone the repo at `ref` into `dest_dir` (a fresh temp dir
        if not given). Returns the local path plus the resolved commit SHA —
        this is what makes the resulting deploy traceable back to an exact
        commit, not just a moving branch name."""
        dest_dir = dest_dir or tempfile.mkdtemp(prefix=f"nakima-deploy-{repo}-")
        if os.listdir(dest_dir):
            raise GitHubSourceError(f"dest_dir {dest_dir} is not empty — refusing to clone into it")

        cmd = ["git", "clone", "--depth", "1", "--branch", ref, self._clone_url(owner, repo), dest_dir]
        env = os.environ.copy()
        if self._token:
            env["GIT_HTTP_EXTRAHEADER"] = f"Authorization: Bearer {self._token}"
        logger.info("Cloning %s/%s@%s", owner, repo, ref)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0:
            shutil.rmtree(dest_dir, ignore_errors=True)
            stderr = result.stderr.replace(self._token, "***") if self._token else result.stderr
            raise GitCommandError(cmd, result.returncode, stderr)

        try:
            sha = self._resolve_local_sha(dest_dir)
        except Exception:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise
        logger.info("Cloned %s/%s@%s -> %s (%d entries)", owner, repo, ref, sha[:12], len(os.listdir(dest_dir)))
        return FetchResult(local_path=dest_dir, resolved_sha=sha, owner=owner, repo=repo, ref=ref)

    def _resolve_local_sha(self, repo_path: str) -> str:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            raise GitCommandError(["git", "rev-parse", "HEAD"], result.returncode, result.stderr)
        return result.stdout.strip()

    def list_repo_files(self, owner: str, repo: str, ref: str = "main", path: str = "") -> list[dict]:
        """Lightweight directory listing via the REST API, without a full
        clone — useful for a quick validate() check (e.g. 'does a package.json
        exist at the root'). Subject to the API's rate limit; callers should
        treat GitHubSourceError here as non-fatal and fall back to
        fetch_artifact if they need certainty."""
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        resp = requests.get(url, headers=headers, params={"ref": ref}, timeout=15)
        if resp.status_code == 403 or (resp.status_code == 200 and "rate limit" in resp.text.lower()):
            raise GitHubSourceError(
                f"GitHub API rate-limited listing {owner}/{repo}/{path}. "
                f"Set GITHUB_TOKEN to raise the 60/hr unauthenticated limit, "
                f"or use fetch_artifact() which doesn't hit this limit."
            )
        if resp.status_code == 404:
            raise GitHubSourceError(f"Not found: {owner}/{repo}/{path}@{ref}")
        resp.raise_for_status()
        return resp.json()

    def cleanup(self, local_path: str) -> None:
        shutil.rmtree(local_path, ignore_errors=True)
