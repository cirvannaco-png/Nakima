"""File validation for the Project Upload Gateway. Extension allowlist +
magic-byte sniffing + size limit — catches "this claims to be a .pdf but
isn't one" and oversized uploads. This is NOT virus/malware scanning; see
documents/gateway.py's docstring for why that's explicitly not built here
and what a real deployment needs to add before accepting uploads from
untrusted users.
"""

from dataclasses import dataclass

MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB — generous for docs, small enough that a single
# upload can't casually exhaust disk on a small deploy target.

# extension -> file_type. Deliberately excludes executable/script
# extensions even if someone renames them to something in this list —
# the magic-byte check below is what actually enforces content matches
# extension, this list only says which extensions are even considered.
_ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".readme": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
}

# Magic-byte signatures for formats where one exists. Formats without a
# reliable signature (markdown/text/json/yaml/sql are all just text) are
# not in this dict and skip the binary-signature check — there's nothing
# meaningful to sniff.
_MAGIC_SIGNATURES: dict[str, bytes] = {
    "pdf": b"%PDF-",
    "docx": b"PK\x03\x04",  # docx is a zip container; this confirms "valid zip", not
    # "valid docx" specifically — python-docx will raise its own error at
    # parse time if the zip's internal structure isn't actually a docx.
}


@dataclass
class ValidationResult:
    ok: bool
    file_type: str | None = None
    reason: str | None = None


class FileValidator:
    def validate(self, filename: str, content: bytes) -> ValidationResult:
        if not filename or "." not in filename:
            return ValidationResult(ok=False, reason="File has no extension.")

        ext = "." + filename.rsplit(".", 1)[-1].lower()
        file_type = _ALLOWED_EXTENSIONS.get(ext)
        if file_type is None:
            return ValidationResult(
                ok=False,
                reason=f"Extension {ext!r} is not accepted. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
            )

        if len(content) == 0:
            return ValidationResult(ok=False, file_type=file_type, reason="File is empty.")
        if len(content) > MAX_SIZE_BYTES:
            return ValidationResult(
                ok=False,
                file_type=file_type,
                reason=f"File is {len(content)} bytes, exceeding the {MAX_SIZE_BYTES} byte limit.",
            )

        signature = _MAGIC_SIGNATURES.get(file_type)
        if signature is not None and not content.startswith(signature):
            return ValidationResult(
                ok=False,
                file_type=file_type,
                reason=f"Content doesn't match the expected {file_type} signature for a .{file_type} file "
                f"— the extension may not reflect the actual content.",
            )

        return ValidationResult(ok=True, file_type=file_type)
