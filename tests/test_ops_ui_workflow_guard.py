"""The ops HTML surface must enforce the same guarantees as the JSON API.

Before this contract, `/ops/ui/<kind>/<id>/edit|submit|approve` were
`@login_required` only: any tenant member could rewrite an approved record in
place, rewind a locked row to "submitted", and forge audit columns through the
form passthrough.
"""
import pytest

from tests.conftest import login_as

FLASK = pytest.importorskip("flask")


def _alpha(app):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name="Alpha Tower").one().id


def _record(app, serial, model_name="RFI"):
    from app.ops import models as M
    model = getattr(M, model_name)
    with app.app_context():
        return model.query.filter_by(serial=serial).one().id


def _make_rfi(client, app, **over):
    payload = {"project_id": _alpha(app), "subject": "موضوع",
               "question": "سؤال", "ball_in_court": "consultant",
               "priority": "normal"}
    payload.update(over)
    r = client.post("/ops/rfis", json=payload)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _set_status(app, record_id, status, model_name="RFI"):
    from app.extensions import db
    from app.ops import models as M
    model = getattr(M, model_name)
    with app.app_context():
        row = db.session.get(model, record_id)
        row.status = status
        db.session.commit()


def _snapshot(app, record_id, model_name="RFI"):
    from app.ops import models as M
    model = getattr(M, model_name)
    with app.app_context():
        row = model.query.get(record_id)
        return {"status": row.status, "subject": row.subject,
                "version": row.version}


class TestUiEditAuthorization:

    def test_non_author_cannot_edit_another_members_record(self, app, client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        login_as(client, "t_safety")
        r = client.post(f"/ops/ui/rfis/{rid}/edit", data={"subject": "مُعدّل"})
        assert r.status_code == 403
        assert _snapshot(app, rid)["subject"] == "موضوع"

    def test_author_can_edit_own_draft(self, app, client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "draft")
        r = client.post(f"/ops/ui/rfis/{rid}/edit", data={"subject": "مُعدّل"})
        assert r.status_code == 302
        assert _snapshot(app, rid)["subject"] == "مُعدّل"

    def test_locked_record_edit_spawns_an_amendment(self, app, client):
        from app.ops.models import RFI
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "approved")
        before = _snapshot(app, rid)
        r = client.post(f"/ops/ui/rfis/{rid}/edit", data={"subject": "تعديل"})
        assert r.status_code == 302
        after = _snapshot(app, rid)
        assert after["status"] == "approved"
        assert after["subject"] == before["subject"]
        assert after["version"] == before["version"]
        with app.app_context():
            amendments = RFI.query.filter_by(supersedes_id=rid).all()
            assert len(amendments) == 1
            assert amendments[0].subject == "تعديل"
            assert amendments[0].status == "draft"
            assert amendments[0].version == before["version"] + 1

    def test_historical_record_edit_is_locked(self, app, client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "amended")
        r = client.post(f"/ops/ui/rfis/{rid}/edit", data={"subject": "x"})
        assert r.status_code == 423
        assert _snapshot(app, rid)["subject"] == "موضوع"

    def test_ui_edit_cannot_reach_another_tenant(self, app, client):
        login_as(client, "t_eng2")
        r = client.post("/ops/ui/rfis/1/edit", data={"subject": "x"})
        assert r.status_code == 404


class TestUiSubmitStateMachine:

    @pytest.mark.parametrize("status", ["pending", "submitted", "approved",
                                        "amended"])
    def test_submit_is_refused_outside_draft_or_rejected(self, app, client,
                                                          status):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, status)
        r = client.post(f"/ops/ui/rfis/{rid}/submit")
        assert r.status_code == 302
        assert _snapshot(app, rid)["status"] == status

    def test_approved_record_cannot_be_rewound_to_submitted(self, app,
                                                             client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "approved")
        client.post(f"/ops/ui/rfis/{rid}/submit", follow_redirects=True)
        assert _snapshot(app, rid)["status"] == "approved"

    def test_draft_can_be_submitted(self, app, client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "draft")
        r = client.post(f"/ops/ui/rfis/{rid}/submit")
        assert r.status_code == 302
        assert _snapshot(app, rid)["status"] == "submitted"

    def test_non_author_cannot_submit(self, app, client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "draft")
        login_as(client, "t_safety")
        r = client.post(f"/ops/ui/rfis/{rid}/submit")
        assert r.status_code == 403
        assert _snapshot(app, rid)["status"] == "draft"


