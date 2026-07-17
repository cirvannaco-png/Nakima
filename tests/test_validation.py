from validation.pipeline import _extract_file_and_line


def test_python_flake8_extraction():
    assert _extract_file_and_line(
        "python", "lint", "app/routes.py:12:5: E302 expected 2 blank lines, got 1"
    ) == ("app/routes.py", 12)


def test_python_pytest_extraction():
    log = "FAILED tests/test_utils.py::test_add - AssertionError: assert 3 == 4"
    assert _extract_file_and_line("python", "test", log) == ("tests/test_utils.py", None)


def test_python_black_extraction():
    assert _extract_file_and_line("python", "format", "would reformat app/utils.py") == ("app/utils.py", None)


def test_go_build_extraction():
    assert _extract_file_and_line("go", "build", "./main.go:15:2: undefined: fmt2") == ("./main.go", 15)


def test_go_test_extraction():
    log = "--- FAIL: TestFoo\n    main_test.go:23: expected 4, got 3"
    assert _extract_file_and_line("go", "test", log) == ("main_test.go", 23)


def test_typescript_build_extraction():
    assert _extract_file_and_line("typescript", "build", "src/index.ts(10,5): error TS2322") == ("src/index.ts", 10)


def test_no_match_returns_none_none():
    assert _extract_file_and_line("python", "lint", "totally unrelated output") == (None, None)
