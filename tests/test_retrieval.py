from intelligence.retrieval import retrieve_code_evidence


def test_retrieval_ranks_relevant_source_and_excludes_requested_files(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def verify_webhook_signature(payload, secret):\n"
        "    return hmac.compare_digest(signature, expected)\n"
    )
    (tmp_path / "auth_helper.py").write_text(
        "def verify_webhook_signature(payload, secret):\n"
        "    return hmac.compare_digest(signature, expected)\n"
    )
    (tmp_path / "billing.py").write_text(
        "def calculate_invoice(subtotal, tax):\n"
        "    return subtotal + tax\n"
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "leak.py").write_text("def verify_webhook_signature(): pass")

    results = retrieve_code_evidence(
        tmp_path,
        "verify webhook signature",
        exclude_files=["auth.py"],
    )

    assert results
    assert results[0]["file"] == "auth_helper.py"
    assert all(item["file"] != "auth.py" for item in results)
    assert all(".git" not in str(item["file"]) for item in results)


def test_retrieval_returns_empty_for_no_query_terms(tmp_path):
    (tmp_path / "app.py").write_text("def run(): return True")
    assert retrieve_code_evidence(tmp_path, "!!!") == []
