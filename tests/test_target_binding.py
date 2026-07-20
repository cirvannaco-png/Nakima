"""Tests for security/target_binding.py. PyGithub's Github/Repository and
the direct Pages REST call are both mocked — no real GitHub API calls —
but the hostname-discovery and matching logic itself is exercised for
real.
"""

import httpx
import pytest
from github import GithubException

import security.target_binding as binding_mod
from security.target_binding import RepoTargetBinding, TargetBindingError


class _FakeStatus:
    def __init__(self, environment_url=None, target_url=None):
        self.environment_url = environment_url
        self.target_url = target_url


class _FakeDeployment:
    def __init__(self, statuses):
        self._statuses = statuses

    def get_statuses(self):
        return self._statuses


class _FakeRepo:
    def __init__(self, homepage=None, has_pages=False, deployments=None, raise_on_deployments=False):
        self.homepage = homepage
        self.has_pages = has_pages
        self._deployments = deployments or []
        self._raise_on_deployments = raise_on_deployments

    def get_deployments(self):
        if self._raise_on_deployments:
            raise GithubException(500, "boom", None)
        return self._deployments


class _FakeGithub:
    def __init__(self, repo=None, raise_not_found=False):
        self._repo = repo
        self._raise_not_found = raise_not_found

    def get_repo(self, full_name):
        if self._raise_not_found:
            raise GithubException(404, "Not Found", None)
        return self._repo


def _make_binding(monkeypatch, repo, pages_response=None):
    monkeypatch.setattr(binding_mod, "Github", lambda token: _FakeGithub(repo=repo))
    if pages_response is not None:

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url, headers=None):
                return pages_response

        monkeypatch.setattr(binding_mod.httpx, "AsyncClient", lambda **kw: _FakeClient())
    return RepoTargetBinding("kelson/test-repo", "fake-token")


# ---------------------------------------------------------------------------


async def test_repo_not_found_raises_target_binding_error(monkeypatch):
    monkeypatch.setattr(binding_mod, "Github", lambda token: _FakeGithub(raise_not_found=True))
    binding = RepoTargetBinding("kelson/nonexistent", "fake-token")
    with pytest.raises(TargetBindingError):
        await binding.discover_allowed_hostnames()


async def test_homepage_field_is_discovered(monkeypatch):
    repo = _FakeRepo(homepage="https://myapp.example.com/")
    binding = _make_binding(monkeypatch, repo)
    hostnames = await binding.discover_allowed_hostnames()
    assert "myapp.example.com" in hostnames


async def test_no_homepage_no_pages_no_deployments_is_empty(monkeypatch):
    repo = _FakeRepo()
    binding = _make_binding(monkeypatch, repo)
    hostnames = await binding.discover_allowed_hostnames()
    assert hostnames == set()


async def test_deployment_environment_url_is_discovered(monkeypatch):
    repo = _FakeRepo(deployments=[_FakeDeployment([_FakeStatus(environment_url="https://staging.example.com/")])])
    binding = _make_binding(monkeypatch, repo)
    hostnames = await binding.discover_allowed_hostnames()
    assert "staging.example.com" in hostnames


async def test_deployment_falls_back_to_target_url(monkeypatch):
    repo = _FakeRepo(deployments=[_FakeDeployment([_FakeStatus(target_url="https://preview.example.com/")])])
    binding = _make_binding(monkeypatch, repo)
    hostnames = await binding.discover_allowed_hostnames()
    assert "preview.example.com" in hostnames


async def test_deployment_lookup_failure_is_not_fatal(monkeypatch):
    repo = _FakeRepo(homepage="https://myapp.example.com", raise_on_deployments=True)
    binding = _make_binding(monkeypatch, repo)
    hostnames = await binding.discover_allowed_hostnames()
    assert hostnames == {"myapp.example.com"}


async def test_pages_html_url_and_cname_discovered(monkeypatch):
    repo = _FakeRepo(has_pages=True)
    pages_response = httpx.Response(
        200,
        json={"html_url": "https://kelson.github.io/nakima/", "cname": "Docs.Example.com"},
        request=httpx.Request("GET", "https://api.github.com/repos/kelson/test-repo/pages"),
    )
    binding = _make_binding(monkeypatch, repo, pages_response=pages_response)
    hostnames = await binding.discover_allowed_hostnames()
    assert "kelson.github.io" in hostnames
    assert "docs.example.com" in hostnames  # lowercased


async def test_pages_api_404_is_not_fatal(monkeypatch):
    repo = _FakeRepo(has_pages=True)
    pages_response = httpx.Response(
        404, json={}, request=httpx.Request("GET", "https://api.github.com/repos/kelson/test-repo/pages")
    )
    binding = _make_binding(monkeypatch, repo, pages_response=pages_response)
    hostnames = await binding.discover_allowed_hostnames()
    assert hostnames == set()


# ---------------------------------------------------------------------------
# is_authorized
# ---------------------------------------------------------------------------


async def test_is_authorized_exact_host_match(monkeypatch):
    repo = _FakeRepo(homepage="https://myapp.example.com")
    binding = _make_binding(monkeypatch, repo)
    assert await binding.is_authorized("https://myapp.example.com/health") is True


async def test_is_authorized_subdomain_match(monkeypatch):
    repo = _FakeRepo(homepage="https://example.com")
    binding = _make_binding(monkeypatch, repo)
    assert await binding.is_authorized("https://api.example.com/") is True


async def test_is_authorized_rejects_unrelated_host(monkeypatch):
    repo = _FakeRepo(homepage="https://myapp.example.com")
    binding = _make_binding(monkeypatch, repo)
    assert await binding.is_authorized("https://totally-different-site.com/") is False


async def test_is_authorized_does_not_treat_suffix_as_subdomain(monkeypatch):
    # "evilexample.com" containing "example.com" as a raw substring must
    # NOT be treated as a subdomain match — only a real "*.example.com" or
    # exact "example.com" counts.
    repo = _FakeRepo(homepage="https://example.com")
    binding = _make_binding(monkeypatch, repo)
    assert await binding.is_authorized("https://evilexample.com/") is False


async def test_is_authorized_rejects_invalid_url(monkeypatch):
    repo = _FakeRepo(homepage="https://myapp.example.com")
    binding = _make_binding(monkeypatch, repo)
    assert await binding.is_authorized("not-a-url") is False
