"""RBAC + permissions on ops controllers."""
import pytest

from tests.conftest import login_as


def test_anonymous_is_denied(client):
    r = client.get("/ops/cost-variances")
    assert r.status_code in (302, 401)  # login redirect or unauthorized
    r = client.post("/ops/rfis", json={})
    assert r.status_code in (302, 401)


def test_engineer_can_create_in_own_project(app, eng_client):
    with app.app_context():
        from app.models import Project
        pa = Project.query.filter_by(name="Alpha Tower").first().id
    r = eng_client.post("/ops/rfis", json={
        "project_id": pa, "subject": "level clash",
        "question": "confirm FFL?", "ball_in_court": "consultant"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["serial"].startswith("RFI-")
    assert body["status"] == "pending"
    assert "مهندس اختبار" in body["signatory"] or body["signatory"]


def test_engineer_cannot_approve(client):
    login_as(client, "t_eng")
    r = client.post("/ops/cost-variances/1/approve",
                    json={"decision": "approve"})
    assert r.status_code == 403


def test_safety_officer_cannot_approve(client):
    login_as(client, "t_safety")
    r = client.post("/ops/rfis/1/approve", json={"decision": "approve"})
    assert r.status_code == 403


@pytest.mark.parametrize("manager", ["t_admin", "t_owner"])
def test_managers_can_approve_and_stamp_reviewer(client, app, manager):
    login_as(client, manager)
    r = client.post("/ops/material-submittals/1/approve",
                    json={"decision": "approve", "notes": "ok"})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "approved"
    with app.app_context():
        from app.ops.models import MaterialSubmittal
        from app.models import User
        rec = MaterialSubmittal.query.get(1)
        assert rec.reviewed_by_id == User.query.filter_by(
            username=manager).first().id
        assert rec.reviewed_at is not None


def test_reject_path_and_bad_decision(client):
    login_as(client, "t_admin")
    r = client.post("/ops/rfis/1/approve", json={"decision": "reject"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "rejected"
    r = client.post("/ops/rfis/1/approve", json={"decision": "maybe"})
    assert r.status_code == 422
