"""Host-side, network-isolated Lab container execution.

The container receives exactly one read-only source archive and an expected
SHA-256 digest. It receives no provider token, clone URL, database URL, Docker
socket, host source directory, or outbound network access.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from lab.result_contract import LabRunResult
from lab.source_bundle import PinnedSourceBundle


class LabRunnerError(RuntimeError):
    """The isolated Lab container could not produce a trusted result."""


class LabRunnerTimeout(LabRunnerError):
    """The isolated Lab container exceeded its wall-clock limit."""


@dataclass(frozen=True, slots=True)
class LabContainerExecution:
    container_id: str
    image: str
    exit_code: int
    result: LabRunResult
    logs: str


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_result_archive(container: Any, max_bytes: int) -> bytes:
    try:
        stream, stat = container.get_archive("/workspace/result.json")
    except (DockerException, NotFound) as exc:
        raise LabRunnerError("Lab container did not produce the required result file") from exc

    declared_size = stat.get("size")
    if isinstance(declared_size, int) and (declared_size <= 0 or declared_size > max_bytes):
        raise LabRunnerError("Lab result file has an invalid size")

    payload = bytearray()
    for chunk in stream:
        payload.extend(chunk)
        if len(payload) > max_bytes * 2:
            raise LabRunnerError("Lab result archive exceeds the configured size limit")

    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
            if len(members) != 1:
                raise LabRunnerError("Lab result archive must contain exactly one file")
            member = members[0]
            if member.name not in {"result.json", "./result.json"} or not member.isfile():
                raise LabRunnerError("Lab result archive contains an unexpected path or file type")
            if member.size <= 0 or member.size > max_bytes:
                raise LabRunnerError("Lab result JSON exceeds the configured size limit")
            source = archive.extractfile(member)
            if source is None:
                raise LabRunnerError("Lab result JSON could not be read")
            content = source.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise LabRunnerError("Lab result JSON exceeds the configured size limit")
            return content
    except LabRunnerError:
        raise
    except (OSError, tarfile.TarError, ValueError) as exc:
        raise LabRunnerError("Lab container returned a malformed result archive") from exc


class LabSandboxRunner:
    """Runs a prebuilt Lab image with one immutable input archive and tmpfs output."""

    def __init__(
        self,
        *,
        image: str = "nakima-lab-runner:latest",
        timeout_seconds: int = 900,
        memory_limit: str = "2g",
        pids_limit: int = 128,
        result_max_bytes: int = 1_000_000,
        docker_client: Any | None = None,
    ) -> None:
        if not image or len(image) > 255:
            raise ValueError("A valid Lab runner image name is required")
        if not 30 <= timeout_seconds <= 3600:
            raise ValueError("Lab runner timeout must be between 30 and 3600 seconds")
        if not 16 <= pids_limit <= 1024:
            raise ValueError("Lab runner pids limit is outside the allowed range")
        if not 1024 <= result_max_bytes <= 4_000_000:
            raise ValueError("Lab result size limit is outside the allowed range")

        self.image = image
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.pids_limit = pids_limit
        self.result_max_bytes = result_max_bytes
        self._docker_client = docker_client

    def _client(self):
        if self._docker_client is None:
            try:
                self._docker_client = docker.from_env(timeout=10)
            except DockerException as exc:
                raise LabRunnerError("Docker is unavailable to the trusted Lab host") from exc
        return self._docker_client

    def _execute_sync(
        self,
        *,
        run_id: uuid.UUID,
        bundle: PinnedSourceBundle,
        trigger: str,
        synthetic_injection_consent_verified: bool,
    ) -> LabContainerExecution:
        allowed_triggers = {"ci_failure", "cve_scan", "synthetic_injection", "manual"}
        if trigger not in allowed_triggers:
            raise LabRunnerError("Unsupported Lab trigger")
        if trigger == "synthetic_injection" and not synthetic_injection_consent_verified:
            raise LabRunnerError("Synthetic injection requires verified repository consent")
        if trigger != "synthetic_injection" and synthetic_injection_consent_verified:
            raise LabRunnerError("Synthetic injection consent flag is invalid for this trigger")

        if not bundle.archive_path.is_file():
            raise LabRunnerError("Pinned source archive does not exist")
        if bundle.archive_size_bytes <= 0 or bundle.archive_size_bytes > 100 * 1024 * 1024:
            raise LabRunnerError("Pinned source archive has an invalid size")
        if bundle.commit_sha != bundle.commit_sha.lower() or len(bundle.commit_sha) not in {40, 64}:
            raise LabRunnerError("Pinned source bundle commit SHA is invalid")
        if len(bundle.archive_sha256) != 64 or any(c not in "0123456789abcdef" for c in bundle.archive_sha256):
            raise LabRunnerError("Pinned source bundle digest is invalid")
        if _archive_sha256(bundle.archive_path) != bundle.archive_sha256:
            raise LabRunnerError("Pinned source archive digest changed before container launch")

        environment = {
            "RUN_ID": str(run_id),
            "COMMIT_SHA": bundle.commit_sha,
            "TRIGGER": trigger,
            "SOURCE_ARCHIVE_PATH": "/input/source.tar.gz",
            "SOURCE_ARCHIVE_SHA256": bundle.archive_sha256,
        }
        if synthetic_injection_consent_verified:
            environment["SYNTHETIC_INJECTION_CONSENT_VERIFIED"] = "true"

        container = None
        started = time.monotonic()
        try:
            container = self._client().containers.run(
                image=self.image,
                command=None,
                detach=True,
                auto_remove=False,
                init=True,
                user="10001:10001",
                working_dir="/workspace",
                environment=environment,
                volumes={
                    str(bundle.archive_path.resolve()): {
                        "bind": "/input/source.tar.gz",
                        "mode": "ro",
                    }
                },
                network_mode="none",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=self.pids_limit,
                mem_limit=self.memory_limit,
                memswap_limit=self.memory_limit,
                nano_cpus=2_000_000_000,
                tmpfs={
                    "/workspace": (
                        "rw,noexec,nosuid,nodev,size=768m,"
                        "uid=10001,gid=10001,mode=0700"
                    )
                },
                labels={
                    "com.nakima.lab": "true",
                    "com.nakima.lab.run-id": str(run_id),
                    "com.nakima.lab.commit-sha": bundle.commit_sha,
                    "com.nakima.lab.archive-sha256": bundle.archive_sha256,
                },
            )

            deadline = started + self.timeout_seconds
            while time.monotonic() < deadline:
                container.reload()
                state = container.attrs.get("State", {})
                status = state.get("Status", container.status)
                if status in {"exited", "dead"}:
                    break
                time.sleep(0.5)
            else:
                try:
                    container.kill()
                except (DockerException, NotFound):
                    pass
                raise LabRunnerTimeout("Lab container exceeded its wall-clock limit")

            state = container.attrs.get("State", {})
            exit_code = state.get("ExitCode")
            if not isinstance(exit_code, int):
                raise LabRunnerError("Docker did not report a valid container exit code")

            try:
                logs_bytes = container.logs(stdout=True, stderr=True, tail=2000)
            except (DockerException, NotFound):
                logs_bytes = b""
            logs = logs_bytes.decode("utf-8", errors="replace")[-100_000:]

            result_bytes = _read_result_archive(container, self.result_max_bytes)
            try:
                result = LabRunResult.model_validate_json(result_bytes)
            except Exception as exc:
                raise LabRunnerError("Lab container result did not satisfy schema version 1.0") from exc

            if result.run_id != run_id or result.commit_sha != bundle.commit_sha:
                raise LabRunnerError("Lab result identity does not match the requested run and pinned commit")
            if exit_code != 0 and result.status != "failed":
                raise LabRunnerError("Non-zero Lab container exit must return a failed result")
            if exit_code == 0 and result.status == "failed":
                raise LabRunnerError("Lab container returned a failed result with a zero exit code")

            return LabContainerExecution(
                container_id=container.id,
                image=self.image,
                exit_code=exit_code,
                result=result,
                logs=logs,
            )
        except LabRunnerError:
            raise
        except (DockerException, NotFound, OSError) as exc:
            raise LabRunnerError("Isolated Lab container execution failed") from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True, v=True)
                except (DockerException, NotFound):
                    pass

    async def execute(
        self,
        *,
        run_id: uuid.UUID,
        bundle: PinnedSourceBundle,
        trigger: str,
        synthetic_injection_consent_verified: bool = False,
    ) -> LabContainerExecution:
        """Execute the synchronous Docker client outside the async event loop."""
        return await asyncio.to_thread(
            self._execute_sync,
            run_id=run_id,
            bundle=bundle,
            trigger=trigger,
            synthetic_injection_consent_verified=synthetic_injection_consent_verified,
        )
