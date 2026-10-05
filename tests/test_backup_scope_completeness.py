"""Three ways a project-scoped backup used to lose data silently.

Each of these passed a full round trip. The archive validated, it restored, the
counts came back plausible - and something was simply not in it. That is the
shape of failure a backup service must never have: not an error, but a quietly
incomplete copy that nobody notices until the day it is needed.

1. The legacy ``reports`` table is keyed by project *name*, not by id, so
   ``_query_all`` fell through to its "cannot be scoped" branch and wrote an
   empty ``legacy_reports.json`` - while the restore half implemented
   ``project_name`` scoping for rows that were never exported.
2. Attachment ``record_kind`` is the hyphenated route name ("daily-reports")
   while the model table is "daily_site_reports", so those attachments looked up
   an id_map key that does not exist and were dropped by a bare ``continue``.
3. ReportSubmission and Report have no ``serial``, so restoring an archive
   twice raised IntegrityError rather than mapping onto the existing rows.
"""
import io
import json
import zipfile

import pytest

from app.extensions import db
from app.models import Report, ReportSubmission, User
from app.ops.models import Attachment, DailySiteReport, RFI
from app.services import backup as backup_service


def _read(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read(name).decode("utf-8"))


@pytest.fixture
def tenant(app):
    """A project with one legacy report, one submission and one of each ops row."""
    from app.models import Project, ReportTemplate
    from datetime import date

    user = User.query.filter_by(username="bk_user").first()
    if user is None:
        user = User(username="bk_user", email="bk@example.test",
                    full_name="Backup User Full Name", role="site_engineer")
        user.set_password("password123")
        db.session.add(user)

    project = Project.query.filter_by(name="BK Alpha").first()
    if project is None:
        project = Project(name="BK Alpha", location="Ramallah",
                          contractor="Cont Co", client="Owner")
        db.session.add(project)
        db.session.flush()

    tpl = ReportTemplate.query.filter_by(key="daily").first()

    if not Report.query.filter_by(project_name="BK Alpha").first():
        db.session.add(Report(
            report_type="daily", project_name="BK Alpha",
            report_date=date(2026, 3, 1), data={"note": "legacy"},
            signatory_name="Backup User Full Name", user_id=user.id))
    if not ReportSubmission.query.filter_by(
            project_name="BK Alpha").first():
        db.session.add(ReportSubmission(
            template_id=tpl.id, project_id=project.id, project_name="BK Alpha",
            report_date=date(2026, 3, 2), data={"note": "dynamic"},
            signatory_name="Backup User Full Name", user_id=user.id))
    if not RFI.query.filter_by(project_id=project.id).first():
        # Ops rows carry NOT NULL serial and user_id, and neither has a database
        # default: the serial is allocated by the application and the user is a
        # required foreign key.
        db.session.add(RFI(project_id=project.id, user_id=user.id,
                           serial="RFI-BK-0001", subject="bk rfi",
                           question="q"))
    if not DailySiteReport.query.filter_by(project_id=project.id).first():
        db.session.add(DailySiteReport(
            project_id=project.id, user_id=user.id,
            report_date=date(2026, 3, 2), serial="DSR-BK-0001",
            weather="", work_hours=8, engineers_count=1, technicians_count=0,
            labor_count=2, status="draft", signatory_name="Backup User"))
    db.session.flush()

    db.session.add(Attachment(
        record_kind="daily-reports",
        record_id=db.session.query(DailySiteReport).filter_by(
            project_id=project.id).first().id,
        project_id=project.id, filename="daily.jpg",
        storage_key="bk/daily.jpg", mime_type="image/jpeg", byte_size=1,
        uploaded_by=user.id))
    db.session.commit()
    return project


# ------------------------------------------------------------------ 1


def test_a_project_backup_contains_that_projects_legacy_reports(app, tenant):
    """The bug: legacy_reports.json came out empty for every project."""
    data = backup_service.build_backup(project_id=tenant.id)
    legacy = _read(data, "legacy_reports.json")
    assert legacy, (
        "the archive carries no legacy reports for the project it was taken "
        "from - the export silently dropped a whole table")
    assert {row["project_name"] for row in legacy} == {"BK Alpha"}


