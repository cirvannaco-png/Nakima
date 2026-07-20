"""Tests for documents/validators.py, documents/parsers.py, and
documents/gateway.py. PDF/DOCX fixtures are real files built with
pypdf/python-docx, not fake byte strings, so extraction is exercised
against the actual library round-trip.
"""

import io

import docx
import pytest
from pypdf import PdfWriter

from documents import validators as validators_mod
from documents.gateway import ProjectUploadGateway
from documents.parsers import extract_text
from documents.validators import FileValidator
from models.repository import Repository

# ---------------------------------------------------------------------------
# Fixtures: real minimal files
# ---------------------------------------------------------------------------


def _blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _docx_bytes(text: str) -> bytes:
    doc = docx.Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# FileValidator
# ---------------------------------------------------------------------------


def test_validator_rejects_no_extension():
    result = FileValidator().validate("noextension", b"hello")
    assert result.ok is False
    assert "no extension" in result.reason.lower()


def test_validator_rejects_disallowed_extension():
    result = FileValidator().validate("script.exe", b"MZ\x90\x00")
    assert result.ok is False
    assert "not accepted" in result.reason


def test_validator_rejects_empty_file():
    result = FileValidator().validate("notes.txt", b"")
    assert result.ok is False
    assert "empty" in result.reason.lower()


def test_validator_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(validators_mod, "MAX_SIZE_BYTES", 10)
    result = FileValidator().validate("notes.txt", b"x" * 100)
    assert result.ok is False
    assert "exceeding" in result.reason


def test_validator_rejects_content_that_doesnt_match_pdf_signature():
    result = FileValidator().validate("fake.pdf", b"this is not a pdf")
    assert result.ok is False
    assert "signature" in result.reason


def test_validator_accepts_real_pdf():
    result = FileValidator().validate("doc.pdf", _blank_pdf_bytes())
    assert result.ok is True
    assert result.file_type == "pdf"


def test_validator_accepts_real_docx():
    result = FileValidator().validate("doc.docx", _docx_bytes("hello"))
    assert result.ok is True
    assert result.file_type == "docx"


def test_validator_accepts_markdown_without_magic_check():
    result = FileValidator().validate("README.md", b"# Hello\n\nSome notes.")
    assert result.ok is True
    assert result.file_type == "markdown"


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


def test_extract_plain_text():
    assert extract_text("text", b"hello world") == "hello world"


def test_extract_markdown_is_plain_text():
    assert extract_text("markdown", b"# Title\nBody") == "# Title\nBody"


def test_extract_json_pretty_prints_valid_json():
    result = extract_text("json", b'{"a": 1, "b": [1, 2]}')
    assert '"a": 1' in result


def test_extract_json_falls_back_to_raw_on_invalid_json():
    result = extract_text("json", b"{not valid json")
    assert result == "{not valid json"


def test_extract_yaml_round_trips():
    result = extract_text("yaml", b"goals:\n  - reduce latency\n")
    assert "reduce latency" in result


def test_extract_yaml_falls_back_on_invalid_yaml():
    result = extract_text("yaml", b"key: : : broken")
    assert "broken" in result


def test_extract_sql_is_plain_text():
    assert extract_text("sql", b"CREATE TABLE t (id INT);") == "CREATE TABLE t (id INT);"


def test_extract_real_docx_returns_paragraph_text():
    result = extract_text("docx", _docx_bytes("Nakima Engineering Intelligence"))
    assert "Nakima Engineering Intelligence" in result


def test_extract_blank_pdf_reports_no_text_layer():
    result = extract_text("pdf", _blank_pdf_bytes())
    assert "No extractable text layer" in result


def test_extract_corrupt_pdf_degrades_instead_of_raising():
    result = extract_text("pdf", b"%PDF-1.4 not actually a valid pdf body")
    assert "extraction failed" in result


# ---------------------------------------------------------------------------
# ProjectUploadGateway (integration, real DB)
# ---------------------------------------------------------------------------


async def _make_repo(db_session, full_name="kelson/test-repo"):
    repo = Repository(full_name=full_name)
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_gateway_uploads_and_persists_a_valid_file(db_session):
    repo = await _make_repo(db_session)
    result = await ProjectUploadGateway(db_session, repo.id).upload("README.md", b"# Vision\nBuild great software.")

    assert result.is_duplicate is False
    assert result.document.status == "processed"
    assert result.document.version == 1
    assert "Build great software" in result.document.extracted_text


async def test_gateway_persists_a_rejected_upload_with_reason(db_session):
    repo = await _make_repo(db_session)
    result = await ProjectUploadGateway(db_session, repo.id).upload("virus.exe", b"MZ\x90\x00")

    assert result.document.status == "rejected"
    assert result.document.rejection_reason is not None
    assert result.document.extracted_text is None


async def test_gateway_detects_duplicate_by_content_hash(db_session):
    repo = await _make_repo(db_session)
    content = b"# Same content\n"
    first = await ProjectUploadGateway(db_session, repo.id).upload("a.md", content)
    second = await ProjectUploadGateway(db_session, repo.id).upload("b.md", content)  # different filename, same bytes

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert second.document.id == first.document.id

    docs = await ProjectUploadGateway(db_session, repo.id).list_documents()
    assert len(docs) == 1


async def test_gateway_version_increments_per_repository(db_session):
    repo = await _make_repo(db_session)
    gateway = ProjectUploadGateway(db_session, repo.id)
    first = await gateway.upload("one.md", b"one")
    second = await gateway.upload("two.md", b"two")

    assert first.document.version == 1
    assert second.document.version == 2


async def test_gateway_rejected_upload_still_consumes_a_version(db_session):
    repo = await _make_repo(db_session)
    gateway = ProjectUploadGateway(db_session, repo.id)
    rejected = await gateway.upload("bad.exe", b"MZ")
    accepted = await gateway.upload("good.md", b"content")

    assert rejected.document.version == 1
    assert accepted.document.version == 2


async def test_gateway_versions_independent_per_repository(db_session):
    repo_a = await _make_repo(db_session, "kelson/repo-a")
    repo_b = await _make_repo(db_session, "kelson/repo-b")
    result_a = await ProjectUploadGateway(db_session, repo_a.id).upload("a.md", b"content-a")
    result_b = await ProjectUploadGateway(db_session, repo_b.id).upload("b.md", b"content-b")

    assert result_a.document.version == 1
    assert result_b.document.version == 1
