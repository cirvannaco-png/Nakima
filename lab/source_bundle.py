"""Trusted-host acquisition and safe extraction of pinned GitHub source bundles.

The sandbox receives only an immutable archive plus its SHA-256 digest. It
never receives a repository URL, GitHub token, or provider credential.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx


GITHUB_API = "https://api.github.com"
ALLOWED_ARCHIVE_REDIRECT_HOST = "codeload.github.com"
DEFAULT_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_UNPACKED_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 100_000
_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_REPOSITORY_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class SourceBundleError(RuntimeError):
    """A pinned source archive could not be acquired or safely extracted."""


@dataclass(frozen=True, slots=True)
class PinnedSourceBundle:
    repository_full_name: str
    commit_sha: str
    archive_path: Path
    archive_sha256: str
    archive_size_bytes: int


def _validate_repository_name(repository_full_name: str) -> tuple[str, str]:
    if not isinstance(repository_full_name, str):
        raise SourceBundleError("Repository name is invalid")
    parts = repository_full_name.split("/")
    if len(parts) != 2 or any(not _REPOSITORY_SEGMENT.fullmatch(part) for part in parts):
        raise SourceBundleError("Repository name must be a valid owner/repository pair")
    if any(part in {".", ".."} for part in parts):
        raise SourceBundleError("Repository name contains an invalid path segment")
    return parts[0], parts[1]


def _validate_commit_sha(commit_sha: str) -> str:
    if not isinstance(commit_sha, str) or not _COMMIT_SHA.fullmatch(commit_sha):
        raise SourceBundleError("A full 40- or 64-character commit SHA is required")
    return commit_sha


def _validate_token(token: str) -> str:
    if (
        not isinstance(token, str)
        or not token
        or token != token.strip()
        or any(character.isspace() for character in token)
        or len(token) > 8192
    ):
        raise SourceBundleError("A valid repository-scoped read-only token is required")
    return token


def _trusted_archive_redirect(location: str) -> str:
    parsed = urlparse(location)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourceBundleError("GitHub returned an invalid archive redirect") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_ARCHIVE_REDIRECT_HOST
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise SourceBundleError("GitHub returned an untrusted archive redirect")
    return location


async def _stream_to_file(
    client: httpx.AsyncClient,
    url: str,
    target_path: Path,
    headers: dict[str, str],
    max_bytes: int,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    try:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > max_bytes:
                        raise SourceBundleError("Source archive exceeds the configured size limit")
                except ValueError as exc:
                    raise SourceBundleError("Source archive has an invalid content length") from exc

            with target_path.open("xb") as target:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise SourceBundleError("Source archive exceeds the configured size limit")
                    digest.update(chunk)
                    target.write(chunk)
    except SourceBundleError:
        target_path.unlink(missing_ok=True)
        raise
    except (httpx.HTTPError, OSError) as exc:
        target_path.unlink(missing_ok=True)
        raise SourceBundleError("Could not download the pinned source archive") from exc

    if total == 0:
        target_path.unlink(missing_ok=True)
        raise SourceBundleError("GitHub returned an empty source archive")
    return digest.hexdigest(), total


async def fetch_pinned_github_bundle(
    repository_full_name: str,
    commit_sha: str,
    repository_scoped_read_token: str,
    destination_path: Path,
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PinnedSourceBundle:
    """Fetch exactly one commit with a single-repository contents:read token.

    The token is sent only to api.github.com. GitHub's codeload redirect is
    separately validated and fetched without an Authorization header. The
    caller is responsible for minting a token restricted to this repository.
    """
    owner, repository = _validate_repository_name(repository_full_name)
    commit_sha = _validate_commit_sha(commit_sha)
    token = _validate_token(repository_scoped_read_token)
    if max_archive_bytes <= 0:
        raise SourceBundleError("Archive size limit must be positive")

    destination_path = Path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise SourceBundleError("Archive destination already exists")

    encoded_owner = quote(owner, safe="")
    encoded_repository = quote(repository, safe="")
    encoded_sha = quote(commit_sha, safe="")
    api_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    timeout = httpx.Timeout(20.0, connect=5.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            commit_response = await client.get(
                f"{GITHUB_API}/repos/{encoded_owner}/{encoded_repository}/commits/{encoded_sha}",
                headers=api_headers,
            )
            commit_response.raise_for_status()
            commit_document = commit_response.json()
            if not isinstance(commit_document, dict) or commit_document.get("sha") != commit_sha:
                raise SourceBundleError("GitHub did not confirm the requested immutable commit")

            archive_url = f"{GITHUB_API}/repos/{encoded_owner}/{encoded_repository}/tarball/{encoded_sha}"
            async with client.stream("GET", archive_url, headers=api_headers) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise SourceBundleError("GitHub archive redirect did not include a location")
                    trusted_location = _trusted_archive_redirect(location)
                elif response.status_code == 200:
                    response.raise_for_status()
                    digest = hashlib.sha256()
                    total = 0
                    content_length = response.headers.get("content-length")
                    if content_length is not None and int(content_length) > max_archive_bytes:
                        raise SourceBundleError("Source archive exceeds the configured size limit")
                    with destination_path.open("xb") as target:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > max_archive_bytes:
                                raise SourceBundleError("Source archive exceeds the configured size limit")
                            digest.update(chunk)
                            target.write(chunk)
                    if total == 0:
                        raise SourceBundleError("GitHub returned an empty source archive")
                    return PinnedSourceBundle(
                        repository_full_name=repository_full_name,
                        commit_sha=commit_sha,
                        archive_path=destination_path,
                        archive_sha256=digest.hexdigest(),
                        archive_size_bytes=total,
                    )
                else:
                    response.raise_for_status()
                    raise SourceBundleError("GitHub returned an unexpected archive response")

            # Do not forward api_headers here. The token must never reach
            # codeload or any archive redirect destination.
            digest, total = await _stream_to_file(
                client,
                trusted_location,
                destination_path,
                {"Accept": "application/octet-stream"},
                max_archive_bytes,
            )
            return PinnedSourceBundle(
                repository_full_name=repository_full_name,
                commit_sha=commit_sha,
                archive_path=destination_path,
                archive_sha256=digest,
                archive_size_bytes=total,
            )
    except SourceBundleError:
        destination_path.unlink(missing_ok=True)
        raise
    except (httpx.HTTPError, ValueError, OSError) as exc:
        destination_path.unlink(missing_ok=True)
        raise SourceBundleError("GitHub source bundle acquisition failed") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_verified_source_bundle(
    bundle: PinnedSourceBundle,
    destination: Path,
    *,
    max_unpacked_bytes: int = DEFAULT_MAX_UNPACKED_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
) -> Path:
    """Verify the archive digest and extract regular files beneath one root.

    Symlinks, hardlinks, devices, FIFOs, path traversal, duplicate names and
    path-type collisions are rejected. Repositories using symlinks therefore
    fail closed until a separately tested safe-link extraction policy exists.
    """
    archive_path = Path(bundle.archive_path)
    destination = Path(destination)
    if not archive_path.is_file():
        raise SourceBundleError("Source archive is missing")
    if _sha256_file(archive_path) != bundle.archive_sha256:
        raise SourceBundleError("Source archive SHA-256 does not match the trusted-host manifest")
    if max_unpacked_bytes <= 0 or max_members <= 0:
        raise SourceBundleError("Extraction limits must be positive")
    if destination.exists():
        raise SourceBundleError("Extraction destination already exists")

    created_destination = False
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if not members or len(members) > max_members:
                raise SourceBundleError("Source archive has an invalid member count")

            planned: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
            roots: set[str] = set()
            seen: dict[tuple[str, ...], str] = {}
            total_unpacked = 0

            for member in members:
                if "\\" in member.name or member.name.startswith("/"):
                    raise SourceBundleError("Source archive contains an unsafe path")
                raw_parts = member.name.split("/")
                if raw_parts and raw_parts[-1] == "":
                    raw_parts.pop()
                if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
                    raise SourceBundleError("Source archive contains an unsafe path")
                if len(raw_parts) == 1:
                    roots.add(raw_parts[0])
                    if not member.isdir():
                        raise SourceBundleError("Source archive root must be a directory")
                    continue

                roots.add(raw_parts[0])
                relative_parts = tuple(raw_parts[1:])
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    raise SourceBundleError("Source archive contains a link or special file")
                if not (member.isdir() or member.isfile()) or member.issparse():
                    raise SourceBundleError("Source archive contains an unsupported member type")

                member_type = "dir" if member.isdir() else "file"
                if relative_parts in seen:
                    raise SourceBundleError("Source archive contains duplicate paths")
                seen[relative_parts] = member_type
                if member.isfile():
                    if member.size < 0:
                        raise SourceBundleError("Source archive contains an invalid file size")
                    total_unpacked += member.size
                    if total_unpacked > max_unpacked_bytes:
                        raise SourceBundleError("Source archive exceeds the unpacked size limit")
                planned.append((member, relative_parts))

            if len(roots) != 1:
                raise SourceBundleError("Source archive must contain exactly one root directory")

            for relative_parts, member_type in seen.items():
                for length in range(1, len(relative_parts)):
                    parent_type = seen.get(relative_parts[:length])
                    if parent_type == "file":
                        raise SourceBundleError("Source archive path collides with a regular file")
                if member_type == "file" and any(
                    other[: len(relative_parts)] == relative_parts and len(other) > len(relative_parts)
                    for other in seen
                ):
                    raise SourceBundleError("Source archive file collides with a child path")

            destination.mkdir(parents=True, exist_ok=False)
            created_destination = True
            for member, relative_parts in planned:
                target = destination.joinpath(*relative_parts)
                resolved_target = target.resolve()
                if destination.resolve() not in resolved_target.parents:
                    raise SourceBundleError("Source archive path escapes the extraction directory")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                source_file = archive.extractfile(member)
                if source_file is None:
                    raise SourceBundleError("Source archive file could not be read")
                with source_file, target.open("xb") as output:
                    while chunk := source_file.read(1024 * 1024):
                        output.write(chunk)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)

            return destination
    except SourceBundleError:
        if created_destination:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    except (OSError, tarfile.TarError, ValueError) as exc:
        if created_destination:
            shutil.rmtree(destination, ignore_errors=True)
        raise SourceBundleError("Source archive could not be safely extracted") from exc
