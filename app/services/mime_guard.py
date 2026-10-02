"""Shared upload guard: declared MIME types must match the actual bytes.

A client-declared ``Content-Type`` is never trusted: ``image/jpeg`` wrapping a
shell script is the whole point of the attack. Every upload path in the
application validates through this module, so the rule has exactly one owner.

**That claim was false on two of three paths.** The ops attachment endpoint and
the dynamic report fields both sniffed the bytes; ``_save_avatar`` in
``app/main/routes.py`` trusted ``file.mimetype`` outright and never looked at
the content at all. Worse, it took the stored extension from the *user's
filename*, so ``avatar.html`` - declared ``image/jpeg``, containing HTML - was
written into ``static/uploads/avatars/`` as ``.html`` and served from there.
Declaring a JPEG was enough to store a page that runs on the app's own origin.

:func:`validate_upload` is the single decision. Each caller keeps its own
response shape, because those are machine contracts asserted by tests: this
raises a rejection carrying a code, and the route turns that into its existing
status and JSON body rather than the module inventing one.
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

#: The extension to store for each confirmed type. Never taken from the
#: uploaded filename: that is the vector. ``avatar.html`` declared as JPEG comes
#: back as image/jpeg from the bytes and is stored as .jpg.
_STORED_EXTENSION = {"image/jpeg": ".jpg", "image/png": ".png",
                     "image/gif": ".gif", "image/webp": ".webp",
                     "application/pdf": ".pdf"}


class UploadRejected(ValueError):
    """An upload that must not be stored, and why.

    ``code`` is one of ``filename``, ``type``, ``size``, ``content``. Callers
    map it to their own response; the message here is for logs, not for users.
    """

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def stored_extension(mime: str) -> str:
    """The extension to write, chosen by the confirmed type only."""
    return _STORED_EXTENSION.get(mime, "")


def validate_upload(payload: bytes, filename: str, declared: str, *,
                    allowed: frozenset | set | None = None,
                    max_bytes: int | None = None) -> str:
    """Decide whether an upload may be stored, and return its confirmed type.

    The checks, in order, so the caller reports the most specific problem:

    1. the declared type is in the allow-list;
    2. the payload is within the size cap;
    3. the filename carries a known extension, when it has one at all;
    4. the bytes really are the declared type.

    Order matters for the report the user sees: a 5 MB text file should be
    called oversized or unsupported, not "content does not match".

    ``allowed`` defaults to :data:`ALLOWED_MIME`; an avatar upload passes a
    narrower set that excludes PDF. ``max_bytes`` defaults to
    :data:`MAX_UPLOAD_BYTES`.
    """
    allowed = ALLOWED_MIME if allowed is None else allowed
    max_bytes = MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    declared = (declared or "").lower()
    name = (filename or "").strip().lower().rsplit("/", 1)[-1]

    # A client that sends no Content-Type at all is judged on the extension,
    # which then still has to match the bytes. Browsers do omit it on some
    # clients, so refusing outright would break a legitimate upload; trusting it
    # without the byte check would not.
    if not declared:
        if "." not in name:
            raise UploadRejected("type", "no declared type and no extension")
        declared = declared_mime(name) or ""

    if declared not in allowed:
        raise UploadRejected("type", declared)
    if max_bytes is not None and len(payload) > max_bytes:
        raise UploadRejected("size", f"{len(payload)} bytes")

    if "." in name and declared_mime(name) is None:
        # A name like x.exe is refused even when the bytes are a real image.
        raise UploadRejected("filename", name)

    if sniff_mime(payload, declared) is None:
        raise UploadRejected("content", declared)
    return declared


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
    """Boolean form of :func:`validate_upload`, for callers that do not need
    the reason.

    Kept because it is a public helper with its own tests, but it no longer has
    an implementation of its own: it delegates. A second, weaker copy of the
    rule is how the three upload paths drifted in the first place.

    The size cap is deliberately not applied here. This predicate is about type
    agreement, and a caller that also has a cap applies it through
    ``validate_upload(..., max_bytes=...)``.
    """
    try:
        validate_upload(payload, filename, declared,
                        max_bytes=None)
    except UploadRejected:
        return False
    return True


__all__ = ["ALLOWED_MIME", "MAX_UPLOAD_BYTES", "UploadRejected",
           "declared_mime", "is_allowed_upload", "sniff_mime",
           "stored_extension", "validate_upload"]
