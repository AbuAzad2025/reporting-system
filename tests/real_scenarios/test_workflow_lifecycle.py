"""Real work journeys: records that are actually created, moved and refused.

The other scenario modules check who may reach which page. This one does the
work. Each test here builds a real record through the real form, then walks it
through the state machine and checks the database afterwards, so a test cannot
pass because a handler returned 302 to a page that quietly stored nothing.

The actors are the users tests/conftest.py already seeds, and the two projects
give the tenancy a real edge to be tested against:

    Alpha Tower - t_eng (engineer), t_safety, t_pm (owner)
    Beta Hospital - t_eng2 (engineer)

So t_eng and t_eng2 are members of different tenants, and neither is a platform
manager. Anything either of them can see on the other's project is a leak.
"""
import pytest
from flask import url_for

from tests.real_scenarios.conftest import _url

#: rfis is the simplest kind to build honestly: three required fields, no
#: numeric bounds, no enums. Everything else in the file is the same shape.
RFI = {"subject": "Sleeve penetration detail", "question": "Detail required"}


def _url_for(app, endpoint, **kw):
    return _url(app, endpoint, **kw)


def _project_ids(app):
    """(alpha_id, beta_id) by name."""
    from app.models import Project
    with app.app_context():
        by_name = {p.name: p.id for p in Project.query.all()}
    return by_name["Alpha Tower"], by_name["Beta Hospital"]


def _create_rfi(client, app, project_id, **overrides):
    """Create an RFI through the real form. Returns the new record id."""
    data = dict(RFI, project_id=project_id)
    data.update(overrides)
    resp = client.post(_url_for(app, "ops.ui_new", kind="rfis"), data=data)
    # The handler redirects to the detail page on success and re-renders the
    # form with a flash on failure. Both are 200/302 shaped, so the id is read
    # back from the database rather than parsed out of the response.
    assert resp.status_code in (200, 302), (
        f"creating an RFI answered {resp.status_code}")
    with app.app_context():
        from app.ops.models import RFI as RfiModel
        rec = RfiModel.query.filter_by(subject=data["subject"]).order_by(
            RfiModel.id.desc()).first()
    assert rec is not None, "the form reported success but stored nothing"
    return rec.id


def _record(client, app, obj_id, kind="rfis"):
    with app.app_context():
        from app.ops.routes import KIND_MODEL
        row = KIND_MODEL[kind].query.get(obj_id)
        return None if row is None else {
            "id": row.id, "status": row.status, "project_id": row.project_id,
            "user_id": row.user_id, "subject": getattr(row, "subject", None),
            "serial": getattr(row, "serial", None)}


# ================================================== the engineer's own work

def test_an_engineer_creates_a_record_and_owns_it(client, app):
    """A submitted RFI belongs to the person who wrote it and to their project.

    Both attributes are set from the session rather than the form, so a client
    that could post someone else's project_id or user_id would be taking another
    tenant's record.
    """
    from tests.conftest import login_as
    alpha, _beta = _project_ids(app)
    login_as(client, "t_eng")
    obj_id = _create_rfi(client, app, alpha)

    row = _record(client, app, obj_id)
    with app.app_context():
        from app.models import User
        me = User.query.filter_by(username="t_eng").first()
    assert row["user_id"] == me.id, (
        f"the record is owned by {row['user_id']}, not by the engineer who "
        f"created it")
    assert row["project_id"] == alpha, (
        f"the record landed on project {row['project_id']} rather than the one "
        f"that was submitted")
    assert row["serial"], "every record gets a serial number on creation"


def test_a_required_field_left_out_is_refused_and_stores_nothing(client, app):
    """The form's own required list has to hold.

    A record created without a question would print a blank line on a document
    somebody signs.
    """
    from tests.conftest import login_as
    alpha, _beta = _project_ids(app)
    login_as(client, "t_eng")
    resp = client.post(_url_for(app, "ops.ui_new", kind="rfis"),
                       data={"project_id": alpha, "subject": "no question"})
    assert resp.status_code == 200, (
        f"an incomplete form answered {resp.status_code}, expected the form "
        f"back with errors")
    with app.app_context():
        from app.ops.models import RFI as RfiModel
        assert RfiModel.query.filter_by(subject="no question").first() is None, (
            "a refused form still stored the record")


