import asyncio
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import git
from github import Github  # PyGithub — safe now that our local package is githubapp, not github


class RepositoryEngine:
    def __init__(self, repo_url: str, github_token: str | None = None):
        self.repo_url = repo_url
        self.github_token = github_token
        self.gh = Github(github_token) if github_token else None
        self.working_dir = Path(f"/tmp/nakima_repos/{self._repo_name()}")
        self.repo: git.Repo | None = None

    def _repo_name(self) -> str:
        """Use owner__repo so that user1/myapp and user2/myapp never share
        the same working directory and clobber each other's clones."""
        parts = self.repo_url.rstrip("/").replace(".git", "").split("/")
        # URL is https://github.com/<owner>/<repo> — take the last two segments.
        return "__".join(parts[-2:]) if len(parts) >= 2 else parts[-1]

    def _authenticated_url(self) -> str:
        """Injects the installation token into the clone URL so git can push
        without a separate credential helper. GitHub App installation tokens
        work as the password with any non-empty username over HTTPS."""
        if not self.github_token:
            return self.repo_url
        parts = urlsplit(self.repo_url)
        netloc = f"x-access-token:{self.github_token}@{parts.netloc}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    async def clone(self):
        """Clone the repo, replacing any existing working directory.

        gitpython's clone_from does real network I/O and must not run on
        the asyncio event loop thread — it would block all other requests
        for the duration of the clone. asyncio.to_thread() offloads it to
        a thread-pool worker.
        """
        if self.working_dir.exists():
            shutil.rmtree(self.working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        url = self._authenticated_url()
        self.repo = await asyncio.to_thread(git.Repo.clone_from, url, self.working_dir)
        return self.repo

    async def checkout_branch(self, branch_name: str):
        def _checkout():
            if branch_name not in self.repo.heads:
                new_branch = self.repo.create_head(branch_name)
                new_branch.checkout()
            else:
                self.repo.heads[branch_name].checkout()
            return self.repo

        self.repo = await asyncio.to_thread(_checkout)
        return self.repo

    async def commit_changes(self, message: str, files: list[str]):
        if not files:
            raise ValueError("commit_changes called with no files to commit")

        def _commit():
            self.repo.index.add(files)
            return self.repo.index.commit(message)

        return await asyncio.to_thread(_commit)

    async def push_branch(self, branch_name: str):
        def _push():
            origin = self.repo.remote(name="origin")
            # Re-point origin at the authenticated URL in case the token was
            # refreshed since clone().
            origin.set_url(self._authenticated_url())
            origin.push(refspec=f"{branch_name}:{branch_name}")

        await asyncio.to_thread(_push)

    async def get_file_history(self, file_path: str) -> list[dict]:
        def _history():
            return list(self.repo.iter_commits(paths=file_path))

        commits = await asyncio.to_thread(_history)
        return [{"hash": c.hexsha, "message": c.message, "author": str(c.author)} for c in commits]

    def get_dependency_graph(self) -> dict:
        """Build a dependency graph from whichever manifest files are
        present. Supports package.json (Node), requirements.txt (Python),
        and pyproject.toml (Python/PEP 517). All three can coexist in the
        same repo."""
        graph: dict = {"nodes": [], "edges": []}
        graph["nodes"].append("root")

        # --- Node.js ---
        package_json = self.working_dir / "package.json"
        if package_json.exists():
            try:
                with open(package_json) as f:
                    pkg = json.load(f)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                for dep in deps:
                    if dep not in graph["nodes"]:
                        graph["nodes"].append(dep)
                    graph["edges"].append(("root", dep))
            except Exception:
                pass

        # --- Python: requirements.txt ---
        requirements_txt = self.working_dir / "requirements.txt"
        if requirements_txt.exists():
            try:
                for raw_line in requirements_txt.read_text().splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # Strip version specifiers, extras, markers
                    dep = line.split("[")[0].split("==")[0].split(">=")[0].split("<=")[0].split("!=")[0].strip()
                    if dep and dep not in graph["nodes"]:
                        graph["nodes"].append(dep)
                        graph["edges"].append(("root", dep))
            except Exception:
                pass

        # --- Python: pyproject.toml ---
        pyproject = self.working_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib  # stdlib in Python 3.11+
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore[no-redef]
                except ImportError:
                    tomllib = None  # type: ignore[assignment]
            if tomllib:
                try:
                    with open(pyproject, "rb") as f:
                        data = tomllib.load(f)
                    # PEP 517 style: [project] dependencies is a list of strings.
                    pep517_deps = data.get("project", {}).get("dependencies", [])
                    # Poetry style: [tool.poetry.dependencies] is a dict of {name: version}.
                    poetry_deps = list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
                    deps = pep517_deps + poetry_deps
                    for raw_dep in deps:
                        dep = str(raw_dep).split("[")[0].split(">=")[0].split("==")[0].strip()
                        if dep and dep != "python" and dep not in graph["nodes"]:
                            graph["nodes"].append(dep)
                            graph["edges"].append(("root", dep))
                except Exception:
                    pass

        return graph
