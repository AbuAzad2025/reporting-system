"""Fail-closed Row Level Security (ORM layer) + IDOR protection.

Tenant boundary = Project. A user may touch a record iff:
  1. they hold a platform-manager global role (superadmin/admin/project_manager), OR
  2. a ProjectMember row links them to the record's project.

Everyone else sees NOTHING — not even existence:
  * object access outside scope -> 404 (no enumeration oracle for IDOR probes)
  * action denied by role (e.g. approve) -> 403 (explicit, auditable)
"""
from functools import wraps
from flask import abort, jsonify
from flask_login import current_user

from app.extensions import db
from app.models import MANAGER_ROLES


def _norm_role(user) -> str:
    return {"user": "site_engineer"}.get(getattr(user, "role", ""),
                                         getattr(user, "role", "") or "")


def is_platform_manager(user) -> bool:
    """Global staff bypass project scoping (they are not tenants)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return _norm_role(user) in MANAGER_ROLES


def accessible_project_ids(user):
    """None = all projects (manager). Otherwise the member-project id set.

    Fail-closed: unknown/anonymous/role-less users get the empty set.
    """
    from app.ops.models import ProjectMember
    if not getattr(user, "is_authenticated", False):
        return set()
    if is_platform_manager(user):
        return None
    rows = db.session.query(ProjectMember.project_id).filter_by(
        user_id=user.id).all()
    return {r[0] for r in rows}


def can_access_project(user, project_id) -> bool:
    if project_id is None:
        return False
    if is_platform_manager(user):
        return True
    ids = accessible_project_ids(user)
    return ids is not None and int(project_id) in ids


def scope_to_tenant(query, model, user):
    """Apply tenant filter to a query over a model with project_id."""
    if is_platform_manager(user):
        return query
    ids = accessible_project_ids(user)
    if not ids:
        return query.filter(db.false())  # fail-closed: match nothing
    return query.filter(model.project_id.in_(ids))


def get_object_or_404_tenant(model, obj_id, user):
    """Fetch + tenant check. Cross-tenant or missing -> 404 (IDOR-safe)."""
    obj = db.session.get(model, int(obj_id))
    if obj is None:
        abort(404)
    if not can_access_project(user, obj.project_id):
        abort(404)  # deliberately indistinguishable from missing
    return obj


def tenant_create_guard(user, project_id):
    """Abort 404 when creating under an out-of-scope project (no oracle)."""
    from app.models import Project
    project = db.session.get(Project, int(project_id)) \
        if str(project_id).isdigit() else None
    if project is None or not can_access_project(user, project.id):
        abort(404)
    return project


def visible_projects(user, active_only: bool = True):
    """Projects the user may see/link: all active (manager) or member rows.

    Single choke point for every project picker in the UI.
    """
    from app.models import Project
    from app.ops.models import ProjectMember
    q = Project.query.order_by(Project.name)
    if active_only:
        q = q.filter_by(is_active=True)
    if is_platform_manager(user):
        return q.all()
    ids = [r[0] for r in db.session.query(
        ProjectMember.project_id).filter_by(user_id=user.id).all()]
    return q.filter(Project.id.in_(ids)).all() if ids else []


def get_linked_project_or_404(user, project_id):
    """Validate a linked project id from a form: digit + exists + in scope.

    Returns the Project; aborts 404 otherwise (no existence oracle).
    Linked reports sync their project_name from the project (single source).
    """
    from app.models import Project
    if not str(project_id or "").isdigit():
        abort(404)
    project = db.session.get(Project, int(project_id))
    if project is None or not can_access_project(user, project.id):
        abort(404)
    return project


def membership_role(user, project_id):
    """The user's row role on a project, or None (platform managers bypass)."""
    from app.ops.models import ProjectMember
    if is_platform_manager(user):
        return "manager"
    row = ProjectMember.query.filter_by(
        user_id=user.id, project_id=int(project_id)).first()
    return row.role_in_project if row else None


def roles_required_json(*roles):
    """Role gate for JSON controllers: authenticated + role match else 403."""
    allowed = set(roles)
    if "admin" in allowed:
        allowed |= {"superadmin", "project_manager"}

    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not getattr(current_user, "is_authenticated", False):
                return jsonify({"error": "authentication required"}), 401
            if _norm_role(current_user) not in allowed:
                return jsonify({"error": "insufficient permissions"}), 403
            return view(*args, **kwargs)
        return wrapper
    return deco
