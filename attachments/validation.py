"""Content-signature validation for screenshot and video evidence."""
from pathlib import PurePosixPath
import re
_SIGNATURES = (("image/png", ".png", lambda b: b.startswith(bytes.fromhex("89504e470d0a1a0a"))), ("image/jpeg", ".jpg", lambda b: b.startswith(bytes.fromhex("ffd8ff"))), ("image/webp", ".webp", lambda b: len(b)>=12 and b[:4]==b"RIFF" and b[8:12]==b"WEBP"), ("video/webm", ".webm", lambda b: b.startswith(bytes.fromhex("1a45dfa3"))), ("video/mp4", ".mp4", lambda b: len(b)>=12 and b[4:8]==b"ftyp"))
def inspect_media_upload(filename: str, content: bytes, declared_content_type: str|None=None) -> tuple[str,str]:
    if not content: raise ValueError("Empty attachment")
    detected=next(((mime,ext) for mime,ext,match in _SIGNATURES if match(content)),None)
    if detected is None: raise ValueError("Only PNG, JPEG, WEBP, MP4 and WEBM are supported")
    mime,ext=detected; declared=(declared_content_type or "").split(";",1)[0].strip().lower()
    if declared and declared not in (mime,"application/octet-stream","binary/octet-stream"): raise ValueError("Content type does not match file signature")
    name=filename.replace("\\","/").split("/")[-1]
    stem=re.sub(r"[^A-Za-z0-9_-]+","-",PurePosixPath(name).stem).strip("-_")[:80] or "attachment"
    return stem+ext,mime
