"""Brand identity: one resolver, one asset store, one set of rules.

Three things used to resolve a tenant's identity, and they disagreed:

  * ``User.get_brand()`` picked branding by the projects the user belongs to.
  * the ``inject_globals`` context processor picked the newest active row in the
    whole table, for every authenticated user.
  * ``base.html`` called the first, while the footer and the ``<title>`` used
    the second.

So one page could show Project A's logo in the header and Project B's company
name in the footer. Everything now goes through :func:`resolve_brand`, which is
cached per request, and templates read ``current_brand``.

Logos are stored as keys relative to the asset root, never as absolute paths.
The previous store returned ``C:\\...\\app\\backups\\images\\...`` and wrote it
into the database, which broke the moment the application moved to another
machine or container, and meant no browser could ever be handed a URL for an
uploaded logo - which is why the header could only ever show the vendor logo.
"""
from __future__ import annotations

import os
import re
import secrets

from flask import current_app, g

HEX_RE = re.compile(r"\A#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")

#: Formats accepted for a logo, mapped to the content type the browser and the
#: PDF renderer are given. SVG is deliberately absent: an SVG is a program, and
#: an uploaded one served from this origin runs with the session of whoever
#: opens the page.
ALLOWED_LOGO_FORMATS = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}

MAX_LOGO_BYTES = 2 * 1024 * 1024

DEFAULT_PRIMARY = "#1e3a5f"
DEFAULT_SECONDARY = "#c9a227"


class LogoRejected(ValueError):
    """The uploaded file is not a logo we are willing to store."""


def asset_root() -> str:
    return os.path.join(current_app.root_path, "uploads", "branding")


def normalise_hex(value: str | None, fallback: str) -> str:
    """Return a safe 6-digit hex, or ``fallback``.

    The value reaches an inline ``<style>`` block, where HTML autoescaping does
    not apply: ``red;} body{display:none`` is inert as a string and live as
    CSS. Anything that is not a hex colour is refused.
    """
    candidate = str(value or "").strip()
    if not HEX_RE.match(candidate):
        return fallback
    if len(candidate) == 4:
        return "#" + "".join(ch * 2 for ch in candidate[1:])
    return candidate.lower()