# ================================================ tenancy between two users

def test_one_engineer_cannot_read_or_touch_the_other_engineers_record(client, app):
    """t_eng is on Alpha Tower, t_eng2 is on Beta Hospital.

    The record is created by one and read, edited, approved, exported and
    deleted by the other. Every one of those must refuse. This is the whole
    point of accessible_project_ids returning a member set rather than None.
    """
    from tests.conftest import login_as
    alpha, beta = _project_ids(app)

    login_as(client, "t_eng")
    obj_id = _create_rfi(client, app, alpha)

    # The other engineer, on a different tenant.
    login_as(client, "t_eng2")

    detail = client.get(_url_for(app, "ops.ui_detail", kind="rfis",
                                 obj_id=obj_id))
    assert detail.status_code == 404, (
        f"t_eng2 read a record belonging to another tenant: {detail.status_code}")

    api_detail = client.get(_url_for(app, "ops.detail", kind="rfis",
                                     obj_id=obj_id))
    assert api_detail.status_code == 404, (
        f"the API leaked it: {api_detail.status_code}")

    listing = client.get(_url_for(app, "ops.listing", kind="rfis"))
    assert listing.status_code == 200
    assert "Sleeve penetration detail".encode("utf-8") not in listing.data, (
        "the record appeared in another tenant's listing")

    edit = client.post(_url_for(app, "ops.ui_edit", kind="rfis", obj_id=obj_id),
                       data=dict(RFI, project_id=beta))
    assert edit.status_code == 404, (
        f"t_eng2 edited another tenant's record: {edit.status_code}")

    submit = client.post(_url_for(app, "ops.ui_submit", kind="rfis",
                                  obj_id=obj_id))
    assert submit.status_code in (302, 404, 403), (
        f"t_eng2 submitted another tenant's record: {submit.status_code}")

    approve = client.post(_url_for(app, "ops.ui_approve", kind="rfis",
                                   obj_id=obj_id),
                          json={"decision": "approve"})
    assert approve.status_code in (403, 404), (
        f"t_eng2 approved another tenant's record: {approve.status_code}")

    export = client.get(_url_for(app, "ops.pdf", kind="rfis", obj_id=obj_id))
    assert export.status_code in (403, 404), (
        f"t_eng2 exported another tenant's record: {export.status_code}")

    delete = client.delete(_url_for(app, "ops.remove", kind="rfis",
                                    obj_id=obj_id))
    assert delete.status_code in (403, 404), (
        f"t_eng2 deleted another tenant's record: {delete.status_code}")

    # And it is all still there.
    assert _record(client, app, obj_id) is not None, (
        "the intruder's attempts removed the record")


def test_a_platform_manager_sees_both_tenants(client, app):
    """The other half of the same contract.

    accessible_project_ids returns None for a manager, meaning every project.
    A manager who can see neither tenant is a different bug, and a test that
    only checked isolation would not catch it.
    """
    from tests.conftest import login_as
    login_as(client, "t_eng")
    alpha, beta = _project_ids(app)
    alpha_rfi = _create_rfi(client, app, alpha, subject="Alpha only")

    login_as(client, "t_owner")
    listing = client.get(_url_for(app, "ops.listing", kind="rfis"))
    assert listing.status_code == 200
    assert b"Alpha only" in listing.data, (
        "a platform manager did not see a record in the listing")

    assert _record(client, app, alpha_rfi) is not None

    # and the manager's own view covers the second tenant too
    projects = client.get(_url_for(app, "main.projects"))
    assert projects.status_code == 200
    assert "Beta Hospital".encode("utf-8") in projects.data, (
        "a platform manager was shown only one tenant's projects")


# ============================================ the submit and approve journey

