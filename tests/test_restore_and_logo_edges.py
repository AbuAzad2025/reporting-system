"""The last two guards: an archive row we cannot place, and a tenant's logo.

Five statements.

The backup one counts what it skipped rather than letting the total look
complete - an attachment pointing at a record kind this service has never heard
of is still something the operator needs to know about, because it is either a
file they are about to lose or evidence that the archive is from a newer
version than the code reading it.

The PDF one is the tenant's logo above the contractual header. Without it a
company that uploaded a logo would find their branding missing from their own
reports, while the owner/consultant/contractor block below it - the part that
is a legal record - stayed put.
"""
import io
import json
import zipfile

import pytest


# ==================================== restoring an archive we cannot place

def _archive(attachments):
    """A minimal, valid platform-scope archive carrying these attachment rows."""
    from app.services.backup import BACKUP_VERSION
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps({
            "version": BACKUP_VERSION,
            "scope": "platform",
            "project_id": None,
            "created_at": "2026-01-01T00:00:00",
            "generator": "tests/test_restore_and_logo_edges.py",
        }, ensure_ascii=False))
        z.writestr("projects.json", json.dumps([], ensure_ascii=False))
        z.writestr("users.json", json.dumps([], ensure_ascii=False))
        z.writestr("attachments.json",
                   json.dumps(attachments, ensure_ascii=False))
    return buf.getvalue()


def _attachment_row(record_kind):
    return {"record_kind": record_kind, "record_id": 1,
            "filename": "evidence.jpg", "stored_key": "reports/evidence.jpg",
            "original_name": "evidence.jpg", "size_bytes": 10,
            "content_type": "image/jpeg"}


def test_an_attachment_for_an_unknown_record_kind_is_counted_not_dropped(app,
                                                                         caplog):
    """A record kind this service does not know.

    It is counted and logged, not silently skipped: an attachment that vanishes
    without a word is either a lost file or a sign the archive came from a newer
    version than the code restoring it, and both need to be visible.
    """
    from app.services.backup import restore_backup
    blob = _archive([_attachment_row("quantum-submittals")])
    with app.app_context():
        with caplog.at_level("WARNING"):
            counts = restore_backup(blob)
    assert counts.get("attachments_skipped") == 1, (
        f"the skipped attachment must be counted, got {counts}")
    assert counts.get("attachments") == 0, (
        "nothing may be restored for a kind we cannot place")
    assert any("quantum-submittals" in r.message for r in caplog.records), (
        "the unknown kind must be named in the log, or nobody can tell which "
        "rows were affected")


def test_a_known_kind_with_no_matching_owner_is_also_counted(app, caplog):
    """The neighbouring case: a kind we do know, pointing at a record that is
    not in this archive.

    There is nothing for it to point at, so it is counted for the same reason -
    and it is not the same branch, so both are worth having.
    """
    from app.services.backup import restore_backup
    blob = _archive([_attachment_row("rfis")])
    with app.app_context():
        with caplog.at_level("WARNING"):
            counts = restore_backup(blob)
    assert counts.get("attachments_skipped") == 1, (
        f"an attachment with no owner in the archive must be counted, "
        f"got {counts}")
    assert counts.get("attachments") == 0


def test_an_archive_with_no_attachments_restores_cleanly(app):
    """The control: nothing to skip, so nothing is reported as skipped.

    Without this the two tests above would also pass if `attachments_skipped`
    were simply always 1.
    """
    from app.services.backup import restore_backup
    with app.app_context():
        counts = restore_backup(_archive([]))
    assert not counts.get("attachments_skipped"), (
        f"an archive with no attachments must not report skips: {counts}")


# ==================================== the tenant's logo in the document

def test_a_tenant_logo_is_placed_in_the_document(app, monkeypatch):
    """A tenant who uploaded a logo gets it in their report.

    Above the header block, not below: the owner/consultant/contractor lines are
    a contractual record and stay as they are, but branding belongs with the
    letterhead.
    """
    from reportlab.platypus import Spacer
    import utils.pdf_generator as gen
    from app.ops.pdf import build_ops_pdf
    from app.services import branding as branding_service
    from app.extensions import db
    from app.models import Project
    from tests.test_pdf_branding_all_paths import _inspection

    asked = []

    def _fake_logo(path):
        asked.append(path)
        return Spacer(1, 12)

    monkeypatch.setattr(gen, "_custom_logo", _fake_logo)
    with app.app_context():
        project = Project.query.first()
        project.logo_path = "uploads/branding/tenant.png"
        db.session.commit()
        brand = branding_service.branding_for_project(project.id)
        record = _inspection(app, project)
        pdf = build_ops_pdf("site-inspections", record,
                            project_name=project.name, brand=brand)
    assert asked == ["uploads/branding/tenant.png"], (
        f"the tenant's stored logo path was not the one drawn: {asked}")
    assert pdf[:4] == b"%PDF", "the document must still build"


def test_a_tenant_with_no_logo_gets_no_placeholder(app):
    """The control: with no logo on the project, nothing is drawn and the
    document still builds."""
    from app.ops.pdf import build_ops_pdf
    from app.services import branding as branding_service
    from utils.pdf_generator import _custom_logo
    from app.extensions import db
    from app.models import Project
    from tests.test_pdf_branding_all_paths import _inspection

    with app.app_context():
        project = Project.query.first()
        project.logo_path = ""
        db.session.commit()
        brand = branding_service.branding_for_project(project.id)
        assert _custom_logo(brand.logo_path) is None, (
            "an empty logo path must draw nothing at all")
        record = _inspection(app, project)
        pdf = build_ops_pdf("site-inspections", record,
                            project_name=project.name, brand=brand)
    assert pdf[:4] == b"%PDF"
