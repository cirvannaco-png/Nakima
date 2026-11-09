"""Persist verified GitHub App installation lifecycle events.

This service is intentionally independent of the workflow token path. GitHub
installation events are signed provider webhooks; they do not need a repo
automation token merely to update the local tenant mapping.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.provider_installation import ProviderInstallation
from models.repository import Repository


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _external_id(value: object, label: str) -> str:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Webhook is missing a valid {label}")
    result = str(value).strip()
    if not result or len(result) > 255:
        raise ValueError(f"Webhook is missing a valid {label}")
    return result


def _github_repo_id(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Repository payload is missing a valid numeric id")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Repository payload is missing a valid numeric id") from exc
    if result <= 0:
        raise ValueError("Repository payload is missing a valid numeric id")
    return result


def _clear_lab_consent(repository: Repository) -> None:
    repository.sandbox_lab_opt_in = False
    repository.sandbox_lab_consented_at = None
    repository.sandbox_lab_consent_actor_id = None
    repository.sandbox_lab_consent_version = None


async def _get_or_create_installation(
    session: AsyncSession,
    installation_payload: dict,
) -> ProviderInstallation:
    external_id = _external_id(installation_payload.get("id"), "installation id")
    result = await session.execute(
        select(ProviderInstallation).where(
            ProviderInstallation.provider == "github",
            ProviderInstallation.external_installation_id == external_id,
        )
    )
    installation = result.scalar_one_or_none()

    account = installation_payload.get("account") or {}
    account_id = account.get("id")
    account_external_id = _external_id(account_id, "account id") if account_id is not None else None
    account_login = account.get("login")
    account_type = account.get("type")

    if installation is None:
        installation = ProviderInstallation(
            provider="github",
            external_installation_id=external_id,
            account_external_id=account_external_id,
            account_login=str(account_login)[:255] if account_login else None,
            account_type=str(account_type)[:32] if account_type else None,
        )
        session.add(installation)
        await session.flush()
        return installation

    if account_external_id is not None:
        installation.account_external_id = account_external_id
    if account_login:
        installation.account_login = str(account_login)[:255]
    if account_type:
        installation.account_type = str(account_type)[:32]
    return installation


async def _upsert_repository(
    session: AsyncSession,
    installation: ProviderInstallation,
    repository_payload: dict,
) -> Repository:
    github_repo_id = _github_repo_id(repository_payload.get("id"))
    full_name = repository_payload.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip() or len(full_name) > 200:
        raise ValueError("Repository payload is missing a valid full_name")
    full_name = full_name.strip()

    result = await session.execute(select(Repository).where(Repository.github_repo_id == github_repo_id))
    repository = result.scalar_one_or_none()

    if repository is None:
        result = await session.execute(select(Repository).where(Repository.full_name == full_name))
        repository = result.scalar_one_or_none()

    if repository is not None and repository.github_repo_id not in (None, github_repo_id):
        raise ValueError(
            f"Repository identity conflict for {full_name}: local row is bound to a different GitHub repository id"
        )

    if repository is None:
        repository = Repository(full_name=full_name, github_repo_id=github_repo_id)
        session.add(repository)
        await session.flush()

    if repository.full_name != full_name:
        collision = await session.execute(
            select(Repository).where(
                Repository.full_name == full_name,
                Repository.id != repository.id,
            )
        )
        if collision.scalar_one_or_none() is not None:
            raise ValueError(f"Repository rename would collide with an existing local repository: {full_name}")
        repository.full_name = full_name

    if repository.provider_installation_id != installation.id:
        _clear_lab_consent(repository)
        repository.provider_installation_id = installation.id

    repository.github_repo_id = github_repo_id
    return repository


async def _remove_repository(
    session: AsyncSession,
    installation: ProviderInstallation,
    repository_payload: dict,
) -> bool:
    github_repo_id = _github_repo_id(repository_payload.get("id"))
    result = await session.execute(select(Repository).where(Repository.github_repo_id == github_repo_id))
    repository = result.scalar_one_or_none()
    if repository is None or repository.provider_installation_id != installation.id:
        return False

    repository.provider_installation_id = None
    _clear_lab_consent(repository)
    return True


async def sync_github_installation_event(
    session: AsyncSession,
    event_type: str,
    payload: dict,
) -> dict:
    """Apply an installation lifecycle event inside the caller's transaction."""
    if event_type not in {"installation", "installation_repositories"}:
        raise ValueError(f"Unsupported installation event type: {event_type}")

    installation_payload = payload.get("installation")
    if not isinstance(installation_payload, dict):
        raise ValueError("Webhook payload is missing its installation object")

    action = payload.get("action")
    if not isinstance(action, str):
        raise ValueError("Webhook payload is missing its installation action")

    installation_actions = {"created", "unsuspend", "new_permissions_accepted", "suspend", "deleted"}
    repository_actions = {"added", "removed"}
    if event_type == "installation" and action not in installation_actions:
        return {"status": "ignored", "action": action, "repositories_added": 0, "repositories_removed": 0}
    if event_type == "installation_repositories" and action not in repository_actions:
        return {"status": "ignored", "action": action, "repositories_added": 0, "repositories_removed": 0}

    if event_type == "installation_repositories" and action == "removed":
        external_id = _external_id(installation_payload.get("id"), "installation id")
        result = await session.execute(
            select(ProviderInstallation).where(
                ProviderInstallation.provider == "github",
                ProviderInstallation.external_installation_id == external_id,
            )
        )
        installation = result.scalar_one_or_none()
        if installation is None:
            # Out-of-order removal events must not manufacture an active
            # installation/tenant that was never registered locally.
            return {"status": "ignored", "action": action, "repositories_added": 0, "repositories_removed": 0}
    else:
        installation = await _get_or_create_installation(session, installation_payload)

    if event_type == "installation":
        if action in {"created", "unsuspend", "new_permissions_accepted"}:
            installation.is_active = True
            installation.deactivated_at = None
        elif action in {"suspend", "deleted"}:
            installation.is_active = False
            installation.deactivated_at = _now_utc_naive()
            result = await session.execute(
                select(Repository).where(Repository.provider_installation_id == installation.id)
            )
            for repository in result.scalars():
                _clear_lab_consent(repository)
                if action == "deleted":
                    repository.provider_installation_id = None

        repository_items = payload.get("repositories") or []
        added = 0
        for item in repository_items:
            await _upsert_repository(session, installation, item)
            added += 1
        return {"status": "synced", "action": action, "repositories_added": added, "repositories_removed": 0}

    if action == "added":
        items = payload.get("repositories_added") or []
        for item in items:
            await _upsert_repository(session, installation, item)
        return {"status": "synced", "action": action, "repositories_added": len(items), "repositories_removed": 0}

    items = payload.get("repositories_removed") or []
    removed = 0
    for item in items:
        removed += int(await _remove_repository(session, installation, item))
    return {"status": "synced", "action": action, "repositories_added": 0, "repositories_removed": removed}
