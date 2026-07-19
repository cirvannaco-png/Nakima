from pathlib import Path

import docker

from core.config import settings


class SandboxExecutor:
    def __init__(self):
        self.client = docker.from_env()
        self.image = settings.SANDBOX_IMAGE

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
        """
        container = self.client.containers.run(
            self.image,
            command="tail -f /dev/null",  # keep alive so we can exec into it
            detach=True,
            volumes={str(repo_dir.resolve()): {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            mem_limit="1g",
            pids_limit=256,  # caps fork bombs from generated code
            cpu_quota=100000,  # 1 CPU (cpu_period defaults to 100000us)
            network_disabled=network_disabled,
        )
        try:
            logs = ""
            for cmd in commands:
                exit_code, output = container.exec_run(cmd)
                logs += output.decode(errors="replace")
                if exit_code != 0:
                    return {"success": False, "logs": logs, "command": cmd}
            return {"success": True, "logs": logs, "command": commands[-1] if commands else ""}
        finally:
            container.stop(timeout=5)
            container.remove()
