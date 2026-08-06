"""Unit tests for planner/token_compressor.py.

Pure function over an already-built ContextBuilder payload, so no DB, no
repo and no provider needed here — the interesting behaviour is entirely
in which snippets survive the budget and what the report says about it.
"""

from planner.token_compressor import CHARS_PER_TOKEN_ESTIMATE, TokenCompressor, _estimate_tokens


def _snippet(name: str, tokens: int) -> dict:
    return {"file": name, "content": "x" * (tokens * CHARS_PER_TOKEN_ESTIMATE)}


def test_estimate_tokens_never_returns_zero_for_nonempty_text():
    assert _estimate_tokens("") == 1
    assert _estimate_tokens("a" * 400) == 100


def test_everything_is_kept_when_it_fits_in_budget():
    context = {
        "requirement": "add a health endpoint",
        "code_snippets": [_snippet("a.py", 10), _snippet("b.py", 10)],
        "dependency_subgraph": {"a.py": {"depended_on_by": ["b.py"]}},
    }

    out = TokenCompressor(max_tokens=8000).compress(context)

    assert [s["file"] for s in out["code_snippets"]] == ["a.py", "b.py"]
    assert out["dependency_subgraph"] == {"a.py": {"depended_on_by": ["b.py"]}}
    assert out["compression"]["snippets_dropped"] == []
    assert out["compression"]["snippets_kept"] == 2


def test_high_fan_in_snippets_survive_and_low_fan_in_ones_are_dropped():
    context = {
        "requirement": "r",
        "code_snippets": [_snippet("lonely.py", 100), _snippet("core.py", 100)],
        "dependency_subgraph": {
            "core.py": {"depended_on_by": ["a.py", "b.py", "c.py"]},
            "lonely.py": {"depended_on_by": []},
        },
    }

    out = TokenCompressor(max_tokens=150).compress(context)

    assert [s["file"] for s in out["code_snippets"]] == ["core.py"]
    assert out["compression"]["snippets_dropped"] == ["lonely.py"]
    # The subgraph is trimmed to the files that actually survived, so the
    # provider never sees edges pointing at content that isn't there.
    assert set(out["dependency_subgraph"]) == {"core.py"}


def test_requirement_is_never_dropped_and_an_oversized_one_empties_the_payload():
    context = {
        "requirement": "q" * 4000,  # ~1000 tokens
        "code_snippets": [_snippet("a.py", 10)],
        "dependency_subgraph": {"a.py": {"depended_on_by": []}},
    }

    out = TokenCompressor(max_tokens=100).compress(context)

    assert out["requirement"] == context["requirement"]
    assert out["code_snippets"] == []
    assert out["dependency_subgraph"] == {}


def test_missing_subgraph_entry_scores_as_zero_fan_in_rather_than_raising():
    context = {
        "requirement": "r",
        "code_snippets": [_snippet("unknown.py", 5)],
        "dependency_subgraph": {},
    }

    out = TokenCompressor(max_tokens=8000).compress(context)

    assert [s["file"] for s in out["code_snippets"]] == ["unknown.py"]
    assert out["compression"]["estimated_tokens_used"] == 5 + _estimate_tokens("r")
