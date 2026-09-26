"""Shared upload guard: declared MIME types must match the actual bytes.

A client-declared ``Content-Type`` is never trusted: ``image/jpeg`` wrapping a
shell script is the whole point of the attack. Every upload path in the
application (ops evidence, dynamic report attachments) validates through
:func:`sniff_mime` so the rule has exactly one owner.
"""
from __future__ import annotations

ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/gif",
                          "image/webp", "application/pdf"})

MAX_UPLOAD_BYTES = 4 * 1024 * 1024

_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"%PDF-", "application/pdf"),
)

_EXTENSIONS = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
               "gif": "image/gif", "webp": "image/webp",
               "pdf": "application/pdf"}


def sniff_mime(payload: bytes, declared: str) -> str | None:
    """Return ``declared`` only when ``payload`` really is that type.

    WebP is confirmed by the ``WEBP`` fourcc at bytes 8..12 rather than the
    bare ``RIFF`` container, so an AVI/WAVE file is rejected. ``None`` means
    the bytes do not match anything acceptable.
    """
    if not payload:
        return None
    declared = (declared or "").lower()
    for signature, mime in _SIGNATURES:
        if not payload.startswith(signature):
            continue
        if mime == "image/webp" and payload[8:12] != b"WEBP":
            return None
        return mime if declared == mime else None
    return None


def declared_mime(filename: str) -> str | None:
    """The type implied by a file extension, or ``None`` when unrecognised."""
    name = (filename or "").strip().lower().rsplit("/", 1)[-1]
    if "." not in name:
        return None
    return _EXTENSIONS.get(name.rsplit(".", 1)[-1])


def is_allowed_upload(payload: bytes, filename: str, declared: str) -> bool:
    """True when the extension, the declared type and the bytes all agree.

    A name carrying a non-media extension (``x.exe``) is refused outright
    even if the bytes look like an image. A name with no extension at all is
    judged on the declared type alone, and still has to match its bytes.
    """
    declared = (declared or "").lower()
    name = (filename or "").strip().lower().rsplit("/", 1)[-1]
    if "." in name:
        expected = declared_mime(name)
        if expected is None:
            return False
    else:
        expected = declared if declared in ALLOWED_MIME else None
    if expected is None:
        return False
    return sniff_mime(payload, expected) == expected


__all__ = ["ALLOWED_MIME", "MAX_UPLOAD_BYTES", "declared_mime", "is_allowed_upload",
           "sniff_mime"]