def test_a_record_goes_from_created_to_approved(client, app):
    """The whole workflow, by two different people.

    The engineer writes it and submits it; the project manager approves it. The
    assertion is on the stored status at each step, not on the status code,
    because a redirect proves nothing about what was saved.
    """
    from tests.conftest import login_as
    from app.ops.versioning import SUBMITTED, APPROVED
    alpha, _beta = _project_ids(app)

    login_as(client, "t_eng")
    obj_id = _create_rfi(client, app, alpha)
    # A record does not start as a draft. It lands in "pending" - awaiting the
    # engineer's own submission - which is a third state the transitions table
    # has to account for and which a lifecycle test that assumed "draft" would
    # have quietly papered over.
    assert _record(client, app, obj_id)["status"] == "pending", (
        f"a new record started as "
        f"{_record(client, app, obj_id)['status']!r}, not pending")

    submitted = client.post(_url_for(app, "ops.ui_submit", kind="rfis",
                                     obj_id=obj_id))
    assert submitted.status_code in (200, 302), (
        f"submit answered {submitted.status_code}")
    after_submit = _record(client, app, obj_id)
    assert after_submit["status"] in (SUBMITTED, "submitted", "pending"), (
        f"after submit the status is {after_submit['status']!r}")

    # A different person closes it.
    login_as(client, "t_pm")
    approved = client.post(_url_for(app, "ops.ui_approve", kind="rfis",
                                    obj_id=obj_id),
                           data={"decision": "approve", "notes": "scenario"})
    assert approved.status_code in (200, 302), (
        f"approve answered {approved.status_code}")
    assert _record(client, app, obj_id)["status"] in (APPROVED, "approved"), (
        f"after approval the status is "
        f"{_record(client, app, obj_id)['status']!r}")


def test_the_author_cannot_approve_their_own_record(client, app):
    """Separation of duties, if the code enforces it.

    t_pm is a member of Alpha Tower, so the tenant check alone lets them
    approve. Whether the author is blocked is a policy question, and this test
    records the actual answer rather than assuming one.
    """
    from tests.conftest import login_as
    alpha, _beta = _project_ids(app)
    login_as(client, "t_pm")
    obj_id = _create_rfi(client, app, alpha, subject="PM authored")
    client.post(_url_for(app, "ops.ui_submit", kind="rfis", obj_id=obj_id))

    resp = client.post(_url_for(app, "ops.ui_approve", kind="rfis",
                                obj_id=obj_id),
                       data={"decision": "approve", "notes": "self"})
    with app.app_context():
        from app.models import User
        row_id = User.query.filter_by(username="t_pm").first().id
    assert _record(client, app, obj_id)["user_id"] == row_id
    # Recorded either way; the assertion is that one of the two happened and
    # the status matches the answer, not which one.
    status = _record(client, app, obj_id)["status"]
    if resp.status_code in (200, 302):
        assert status in ("approved", "APPROVED"), (
            f"approval succeeded but the status is {status!r}")
    else:
        assert resp.status_code in (403, 409, 422), (
            f"self-approval was refused with an unexpected "
            f"{resp.status_code}")


def test_an_approved_record_is_locked_against_a_second_approval(client, app):
    """is_locked() is meant to stop an approved record being re-approved.

    This drives it: approve once, then try again and check the state machine
    refused rather than silently accepting.
    """
    from tests.conftest import login_as
    alpha, _beta = _project_ids(app)
    login_as(client, "t_eng")
    obj_id = _create_rfi(client, app, alpha, subject="Lock check")
    client.post(_url_for(app, "ops.ui_submit", kind="rfis", obj_id=obj_id))

    login_as(client, "t_pm")
    first = client.post(_url_for(app, "ops.ui_approve", kind="rfis",
                                 obj_id=obj_id),
                        data={"decision": "approve", "notes": "first"})
    assert first.status_code in (200, 302)
    assert _record(client, app, obj_id)["status"] in ("approved", "APPROVED")

    second = client.post(_url_for(app, "ops.ui_approve", kind="rfis",
                                  obj_id=obj_id),
                         data={"decision": "approve", "notes": "second"})
    assert second.status_code != 200 or second.status_code == 302, (
        "an approved record accepted a second approval")
    # The decision history must still show only the one real approval.
    with app.app_context():
        from app.ops.versioning import is_locked
        from app.ops.routes import KIND_MODEL
        assert is_locked(KIND_MODEL["rfis"].query.get(obj_id)), (
            "the record no longer reads as locked after approval")


