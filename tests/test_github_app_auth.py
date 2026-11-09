import pytest

from githubapp.auth import GitHubAppAuth, GitHubAppAuthError


class _Response:
    status_code = 201
    text = ""

    def __init__(self, token):
        self._token = token

    def json(self):
        return {"token": self._token}


class _AsyncClient:
    def __init__(self, tokens):
        self.tokens = iter(tokens)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(next(self.tokens))


@pytest.mark.asyncio
async def test_installation_tokens_are_scoped_by_repository_and_permissions(monkeypatch):
    import githubapp.auth as auth_module

    client = _AsyncClient(["repo-101-write", "repo-202-read", "repo-101-read"])
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda timeout: client)

    auth = GitHubAppAuth.__new__(GitHubAppAuth)
    auth._token_cache = {}
    auth._generate_jwt = lambda: "app-jwt"

    write_permissions = {"contents": "write", "pull_requests": "write"}
    read_permissions = {"contents": "read", "metadata": "read"}

    first = await auth.get_repository_installation_token(7, 101, write_permissions)
    cached = await auth.get_repository_installation_token(7, 101, dict(reversed(list(write_permissions.items()))))
    second_repo = await auth.get_repository_installation_token(7, 202, read_permissions)
    different_permissions = await auth.get_repository_installation_token(7, 101, read_permissions)

    assert first == cached == "repo-101-write"
    assert second_repo == "repo-202-read"
    assert different_permissions == "repo-101-read"
    assert len(client.calls) == 3

    first_payload = client.calls[0][1]["json"]
    assert first_payload["repository_ids"] == [101]
    assert first_payload["permissions"] == write_permissions
    assert client.calls[1][1]["json"]["repository_ids"] == [202]
    assert client.calls[2][1]["json"]["permissions"] == read_permissions


@pytest.mark.asyncio
async def test_repository_scoped_token_rejects_invalid_scope():
    auth = GitHubAppAuth.__new__(GitHubAppAuth)
    auth._token_cache = {}

    with pytest.raises(GitHubAppAuthError):
        await auth.get_repository_installation_token(7, 0, {"contents": "read"})

    with pytest.raises(GitHubAppAuthError):
        await auth.get_repository_installation_token(7, 101, {})
