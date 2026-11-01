"""Content-signature validation for screenshot and video evidence."""
from pathlib import PurePosixPath
import re

_SIGNATURES = (
    ("image/png", ".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    ("image/jpeg", ".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    ("image/webp", ".webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
    ("video/webm", ".webm", lambda data: data.startswith(b"\x1a\x45\xdf\xa3")),
    ("video/mp4", ".mp4", lambda data: len(data) >= 12 and data[4:8] == b"ftyp"),
)

def inspect_media_upload(filename: str, content: bytes, declared_content_type: str | None = None) -> tuple[str, str]:
    """Return a sanitized filename and MIME type determined from file bytes."""
    if not content:
        raise ValueError("The uploaded attachment is empty.")
    detected = next(((mime, extension) for mime, extension, matcher in _SIGNATURES if matcher(content)), None)
    if detected is None:
        raise ValueError("Unsupported media. Use PNG, JPEG, WEBP, MP4 or WEBM files.")
    media_type, extension = detected
    declared = (declared_content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in (media_type, "application/octet-stream", "binary/octet-stream"):
        if not (media_type == "video/mp4" and declared == "video/quicktime"):
            raise ValueError("The declared content type does not match the file signature.")
    basename = filename.replace("\\", "/").split("/")[-1]
    stem = PurePosixPath(basename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")[:80] or "attachment"
    return f"{safe_stem}{extension}", media_type
