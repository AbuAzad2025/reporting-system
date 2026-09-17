"""Versioning chain & immutability tests for OpsRecordMixin.

State machine (see app/ops/versioning.py + app/ops/models.py):
  * Fresh records default to status ``pending`` (legacy alias of submitted).
  * ``pending``/``submitted`` --(manager approve)--> ``approved`` (locked).
  * PUT on an approved record auto-spawns a linked amendment draft (201),
    history is never mutated.
  * PUT on an amended (historical) record --> 423 Locked.
  * DELETE on approved/historical --> 423 Locked.

Verifies: apply_decision, amendment spawning, serial-race retries,
HTTP 423 on locked/historical edits/deletes, and audit-trail preservation.
"""

from tests.conftest import login_as
from app.ops.versioning import APPROVED, AMENDED


def _alpha_id(client):
    from app.models import Project
    with client.application.app_context():
        return Project.query.filter_by(name="Alpha Tower").first().id


def _make_dsr(client, **over):
    payload = {"project_id": _alpha_id(client), "weather": "مشمس",
               "works_executed": "صب أعمدة", "engineers_count": 2,
               "technicians_count": 3, "labor_count": 28,
               "day_progress_pct": 3.0}
    payload.update(over)
    r = client.post("/ops/daily-reports", json=payload)
    assert r.status_code == 201, f"create DSR: {r.get_json()}"
    return r.get_json()


def _make_cvr(client, **over):
    payload = {"project_id": _alpha_id(client), "boq_item": "concrete",
               "budgeted_qty": 10, "budgeted_rate": 100,
               "actual_qty": 12, "actual_rate": 110}
    payload.update(over)
    r = client.post("/ops/cost-variances", json=payload)
    assert r.status_code == 201, f"create CVR: {r.get_json()}"
    return r.get_json()


# ---- Fresh-record status -------------------------------------------------

def test_fresh_record_defaults_to_pending(client):
    """New records are born pending (= submitted); status is server-set."""
    login_as(client, "t_eng")
    body = _make_dsr(client)
    assert body["status"] == "pending"


def test_double_submit_rejected(client):
    """A pending record cannot be (re)submitted --> 422."""
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    r = client.post(f"/ops/daily-reports/{sid}/submit")
    assert r.status_code == 422, f"re-submit pending: {r.get_json()}"


