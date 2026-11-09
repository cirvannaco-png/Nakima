from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import settings


@dataclass(frozen=True, slots=True)
class LabPrincipal:
    issuer: str
    subject: str


class LabOIDCNotConfigured(RuntimeError):
    pass


class InvalidLabToken(RuntimeError):
    pass


class LabIdentityProviderUnavailable(RuntimeError):
    pass


class OIDCVerifier:
    """Validates OIDC JWTs against a cached, explicitly configured JWKS."""

    ALLOWED_ALGORITHMS = {"RS256", "ES256"}

    def __init__(self, config=settings):
        self.config = config
        self._jwks: dict | None = None
        self._jwks_expires_at = 0.0
        self._lock = asyncio.Lock()

    def _configuration(self) -> tuple[str, str, str]:
        issuer = self.config.LAB_OIDC_ISSUER
        audience = self.config.LAB_OIDC_AUDIENCE
        jwks_url = self.config.LAB_OIDC_JWKS_URL
        if not issuer or not audience or not jwks_url:
            raise LabOIDCNotConfigured("Lab OIDC is not fully configured")

        issuer_parsed = urlparse(issuer)
        parsed = urlparse(jwks_url)
        local_http_allowed = (
            self.config.ENVIRONMENT != "production"
            and parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        local_issuer_http_allowed = (
            self.config.ENVIRONMENT != "production"
            and issuer_parsed.scheme == "http"
            and issuer_parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if issuer_parsed.scheme != "https" and not local_issuer_http_allowed:
            raise LabOIDCNotConfigured("The configured OIDC issuer must use HTTPS")
        if parsed.scheme != "https" and not local_http_allowed:
            raise LabOIDCNotConfigured("The configured OIDC JWKS endpoint must use HTTPS")
        if parsed.username or parsed.password or not parsed.hostname:
            raise LabOIDCNotConfigured("The configured OIDC JWKS endpoint is invalid")
        return issuer, audience, jwks_url

    async def _fetch_jwks(self, jwks_url: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                response = await client.get(
                    jwks_url,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LabIdentityProviderUnavailable("Could not retrieve OIDC signing keys") from exc
        if not isinstance(document, dict) or not isinstance(document.get("keys"), list) or not document["keys"]:
            raise LabIdentityProviderUnavailable("OIDC JWKS document is malformed")
        return document

    async def _get_jwks(self, jwks_url: str, force_refresh: bool = False) -> dict:
        now = time.monotonic()
        if not force_refresh and self._jwks is not None and self._jwks_expires_at > now:
            return self._jwks

        async with self._lock:
            now = time.monotonic()
            if not force_refresh and self._jwks is not None and self._jwks_expires_at > now:
                return self._jwks
            document = await self._fetch_jwks(jwks_url)
            ttl = int(self.config.LAB_OIDC_JWKS_CACHE_SECONDS)
            self._jwks = document
            self._jwks_expires_at = time.monotonic() + ttl
            return document

    async def verify(self, token: str) -> LabPrincipal:
        issuer, audience, jwks_url = self._configuration()
        if not token or len(token) > 16_384:
            raise InvalidLabToken("Bearer token is empty or too large")

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidLabToken("Bearer token header is invalid") from exc

        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in self.ALLOWED_ALGORITHMS or not isinstance(key_id, str) or not key_id:
            raise InvalidLabToken("Bearer token uses an unsupported algorithm or key identifier")

        jwks_document = await self._get_jwks(jwks_url)
        try:
            jwk_set = jwt.PyJWKSet.from_dict(jwks_document)
            candidates = [key for key in jwk_set.keys if key.key_id == key_id]
            if not candidates:
                # Permit provider key rotation without waiting for the whole
                # cache TTL, but never fall back to a different key.
                jwks_document = await self._get_jwks(jwks_url, force_refresh=True)
                jwk_set = jwt.PyJWKSet.from_dict(jwks_document)
                candidates = [key for key in jwk_set.keys if key.key_id == key_id]
            if len(candidates) != 1:
                raise InvalidLabToken("Bearer token signing key is missing or ambiguous")
            signing_key = candidates[0]
            if signing_key.algorithm_name and signing_key.algorithm_name != algorithm:
                raise InvalidLabToken("Bearer token algorithm does not match its signing key")

            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                issuer=issuer,
                audience=audience,
                leeway=int(self.config.LAB_OIDC_CLOCK_SKEW_SECONDS),
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
        except InvalidLabToken:
            raise
        except jwt.PyJWTError as exc:
            raise InvalidLabToken("Bearer token failed OIDC validation") from exc

        subject = claims.get("sub")
        claim_issuer = claims.get("iss")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise InvalidLabToken("OIDC subject is invalid")
        if claim_issuer != issuer:
            raise InvalidLabToken("OIDC issuer mismatch")
        return LabPrincipal(issuer=issuer, subject=subject)


oidc_verifier = OIDCVerifier()
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_lab_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> LabPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid OIDC bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await oidc_verifier.verify(credentials.credentials)
    except LabOIDCNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lab identity provider is not configured",
        ) from exc
    except LabIdentityProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lab identity provider is temporarily unavailable",
        ) from exc
    except InvalidLabToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OIDC bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
