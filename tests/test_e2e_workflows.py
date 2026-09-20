"""WORKSTREAM 4: end-to-end lifecycle across all nine ops modules.

Full chain per module: engineer creates → attachment → dual-party
feedback → reject → resubmit → RBAC-denied approve → manager approve →
amendment → approve amendment → history → PDF → archive.
"""
import io

import pytest

from tests.conftest import login_as

KINDS = ["site-inspections", "material-submittals", "rfis",
         "cost-variances", "progress-billings",
         "subcontractor-performances", "daily-reports",
         "variation-orders", "safety-reports"]

PAYLOADS = {
    "site-inspections": {"test_category": "concrete", "test_type": "cube 7d",
                         "verdict": "pass", "result_value": 30,
                         "acceptance_min": 25},
    "material-submittals": {"material_name": "rebar", "quantity": 40},
    "rfis": {"subject": "clash", "question": "duct vs beam?",
             "ball_in_court": "consultant"},
    "cost-variances": {"boq_item": "concrete", "budgeted_qty": 10,
                       "budgeted_rate": 100, "actual_qty": 12,
                       "actual_rate": 110},
    "progress-billings": {"work_item": "slab", "qty_completed": 10,
                          "rate": 1000},
    "subcontractor-performances": {"subcontractor": "ACME",
                                   "quality_score": 90},
    "daily-reports": {"weather": "مشمس", "temp_c": 30.0, "work_hours": 8.0,
                       "engineers_count": 2, "technicians_count": 3,
                       "labor_count": 28,
                       "labor_table": [{"trade": "حدادة", "count": 8}],
                       "equipment_table": [{"eq_type": "رافعة", "qty": 1, "hours": 8, "status": "operating"}],
                       "work_fronts": [{"area": "الدور الثالث", "activity": "صب أعمدة", "progress_pct": 50}]},
    "variation-orders": {"title": "تعميق الأساسات", "description": "وصف فني",
                         "cost_impact": 1000, "time_impact_days": 2},
    "safety-reports": {"area": "الدور الثالث", "hazard": "غياب حواجز",
                       "risk_level": "مرتفع"},
}


def _alpha_pid(client):
    from app.models import Project
    with client.application.app_context():
        return Project.query.filter_by(name="Alpha Tower").first().id


