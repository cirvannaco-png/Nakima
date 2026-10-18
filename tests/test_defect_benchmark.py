from scripts.benchmark_defect_detection import match_findings, parse_findings


def test_parse_findings_accepts_markdown_json_fence():
    content = chr(96) * 3 + 'json\n{"findings": []}\n' + chr(96) * 3
    assert parse_findings(content) == []


def test_match_findings_counts_true_positive_false_positive_and_miss():
    predicted = [
        {"file": "a.py", "line": 12, "rule": "null-dereference"},
        {"file": "b.py", "line": 50, "rule": "made-up"},
    ]
    expected = [
        {"file": "a.py", "line": 10, "rule": "null-dereference"},
        {"file": "c.py", "line": 7, "rule": "unsafe-input"},
    ]
    assert match_findings(predicted, expected) == (1, 1, 1)
