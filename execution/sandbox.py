from pathlib import Path

import docker

from core.config import settings


class SandboxExecutor:
    def __init__(self):
        self.client = docker.from_env()
        self.image = settings.SANDBOX_IMAGE

    async def run_build(self, repo_dir: Path, commands: list) -> dict:
        return await self._run_in_container(repo_dir, commands)

    async def run_tests(self, repo_dir: Path, test_command: str) -> dict:
        return await self._run_in_container(repo_dir, [test_command])

    async def _run_in_container(self, repo_dir: Path, commands: list) -> dict:
        container = self.client.containers.run(
            self.image,
            command="tail -f /dev/null",  # keep alive so we can exec into it
            detach=True,
            volumes={str(repo_dir.resolve()): {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            mem_limit="1g",
            network_disabled=True,  # generated code shouldn't get network access during validation
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