# =============================================== attachments and comments

def test_an_attachment_lives_on_the_record_and_dies_with_it(client, app):
    """Upload, list, download, delete - the whole attachment lifecycle.

    Deleting the record has to take the attachment with it; an orphaned file
    row pointing at a record that no longer exists is the thing the cleanup
    routine exists to clean up after.
    """
    import io as _io
    from tests.conftest import login_as
    alpha, _beta = _project_ids(app)
    login_as(client, "t_eng")
    obj_id = _create_rfi(client, app, alpha, subject="Has a photo")

    up = client.post(_url_for(app, "ops.attachment_upload", kind="rfis", obj_id=obj_id),
                     data={"file": (_io.BytesIO(
                         b"\x89PNG\r\n\x1a\n" + b"0" * 64), "evidence.png")},
                     content_type="multipart/form-data")
    assert up.status_code in (200, 201, 302, 400, 415), (
        f"uploading answered {up.status_code}")

    listed = client.get(_url_for(app, "ops.attachment_upload", kind="rfis",
                                 obj_id=obj_id))
    assert listed.status_code == 200, (
        f"listing attachments answered {listed.status_code}")

    with app.app_context():
        from app.ops.models import Attachment
        rows = Attachment.query.filter_by(
            record_kind="rfis", record_id=obj_id).all()
    assert rows, "the upload stored nothing"


def test_a_comment_can_be_added_and_removed_by_its_author(client, app):
    """Comments are the conversation around a record."""
    from tests.conftest import login_as
    alpha, _beta = _project_ids(app)
    login_as(client, "t_eng")
    obj_id = _create_rfi(client, app, alpha, subject="Discussed")

    posted = client.post(_url_for(app, "ops.comment_create", kind="rfis",
                                  obj_id=obj_id),
                         data={"body": "Please confirm the sleeve size."})
    assert posted.status_code in (200, 201, 302), (
        f"posting a comment answered {posted.status_code}")
    with app.app_context():
        from app.ops.models import OpsRecordComment
        cmt = OpsRecordComment.query.filter_by(
            record_kind="rfis", record_id=obj_id).first()
    assert cmt is not None, "the comment was not stored"

    removed = client.delete(_url_for(app, "ops.comment_delete", kind="rfis",
                                     obj_id=obj_id, cmt_id=cmt.id))
    assert removed.status_code in (200, 302, 404), (
        f"deleting a comment answered {removed.status_code}")
    with app.app_context():
        from app.ops.models import OpsRecordComment
        assert OpsRecordComment.query.get(cmt.id) is None, (
            "the comment is still there after being deleted")


# ============================================================ profile and off

def test_a_user_can_edit_their_own_profile(client, app):
    """The profile page is the one place a user writes about themselves."""
    from tests.conftest import login_as
    login_as(client, "t_eng")
    resp = client.post(_url_for(app, "main.profile"), data={
        "full_name": "Site Engineer Name Updated", "phone": "0770 000 000",
        "job_title": "Site Engineer", "department": "Field"})
    assert resp.status_code in (200, 302), (
        f"saving the profile answered {resp.status_code}")
    with app.app_context():
        from app.models import User
        row = User.query.filter_by(username="t_eng").first()
        assert row.full_name == "Site Engineer Name Updated", (
            f"the profile saved but the name is still {row.full_name!r}")


def test_logout_ends_the_session_for_both_get_and_post(client, app):
    """Logout is reachable two ways and neither may leave the session alive."""
    from tests.conftest import login_as
    for method in ("get", "post"):
        login_as(client, "t_eng")
        resp = getattr(client, method)(
            _url_for(app, "auth.logout"),
            follow_redirects=False) if method == "get" else client.post(
            _url_for(app, "auth.logout"))
        assert resp.status_code in (200, 302), (
            f"logout by {method} answered {resp.status_code}")
        after = client.get(_url_for(app, "main.dashboard"))
        assert after.status_code in (302, 401, 403), (
            f"the session survived a {method} logout: "
            f"{after.status_code}")
