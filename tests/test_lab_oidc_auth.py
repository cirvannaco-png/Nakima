import base64
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from lab.auth import InvalidLabToken, LabOIDCNotConfigured, OIDCVerifier


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _identity_config(**overrides):
    values = {
        "LAB_OIDC_ISSUER": "https://identity.example.test/",
        "LAB_OIDC_AUDIENCE": "nakima-lab-api",
        "LAB_OIDC_JWKS_URL": "https://identity.example.test/.well-known/jwks.json",
        "LAB_OIDC_JWKS_CACHE_SECONDS": 300,
        "LAB_OIDC_CLOCK_SKEW_SECONDS": 0,
        "ENVIRONMENT": "test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "lab-test-key",
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }
    return private_key, jwks


class StubJWKSVerifier(OIDCVerifier):
    def __init__(self, config, document):
        super().__init__(config)
        self.document = document
        self.fetch_count = 0

    async def _fetch_jwks(self, jwks_url: str) -> dict:
        self.fetch_count += 1
        return self.document


def _token(
    private_key,
    *,
    issuer="https://identity.example.test/",
    audience="nakima-lab-api",
    subject="user-123",
    exp=None,
):
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": exp if exp is not None else now + 300,
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "lab-test-key"})


@pytest.mark.asyncio
async def test_oidc_verifier_accepts_valid_signature_and_claims(signing_material):
    private_key, jwks = signing_material
    verifier = StubJWKSVerifier(_identity_config(), jwks)

    principal = await verifier.verify(_token(private_key))

    assert principal.issuer == "https://identity.example.test/"
    assert principal.subject == "user-123"


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_wrong_issuer(signing_material):
    private_key, jwks = signing_material
    verifier = StubJWKSVerifier(_identity_config(), jwks)

    with pytest.raises(InvalidLabToken):
        await verifier.verify(_token(private_key, issuer="https://attacker.example.test/"))


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_wrong_audience(signing_material):
    private_key, jwks = signing_material
    verifier = StubJWKSVerifier(_identity_config(), jwks)

    with pytest.raises(InvalidLabToken):
        await verifier.verify(_token(private_key, audience="other-api"))


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_expired_token(signing_material):
    private_key, jwks = signing_material
    verifier = StubJWKSVerifier(_identity_config(), jwks)

    with pytest.raises(InvalidLabToken):
        await verifier.verify(_token(private_key, exp=int(time.time()) - 60))


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_unknown_kid(signing_material):
    private_key, jwks = signing_material
    verifier = StubJWKSVerifier(_identity_config(), jwks)
    token = jwt.encode(
        {
            "iss": "https://identity.example.test/",
            "aud": "nakima-lab-api",
            "sub": "user-123",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "unknown-key"},
    )

    with pytest.raises(InvalidLabToken):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_unsupported_algorithm(signing_material):
    private_key, jwks = signing_material
    verifier = StubJWKSVerifier(_identity_config(), jwks)
    token = jwt.encode(
        {
            "iss": "https://identity.example.test/",
            "aud": "nakima-lab-api",
            "sub": "user-123",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        "not-a-real-signing-key",
        algorithm="HS256",
        headers={"kid": "lab-test-key"},
    )

    with pytest.raises(InvalidLabToken):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_oidc_verifier_requires_complete_configuration(signing_material):
    private_key, jwks = signing_material
    config = _identity_config(LAB_OIDC_JWKS_URL=None)
    verifier = StubJWKSVerifier(config, jwks)

    with pytest.raises(LabOIDCNotConfigured):
        await verifier.verify(_token(private_key))


@pytest.mark.asyncio
async def test_oidc_verifier_rejects_non_https_jwks_endpoint(signing_material):
    private_key, jwks = signing_material
    config = _identity_config(LAB_OIDC_JWKS_URL="http://identity.example.test/keys")
    verifier = StubJWKSVerifier(config, jwks)

    with pytest.raises(LabOIDCNotConfigured):
        await verifier.verify(_token(private_key))


@pytest.mark.asyncio
async def test_oidc_verifier_caches_jwks_document(signing_material):
    private_key, jwks = signing_material
    verifier = StubJWKSVerifier(_identity_config(), jwks)

    await verifier.verify(_token(private_key, subject="first"))
    await verifier.verify(_token(private_key, subject="second"))

    assert verifier.fetch_count == 1
