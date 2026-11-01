from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
ALLOWED = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
    "video/mp4": (b"\x00\x00\x00",),
    "video/webm": (b"\x1a\x45\xdf\xa3",),
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class ValidatedAttachment:
    filename: str
    media_type: str
    size_bytes: int
    sha256: str


def validate_attachment(filename: str, media_type: str, content: bytes) -> ValidatedAttachment:
    """Validate size, declared type and file signature; never trust browser MIME."""
    if not content:
        raise ValueError("Attachment is empty")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Attachment exceeds the 20 MiB limit")
    if media_type not in ALLOWED:
        raise ValueError("Unsupported attachment type")
    if media_type == "image/webp":
        valid = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    elif media_type == "video/mp4":
        valid = len(content) >= 12 and content[4:8] == b"ftyp"
    else:
        valid = any(content.startswith(signature) for signature in ALLOWED[media_type])
    if not valid:
        raise ValueError("File signature does not match the declared media type")
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    clean = _SAFE_NAME.sub("_", basename).strip("._") or "attachment"
    return ValidatedAttachment(clean[:180], media_type, len(content), hashlib.sha256(content).hexdigest())
