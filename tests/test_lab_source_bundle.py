import hashlib
import io
import tarfile
from pathlib import Path

import httpx
import pytest

from lab.source_bundle import (
    PinnedSourceBundle,
    SourceBundleError,
    extract_verified_source_bundle,
    fetch_pinned_github_bundle,
)


COMMIT_SHA = "a" * 40


def _tar_bytes(member_name="repo-root/src/main.py", content=b"print('hello')", *, symlink=False):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        root = tarfile.TarInfo("repo-root/")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)

        if symlink:
            link = tarfile.TarInfo(member_name)
            link.type = tarfile.SYMTYPE
            link.linkname = "../../../../etc/passwd"
            archive.addfile(link)
        else:
            member = tarfile.TarInfo(member_name)
            member.size = len(content)
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(content))
    return payload.getvalue()


@pytest.mark.asyncio
async def test_fetch_pinned_bundle_checks_commit_and_never_forwards_token_to_codeload(tmp_path):
    archive_bytes = _tar_bytes()
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if request.url.host == "api.github.com" and request.url.path.endswith(f"/commits/{COMMIT_SHA}"):
            return httpx.Response(200, json={"sha": COMMIT_SHA})
        if request.url.host == "api.github.com" and request.url.path.endswith(f"/tarball/{COMMIT_SHA}"):
            return httpx.Response(
                302,
                headers={"location": (f"https://codeload.github.com/owner/repo/legacy.tar.gz/{COMMIT_SHA}")},
            )
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=archive_bytes)
        return httpx.Response(404)

    bundle_path = tmp_path / "source.tar.gz"
    bundle = await fetch_pinned_github_bundle(
        "owner/repo",
        COMMIT_SHA,
        "test-repository-read-token",
        bundle_path,
        transport=httpx.MockTransport(handler),
    )

    assert bundle.commit_sha == COMMIT_SHA
    assert bundle.archive_path == bundle_path
    assert bundle.archive_sha256 == hashlib.sha256(archive_bytes).hexdigest()
    assert bundle.archive_size_bytes == len(archive_bytes)
    api_requests = [request for request in seen_requests if request.url.host == "api.github.com"]
    archive_requests = [request for request in seen_requests if request.url.host == "codeload.github.com"]
    assert api_requests
    assert all(request.headers.get("authorization") == "Bearer test-repository-read-token" for request in api_requests)
    assert len(archive_requests) == 1
    assert "authorization" not in archive_requests[0].headers


@pytest.mark.asyncio
async def test_fetch_rejects_commit_mismatch_before_archive_request(tmp_path):
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path.endswith(f"/commits/{COMMIT_SHA}"):
            return httpx.Response(200, json={"sha": "b" * 40})
        return httpx.Response(302, headers={"location": "https://codeload.github.com/owner/repo/archive.tar.gz"})

    with pytest.raises(SourceBundleError, match="did not confirm"):
        await fetch_pinned_github_bundle(
            "owner/repo",
            COMMIT_SHA,
            "test-token",
            tmp_path / "source.tar.gz",
            transport=httpx.MockTransport(handler),
        )
    assert not any(path.endswith(f"/tarball/{COMMIT_SHA}") for path in seen_paths)
    assert not (tmp_path / "source.tar.gz").exists()


@pytest.mark.asyncio
async def test_fetch_rejects_archive_redirect_to_untrusted_host(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/commits/{COMMIT_SHA}"):
            return httpx.Response(200, json={"sha": COMMIT_SHA})
        return httpx.Response(302, headers={"location": "https://attacker.example/archive.tar.gz"})

    with pytest.raises(SourceBundleError, match="untrusted"):
        await fetch_pinned_github_bundle(
            "owner/repo",
            COMMIT_SHA,
            "test-token",
            tmp_path / "source.tar.gz",
            transport=httpx.MockTransport(handler),
        )
    assert not (tmp_path / "source.tar.gz").exists()


def _bundle_from_bytes(tmp_path: Path, content: bytes) -> PinnedSourceBundle:
    archive_path = tmp_path / "fixture.tar.gz"
    archive_path.write_bytes(content)
    return PinnedSourceBundle(
        repository_full_name="owner/repo",
        commit_sha=COMMIT_SHA,
        archive_path=archive_path,
        archive_sha256=hashlib.sha256(content).hexdigest(),
        archive_size_bytes=len(content),
    )


def test_extract_verified_bundle_strips_single_archive_root_and_preserves_executable_mode(tmp_path):
    archive = _bundle_from_bytes(tmp_path, _tar_bytes(content=b"print('hello')"))
    destination = tmp_path / "workspace"

    extracted = extract_verified_source_bundle(archive, destination)

    entrypoint = extracted / "src" / "main.py"
    assert entrypoint.read_bytes() == b"print('hello')"
    assert entrypoint.stat().st_mode & 0o111


def test_extract_rejects_archive_digest_mismatch(tmp_path):
    archive = _bundle_from_bytes(tmp_path, _tar_bytes())
    archive.archive_path.write_bytes(b"tampered")

    with pytest.raises(SourceBundleError, match="SHA-256"):
        extract_verified_source_bundle(archive, tmp_path / "workspace")
    assert not (tmp_path / "workspace").exists()

def test_extract_rejects_path_traversal_without_creating_workspace(tmp_path):
    archive = _bundle_from_bytes(
        tmp_path,
        _tar_bytes(member_name="repo-root/../../outside.txt", content=b"owned"),
    )

    with pytest.raises(SourceBundleError, match="unsafe path"):
        extract_verified_source_bundle(archive, tmp_path / "workspace")

    assert not (tmp_path / "workspace").exists()
    assert not (tmp_path / "outside.txt").exists()


def test_extract_rejects_symlinks_without_creating_workspace(tmp_path):
    archive = _bundle_from_bytes(tmp_path, _tar_bytes(symlink=True))

    with pytest.raises(SourceBundleError, match="link or special"):
        extract_verified_source_bundle(archive, tmp_path / "workspace")

    assert not (tmp_path / "workspace").exists()


def test_extract_rejects_multiple_archive_roots(tmp_path):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for root_name in ("root-a", "root-b"):
            root = tarfile.TarInfo(f"{root_name}/")
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
    bundle = _bundle_from_bytes(tmp_path, payload.getvalue())

    with pytest.raises(SourceBundleError, match="exactly one root"):
        extract_verified_source_bundle(bundle, tmp_path / "workspace")



@pytest.mark.asyncio
async def test_fetch_rejects_codeload_path_for_another_repository(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/commits/{COMMIT_SHA}"):
            return httpx.Response(200, json={"sha": COMMIT_SHA})
        return httpx.Response(
            302,
            headers={"location": (f"https://codeload.github.com/attacker/other/legacy.tar.gz/{COMMIT_SHA}")},
        )

    with pytest.raises(SourceBundleError, match="untrusted"):
        await fetch_pinned_github_bundle(
            "owner/repo",
            COMMIT_SHA,
            "test-token",
            tmp_path / "source.tar.gz",
            transport=httpx.MockTransport(handler),
        )
    assert not (tmp_path / "source.tar.gz").exists()
