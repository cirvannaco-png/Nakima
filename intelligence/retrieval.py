"""Deterministic lexical retrieval for repository-grounded model context.

This is intentionally dependency-free and bounded. It supplements, rather than
replaces, the existing repository dependency graph and AST analysis.
"""

import math
import re
from pathlib import Path
from typing import Iterable

SUPPORTED_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".go"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text):
        camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw)
        tokens.extend(part.lower() for part in re.split(r"[_\s]+", camel_split) if len(part) >= 3)
    return tokens


def retrieve_code_evidence(
    repo_dir: Path,
    query: str,
    *,
    top_k: int = 8,
    max_chars: int = 1800,
    max_files: int = 2000,
    exclude_files: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Return bounded, scored source excerpts relevant to query terms.

    Scores are BM25-inspired lexical relevance scores, not calibrated
    probabilities. Returned paths are repository-relative and line numbers
    refer to the first line of each excerpt.
    """
    root = Path(repo_dir).resolve()
    query_terms = set(_tokens(query))
    if not query_terms or top_k <= 0:
        return []

    excluded = {Path(item).as_posix() for item in exclude_files}
    documents: list[tuple[str, list[str], list[str]]] = []
    for path in root.rglob("*"):
        if len(documents) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in excluded or any(part in SKIP_DIRS for part in Path(relative).parts):
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            if resolved.stat().st_size > 256_000:
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except (OSError, ValueError):
            continue
        if not lines:
            continue
        # Avoid feeding extremely large files into the model.
        text = "\n".join(lines[:2000])
        tokens = _tokens(text)
        if not tokens:
            continue
        documents.append((relative, lines, tokens))

    if not documents:
        return []

    document_frequency = {term: sum(1 for _, _, tokens in documents if term in set(tokens)) for term in query_terms}
    avg_length = sum(len(tokens) for _, _, tokens in documents) / len(documents)
    scored: list[tuple[float, str, int, str, list[str]]] = []
    for relative, lines, tokens in documents:
        token_counts: dict[str, int] = {}
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
        length_norm = len(tokens) / max(avg_length, 1.0)
        score = 0.0
        for term in query_terms:
            frequency = token_counts.get(term, 0)
            if not frequency:
                continue
            idf = math.log(1 + (len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            score += idf * (frequency * 2.2) / (frequency + 1.2 * (0.25 + 0.75 * length_norm))

        if score <= 0:
            continue
        best_line = max(
            range(len(lines)),
            key=lambda index: sum(1 for term in query_terms if term in set(_tokens(lines[index]))),
        )
        start = max(0, best_line - 5)
        end = min(len(lines), best_line + 6)
        excerpt = "\n".join(lines[start:end])[:max_chars]
        scored.append((score, relative, start + 1, excerpt, lines))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"file": relative, "line": line, "score": round(score, 4), "content": excerpt}
        for score, relative, line, excerpt, _ in scored[:top_k]
    ]
