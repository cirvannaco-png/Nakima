from pathlib import Path

from tree_sitter import Parser
from tree_sitter_languages import get_language


class RepositoryAnalyzer:
    def __init__(self, repo_dir: Path, language: str = "python"):
        self.repo_dir = Path(repo_dir)
        self.parser = Parser()
        self.parser.set_language(get_language(language))

    def get_enclosing_scope(self, file_path: str, line_number: int) -> str:
        """Return the name of the function/class/method that contains the
        given (1-indexed) line, or 'global' / 'unknown'."""
        full_path = self.repo_dir / file_path
        if not full_path.exists():
            return "unknown"
        try:
            code = full_path.read_text()
        except Exception:
            return "unknown"

        tree = self.parser.parse(code.encode())
        target_line = line_number - 1  # tree-sitter is 0-indexed
        node = tree.root_node.descendant_for_point_range((target_line, 0), (target_line, 999))

        while node is not None:
            if node.type in ("function_definition", "class_definition"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    return name_node.text.decode()
            node = node.parent
        return "global"

    def extract_structure_summary(self, max_files: int = 50) -> str:
        """Lightweight repo structure summary (top-level function/class names
        per file) used as context for the planner."""
        lines = []
        for py_file in list(self.repo_dir.rglob("*.py"))[:max_files]:
            rel = py_file.relative_to(self.repo_dir)
            try:
                code = py_file.read_text()
            except Exception:
                continue
            tree = self.parser.parse(code.encode())
            names = []
            for child in tree.root_node.children:
                if child.type in ("function_definition", "class_definition"):
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        names.append(name_node.text.decode())
            if names:
                lines.append(f"{rel}: {', '.join(names)}")
        return "\n".join(lines)

    def build_dependency_graph(self) -> dict:
        graph: dict = {"nodes": [], "edges": []}
        req_file = self.repo_dir / "requirements.txt"
        if req_file.exists():
            graph["nodes"].append("root")
            for line in req_file.read_text().splitlines():
                pkg = line.strip().split("==")[0].split(">=")[0].strip()
                if pkg and not pkg.startswith("#"):
                    graph["nodes"].append(pkg)
                    graph["edges"].append(("root", pkg))
        return graph
