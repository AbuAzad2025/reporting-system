"""Tenant isolation + IDOR prevention (fail-closed, no oracle leaks)."""
from tests.conftest import login_as


def _ids(app):
    with app.app_context():
        from app.models import Project
        from app.ops.models import CostVariance
        pa = Project.query.filter_by(name="Alpha Tower").first().id
        pb = Project.query.filter_by(name="Beta Hospital").first().id
        in_b = CostVariance.query.filter_by(serial="CVR-000002").first().id
        in_a = CostVariance.query.filter_by(serial="CVR-000001").first().id
    return pa, pb, in_a, in_b


def test_isolation_helper_fail_closed_paths(app):
    from types import SimpleNamespace
    import pytest
    from werkzeug.exceptions import NotFound
    from app.ops.isolation import (accessible_project_ids, can_access_project,
                                   get_linked_project_or_404, is_platform_manager)

    anonymous = SimpleNamespace(is_authenticated=False)
    manager = SimpleNamespace(is_authenticated=True, role="admin")
    assert is_platform_manager(None) is False
    assert accessible_project_ids(anonymous) == set()
    assert accessible_project_ids(manager) is None
    assert can_access_project(manager, None) is False
    with app.app_context():
        with pytest.raises(NotFound):
            get_linked_project_or_404(manager, "not-a-project")


def test_roles_required_json_rejects_anonymous(app):
    from app.ops.isolation import roles_required_json

    @roles_required_json("admin")
    def view():
        return "ok"

    with app.test_request_context():
        response, status = view()
        assert status == 401
        assert response.get_json() == {"error": "authentication required"}


def test_cross_tenant_read_is_404_not_403(app, client):
    # t_eng belongs to Alpha only; Beta's CVR-000002 must look nonexistent
    login_as(client, "t_eng")
    _pa, _pb, _a, in_b = _ids(app)
    assert client.get(f"/ops/cost-variances/{in_b}").status_code == 404
    assert client.get(f"/ops/cost-variances/{in_b}/pdf").status_code == 404


def test_cross_tenant_write_is_404(app, client):
    login_as(client, "t_eng")
    _pa, _pb, _a, in_b = _ids(app)
    assert client.put(f"/ops/cost-variances/{in_b}",
                      json={"reason": "x"}).status_code == 404
    assert client.delete(f"/ops/cost-variances/{in_b}").status_code == 404
    assert client.post(f"/ops/cost-variances/{in_b}/approve",
                       json={"decision": "approve"}).status_code in (403, 404)


def test_create_under_foreign_project_is_404(app, client):
    login_as(client, "t_eng")
    _pa, pb, _a, _b = _ids(app)
    r = client.post("/ops/rfis", json={"project_id": pb, "subject": "s",
                                       "question": "q"})
    assert r.status_code == 404


def test_project_move_to_foreign_project_is_404(app, client):
    login_as(client, "t_eng")
    _pa, pb, in_a, _b = _ids(app)
    r = client.put(f"/ops/cost-variances/{in_a}", json={"project_id": pb})
    assert r.status_code == 404


def test_listing_is_tenant_scoped(app, client):
    login_as(client, "t_eng")
    serials = {r["serial"] for r in
               client.get("/ops/cost-variances").get_json()["results"]}
    assert "CVR-000001" in serials and "CVR-000002" not in serials
    login_as(client, "t_eng2")  # Beta member sees only Beta
    serials = {r["serial"] for r in
               client.get("/ops/cost-variances").get_json()["results"]}
    assert serials == {"CVR-000002"}


def test_manager_global_bypass_sees_all(app, client):
    login_as(client, "t_admin")
    serials = {r["serial"] for r in
               client.get("/ops/cost-variances").get_json()["results"]}
    assert {"CVR-000001", "CVR-000002"} <= serials
    _pa, _pb, _a, in_b = _ids(app)
    assert client.get(f"/ops/cost-variances/{in_b}").status_code == 200


def test_memberless_user_sees_nothing(client, app):
    with app.app_context():
        from app.models import User
        from app.extensions import db
        u = User(username="t_lonely", email="lonely@t.com",
                 full_name="مستخدم بلا مشروع اختبار", role="site_engineer")
        u.set_password("pw12345")
        db.session.add(u)
        db.session.commit()
    login_as(client, "t_lonely")
    assert client.get("/ops/cost-variances").get_json()["results"] == []
    assert client.get("/ops/api/archive").get_json()["total"] == 0


def test_ghost_project_create_is_404(eng_client):
    r = eng_client.post("/ops/rfis", json={"project_id": 999999,
                                           "subject": "s", "question": "q"})
    assert r.status_code == 404
