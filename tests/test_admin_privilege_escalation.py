"""Platform-admin routes must reject project_manager (privilege escalation).

A project manager is a tenant-side approver. It must never reach the platform
surfaces that create/delete templates and fields, manage projects, edit
branding, or change user roles — the last one would let it mint itself an
`admin` account and take the whole platform.
"""
import pytest

from tests.conftest import login_as

PLATFORM_ROUTES = [
    ("GET", "/admin/templates"),
    ("GET", "/admin/templates/new"),
    ("GET", "/admin/projects"),
    ("GET", "/admin/users"),
    ("GET", "/admin/branding/1"),
]

PLATFORM_POST_ROUTES = [
    "/admin/templates/new",
    "/admin/templates/reset-defaults",
    "/admin/templates/1/fields",
    "/admin/templates/1/edit",
    "/admin/templates/1/delete",
    "/admin/projects",
    "/admin/users/2/role",
    "/admin/users/2/suspend",
    "/admin/users/2/delete",
    "/admin/branding/1",
    "/admin/fields/1/delete",
    "/admin/fields/1/move/up",
    "/admin/fields/1/columns",
    "/admin/fields/1/columns/x/delete",
]


@pytest.mark.parametrize("method,url", PLATFORM_ROUTES)
def test_project_manager_cannot_read_platform_pages(client, method, url):
    login_as(client, "t_pm")
    r = client.open(url, method=method, follow_redirects=True)
    assert r.status_code == 200
    assert r.headers.get("Location") is None
    body = r.get_data(as_text=True)
    assert "لا تملك صلاحية الوصول" in body


@pytest.mark.parametrize("url", PLATFORM_POST_ROUTES)
def test_project_manager_cannot_mutate_platform_state(client, app, url):
    login_as(client, "t_pm")
    r = client.post(url, data={}, follow_redirects=True)
    assert r.status_code == 200
    assert "لا تملك صلاحية الوصول" in r.get_data(as_text=True)


def test_project_manager_cannot_promote_anyone_to_admin(client, app):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        victim = User(username="escalation_victim",
                      email="victim@escalation.test",
                      full_name="مستخدم ضحية تصعيد الصلاحيات",
                      role="site_engineer")
        victim.set_password("pw12345")
        db.session.add(victim)
        db.session.commit()
        victim_id = victim.id
    login_as(client, "t_pm")
    client.post(f"/admin/users/{victim_id}/role",
                data={"role": "admin"}, follow_redirects=True)
    with app.app_context():
        assert db.session.get(User, victim_id).role == "site_engineer"


def test_project_manager_cannot_reset_default_templates(client, app):
    from app.models import ReportTemplate
    with app.app_context():
        before = ReportTemplate.query.count()
    login_as(client, "t_pm")
    client.post("/admin/templates/reset-defaults", follow_redirects=True)
    with app.app_context():
        assert ReportTemplate.query.count() == before


def test_admin_and_superadmin_still_reach_the_platform(client):
    for username in ("t_admin", "t_owner"):
        login_as(client, username)
        assert client.get("/admin/templates").status_code == 200
        assert client.get("/admin/users").status_code == 200


def test_strict_gate_does_not_change_legacy_admin_expansion(app):
    from flask import g, session
    from app.models import User
    from app.utils.decorators import roles_required

    def _view():
        return "ok"

    legacy = roles_required("admin")(_view)
    strict = roles_required("admin", expand_admin=False)(_view)
    with app.app_context():
        pm_id = User.query.filter_by(username="t_pm").first().id
    with app.test_request_context("/admin/users"):
        g.pop("_login_user", None)
        session["_user_id"] = str(pm_id)
        assert legacy() == "ok"
        assert strict().status_code == 302