def sniff_logo_format(data: bytes) -> str:
    """Identify an image by its magic bytes, ignoring the filename."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    raise LogoRejected("الملف ليس صورة PNG أو JPEG أو WebP.")


def store_logo(filename: str, data: bytes) -> str:
    """Validate and save a logo; return the key relative to the asset root.

    A failure to write is reported as a rejection, not as an OSError. A full
    disk or a permission problem must not take down the form that submitted
    the logo, and the caller only knows how to handle one kind of failure.
    """
    if not data:
        raise LogoRejected("الملف فارغ.")
    if len(data) > MAX_LOGO_BYTES:
        raise LogoRejected("حجم الشعار يجب ألا يتجاوز 2 ميجابايت.")
    ext, _content_type = ALLOWED_LOGO_FORMATS[sniff_logo_format(data)]
    root = asset_root()
    key = f"{secrets.token_hex(8)}.{ext}"
    try:
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, key), "wb") as fh:
            fh.write(data)
    except OSError as exc:
        raise LogoRejected(f"تعذّر حفظ الشعار على الخادم ({exc}).") from exc
    return key


def logo_path(key: str) -> str | None:
    """Absolute path for a stored logo, or None.

    A relative key is looked up first in the branding directory, then under
    the image store, because project logos and tenant logos are written by two
    different upload paths and both are keyed relative to their own root now.

    Absolute paths written by earlier versions are still honoured, so existing
    projects keep their header until the logo is uploaded again.
    """
    if not key:
        return None
    candidate = str(key)
    if os.path.isabs(candidate):
        return candidate if os.path.isfile(candidate) else None
    for root in (asset_root(), image_root()):
        real_root = os.path.realpath(root)
        resolved = os.path.realpath(os.path.join(real_root, candidate))
        if resolved != real_root and not resolved.startswith(real_root + os.sep):
            continue
        if os.path.isfile(resolved):
            return resolved
    return None


def image_root() -> str:
    from app.services.storage import BACKUP_LOCAL_DIR
    return BACKUP_LOCAL_DIR


def logo_url(key: str) -> str | None:
    """Browser URL for a stored logo, or None when there is no usable file."""
    if not key:
        return None
    if os.path.isabs(str(key)):
        return None
    return f"/uploads/branding/{key}"


def delete_logo(key: str) -> None:
    path = logo_path(key)
    if not path or os.path.isabs(str(key)):
        return
    try:
        os.remove(path)
    except OSError:
        pass


class BrandView:
    """Resolved identity for the current request, with fallbacks applied."""

    __slots__ = ("row", "company_ar", "company_en", "primary", "secondary",
                 "logo_path", "logo2_path", "logo_url", "logo2_url",
                 "header_ar", "header_en", "footer_notes", "disclaimer",
                 "app_name")

    def __init__(self, row, cfg):
        self.row = row
        self.app_name = cfg.get("APP_NAME_AR") or ""
        self.company_ar = (getattr(row, "company_name_ar", "") or "").strip() \
            or (cfg.get("COMPANY_NAME_AR") or "")
        self.company_en = (getattr(row, "company_name_en", "") or "").strip() \
            or (cfg.get("COMPANY_NAME_EN") or "")
        self.primary = normalise_hex(
            getattr(row, "primary_color", ""), DEFAULT_PRIMARY)
        self.secondary = normalise_hex(
            getattr(row, "secondary_color", ""), DEFAULT_SECONDARY)
        self.logo_path = (getattr(row, "logo_path", "") or "").strip()
        self.logo2_path = (getattr(row, "logo2_path", "") or "").strip()
        self.logo_url = logo_url(self.logo_path) or self._fallback_logo()
        self.logo2_url = logo_url(self.logo2_path)
        self.header_ar = (getattr(row, "custom_header_text_ar", "") or "").strip()
        self.header_en = (getattr(row, "custom_header_text_en", "") or "").strip()
        self.footer_notes = (getattr(row, "custom_footer_notes", "") or "").strip()
        self.disclaimer = (getattr(row, "disclaimer_text", "") or "").strip()

    def _fallback_logo(self) -> str:
        try:
            return current_app.url_for("static",
                                        filename="img/brand/azad-logo.png")
        except RuntimeError:
            return "/static/img/brand/azad-logo.png"

    @property
    def has_logo(self) -> bool:
        return bool(self.logo_url)

    @property
    def is_default_logo(self) -> bool:
        return not logo_url(self.logo_path)


def _project_ids_for(user) -> list[int]:
    from app.ops.models import ProjectMember
    return [pm.project_id for pm in
            ProjectMember.query.filter_by(user_id=user.id).all()]


def resolve_brand(user=None) -> BrandView:
    """The identity for this request. Cached on ``g`` for the whole request."""
    cached = getattr(g, "_brand_view", None)
    if cached is not None:
        return cached

    from app.models import TenantBranding
    row = None
    if user is not None and getattr(user, "is_authenticated", False):
        project_ids = _project_ids_for(user)
        if project_ids:
            row = (TenantBranding.query
                   .filter(TenantBranding.project_id.in_(project_ids))
                   .filter_by(is_active=True)
                   .order_by(TenantBranding.updated_at.desc())
                   .first())
        if row is None and getattr(user, "norm_role", "") in {
                "superadmin", "admin", "project_manager", "project_director"}:
            row = (TenantBranding.query.filter_by(is_active=True)
                   .order_by(TenantBranding.updated_at.desc()).first())

    view = BrandView(row, current_app.config)
    g._brand_view = view
    return view


def branding_for_project(project_id) -> BrandView:
    """Identity for one project, used when rendering a report or a PDF."""
    from app.models import TenantBranding
    row = None
    if project_id:
        row = (TenantBranding.query
               .filter_by(project_id=project_id, is_active=True)
               .order_by(TenantBranding.updated_at.desc()).first())
    return BrandView(row, current_app.config)
