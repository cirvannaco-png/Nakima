from repository.analysis import RepositoryAnalyzer


def test_extract_symbols_distinguishes_function_method_class(sample_repo):
    analyzer = RepositoryAnalyzer(sample_repo)
    symbols = analyzer.extract_symbols(sample_repo / "sample.py")

    by_name = {s["name"]: s for s in symbols}
    assert by_name["Widget"]["type"] == "class"
    assert by_name["__init__"]["type"] == "method"
    assert by_name["render"]["type"] == "method"
    assert by_name["standalone_function"]["type"] == "function"
    assert {"import os", "from pathlib import Path"} == {s["name"] for s in symbols if s["type"] == "import"}


def test_extract_symbols_unsupported_extension_returns_empty(sample_repo):
    analyzer = RepositoryAnalyzer(sample_repo)
    unsupported = sample_repo / "notes.txt"
    unsupported.write_text("not code")
    assert analyzer.extract_symbols(unsupported) == []


def test_get_enclosing_scope(sample_repo):
    analyzer = RepositoryAnalyzer(sample_repo)
    assert analyzer.get_enclosing_scope("sample.py", 8) == "Widget"
    assert analyzer.get_enclosing_scope("sample.py", 12) == "standalone_function"
    assert analyzer.get_enclosing_scope("sample.py", 1) == "global"


def test_get_enclosing_scope_out_of_range_is_safe(sample_repo):
    analyzer = RepositoryAnalyzer(sample_repo)
    assert analyzer.get_enclosing_scope("sample.py", 9999) == "unknown"