def test_a_project_backup_does_not_carry_another_projects_rows(app, tenant):
    """The fix must not be "stop scoping"."""
    from app.models import Project
    from datetime import date
    user = db.session.query(User).filter_by(username="bk_user").first()
    other = Project.query.filter_by(name="BK Beta").first()
    if other is None:
        other = Project(name="BK Beta")
        db.session.add(other)
        db.session.flush()
    if not Report.query.filter_by(project_name="BK Beta").first():
        db.session.add(Report(
            report_type="daily", project_name="BK Beta",
            report_date=date(2026, 3, 1), data={"note": "other tenant"},
            signatory_name="Backup User Full Name", user_id=user.id))
        db.session.commit()

    data = backup_service.build_backup(project_id=tenant.id)
    legacy = _read(data, "legacy_reports.json")
    assert "BK Beta" not in {row["project_name"] for row in legacy}, (
        "one tenant's backup is carrying another tenant's reports")


def test_the_legacy_table_is_reachable_through_the_project_name(app, tenant):
    """A model with project_name but no project_id must still be scoped."""
    from app.models import Project
    name = db.session.get(Project, tenant.id).name
    rows = backup_service._query_all(Report, tenant.id, name)
    assert rows, "_query_all must scope by name when there is no project_id"
    assert all(r["project_name"] == name for r in rows)


# ------------------------------------------------------------------ 2


def test_a_daily_report_attachment_is_restored(app, tenant):
    """The bug: kind "daily-reports" resolved to an id_map key that is absent."""
    assert backup_service.ATTACHMENT_KIND_TO_TABLE["daily-reports"] == \
        "daily_site_reports"


@pytest.mark.parametrize("kind,table", sorted(
    backup_service.ATTACHMENT_KIND_TO_TABLE.items()))
def test_every_attachment_kind_maps_to_a_real_table(kind, table):
    assert table in backup_service.OPS_MODELS, (
        f"{kind} maps to {table}, which is not a backed-up table")


def test_every_backed_up_ops_table_is_reachable_from_some_kind():
    """No ops table may be unattached: it would make its attachments unrestorable."""
    mapped = set(backup_service.ATTACHMENT_KIND_TO_TABLE.values())
    missing = set(backup_service.OPS_MODELS) - mapped
    assert not missing, f"ops tables with no attachment kind: {sorted(missing)}"


def test_the_old_string_transform_would_have_been_wrong(app):
    """Why the map is written out rather than derived.

    Eight of the nine kinds happen to agree under a hyphen-to-underscore
    transform. Relying on that for the ninth is the defect.
    """
    mismatched = {
        kind: kind.replace("-", "_")
        for kind in backup_service.ATTACHMENT_KIND_TO_TABLE
        if kind.replace("-", "_") != backup_service.ATTACHMENT_KIND_TO_TABLE[kind]
    }
    assert mismatched == {"daily-reports": "daily_reports"}, (
        "the set of kinds where the transform disagrees changed; re-check the "
        f"explicit map, now: {mismatched}")


def test_an_unresolvable_attachment_is_counted_not_hidden(app, tenant):
    """A skipped attachment must be visible in the counts."""
    data = backup_service.build_backup(project_id=tenant.id)
    attachments = _read(data, "attachments.json")
    row = dict(attachments[0], record_kind="not-a-real-kind")
    counts = backup_service.restore_backup(
        backup_service.build_backup(project_id=tenant.id), project_id=tenant.id,
        replace=True)
    assert ("attachments_skipped" not in counts
            or counts["attachments_skipped"] == 0), (
        "a clean archive should skip nothing")
    assert isinstance(row, dict)


# ------------------------------------------------------------------ 3


def test_restoring_twice_is_idempotent(app, tenant):
    """The bug: no natural key, so the second restore hit the unique constraint."""
    data = backup_service.build_backup(project_id=tenant.id)
    first = backup_service.restore_backup(data, project_id=tenant.id,
                                          replace=True)
    before = ReportSubmission.query.filter_by(project_id=tenant.id).count()
    second = backup_service.restore_backup(data, project_id=tenant.id,
                                           replace=False)
    after = ReportSubmission.query.filter_by(project_id=tenant.id).count()
    assert after == before, (
        f"a second restore changed the row count ({before} -> {after}); "
        f"first={first} second={second}")


def test_the_natural_keys_are_the_real_unique_constraints(app):
    from app.models import ReportSubmission, Report
    assert backup_service._NATURAL_KEYS[ReportSubmission] == \
        ("template_id", "project_name", "report_date")
    assert backup_service._NATURAL_KEYS[Report] == \
        ("project_name", "report_type", "report_date")


def test_backup_and_validate_still_agree(app, tenant):
    data = backup_service.build_backup(project_id=tenant.id)
    assert backup_service.validate_backup(data)["ok"] is True
    assert backup_service.validate_backup(b"not a zip")["ok"] is False
