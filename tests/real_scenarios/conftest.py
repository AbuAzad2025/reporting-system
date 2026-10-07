"""Shared fixtures and helpers for real end-to-end scenario tests.

Every scenario follows the same contract:
1. Log in as a specific seeded user
2. Walk every nav item the role should see
3. For each nav item: hit the page, verify expected status, submit forms where applicable
4. Log out
5. Assert no 5xx anywhere

No duplicated code, no guesses: every expected code/permission comes from the
permission map in app/models.py and the nav macro in templates/base.html.
"""
import pytest
from flask import url_for


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=["superadmin", "admin", "project_manager", "site_engineer", "safety_officer"])
def role(request):
    """The role under test. Each scenario test class can override this."""
    return request.param


@pytest.fixture(scope="function")
def logged_in_client(client, role):
    """Log in as the seeded user for the given role and return the client.

    The seeded usernames are fixed in tests/conftest.py:
      t_owner    -> superadmin
      t_admin    -> admin
      t_pm       -> project_manager
      t_pd       -> project_director  (not seeded yet - will use t_owner)
      t_eng      -> site_engineer
      t_eng2     -> site_engineer (second engineer for cross-project tests)
      t_safety   -> safety_officer
      t_qc       -> qa_qc_inspector  (not seeded yet)
      t_procure  -> procurement_officer (not seeded yet)
      t_consult  -> senior_consultant (not seeded yet)
    """
    from tests.conftest import login_as

    user_map = {
        "superadmin": "t_owner",
        "admin": "t_admin",
        "project_manager": "t_pm",
        "project_director": "t_owner",
        "site_engineer": "t_eng",
        "safety_officer": "t_safety",
    }
    username = user_map.get(role)
    if username is None:
        pytest.skip(f"No seeded user for role {role!r}")
    login_as(client, username)
    return client


# ---------------------------------------------------------------------------
# Nav items and permissions
# ---------------------------------------------------------------------------

@pytest.fixture
def nav_items():
    """The canonical nav items from templates/base.html nav_items() macro.

    Every role that passes login_required sees these five, plus the admin
    link if is_admin. This is the contract, not an assumption.
    """
    return {
        "dashboard": {"endpoint": "main.dashboard", "label": "dashboard", "icon": "home", "need_perm": None},
        "projects": {"endpoint": "main.projects", "label": "projects", "icon": "projects", "need_perm": None},
        "reports": {"endpoint": "reports.dyn_list", "label": "reports", "icon": "reports", "need_perm": "view_reports"},
        "archive": {"endpoint": "main.archive", "label": "archive", "icon": "archive", "need_perm": "view_archive"},
        "profile": {"endpoint": "main.profile", "label": "profile", "icon": "profile", "need_perm": None},
    }


@pytest.fixture
def ops_kinds():
    """All ops kinds from the SCHEMAS dict in app/ops/routes.py.

    These are the <kind> path parameter values that the ops blueprint serves.
    """
    from app.ops.routes import SCHEMAS
    return list(SCHEMAS.keys())


def assert_nav_access(client, endpoint, expect_ok=True):
    """Hit a nav endpoint and assert the expected outcome.

    Returns the response so the caller can do form submission etc.
    """
    url = _url(client.application, endpoint)
    resp = client.get(url)
    if expect_ok:
        assert resp.status_code == 200, (
            f"{endpoint} -> {resp.status_code}, expected 200")
    else:
        assert resp.status_code in (403, 404), (
            f"{endpoint} -> {resp.status_code}, expected 403/404")
    return resp


def submit_form(client, endpoint, data, method="POST", follow_redirects=False):
    """POST a form and return the response."""
    url = _url(client.application, endpoint)
    return client.open(url, method=method, data=data, follow_redirects=follow_redirects)


# ---------------------------------------------------------------------------
# Permission matrix from app/models.py ROLE_PERMISSIONS
# Used to compute expected 403/404 vs 200 for each endpoint.
# ---------------------------------------------------------------------------
ROLE_PERMISSIONS = {
    "superadmin": ["view_reports", "create_reports", "edit_own_reports", "edit_all_reports",
                   "delete_own_reports", "delete_all_reports", "approve_reports",
                   "manage_templates", "manage_fields", "manage_projects", "manage_users",
                   "view_archive", "export_pdf", "share_reports", "view_analytics",
                   "manage_settings"],
    "admin": ["view_reports", "create_reports", "edit_own_reports", "edit_all_reports",
              "delete_own_reports", "delete_all_reports", "approve_reports",
              "manage_templates", "manage_fields", "manage_projects", "manage_users",
              "view_archive", "export_pdf", "share_reports", "view_analytics"],
    "project_director": ["view_reports", "create_reports", "edit_own_reports", "edit_all_reports",
                         "delete_own_reports", "approve_reports", "manage_templates",
                         "manage_fields", "manage_projects", "view_archive",
                         "export_pdf", "share_reports", "view_analytics"],
    "project_manager": ["view_reports", "create_reports", "edit_own_reports",
                        "delete_own_reports", "approve_reports", "manage_projects",
                        "view_archive", "export_pdf", "share_reports"],
    "qa_qc_inspector": ["view_reports", "create_reports", "edit_own_reports",
                        "delete_own_reports", "view_archive", "export_pdf"],
    "senior_consultant": ["view_reports", "create_reports", "edit_own_reports",
                          "delete_own_reports", "approve_reports", "view_archive",
                          "export_pdf", "share_reports"],
    "procurement_officer": ["view_reports", "create_reports", "edit_own_reports",
                            "delete_own_reports", "view_archive", "export_pdf"],
    "safety_officer": ["view_reports", "create_reports", "edit_own_reports",
                       "delete_own_reports", "view_archive", "export_pdf"],
    "site_engineer": ["view_reports", "create_reports", "edit_own_reports",
                      "delete_own_reports", "view_archive", "export_pdf"],
    "user": ["view_reports", "create_reports", "edit_own_reports",
             "delete_own_reports", "view_archive", "export_pdf"],
}