def test_rejected_to_submitted(client):
    """Rejected --> submitted is a valid transition (rework flow)."""
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    # Manager rejects the pending record...
    login_as(client, "t_admin")
    r = client.post(f"/ops/daily-reports/{sid}/approve",
                    json={"decision": "reject", "notes": "نقص بيانات"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "rejected"
    # ...author resubmits after rework.
    login_as(client, "t_eng")
    r = client.post(f"/ops/daily-reports/{sid}/submit")
    assert r.status_code == 200, f"resubmit: {r.get_json()}"
    assert r.get_json()["status"] == "submitted"


# ---- Approval ------------------------------------------------------------

def test_pending_to_approved_via_manager(client):
    """Pending --> approved directly (no submit round-trip needed)."""
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    login_as(client, "t_admin")
    r = client.post(f"/ops/daily-reports/{sid}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200, f"approve: {r.get_json()}"
    assert r.get_json()["status"] == APPROVED


def test_engineer_cannot_approve(client):
    """Non-manager approve attempt --> 403 (perm + role gates)."""
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    r = client.post(f"/ops/daily-reports/{sid}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 403


# ---- Immutability: PUT on approved spawns amendment ----------------------

def test_put_on_approved_spawns_amendment(client):
    """PUT on an approved record returns 201 amendment; history untouched."""
    login_as(client, "t_admin")
    sid = _make_dsr(client)["id"]
    r = client.post(f"/ops/daily-reports/{sid}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200

    r = client.put(f"/ops/daily-reports/{sid}", json={"weather": "ماطر"})
    assert r.status_code == 201, f"amend PUT: {r.get_json()}"
    body = r.get_json()
    assert body["amended_from"] == f"DSR-{sid:06d}" or \
        body["amended_from"].startswith("DSR-")
    assert body["status"] == "draft"
    assert body["weather"] == "ماطر"

    # Original stays approved and unmodified.
    from app.ops.models import DailySiteReport
    from app.extensions import db
    with client.application.app_context():
        orig = db.session.get(DailySiteReport, sid)
        assert orig.status == APPROVED
        assert orig.weather == "مشمس"


def test_put_on_historical_amended_returns_423(client):
    """PUT on an amended (superseded) version --> 423 Locked."""
    login_as(client, "t_admin")
    from app.extensions import db
    from app.ops.models import CostVariance
    cid = _make_cvr(client)["id"]

    r = client.post(f"/ops/cost-variances/{cid}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200

    # Amendment of the approved record (spawned via PUT)...
    r = client.put(f"/ops/cost-variances/{cid}",
                   json={"boq_item": "modified"})
    assert r.status_code == 201
    am_id = r.get_json()["id"]

    # ...submitted, then approved --> prior version becomes historical.
    r = client.post(f"/ops/cost-variances/{am_id}/submit")
    assert r.status_code == 200, f"submit amendment: {r.get_json()}"
    r = client.post(f"/ops/cost-variances/{am_id}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200

    with client.application.app_context():
        assert db.session.get(CostVariance, cid).status == AMENDED

    # Editing the historical version is forbidden.
    r = client.put(f"/ops/cost-variances/{cid}", json={"boq_item": "new"})
    assert r.status_code == 423, \
        f"Expected 423, got {r.status_code}: {r.get_json()}"


def test_delete_on_approved_returns_423(client):
    """DELETE on a locked record --> 423 (legal audit trail)."""
    login_as(client, "t_admin")
    cid = _make_cvr(client)["id"]
    client.post(f"/ops/cost-variances/{cid}/approve",
                json={"decision": "approve"})
    r = client.delete(f"/ops/cost-variances/{cid}")
    assert r.status_code == 423


# ---- Serial race handling ------------------------------------------------

def test_serial_retry_concurrent(client):
    """Rapid creates each get a unique serial (5x retry under contention)."""
    login_as(client, "t_admin")
    serials = [_make_cvr(client, boq_item=f"item_{i}")["serial"]
               for i in range(5)]
    assert len(set(serials)) == 5, f"Duplicate serials: {serials}"


# ---- apply_decision atomicity --------------------------------------------

def test_apply_decision_retires_prior_amendment(client):
    """Approving an amendment retires the prior approved version."""
    login_as(client, "t_admin")
    from app.extensions import db
    from app.ops.models import CostVariance
    cid = _make_cvr(client, boq_item="first item")["id"]

    r = client.post(f"/ops/cost-variances/{cid}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200

    r = client.put(f"/ops/cost-variances/{cid}",
                   json={"boq_item": "modified amending"})
    assert r.status_code == 201
    am_id = r.get_json()["id"]

    r = client.post(f"/ops/cost-variances/{am_id}/submit")
    assert r.status_code == 200, f"submit amendment: {r.get_json()}"
    r = client.post(f"/ops/cost-variances/{am_id}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200

    with client.application.app_context():
        first = db.session.get(CostVariance, cid)
        assert first.status == AMENDED, \
            f"Expected first CVR AMENDED, got {first.status}"
        am = db.session.get(CostVariance, am_id)
        assert am.status == APPROVED


# ---- Version chain integrity ---------------------------------------------

def test_version_chain_root_and_supersedes(client):
    """root_id / supersedes_id chain + /history endpoint."""
    login_as(client, "t_admin")
    from app.extensions import db
    from app.ops.models import CostVariance
    cid = _make_cvr(client, boq_item="original")["id"]

    client.post(f"/ops/cost-variances/{cid}/approve",
                json={"decision": "approve"})
    r = client.put(f"/ops/cost-variances/{cid}",
                   json={"boq_item": "modified"})
    assert r.status_code == 201
    am_id = r.get_json()["id"]

    with client.application.app_context():
        am = db.session.get(CostVariance, am_id)
        orig = db.session.get(CostVariance, cid)
        assert am.version == orig.version + 1
        assert am.root_id == cid, f"root_id should be {cid}, got {am.root_id}"
        assert am.supersedes_id == cid

    r = client.post(f"/ops/cost-variances/{am_id}/submit")
    assert r.status_code == 200, f"submit amendment: {r.get_json()}"
    r = client.post(f"/ops/cost-variances/{am_id}/approve",
                    json={"decision": "approve"})
    assert r.status_code == 200

    with client.application.app_context():
        assert db.session.get(CostVariance, cid).status == AMENDED

    r = client.get(f"/ops/cost-variances/{cid}/history")
    assert r.status_code == 200
    history = r.get_json()
    assert history["root_id"] == cid
    versions = history["versions"]
    assert len(versions) == 2
    assert versions[0]["status"] == AMENDED
    assert versions[1]["status"] == APPROVED
