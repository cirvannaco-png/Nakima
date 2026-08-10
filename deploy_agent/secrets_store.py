"""
Encrypted-at-rest credential store for deploy platforms.

Design:
- Values are encrypted with Fernet (symmetric, authenticated) before hitting Postgres.
- The Fernet key itself is NEVER stored in the DB — it comes from an env var
  (Render env var in your current setup) so a DB dump alone never leaks tokens.
- Adapters never call this module directly. Only the orchestrator does, and
  only immediately before constructing an adapter instance — decrypted
  credentials should live in memory as briefly as possible.

Swap `InMemorySecretsBackend` for a real Postgres-backed implementation
(same interface) once you wire this into Nakima's actual DB layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SecretsStoreError(Exception):
    pass


class MissingMasterKeyError(SecretsStoreError):
    pass


class CredentialNotFoundError(SecretsStoreError):
    pass


@dataclass
class StoredCredential:
    platform: str
    label: str                     # e.g. "prod", "cirvanna-project"
    encrypted_value: bytes
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = None


class SecretsStore:
    """
    Fernet-backed secrets store. Values in: plaintext dict of credential
    fields (e.g. {"api_token": "..."}) serialized to bytes before encryption.
    """

    MASTER_KEY_ENV = "NAKIMA_DEPLOY_SECRETS_KEY"

    def __init__(self, backend: "SecretsBackend", master_key: Optional[str] = None):
        key = master_key or os.environ.get(self.MASTER_KEY_ENV)
        if not key:
            raise MissingMasterKeyError(
                f"Set {self.MASTER_KEY_ENV} (generate with Fernet.generate_key()) "
                "before starting the deploy agent."
            )
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        self._backend = backend

    @staticmethod
    def generate_master_key() -> str:
        """Run once, store the result as NAKIMA_DEPLOY_SECRETS_KEY in Render."""
        return Fernet.generate_key().decode()

    def put(self, platform: str, label: str, fields: dict[str, str]) -> None:
        import json
        raw = json.dumps(fields).encode("utf-8")
        encrypted = self._fernet.encrypt(raw)
        self._backend.save(StoredCredential(platform=platform, label=label, encrypted_value=encrypted))

    def get(self, platform: str, label: str = "default") -> dict[str, str]:
        import json
        record = self._backend.load(platform, label)
        if record is None:
            raise CredentialNotFoundError(f"No credential stored for platform={platform} label={label}")
        try:
            raw = self._fernet.decrypt(record.encrypted_value)
        except InvalidToken as exc:
            raise SecretsStoreError(
                f"Failed to decrypt credential for {platform}/{label} — "
                "wrong master key or corrupted record."
            ) from exc
        self._backend.mark_used(platform, label)
        return json.loads(raw.decode("utf-8"))

    def delete(self, platform: str, label: str = "default") -> None:
        self._backend.delete(platform, label)


class SecretsBackend:
    """Storage backend interface. Implement against Postgres for production."""

    def save(self, credential: StoredCredential) -> None:
        raise NotImplementedError

    def load(self, platform: str, label: str) -> Optional[StoredCredential]:
        raise NotImplementedError

    def mark_used(self, platform: str, label: str) -> None:
        raise NotImplementedError

    def delete(self, platform: str, label: str) -> None:
        raise NotImplementedError


class InMemorySecretsBackend(SecretsBackend):
    """Dev/test backend. Do not use in production — process restart loses everything."""

    def __init__(self):
        self._store: dict[tuple[str, str], StoredCredential] = {}

    def save(self, credential: StoredCredential) -> None:
        self._store[(credential.platform, credential.label)] = credential

    def load(self, platform: str, label: str) -> Optional[StoredCredential]:
        return self._store.get((platform, label))

    def mark_used(self, platform: str, label: str) -> None:
        key = (platform, label)
        if key in self._store:
            self._store[key].last_used_at = datetime.now(timezone.utc)

    def delete(self, platform: str, label: str) -> None:
        self._store.pop((platform, label), None)
