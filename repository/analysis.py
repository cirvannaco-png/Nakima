from pathlib import Path
from typing import Dict, List, Optional

from tree_sitter import Node, Parser
from tree_sitter_languages import get_language

# Extension -> tree-sitter grammar name.
LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
}

# Per-language node type names differ (Python has no separate "method"
# node — a method is just a function_definition nested inside a
# class_definition; JS/TS do have a distinct method_definition node).
LANG_NODE_TYPES = {
    "python": {
        "function": "function_definition",
        "class": "class_definition",
        "method": None,  # detected structurally: function_definition inside class_definition
        "imports": ("import_statement", "import_from_statement"),
    },
    "javascript": {
        "function": "function_declaration",
        "class": "class_declaration",
        "method": "method_definition",
        "imports": ("import_statement",),
    },
    "typescript": {
        "function": "function_declaration",
        "class": "class_declaration",
        "method": "method_definition",
        "imports": ("import_statement",),
    },
    "tsx": {
        "function": "function_declaration",
        "class": "class_declaration",
        "method": "method_definition",
        "imports": ("import_statement",),
    },
    "go": {
        "function": "function_declaration",
        "class": "type_declaration",
        "method": "method_declaration",
        "imports": ("import_declaration",),
    },
}


class RepositoryAnalyzer:
    """Multi-language tree-sitter wrapper. Holds one parser per language
    (lazily built) instead of being locked to a single language at
    construction time, since a repo — and even a single call to
    GraphBuilder — mixes file types."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)
        self._parsers: Dict[str, Parser] = {}

    def _language_for(self, file_path: Path) -> Optional[str]:
        return LANG_BY_EXT.get(Path(file_path).suffix)

    def _get_parser(self, language: str) -> Parser:
        if language not in self._parsers:
            lang_obj = get_language(language)
            try:
                # tree-sitter < 0.22
                parser = Parser()
                parser.set_language(lang_obj)
            except AttributeError:
                # tree-sitter >= 0.22 removed set_language(); language is
                # passed to the constructor or assigned as a property instead.
                try:
                    parser = Parser(lang_obj)
                except TypeError:
                    parser = Parser()
                    parser.language = lang_obj
            self._parsers[language] = parser
        return self._parsers[language]

    def get_enclosing_scope(self, file_path: str, line_number: int) -> str:
        full_path = self.repo_dir / file_path
        language = self._language_for(full_path)
        if not language or not full_path.exists():
            return "unknown"
        try:
            code = full_path.read_text()
        except Exception:
            return "unknown"

        parser = self._get_parser(language)
        tree = parser.parse(code.encode())
        target_line = line_number - 1
        lines = code.split("\n")
        if target_line < 0 or target_line >= len(lines):
            return "unknown"
        # descendant_for_point_range does NOT clamp an out-of-bounds end
        # column — passing something like 999 silently returns the root
        # node instead of the innermost node on that line. Use the real
        # line length instead.
        end_col = max(len(lines[target_line]) - 1, 0)
        node = tree.root_node.descendant_for_point_range((target_line, 0), (target_line, end_col))

        node_types = LANG_NODE_TYPES.get(language, {})
        scope_types = {t for t in (node_types.get("function"), node_types.get("class"), node_types.get("method")) if t}
        while node is not None:
            if node.type in scope_types:
                name_node = node.child_by_field_name("name")
                if name_node:
                    return name_node.text.decode()
            node = node.parent
        return "global"

    def extract_symbols(self, file_path: Path) -> List[Dict]:
        """Extract function/class/method/import symbols from a single file.
        Returns [] for unsupported file types instead of guessing with the
        wrong grammar."""
        file_path = Path(file_path)
        language = self._language_for(file_path)
        if not language:
            return []
        try:
            code = file_path.read_bytes()
        except Exception:
            return []

        parser = self._get_parser(language)
        tree = parser.parse(code)
        rel_path = str(file_path.relative_to(self.repo_dir)) if file_path.is_absolute() else str(file_path)

        symbols: List[Dict] = []
        node_types = LANG_NODE_TYPES.get(language, {})
        self._extract_recursive(tree.root_node, symbols, rel_path, language, node_types, inside_class=False)
        return symbols

    def _extract_recursive(
        self, node: Node, symbols: List[Dict], rel_path: str, language: str, node_types: Dict, inside_class: bool
    ):
        func_type = node_types.get("function")
        class_type = node_types.get("class")
        method_type = node_types.get("method")
        import_types = node_types.get("imports", ())

        is_class = node.type == class_type
        is_explicit_method = method_type and node.type == method_type
        is_function = func_type and node.type == func_type

        if is_class:
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "type": "class",
                    "name": name_node.text.decode(),
                    "file": rel_path,
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "properties": {},
                })
        elif is_explicit_method or (is_function and inside_class):
            # Python has no distinct method node — a function_definition
            # directly nested inside a class body is a method.
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "type": "method",
                    "name": name_node.text.decode(),
                    "file": rel_path,
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "properties": {"decorators": self._extract_decorators(node)},
                })
        elif is_function:
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append({
                    "type": "function",
                    "name": name_node.text.decode(),
                    "file": rel_path,
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "properties": {"decorators": self._extract_decorators(node)},
                })
        elif node.type in import_types:
            self._extract_import_symbol(node, symbols, rel_path, language)

        for child in node.children:
            self._extract_recursive(child, symbols, rel_path, language, node_types, inside_class=(inside_class or is_class))

    def _extract_decorators(self, func_node: Node) -> List[str]:
        decorators = []
        for child in func_node.children:
            if child.type == "decorator":
                decorators.append(child.text.decode().strip())
        return decorators

    def _extract_import_symbol(self, node: Node, symbols: List[Dict], rel_path: str, language: str):
        targets = self._resolve_import_targets(node, language)
        symbols.append({
            "type": "import",
            "name": node.text.decode().strip(),
            "file": rel_path,
            "line_start": node.start_point[0] + 1,
            "line_end": node.end_point[0] + 1,
            "properties": {"dependencies": targets},
        })

    def _resolve_import_targets(self, node: Node, language: str) -> List[str]:
        if language == "python":
            if node.type == "import_statement":
                return [c.text.decode() for c in node.children if c.type == "dotted_name"]
            elif node.type == "import_from_statement":
                module_node = node.child_by_field_name("module_name")
                return [module_node.text.decode()] if module_node else []
        elif language in ("javascript", "typescript", "tsx"):
            for child in node.children:
                if child.type == "string":
                    return [child.text.decode().strip("'\"")]
        return []

    def extract_structure_summary(self, max_files: int = 50) -> str:
        lines = []
        candidates = [
            f for f in self.repo_dir.rglob("*") if f.suffix in LANG_BY_EXT and f.is_file()
        ][:max_files]
        for f in candidates:
            symbols = self.extract_symbols(f)
            names = [s["name"] for s in symbols if s["type"] in ("function", "class")]
            if names:
                lines.append(f"{f.relative_to(self.repo_dir)}: {', '.join(names)}")
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
