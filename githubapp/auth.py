"""
GitHub App authentication: JWT generation + installation access token exchange.

Bugs fixed from the original scaffold:
  1. `settings.GITHUB_PRIVATE_key` (lowercase typo) -> `settings.GITHUB_PRIVATE_KEY`.
     This attribute didn't exist on Settings at all, so every call would have
     raised AttributeError before ever reaching GitHub.
  2. `serialization.load_ssh_private_key(...)` -> `load_pem_private_key(...)`.
     GitHub App private keys are PKCS#1 RSA keys in PEM format (the .pem file
     you download once from the App's settings page). They are NOT OpenSSH
     format keys, so load_ssh_private_key would throw a ValueError on any
     real GitHub App key, every time.
  3. Installation tokens were being re-fetched from GitHub on every single
     call with no caching. GitHub installation tokens are valid for 1 hour;
     added an in-memory cache with expiry so we're not making a network
     round-trip to GitHub on every webhook delivery.
"""

import time

import httpx
import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from core.config import settings


class GitHubAppAuthError(Exception):
    pass


class GitHubAppAuth:
    """Manages GitHub App authentication: JWT generation and installation token exchange."""

    def __init__(self):
        self.app_id = settings.GITHUB_APP_ID
        if not self.app_id:
            raise GitHubAppAuthError("GITHUB_APP_ID is not configured. Set it in your .env or environment.")
        self._private_key_pem = self._load_private_key()
        # installation_id -> {"token": str, "expires_at": float (unix ts)}
        self._token_cache: dict[int, dict[str, float | str]] = {}

    def _load_private_key(self) -> str:
        if settings.GITHUB_PRIVATE_KEY:
            return settings.GITHUB_PRIVATE_KEY
        key_path = settings.GITHUB_PRIVATE_KEY_PATH
        if not key_path:
            raise GitHubAppAuthError(
                "GitHub App private key not configured. Set GITHUB_PRIVATE_KEY "
                "(raw PEM contents) or GITHUB_PRIVATE_KEY_PATH (path to the .pem "
                "file downloaded from your GitHub App settings)."
            )
        with open(key_path) as f:
            return f.read()

    def _generate_jwt(self) -> str:
        """Generate the short-lived App JWT used to authenticate as the App itself
        (as opposed to a specific installation)."""
        now = int(time.time())
        payload = {
            "iat": now - 60,  # backdated 60s to tolerate clock drift, per GitHub's docs
            "exp": now + 600,  # GitHub caps this at 10 minutes
            "iss": self.app_id,
        }
        try:
            private_key = serialization.load_pem_private_key(
                self._private_key_pem.encode(), password=None, backend=default_backend()
            )
        except ValueError as e:
            raise GitHubAppAuthError(
                "Could not parse the GitHub App private key as PEM. Make sure you're "
                "using the .pem file downloaded from the App's settings page, not a "
                "converted or SSH-format key."
            ) from e
        return jwt.encode(payload, private_key, algorithm="RS256")

    async def get_installation_token(self, installation_id: int, force_refresh: bool = False) -> str:
        """Exchanges (or reuses a cached) JWT for an installation access token."""
        cached = self._token_cache.get(installation_id)
        if cached and not force_refresh and cached["expires_at"] > time.time() + 30:
            return str(cached["token"])

        jwt_token = self._generate_jwt()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if resp.status_code != 201:
                raise GitHubAppAuthError(
                    f"Failed to get installation token for installation {installation_id}: "
                    f"{resp.status_code} {resp.text}"
                )
            data = resp.json()

        # GitHub returns "expires_at" as an ISO8601 string; token is valid for 1 hour.
        self._token_cache[installation_id] = {
            "token": data["token"],
            "expires_at": time.time() + 3600 - 60,  # shave a minute off for safety
        }
        return data["token"]


class _LazyGitHubAppAuth:
    """Defer GitHubAppAuth() construction until the first attribute access.

    Importing this module used to instantiate GitHubAppAuth() at import time,
    which fails hard when GITHUB_APP_ID or the private key are unset — that
    made `from githubapp.app import router` (and therefore `create_app()`)
    impossible to import in tests, CI, or before the app is fully configured.
    """

    _inner = None

    def _get(self):
        if self._inner is None:
            self._inner = GitHubAppAuth()
        return self._inner

    def __getattr__(self, name):
        return getattr(self._get(), name)


github_auth = _LazyGitHubAppAuth()
