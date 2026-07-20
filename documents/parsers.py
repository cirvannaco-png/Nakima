"""Extracts plain text from an uploaded file's raw bytes, dispatched by
the file_type FileValidator already determined. Every extractor degrades
to "best effort raw decode" rather than raising — a document Nakima can't
parse perfectly should still get *something* stored (even if it's messy)
rather than losing the upload entirely, since a human can still read a
slightly-mangled extraction but can't read a row that doesn't exist.
"""

import io
import json
import logging

import yaml
from docx import Document as DocxDocument
from pypdf import PdfReader

logger = logging.getLogger(__name__)


class TextExtractionError(Exception):
    pass


def extract_text(file_type: str, content: bytes) -> str:
    extractor = _EXTRACTORS.get(file_type)
    if extractor is None:
        raise TextExtractionError(f"No extractor registered for file_type={file_type!r}")
    return extractor(content)


def _extract_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages).strip()
        if text:
            return text
        return "[No extractable text layer — likely a scanned/image-only PDF.]"
    except Exception as e:
        logger.warning(f"PDF extraction failed, falling back to a note: {e}")
        return f"[PDF text extraction failed: {type(e).__name__}]"


def _extract_docx(content: bytes) -> str:
    try:
        doc = DocxDocument(io.BytesIO(content))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts).strip() or "[Document has no extractable paragraph or table text.]"
    except Exception as e:
        logger.warning(f"DOCX extraction failed, falling back to a note: {e}")
        return f"[DOCX text extraction failed: {type(e).__name__}]"


def _extract_plain_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _extract_json(content: bytes) -> str:
    try:
        parsed = json.loads(content)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return _extract_plain_text(content)  # not valid JSON — store the raw text rather than reject


def _extract_yaml(content: bytes) -> str:
    try:
        parsed = yaml.safe_load(content)
        return yaml.dump(parsed, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except yaml.YAMLError:
        return _extract_plain_text(content)


_EXTRACTORS = {
    "pdf": _extract_pdf,
    "docx": _extract_docx,
    "markdown": _extract_plain_text,
    "text": _extract_plain_text,
    "sql": _extract_plain_text,
    "json": _extract_json,
    "yaml": _extract_yaml,
}
