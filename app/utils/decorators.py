"""Role helpers + access decorators for the multi-tier RBAC model."""
from functools import wraps
from flask import flash, redirect, url_for
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
            if not current_user.is_authenticated or \
                    norm_role(getattr(current_user, "role", "")) not in allowed:
                flash("صلاحيات غير كافية للوصول إلى هذه الصفحة.", "danger")
                return redirect(url_for("main.dashboard"))
            return view(*args, **kwargs)
        return wrapper
    return deco


def permission_required(*perms):
    """Require user to have ALL specified permissions (fail-closed)."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("يرجى تسجيل الدخول أولاً.", "warning")
                return redirect(url_for("auth.login"))
            if not current_user.has_all_perms(*perms):
                flash("صلاحيات غير كافية لتنفيذ هذا الإجراء.", "danger")
                return redirect(url_for("main.dashboard"))
            return view(*args, **kwargs)
        return wrapper
    return deco


def any_permission_required(*perms):
    """Require user to have AT LEAST ONE of the specified permissions."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("يرجى تسجيل الدخول أولاً.", "warning")
                return redirect(url_for("auth.login"))
            if not current_user.has_any_perm(*perms):
                flash("صلاحيات غير كافية لتنفيذ هذا الإجراء.", "danger")
                return redirect(url_for("main.dashboard"))
            return view(*args, **kwargs)
        return wrapper
    return deco


admin_required = roles_required("admin", "superadmin", "project_manager")
superadmin_required = roles_required("superadmin")
template_manager_required = roles_required("admin", "superadmin")
