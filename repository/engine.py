import shutil
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import git
from github import Github  # PyGithub — safe now that our local package is githubapp, not github


class RepositoryEngine:
    def __init__(self, repo_url: str, github_token: Optional[str] = None):
        self.repo_url = repo_url
        self.github_token = github_token
        self.gh = Github(github_token) if github_token else None
        self.working_dir = Path(f"/tmp/nakima_repos/{self._repo_name()}")
        self.repo: Optional[git.Repo] = None

    def _repo_name(self) -> str:
        return self.repo_url.rstrip("/").split("/")[-1].replace(".git", "")

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
        if self.working_dir.exists():
            shutil.rmtree(self.working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.repo = git.Repo.clone_from(self._authenticated_url(), self.working_dir)
        return self.repo

    async def checkout_branch(self, branch_name: str):
        if branch_name not in self.repo.heads:
            new_branch = self.repo.create_head(branch_name)
            new_branch.checkout()
        else:
            self.repo.heads[branch_name].checkout()
        return self.repo

    async def commit_changes(self, message: str, files: List[str]):
        if not files:
            raise ValueError("commit_changes called with no files to commit")
        self.repo.index.add(files)
        return self.repo.index.commit(message)

    async def push_branch(self, branch_name: str):
        origin = self.repo.remote(name="origin")
        # Re-point origin at the authenticated URL in case the token was
        # refreshed since clone().
        origin.set_url(self._authenticated_url())
        origin.push(refspec=f"{branch_name}:{branch_name}")

    async def get_file_history(self, file_path: str) -> List[Dict]:
        commits = list(self.repo.iter_commits(paths=file_path))
        return [{"hash": c.hexsha, "message": c.message, "author": str(c.author)} for c in commits]

    def get_dependency_graph(self) -> Dict:
        graph: Dict = {"nodes": [], "edges": []}
        package_json = self.working_dir / "package.json"
        if package_json.exists():
            import json

            with open(package_json) as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            graph["nodes"].append("root")
            for dep in deps:
                graph["nodes"].append(dep)
                graph["edges"].append(("root", dep))
        return graph