class TestUiApprovalWorkflow:

    def test_non_approver_cannot_approve(self, app, client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        r = client.post(f"/ops/ui/rfis/{rid}/approve")
        assert r.status_code == 403
        assert _snapshot(app, rid)["status"] == "pending"

    def test_approval_records_the_reviewer(self, app, client):
        from app.extensions import db
        from app.ops.models import RFI
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        login_as(client, "t_admin")
        r = client.post(f"/ops/ui/rfis/{rid}/approve")
        assert r.status_code == 302
        with app.app_context():
            row = db.session.get(RFI, rid)
            assert row.status == "approved"
            assert row.reviewed_by_id is not None
            assert row.reviewed_at is not None

    def test_draft_cannot_be_approved_out_of_order(self, app, client):
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "draft")
        login_as(client, "t_admin")
        r = client.post(f"/ops/ui/rfis/{rid}/approve", follow_redirects=True)
        assert r.status_code == 200
        assert _snapshot(app, rid)["status"] == "draft"

    def test_approving_an_amendment_retires_the_prior_version(self, app,
                                                              client):
        from app.ops.models import RFI
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "approved")
        client.post(f"/ops/ui/rfis/{rid}/edit", data={"subject": "تعديل"})
        with app.app_context():
            amendment = RFI.query.filter_by(supersedes_id=rid).one()
            amid = amendment.id
        login_as(client, "t_admin")
        client.post(f"/ops/ui/rfis/{amid}/submit")
        client.post(f"/ops/ui/rfis/{amid}/approve", follow_redirects=True)
        with app.app_context():
            assert RFI.query.get(rid).status == "amended"
            assert RFI.query.get(amid).status == "approved"


class TestMassAssignmentGuard:

    @pytest.mark.parametrize("payload", [
        {"version": "999"},
        {"root_id": "1"},
        {"supersedes_id": "1"},
        {"review_notes": "forged"},
        {"status": "approved"},
        {"serial": "RFI-FORGED"},
        {"user_id": "1"},
        {"signatory_name": "forged"},
        {"reviewed_by_id": "1"},
    ])
    def test_protected_columns_cannot_be_written_through_the_api(
            self, app, client, payload):
        from app.extensions import db
        from app.ops.models import RFI
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        before = _snapshot(app, rid)
        r = client.put(f"/ops/rfis/{rid}", json=payload)
        assert r.status_code == 200
        with app.app_context():
            row = db.session.get(RFI, rid)
            assert row.version == before["version"]
            assert row.root_id is None
            assert row.supersedes_id is None
            assert (row.review_notes or "") != "forged"
            assert row.status == "pending"
            assert row.serial.startswith("RFI-")
            assert row.signatory_name != "forged"

    def test_protected_columns_cannot_be_written_through_the_form(
            self, app, client):
        from app.extensions import db
        from app.ops.models import RFI
        login_as(client, "t_eng")
        rid = _make_rfi(client, app)
        _set_status(app, rid, "draft")
        r = client.post(f"/ops/ui/rfis/{rid}/edit", data={
            "subject": "سليم", "version": "999", "root_id": "7",
            "supersedes_id": "9", "review_notes": "forged",
            "status": "approved"})
        assert r.status_code == 302
        with app.app_context():
            row = db.session.get(RFI, rid)
            assert row.version == 1
            assert row.root_id is None
            assert row.supersedes_id is None
            assert (row.review_notes or "") != "forged"
            assert row.status == "draft"
            assert row.subject == "سليم"
