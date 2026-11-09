import hashlib
import io
import tarfile
import uuid
from pathlib import Path

import pytest

from lab.result_contract import LabRunResult
from lab.runner import LabRunnerError, LabSandboxRunner
from lab.source_bundle import PinnedSourceBundle


class FakeContainer:
    id = "fake-container-id"
    status = "exited"

    def __init__(self, result: LabRunResult, exit_code: int = 0):
        self.attrs = {"State": {"Status": "exited", "ExitCode": exit_code}}
        self.result = result
        self.removed = False
        self.killed = False

    def reload(self):
        return None

    def logs(self, **kwargs):
        return b"fake runner log"

    def get_archive(self, path: str):
        assert path == "/output/result.json"
        payload = self.result.model_dump_json().encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:") as archive:
            member = tarfile.TarInfo("result.json")
            member.size = len(payload)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(payload))
        return [buffer.getvalue()], {"name": "result.json", "size": len(payload)}

    def remove(self, **kwargs):
        self.removed = True

    def kill(self):
        self.killed = True


class FakeContainers:
    def __init__(self, container: FakeContainer):
        self.container = container
        self.kwargs = None

    def run(self, **kwargs):
        self.kwargs = kwargs
        return self.container


class FakeDockerClient:
    def __init__(self, container: FakeContainer):
        self.containers = FakeContainers(container)


def _bundle(tmp_path: Path) -> PinnedSourceBundle:
    archive_path = tmp_path / "pinned-source.tar.gz"
    archive_path.write_bytes(b"trusted archive fixture")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    return PinnedSourceBundle(
        repository_full_name="example/repository",
        commit_sha="a" * 40,
        archive_path=archive_path,
        archive_sha256=digest,
        archive_size_bytes=archive_path.stat().st_size,
    )


def _valid_result(run_id: uuid.UUID) -> LabRunResult:
    return LabRunResult(
        run_id=run_id,
        commit_sha="a" * 40,
        status="no_issue_found",
        baseline_passed=True,
        full_test_suite_passed=True,
        requires_mandatory_review=False,
        duration_seconds=0.25,
    )


@pytest.mark.asyncio
async def test_runner_launches_networkless_container_with_only_readonly_archive(
    tmp_path,
):
    run_id = uuid.uuid4()
    bundle = _bundle(tmp_path)
    container = FakeContainer(_valid_result(run_id))
    client = FakeDockerClient(container)
    runner = LabSandboxRunner(docker_client=client)

    outcome = await runner.execute(
        run_id=run_id,
        bundle=bundle,
        trigger="manual",
    )

    options = client.containers.kwargs
    assert outcome.result.run_id == run_id
    assert outcome.result.commit_sha == bundle.commit_sha
    assert outcome.exit_code == 0
    assert outcome.logs == "fake runner log"
    assert container.removed is True

    assert options["network_mode"] == "none"
    assert options["read_only"] is True
    assert options["user"] == "0:0"
    assert options["cap_drop"] == ["ALL"]
    assert set(options["cap_add"]) == {"CHOWN", "SETUID", "SETGID"}
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["pids_limit"] == 128
    assert options["mem_limit"] == "2g"
    assert options["memswap_limit"] == "2g"
    assert set(options["tmpfs"]) == {"/workspace", "/output"}
    assert "mode=0700" in options["tmpfs"]["/output"]

    assert len(options["volumes"]) == 1
    archive_mount = next(iter(options["volumes"].values()))
    assert archive_mount == {"bind": "/input/source.tar.gz", "mode": "ro"}

    env = options["environment"]
    assert env["RUN_ID"] == str(run_id)
    assert env["COMMIT_SHA"] == bundle.commit_sha
    assert env["SOURCE_ARCHIVE_SHA256"] == bundle.archive_sha256
    assert env["SOURCE_ARCHIVE_PATH"] == "/input/source.tar.gz"
    assert "REPO_CLONE_URL" not in env
    assert "GITHUB_TOKEN" not in env
    assert "DATABASE_URL" not in env


@pytest.mark.asyncio
async def test_runner_rejects_modified_archive_before_container_launch(tmp_path):
    run_id = uuid.uuid4()
    bundle = _bundle(tmp_path)
    bundle.archive_path.write_bytes(b"modified archive")
    client = FakeDockerClient(FakeContainer(_valid_result(run_id)))
    runner = LabSandboxRunner(docker_client=client)

    with pytest.raises(LabRunnerError, match="digest changed"):
        await runner.execute(run_id=run_id, bundle=bundle, trigger="manual")

    assert client.containers.kwargs is None


@pytest.mark.asyncio
async def test_runner_requires_consent_before_synthetic_injection(tmp_path):
    run_id = uuid.uuid4()
    client = FakeDockerClient(FakeContainer(_valid_result(run_id)))
    runner = LabSandboxRunner(docker_client=client)

    with pytest.raises(LabRunnerError, match="consent"):
        await runner.execute(
            run_id=run_id,
            bundle=_bundle(tmp_path),
            trigger="synthetic_injection",
        )

    assert client.containers.kwargs is None


@pytest.mark.asyncio
async def test_runner_rejects_result_identity_mismatch_and_still_removes_container(tmp_path):
    run_id = uuid.uuid4()
    wrong_result = _valid_result(uuid.uuid4())
    container = FakeContainer(wrong_result)
    client = FakeDockerClient(container)
    runner = LabSandboxRunner(docker_client=client)

    with pytest.raises(LabRunnerError, match="identity"):
        await runner.execute(run_id=run_id, bundle=_bundle(tmp_path), trigger="manual")

    assert container.removed is True


@pytest.mark.asyncio
async def test_runner_requires_failed_contract_for_nonzero_exit(tmp_path):
    run_id = uuid.uuid4()
    failed_result = LabRunResult(
        run_id=run_id,
        commit_sha="a" * 40,
        status="failed",
        error_code="test_failure",
        error="suite failed",
        duration_seconds=1.0,
    )
    container = FakeContainer(failed_result, exit_code=1)
    client = FakeDockerClient(container)
    runner = LabSandboxRunner(docker_client=client)

    outcome = await runner.execute(run_id=run_id, bundle=_bundle(tmp_path), trigger="manual")

    assert outcome.exit_code == 1
    assert outcome.result.status == "failed"
    assert container.removed is True