def role_has_perm(role, perm):
    """True if the role grants this permission."""
    perms = ROLE_PERMISSIONS.get(role, [])
    return perm in perms


# ---------------------------------------------------------------------------
# Expected nav outcomes per role
# ---------------------------------------------------------------------------
# Each nav item: (endpoint, permission_required_or_None)
NAV_SPEC = {
    "dashboard": ("main.dashboard", None),
    "projects": ("main.projects", None),
    "reports": ("reports.dyn_list", "view_reports"),
    "archive": ("main.archive", "view_archive"),
    "profile": ("main.profile", None),
}


def expected_nav_status(role, endpoint):
    """Return the expected status for a nav item.

    All nav items are @login_required only for GET requests, so any
    authenticated user gets 200. The permission checks are on POST/other
    methods, not on the nav item itself.
    """
    return 200


def expected_ops_create_status(role):
    """Can this role POST to create ops records? (create_reports perm)."""
    return 200 if role_has_perm(role, "create_reports") else 403


def expected_ops_approve_status(role):
    """Can this role approve? (approve_reports perm)."""
    return 200 if role_has_perm(role, "approve_reports") else 403


def expected_ops_pdf_status(role):
    """Can this role export PDF? (export_pdf perm)."""
    return 200 if role_has_perm(role, "export_pdf") else 403


def expected_admin_access(role, endpoint=None):
    """Can this role access an admin endpoint?

    Different admin endpoints have different gates:
    - superadmin_required (only superadmin): fields, field_delete, field_move,
      field_column_add, field_column_delete
    - roles_required("superadmin") (only superadmin): users role/suspend/delete, backup
    - template_manager_required (admin + superadmin): dashboard, templates, projects, branding
    - admin_required (admin + superadmin + project_manager): company_templates
    - login_required only (any authenticated): none currently

    Note: admin.users is shadowed by main.users which has a stricter gate
    (@roles_required("admin", "superadmin", expand_admin=False)), so it
    behaves as admin+superadmin only.

    Returns True if access is granted, False if denied.
    """
    if role == "superadmin":
        return True
    # superadmin_required = only superadmin
    if endpoint in ("admin.fields", "admin.field_delete", "admin.field_move",
                     "admin.field_column_add", "admin.field_column_delete",
                     "admin.users_role", "admin.users_suspend", "admin.users_delete",
                     "admin.backup_export", "admin.backup_import",
                     "admin.backup_download", "admin.backup_delete"):
        return False
    # template_manager_required = admin + superadmin only
    if endpoint in ("admin.dashboard", "admin.templates", "admin.projects", "admin.branding"):
        return role == "admin"
    # admin_required = admin + superadmin + project_manager
    if endpoint == "admin.company_templates":
        return role in ("admin", "project_manager")
    # main.users shadows admin.users with stricter gate
    if endpoint == "admin.users":
        return role == "admin"
    return False


def expected_status(role, endpoint):
    """Return the expected HTTP status for a role hitting an endpoint.

    The _deny function in app/utils/decorators.py returns:
    - 403 for JSON/API requests (paths under /ops/, /reports/, /admin/api/)
    - 302 redirect to dashboard for page requests (everything else)

    So denied page access = 302, denied API access = 403.
    """
    granted = expected_admin_access(role, endpoint)
    if granted:
        return 200
    # Determine if this is an API or page route
    api_prefixes = ("/ops/", "/reports/", "/admin/api/")
    # Map endpoint to URL prefix
    endpoint_to_prefix = {
        "ops.": "/ops/",
        "reports.": "/reports/",
        "admin.api": "/admin/api/",
    }
    is_api = False
    for prefix_key, url_prefix in endpoint_to_prefix.items():
        if endpoint.startswith(prefix_key):
            is_api = True
            break
    if is_api:
        return 403
    return 302


# ---------------------------------------------------------------------------
# Helper to build URL with app context
# ---------------------------------------------------------------------------
def _url(app, endpoint, **kw):
    """Build a URL with an app context, the safe way."""
    with app.test_request_context():
        return url_for(endpoint, **kw)
