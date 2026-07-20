"""Verifies a target URL actually belongs to the repository Nakima has
indexed, using GitHub's own records rather than trusting a user-typed
string. This is the binding an active-exploitation tool (a Pentest
Simulator) would require before running against a URL — see the
conversation that scoped this: DAST's existing SSRF guard
(security/dast.py) stops it from being pointed at Nakima's own internal
network, but says nothing about whether the *external* target actually
belongs to whoever's asking, which matters far more once "observational
checks" becomes "active exploitation attempts."

Three sources, each something only the repo's owner/admin controls —
discovering them requires the same GitHub token used to index the repo,
so a URL only ends up "allowed" if someone with real access to the repo
put it there:
  1. The repository's `homepage` field (Settings -> General -> Website).
  2. Its GitHub Pages URL and custom domain, if Pages is enabled (fetched
     via a direct REST call — PyGithub 2.4.0 doesn't expose a
     `get_pages()` method, only the `has_pages` flag).
  3. Deployment environment URLs recorded via the GitHub Deployments API
     — what `actions/deploy-pages` and most CD workflows populate on
     every deploy.

A target passes if its hostname exactly matches, or is a subdomain of,
any discovered hostname. This doesn't prove the human requesting the
scan is who they claim to be — it proves the URL is one GitHub has on
record for this specific repository, which is the check that actually
closes the gap: attaching an arbitrary third party's URL to your own
repo's homepage/Pages config/deployment record requires having
write/admin access to that repo, not just knowing a URL exists.
"""

import logging
from urllib.parse import urlparse

import httpx
from github import Github, GithubException

logger = logging.getLogger(__name__)

_PAGES_API_TIMEOUT = 10.0


class TargetBindingError(Exception):
    pass


class RepoTargetBinding:
    def __init__(self, repo_full_name: str, github_token: str):
        self.repo_full_name = repo_full_name
        self.github_token = github_token
        self._gh = Github(github_token)

    async def discover_allowed_hostnames(self) -> set[str]:
        try:
            repo = self._gh.get_repo(self.repo_full_name)
        except GithubException as e:
            raise TargetBindingError(f"Couldn't look up {self.repo_full_name} on GitHub: {e}") from e

        hostnames: set[str] = set()

        if repo.homepage:
            host = self._hostname(repo.homepage)
            if host:
                hostnames.add(host)

        if repo.has_pages:
            hostnames |= await self._pages_hostnames()

        try:
            for deployment in repo.get_deployments()[:20]:  # most-recent-first; capped for latency
                for status in deployment.get_statuses()[:5]:
                    url = status.environment_url or status.target_url
                    host = self._hostname(url) if url else None
                    if host:
                        hostnames.add(host)
        except GithubException as e:
            logger.warning(f"Couldn't list deployments for {self.repo_full_name}: {e}")

        return hostnames

    async def is_authorized(self, target_url: str) -> bool:
        target_host = self._hostname(target_url)
        if not target_host:
            return False
        allowed = await self.discover_allowed_hostnames()
        return any(target_host == h or target_host.endswith("." + h) for h in allowed)

    async def _pages_hostnames(self) -> set[str]:
        hostnames: set[str] = set()
        try:
            async with httpx.AsyncClient(timeout=_PAGES_API_TIMEOUT) as client:
                resp = await client.get(
                    f"https://api.github.com/repos/{self.repo_full_name}/pages",
                    headers={
                        "Authorization": f"Bearer {self.github_token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                if resp.status_code != 200:
                    # Pages API can 404 even with has_pages=True (e.g.
                    # private Pages sites the token lacks scope for) — not
                    # fatal, just nothing to add from this source.
                    return hostnames
                data = resp.json()
        except httpx.RequestError as e:
            logger.warning(f"Couldn't reach the GitHub Pages API for {self.repo_full_name}: {e}")
            return hostnames

        if data.get("html_url"):
            host = self._hostname(data["html_url"])
            if host:
                hostnames.add(host)
        cname = data.get("cname")
        if cname:
            hostnames.add(cname.lower())
        return hostnames

    def _hostname(self, url: str) -> str | None:
        try:
            host = urlparse(url).hostname
        except ValueError:
            return None
        return host.lower() if host else None
