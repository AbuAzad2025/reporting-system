"""Role helpers + access decorators for the multi-tier RBAC model.

Fail-closed by design: every decorator returns an explicit denial response
(403 for authenticated users, 401 for unauthenticated JSON/API requests) and
never silently falls through to the protected view.
"""
from functools import wraps
from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user

# Role hierarchy (low -> high privilege)
ROLE_ORDER = ["site_engineer", "safety_officer", "procurement_officer",
              "qa_qc_inspector", "senior_consultant", "project_manager",
              "project_director", "admin", "superadmin"]
# Legacy aliases still stored in old rows
LEGACY_ROLE_MAP = {"user": "site_engineer"}

MANAGER_ROLES = {"admin", "superadmin", "project_manager", "project_director"}
TEMPLATE_MANAGER_ROLES = {"admin", "superadmin"}
USER_MANAGER_ROLES = {"admin", "superadmin"}


def norm_role(role: str) -> str:
    role = role or "site_engineer"
    # Legacy aliases
    if role in LEGACY_ROLE_MAP:
        return LEGACY_ROLE_MAP[role]
    # Valid roles
    valid_roles = {"superadmin", "admin", "project_manager", "project_director",
                   "qa_qc_inspector", "senior_consultant", "procurement_officer",
                   "safety_officer", "site_engineer"}
    return role if role in valid_roles else "site_engineer"


#: URL prefixes served as machine-readable JSON APIs (denials are 401/403,
#: never login redirects) — page routes outside these get flash+redirect.
JSON_API_PREFIXES = ("/ops/", "/reports/", "/admin/api/")


def _is_json_request() -> bool:
    """True for API/JSON callers so denials are machine-readable (403/401)."""
    return (request.is_json
            or request.path.startswith(JSON_API_PREFIXES))


def _deny(message: str, code: int):
    """Unified denial response: JSON for API, flash+redirect for pages.

    JSON keeps stable English codes (machine contract, asserted by tests);
    page flashes are Arabic (human UI language).
    """
    if _is_json_request():
        return jsonify({"error": message}), code
    if code == 401:
        flash("يرجى تسجيل الدخول أولاً للوصول إلى هذه الصفحة.", "warning")
    else:
        flash("لا تملك صلاحية الوصول إلى هذه الصفحة.", "danger")
    return redirect(url_for("main.dashboard"))


def has_role(*roles) -> bool:
    if not current_user.is_authenticated:
        return False
    return norm_role(getattr(current_user, "role", "")) in set(roles)


def roles_required(*roles):
    """Allow only the given roles (legacy 'admin' counts as manager)."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            allowed = set(roles)
            # legacy compat: 'admin' gate also admits superadmin/project_manager
            if "admin" in allowed:
                allowed |= {"superadmin", "project_manager"}
            if not current_user.is_authenticated:
                return _deny("authentication required", 401)
            if norm_role(getattr(current_user, "role", "")) not in allowed:
                return _deny("insufficient permissions", 403)
            return view(*args, **kwargs)
        return wrapper
    return deco


def permission_required(*perms):
    """Require user to have ALL specified permissions (fail-closed)."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return _deny("authentication required", 401)
            if not current_user.has_all_perms(*perms):
                return _deny("insufficient permissions", 403)
            return view(*args, **kwargs)
        return wrapper
    return deco


def any_permission_required(*perms):
    """Require user to have AT LEAST ONE of the specified permissions."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return _deny("authentication required", 401)
            if not current_user.has_any_perm(*perms):
                return _deny("insufficient permissions", 403)
            return view(*args, **kwargs)
        return wrapper
    return deco


admin_required = roles_required("admin", "superadmin", "project_manager")
superadmin_required = roles_required("superadmin")
template_manager_required = roles_required("admin", "superadmin")