@pytest.mark.parametrize("kind", KINDS)
def test_full_lifecycle_e2e(client, kind):
    pid = _alpha_pid(client)

    # 1. engineer creates (pending)
    login_as(client, "t_eng")
    r = client.post(f"/ops/{kind}",
                    json={"project_id": pid, **PAYLOADS[kind]})
    assert r.status_code == 201, f"{kind} create: {r.get_json()}"
    rec = r.get_json()
    oid, serial = rec["id"], rec["serial"]
    assert rec["status"] == "pending"

    # 2. evidence attachment (bytes round-trip later)
    payload = b"e2e-evidence"
    r = client.post(f"/ops/{kind}/{oid}/attachments", data={
        "file": (io.BytesIO(payload), "proof.jpg")},
        content_type="multipart/form-data")
    assert r.status_code == 201, f"{kind} attach: {r.get_json()}"
    att_id = r.get_json()["id"]

    # 3. dual-party feedback: consultant review + contractor reply
    login_as(client, "t_admin")
    r = client.post(f"/ops/{kind}/{oid}/comments",
                    json={"body": "مراجعة إدارية: دقق البيانات"})
    assert r.status_code == 201
    assert r.get_json()["party"] == "consultant"
    login_as(client, "t_eng")
    r = client.post(f"/ops/{kind}/{oid}/comments",
                    json={"body": "تم التدقيق"})
    assert r.status_code == 201
    assert r.get_json()["party"] == "contractor"

    # 4. reject → resubmit (rework loop)
    login_as(client, "t_admin")
    r = client.post(f"/ops/{kind}/{oid}/approve",
                    json={"decision": "reject", "notes": "نقص"})
    assert r.status_code == 200, f"{kind} reject: {r.get_json()}"
    assert r.get_json()["status"] == "rejected"
    login_as(client, "t_eng")
    r = client.post(f"/ops/{kind}/{oid}/submit")
    assert r.status_code == 200, f"{kind} submit: {r.get_json()}"

    # 5. RBAC: engineer cannot approve; manager can
    r = client.post(f"/ops/{kind}/{oid}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 403
    login_as(client, "t_admin")
    r = client.post(f"/ops/{kind}/{oid}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200, f"{kind} approve: {r.get_json()}"
    assert r.get_json()["status"] == "approved"

    # 6. amendment via PUT (immutable trail)
    login_as(client, "t_eng")
    r = client.put(f"/ops/{kind}/{oid}", json={"report_date": "2026-09-16"})
    assert r.status_code == 201, f"{kind} amend: {r.get_json()}"
    am_id = r.get_json()["id"]
    r = client.post(f"/ops/{kind}/{am_id}/submit")
    assert r.status_code == 200
    login_as(client, "t_admin")
    r = client.post(f"/ops/{kind}/{am_id}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200

    # 7. history shows the two-generation chain
    r = client.get(f"/ops/{kind}/{oid}/history")
    assert r.status_code == 200
    versions = r.get_json()["versions"]
    assert [v["status"] for v in versions] == ["amended", "approved"]

    # 8. PDF renders for both generations
    assert client.get(f"/ops/{kind}/{oid}/pdf").status_code == 200
    r = client.get(f"/ops/{kind}/{am_id}/pdf")
    assert r.status_code == 200 and r.data[:5] == b"%PDF-"

    # 9. attachment bytes survive the lifecycle
    login_as(client, "t_eng")
    r = client.get(f"/ops/{kind}/{oid}/attachments/{att_id}/download")
    assert r.status_code == 200 and r.data == payload

    # 10. comments thread intact
    r = client.get(f"/ops/{kind}/{oid}/comments")
    assert len(r.get_json()["comments"]) == 2

    # 11. archive surfaces the serial
    r = client.get(f"/ops/api/archive?q={serial}")
    assert r.status_code == 200
    assert any(row["serial"] == serial
               for row in r.get_json()["results"]), f"{kind} in archive"


def test_three_generation_chain_e2e(client):
    """approve → amend → approve → amend → approve: only latest approved."""
    login_as(client, "t_eng")
    pid = _alpha_pid(client)
    oid = client.post("/ops/cost-variances", json={
        "project_id": pid, "boq_item": "chain",
        "budgeted_qty": 10, "budgeted_rate": 100,
        "actual_qty": 12, "actual_rate": 110}).get_json()["id"]
    login_as(client, "t_admin")
    client.post(f"/ops/cost-variances/{oid}/approve",
                json={"decision": "approve"})
    current = oid
    for tag in ("v2", "v3"):
        login_as(client, "t_eng")
        current = client.put(f"/ops/cost-variances/{current}",
                             json={"boq_item": f"chain-{tag}"}
                             ).get_json()["id"]
        client.post(f"/ops/cost-variances/{current}/submit")
        login_as(client, "t_admin")
        r = client.post(f"/ops/cost-variances/{current}/approve",
                        json={"decision": "approve"})
        assert r.status_code == 200
    r = client.get(f"/ops/cost-variances/{oid}/history")
    statuses = [v["status"] for v in r.get_json()["versions"]]
    assert statuses == ["amended", "amended", "approved"]


def test_rbac_cross_role_e2e(client):
    """One record, three roles: eng creates, safety blocked, admin
    approves, owner sees it in cross-tenant analytics."""
    login_as(client, "t_eng")
    pid = _alpha_pid(client)
    oid = client.post("/ops/rfis", json={
        "project_id": pid, "subject": "e2e-rbac", "question": "q?",
        "ball_in_court": "consultant"}).get_json()["id"]
    login_as(client, "t_safety")
    assert client.post(f"/ops/rfis/{oid}/approve",
                       json={"decision": "approve"}).status_code == 403
    login_as(client, "t_admin")
    assert client.post(f"/ops/rfis/{oid}/approve",
                       json={"decision": "approve"}).status_code == 200
    login_as(client, "t_owner")
    data = client.get("/admin/api/analytics").get_json()
    assert data["by_kind"]["rfis"]["by_status"].get("approved", 0) >= 1


def test_batch_export_e2e(client):
    """Admin aggregates a project range into one PDF."""
    login_as(client, "t_admin")
    pid = _alpha_pid(client)
    r = client.post("/ops/batch-export",
                    json={"project_id": pid,
                          "from": "2020-01-01", "to": "2030-01-01"})
    assert r.status_code == 200, r.get_json()
    assert r.content_type == "application/pdf"
    assert r.data[:5] == b"%PDF-"


def test_delete_draft_cascades_everything_e2e(client):
    """Draft delete removes bytes, attachment rows, and feedback threads."""
    import os
    from app.ops.models import Attachment, OpsRecordComment
    login_as(client, "t_eng")
    pid = _alpha_pid(client)
    oid = client.post("/ops/rfis", json={
        "project_id": pid, "subject": "doomed", "question": "q?",
        "ball_in_court": "consultant"}).get_json()["id"]
    key = client.post(f"/ops/rfis/{oid}/attachments", data={
        "file": (io.BytesIO(b"bye"), "bye.jpg")},
        content_type="multipart/form-data").get_json()["storage_key"]
    abs_path = os.path.join(client.application.config["UPLOAD_FOLDER"],
                            key)
    assert os.path.isfile(abs_path)
    client.post(f"/ops/rfis/{oid}/comments", json={"body": "thread"})
    assert client.delete(f"/ops/rfis/{oid}").status_code == 200
    assert not os.path.exists(abs_path)
    with client.application.app_context():
        assert Attachment.query.filter_by(
            record_kind="rfis", record_id=oid).count() == 0
        assert OpsRecordComment.query.filter_by(
            record_kind="rfis", record_id=oid).count() == 0
    assert client.get(f"/ops/rfis/{oid}/history").status_code == 404
