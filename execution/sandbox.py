import asyncio
import logging
from pathlib import Path

import docker

from core.config import settings

logger = logging.getLogger(__name__)


class SandboxExecutor:
    """Runs commands in isolated Docker containers.

    Docker availability is checked lazily on the first _run_in_container call
    — constructing a SandboxExecutor never fails even when no Docker daemon is
    reachable (e.g. Render's native Python environment, CI without DinD).
    When Docker is unavailable each call returns a structured failure dict
    with a clear message so ValidationPipeline can degrade gracefully and
    _fail_task() gets a human-readable error instead of a raw DockerException.
    """

    def __init__(self):
        self._client: docker.DockerClient | None = None
        self.image = settings.SANDBOX_IMAGE

    def _get_client(self) -> docker.DockerClient:
        """Lazily initialise the Docker client.

        Raises docker.errors.DockerException if the daemon is not reachable.
        Called only at the start of an actual container operation so that
        importing this module and constructing SandboxExecutor never fail.
        """
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    async def run_build(self, repo_dir: Path, commands: list, network_disabled: bool = True) -> dict:
        return await self._run_in_container(repo_dir, commands, network_disabled=network_disabled)

    async def run_tests(self, repo_dir: Path, test_command: str) -> dict:
        return await self._run_in_container(repo_dir, [test_command])

    async def _run_in_container(self, repo_dir: Path, commands: list, network_disabled: bool = True) -> dict:
        """Runs `commands` inside a short-lived, resource-capped container.

        `network_disabled` defaults to True because most callers here are
        executing AI-generated code (build/test/lint), which must never get
        network access. The one legitimate exception is a trusted,
        non-generated dependency-audit scan (see agents/security_agent.py),
        which needs network to reach the vulnerability feed and passes
        network_disabled=False explicitly — it never executes repo code.

        All Docker SDK calls are synchronous blocking I/O. They run in a
        thread-pool worker via asyncio.to_thread() so they never stall the
        FastAPI event loop.
        """
        try:
            client = self._get_client()
        except docker.errors.DockerException as exc:
            logger.warning("Docker daemon not available; sandbox execution skipped: %s", exc)
            return {
                "success": False,
                "logs": (
                    f"Docker daemon not available on this host: {exc}\n"
                    "Sandbox validation requires a running Docker daemon. "
                    "Enable Docker-in-Docker (DinD) for the deployment environment, "
                    "or run Nakima on a host with Docker installed and accessible."
                ),
                "command": commands[0] if commands else "",
            }

        def _start_container():
            return client.containers.run(
                self.image,
                command="tail -f /dev/null",  # keep alive so we can exec into it
                detach=True,
                volumes={str(repo_dir.resolve()): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                mem_limit="1g",
                pids_limit=256,  # caps fork bombs from generated code
                cpu_quota=100000,  # 1 CPU (cpu_period defaults to 100000µs)
                network_disabled=network_disabled,
            )

        container = await asyncio.to_thread(_start_container)
        try:
            logs = ""
            for cmd in commands:
                exit_code, output = await asyncio.to_thread(container.exec_run, cmd)
                logs += output.decode(errors="replace")
                if exit_code != 0:
                    return {"success": False, "logs": logs, "command": cmd}
            return {"success": True, "logs": logs, "command": commands[-1] if commands else ""}
        finally:
            await asyncio.to_thread(container.stop, timeout=5)
            await asyncio.to_thread(container.remove)
