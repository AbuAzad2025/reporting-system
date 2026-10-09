"""Reachable-branch tests for the backup service and the model helpers.

``app/services/backup.py`` and ``app/models.py`` keep a handful of branches the
rest of the suite never reaches. Every test here drives the real code against
the shared ``app`` / ``client`` fixtures (tests/conftest.py) or calls the pure
helper directly, and asserts concrete values or database state - never a bare
truthiness or smoke check.

backup.py branches pinned here:
  * ``_json_default``      - date, datetime and the ``str()`` fallback
  * ``_model_to_dict``     - a live row and a row whose optionals are NULL
  * ``_query_all``         - unscoped, ``project_id`` filter, the
                             relationship-only (``model.project.has()``) filter
                             and the "not tenant scoped at all" bail-out
  * ``_parse_date`` / ``_parse_datetime`` - already-parsed date objects
  * ``_scoped_rows``       - project_name-only rows, rows with no tenant key
  * ``restore_backup``     - missing target project, platform-scope user FK
                             remap, submission / legacy-report / attachment
                             re-insertion
  * ``validate_backup``    - empty buffer, non-ZIP payload, broken
                             metadata.json, CRC-corrupt member
  * ``backup_size`` / ``backup_filename`` / ``export_to_stream`` /
    ``export_to_file`` / ``import_from_file``

models.py branches pinned here:
  * ``User.can_manage_users`` / ``User.can_manage_templates`` (incl. the legacy
    ``"user"`` role alias)
  * brand resolution - unauthenticated caller, tenant member, platform
    manager fallback, and a user with no tenant at all
  * ``Report.get`` and the ``TenantBranding`` / ``TenantTemplateOverride``
    ``__repr__`` methods
"""
import io
import json
import re
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from flask_login import AnonymousUserMixin

from app.extensions import db
from app.models import (REPORT_TYPES, Project, Report, ReportSubmission,
                        ReportTemplate, TenantBranding, TenantTemplateOverride,
                        User)
from app.ops.models import (Attachment, ProgressBilling, ProjectMember,
                            SiteInspection)
from app.services.backup import (BACKUP_VERSION, OPS_MODELS, _json_default,
                                  _model_to_dict, _parse_date, _parse_datetime,
                                  _query_all, _scoped_rows, backup_filename,
                                  backup_size, build_backup, export_to_file,
                                  export_to_stream, import_from_file,
                                  restore_backup, validate_backup)
from tests.conftest import login_as, _SEEDED_USERNAMES

ALPHA = "Alpha Tower"
BETA = "Beta Hospital"
#: The seeded accounts. Read from the fixture's own table rather than
#: restated here: when a role is seeded this list has to follow, and a
#: hand-copied set is how four new roles turned six count assertions red
#: without anybody noticing which number was the stale one.
SEEDED_USERS = set(_SEEDED_USERNAMES)

#: Accounts seeded as members of Alpha Tower, by name. Same reasoning.
ALPHA_MEMBERS = {"t_eng", "t_safety", "t_pm", "t_pd", "t_qc", "t_consult",
                 "t_procure"}

#: Every seeded ProjectMember row across both projects.
PLATFORM_MEMBERS = len(ALPHA_MEMBERS) + 1  # + the Beta engineer


# --------------------------------------------------------------------- utils
def _user(username):
    return User.query.filter_by(username=username).one()


def _project(name):
    return Project.query.filter_by(name=name).one()


def _template(key="daily"):
    return ReportTemplate.query.filter_by(key=key).one()


def _submission(project, author, data, report_date=date(2026, 3, 4)):
    sub = ReportSubmission(template_id=_template().id, project_id=project.id,
                           project_name=project.name, report_date=report_date,
                           data=data, signatory_name=author.full_name,
                           user_id=author.id)
    db.session.add(sub)
    db.session.commit()
    return sub


def _project_archive(payloads, project_id, version=BACKUP_VERSION):
    """Hand-built project-scoped archive (same layout build_backup writes)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps({
            "version": version, "scope": "project", "project_id": project_id,
            "created_at": "2026-01-01T00:00:00", "generator": "branch tests"}))
        for name, rows in payloads.items():
            z.writestr(name, json.dumps(rows))
    return buf.getvalue()


# --------------------------------------------------------- JSON serialisation
def test_json_default_serialises_dates_and_falls_back_to_str():
    assert _json_default(date(2026, 3, 4)) == "2026-03-04"
    assert _json_default(datetime(2026, 3, 4, 5, 6, 7)) == "2026-03-04T05:06:07"
    # Values json cannot encode are stringified instead of raising.
    assert _json_default(Decimal("12.50")) == "12.50"
    assert _json_default({"k": 1}) == "{'k': 1}"
    payload = json.dumps({"d": date(2026, 3, 4), "amount": Decimal("2.5")},
                         default=_json_default)
    assert payload == '{"d": "2026-03-04", "amount": "2.5"}'


def test_model_to_dict_reads_a_live_row_and_keeps_nulls(app):
    with app.app_context():
        eng = _user("t_eng")
        data = _model_to_dict(eng)
        assert set(data) == {c.name for c in User.__table__.columns}
        assert data["id"] == eng.id
        assert data["username"] == "t_eng"
        assert data["role"] == "site_engineer"
        assert data["created_at"] == eng.created_at.isoformat()
        assert json.loads(json.dumps(data))["full_name"] == eng.full_name

        # Blanked out after the insert, so the defaults really do land as NULL.
        nullable = ("phone", "company", "avatar", "job_title", "department",
                    "certification", "notification_prefs", "created_at")
        nulls = User(username="t_nulls", email="nulls@t.com",
                     full_name="No Optionals", role="site_engineer",
                     password_hash="x")
        db.session.add(nulls)
        db.session.commit()
        for column in nullable:
            setattr(nulls, column, None)
        db.session.commit()
        db.session.refresh(nulls)
        empty = _model_to_dict(nulls)
        for column in nullable:
            assert column in empty
            assert empty[column] is None


# ------------------------------------------------------------- tenant queries
def test_query_all_without_a_project_filter_returns_every_row(app):
    with app.app_context():
        users = _query_all(User)
        assert len(users) == len(SEEDED_USERS)
        assert {u["username"] for u in users} == SEEDED_USERS

        alpha = _project(ALPHA)
        members = _query_all(ProjectMember, project_id=alpha.id)
        assert len(members) == len(ALPHA_MEMBERS)
        assert {m["user_id"] for m in members} == {
            _user(name).id for name in ALPHA_MEMBERS}
        assert {m["project_id"] for m in members} == {alpha.id}
        assert {m["role_in_project"] for m in members} == {"member", "owner"}
        assert {m["id"] for m in members} == {
            m.id for m in ProjectMember.query.filter_by(
                project_id=alpha.id).all()}

        inspections = _query_all(SiteInspection, project_id=alpha.id)
        assert [i["serial"] for i in inspections] == ["SIR-000001"]
        assert inspections[0]["result_value"] == 28.0


def test_query_all_scopes_a_model_that_only_has_a_project_relationship(app):
    with app.app_context():
        alpha = _project(ALPHA)
        beta = _project(BETA)
        mine = _submission(alpha, _user("t_eng"), {"weather": "clear"})
        theirs = _submission(beta, _user("t_eng2"), {"weather": "rain"},
                             report_date=date(2026, 3, 5))

        class _ProjectLinkedOnly:
            """Stands in for a model with no project_id column.

            ``query`` and ``project`` are borrowed from a real model that
            reaches its project through a many-to-one relationship, which is
            the shape the relationship branch of ``_query_all`` is written for.
            """
            query = ReportSubmission.query
            project = ReportSubmission.project

        rows = _query_all(_ProjectLinkedOnly, project_id=alpha.id)
        assert [r["id"] for r in rows] == [mine.id]
        assert rows[0]["project_name"] == ALPHA
        assert rows[0]["report_date"] == "2026-03-04"
        assert rows[0]["data"] == {"weather": "clear"}
        assert [r["id"] for r in
                _query_all(_ProjectLinkedOnly, project_id=beta.id)] == [theirs.id]


def test_query_all_skips_a_model_outside_the_tenant_schema(app):
    with app.app_context():
        assert len(_query_all(User)) == len(SEEDED_USERS)
        # User is platform-scoped: it has neither project_id nor project, so a
        # project filter can never match and yields no rows at all.
        assert _query_all(User, project_id=_project(ALPHA).id) == []


def test_scoped_rows_keeps_only_rows_of_the_target_tenant(app):
    with app.app_context():
        alpha = _project(ALPHA)
        rows = [
            {"id": 1, "project_id": alpha.id},
            {"id": 2, "project_id": alpha.id + 99},
            {"id": 3, "project_id": None},
            {"id": 4, "project_name": ALPHA},
            {"id": 5, "project_name": BETA},
            {"id": 6, "key": "shared-table"},
        ]
        kept = _scoped_rows(rows, alpha.id, ALPHA)
        assert [r["id"] for r in kept] == [1, 4, 6]
        # A platform restore keeps every row verbatim.
        assert _scoped_rows(rows, None, ALPHA) == rows
        # Legacy rows are only linked by name, so an unnamed target drops them.
        assert _scoped_rows([{"id": 4, "project_name": ALPHA}], alpha.id, "") == []


def test_parse_helpers_accept_already_parsed_date_objects():
    moment = datetime(2026, 3, 4, 5, 6, 7)
    day = date(2026, 3, 4)
    assert _parse_date(moment) == day
    assert _parse_date(day) is day
    assert _parse_datetime(moment) is moment
    assert _parse_datetime(day) == datetime(2026, 3, 4)
    # The ISO-string path still drives the restore coercion.
    assert _parse_date("2026-03-04T05:06:07") == day
    assert _parse_datetime("2026-03-04T05:06:07Z") == moment
    assert _parse_date("") is None
    assert _parse_datetime("not-a-date") is None


# ------------------------------------------------------------------- restore
def test_restore_of_a_project_archive_needs_an_existing_target(app):
    with app.app_context():
        alpha = _project(ALPHA)
        data = build_backup(project_id=alpha.id)
        with pytest.raises(ValueError, match="Target project not found"):
            restore_backup(data, project_id=alpha.id + 999)
        # The failed restore rolled back: the database is untouched and the
        # session is still usable.
        assert Project.query.count() == 2
        assert db.session.get(Project, alpha.id).name == ALPHA
        assert len(_query_all(SiteInspection, project_id=alpha.id)) == 1


def test_platform_restore_remaps_user_foreign_keys_onto_restored_ids(app):
    with app.app_context():
        alpha = _project(ALPHA)
        eng = _user("t_eng")
        signatory = eng.full_name
        old_eng_id = eng.id
        _submission(alpha, eng, {"weather": "clear", "labor_count": 10})
        data = build_backup()

        # Drop the engineer plus every row that pointed at them, so the restore
        # has to insert them again under whatever id the users table hands out.
        db.session.delete(ReportSubmission.query.one())
        for member in ProjectMember.query.filter_by(user_id=old_eng_id).all():
            db.session.delete(member)
        for model_cls in OPS_MODELS.values():
            for row in model_cls.query.filter_by(user_id=old_eng_id).all():
                db.session.delete(row)
        db.session.delete(eng)
        db.session.commit()
        assert User.query.filter_by(username="t_eng").first() is None
        assert ReportSubmission.query.count() == 0

        counts = restore_backup(data)

        restored = _user("t_eng")
        assert restored.id != old_eng_id, "ids must differ to prove the remap"
        assert counts["users"] == len(SEEDED_USERS)
        assert User.query.count() == len(SEEDED_USERS)
        assert restored.check_password("pw12345") is True

        # No restored row still points at the pre-restore user id.
        assert ReportSubmission.query.filter_by(user_id=old_eng_id).count() == 0
        for model_cls in OPS_MODELS.values():
            assert model_cls.query.filter_by(user_id=old_eng_id).count() == 0
            assert model_cls.query.filter_by(user_id=restored.id).count() > 0

        assert ReportSubmission.query.one().user_id == restored.id
        inspection = SiteInspection.query.filter_by(serial="SIR-000001").one()
        assert inspection.user_id == restored.id
        assert inspection.signatory_name == signatory
        # reviewed_by_id pointed at an untouched user and keeps its id.
        assert ProgressBilling.query.one().reviewed_by_id == _user("t_admin").id
        members = ProjectMember.query.filter_by(user_id=restored.id).all()
        assert [m.project_id for m in members] == [alpha.id]
        assert members[0].role_in_project == "member"


def test_project_scope_restore_reinserts_submissions_and_attachments(app):
    with app.app_context():
        alpha = _project(ALPHA)
        eng = _user("t_eng")
        inspection = SiteInspection.query.filter_by(serial="SIR-000001").one()
        answers = {"weather": "clear", "labor_count": 10}
        _submission(alpha, eng, answers)
        attachment = Attachment(record_kind="site-inspections",
                                record_id=inspection.id, project_id=alpha.id,
                                filename="cube.png",
                                storage_key="alpha/inspections/cube.png",
                                mime_type="image/png", byte_size=1234,
                                uploaded_by=eng.id)
        db.session.add(attachment)
        db.session.commit()
        data = build_backup(project_id=alpha.id)

        db.session.delete(ReportSubmission.query.one())
        db.session.delete(Attachment.query.one())
        db.session.commit()
        assert ReportSubmission.query.count() == 0
        assert Attachment.query.count() == 0

        counts = restore_backup(data, project_id=alpha.id)

        assert counts["report_submissions"] == 1
        assert counts["attachments"] == 1
        assert counts["site_inspections"] == 1
        assert counts["project_members"] == len(ALPHA_MEMBERS)

        back = ReportSubmission.query.one()
        assert back.project_id == alpha.id
        assert back.project_name == ALPHA
        assert back.user_id == eng.id
        assert back.data == answers
        assert back.report_date == date(2026, 3, 4)
        assert isinstance(back.created_at, datetime)
        assert back.created_at.tzinfo is None

        att = Attachment.query.one()
        assert att.record_id == inspection.id
        assert att.record_kind == "site-inspections"
        assert att.storage_key == "alpha/inspections/cube.png"
        assert att.byte_size == 1234
        assert att.uploaded_by == eng.id
        assert att.mime_type == "image/png"


def test_project_scope_restore_reinserts_legacy_reports_linked_by_name(app):
    with app.app_context():
        alpha = _project(ALPHA)
        eng = _user("t_eng")
        eng2 = _user("t_eng2")
        data = _project_archive({"legacy_reports.json": [
            {"id": 900, "report_type": "daily", "project_name": ALPHA,
             "location": "Riyadh", "contractor": "Alpha Main",
             "report_date": "2026-02-01",
             "data": {"weather": "clear", "labor_count": 10},
             "signatory_name": eng.full_name, "user_id": eng.id,
             "created_at": "2026-02-01T07:00:00",
             "updated_at": "2026-02-01T07:30:00"},
            {"id": 901, "report_type": "daily", "project_name": BETA,
             "location": "Jeddah", "contractor": "Beta Main",
             "report_date": "2026-02-01", "data": {"weather": "rain"},
             "signatory_name": eng2.full_name, "user_id": eng2.id,
             "created_at": "2026-02-01T07:00:00",
             "updated_at": "2026-02-01T07:30:00"},
        ]}, project_id=alpha.id)

        counts = restore_backup(data, project_id=alpha.id)

        # The Beta row carries no project_id, so only the name link filters it.
        assert counts["legacy_reports"] == 1
        assert Report.query.count() == 1
        row = Report.query.one()
        assert row.project_name == ALPHA
        assert row.report_type == "daily"
        assert row.location == "Riyadh"
        assert row.user_id == eng.id
        assert row.report_date == date(2026, 2, 1)
        assert row.created_at == datetime(2026, 2, 1, 7, 0)
        assert row.updated_at == datetime(2026, 2, 1, 7, 30)
        assert row.data == {"weather": "clear", "labor_count": 10}
        assert row.get("labor_count") == 10


# ---------------------------------------------------------------- validation
def test_validate_backup_rejects_an_empty_buffer():
    result = validate_backup(b"")
    assert result["ok"] is False
    assert result["error"] == "File is not a zip file"
    assert result["size"] == 0
    assert "metadata" not in result


def test_validate_backup_rejects_a_non_zip_payload():
    payload = b"this is definitely not a zip archive"
    result = validate_backup(payload)
    assert result["ok"] is False
    assert result["error"] == "File is not a zip file"
    assert result["size"] == len(payload) == 36
    assert "metadata" not in result


def test_validate_backup_rejects_a_zip_with_broken_metadata():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", b"{not json")
        z.writestr("users.json", b"[]")
    data = buf.getvalue()
    result = validate_backup(data)
    assert result["ok"] is False
    assert "Expecting property name" in result["error"]
    assert result["size"] == len(data)
    assert "metadata" not in result

    # A structurally valid archive without metadata.json fails the same way.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("users.json", b"[]")
    missing = validate_backup(buf.getvalue())
    assert missing["ok"] is False
    assert "metadata.json" in missing["error"]


def test_validate_backup_reports_a_corrupt_archive_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("metadata.json", json.dumps(
            {"version": BACKUP_VERSION, "scope": "platform"}))
        z.writestr("payload.txt", b"A" * 200)
    data = bytearray(buf.getvalue())
    offset = data.find(b"A" * 200)
    assert offset > 0
    data[offset + 10] = ord("B")

    result = validate_backup(bytes(data))
    assert result["ok"] is False
    assert result["error"] == "Corrupt archive member: payload.txt"
    assert result["size"] == len(data)
    assert "metadata" not in result


def test_validate_backup_accepts_a_real_archive(app):
    with app.app_context():
        data = build_backup()
        result = validate_backup(data)

    assert result["ok"] is True
    assert result["size"] == len(data) == backup_size(data)
    assert set(result) == {"ok", "metadata", "size"}
    meta = result["metadata"]
    assert meta["version"] == BACKUP_VERSION
    assert meta["scope"] == "platform"
    assert meta["project_id"] is None
    assert meta["generator"] == "Azadexa Cloud Backup Service"
    created = datetime.fromisoformat(meta["created_at"])
    assert created.tzinfo is None
    drift = abs((datetime.now(timezone.utc).replace(tzinfo=None) - created)
                .total_seconds())
    assert drift < 120, f"metadata stamp is {drift}s away from now"


# ------------------------------------------------------------------ exports
def test_backup_size_is_the_archive_length(app, tmp_path):
    with app.app_context():
        data = build_backup()
    target = tmp_path / "sized.zip"
    assert target.write_bytes(data) == len(data)
    assert backup_size(data) == target.stat().st_size
    assert backup_size(target.read_bytes()) == target.stat().st_size
    assert backup_size(b"") == 0
    assert backup_size(b"12345") == 5


def test_backup_filename_carries_scope_project_and_utc_stamp():
    platform = backup_filename()
    assert re.fullmatch(r"azadexa-platform-\d{8}-\d{6}\.zip", platform)
    platform_stamp = platform[len("azadexa-platform-"):-len(".zip")]
    parsed = datetime.strptime(platform_stamp, "%Y%m%d-%H%M%S")
    assert parsed.year >= 2026
    drift = abs((datetime.now(timezone.utc).replace(tzinfo=None) - parsed)
                .total_seconds())
    assert drift < 120, f"stamp is {drift}s away from now"

    project = backup_filename(project_id=42)
    assert re.fullmatch(r"azadexa-project-42-\d{8}-\d{6}\.zip", project)
    assert project.endswith(".zip")
    assert project != platform
    project_stamp = project[len("azadexa-project-42-"):-len(".zip")]
    assert re.fullmatch(r"\d{8}-\d{6}", project_stamp)
    assert datetime.strptime(project_stamp, "%Y%m%d-%H%M%S")


def test_export_to_stream_round_trips_through_restore(app):
    with app.app_context():
        alpha = _project(ALPHA)
        eng = _user("t_eng")
        answers = {"weather": "clear", "labor_count": 10}
        _submission(alpha, eng, answers)

        stream = export_to_stream()
        data = stream.getvalue()
        assert data[:2] == b"PK"
        assert backup_size(data) == len(data)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            meta = json.loads(archive.read("metadata.json").decode("utf-8"))
        assert meta["scope"] == "platform"
        assert meta["version"] == BACKUP_VERSION
        assert meta["project_id"] is None
        assert meta["generator"] == "Azadexa Cloud Backup Service"
        assert validate_backup(data)["ok"] is True

        db.session.delete(ReportSubmission.query.one())
        db.session.commit()

        counts = restore_backup(data)

        assert counts["users"] == len(SEEDED_USERS)
        assert counts["projects"] == 2
        assert counts["project_members"] == PLATFORM_MEMBERS
        assert counts["report_submissions"] == 1
        assert counts["site_inspections"] == 1
        assert counts["cost_variances"] == 2
        assert counts["attachments"] == 0
        assert User.query.count() == len(SEEDED_USERS)
        assert Project.query.count() == 2
        back = ReportSubmission.query.one()
        assert back.data == answers
        assert back.user_id == eng.id
        assert back.project_name == ALPHA
        assert SiteInspection.query.filter_by(
            serial="SIR-000001").one().project_id == alpha.id


def test_export_to_file_and_import_from_file_round_trip(app, tmp_path):
    with app.app_context():
        alpha = _project(ALPHA)
        eng = _user("t_eng")
        answers = {"weather": "clear", "labor_count": 10}
        _submission(alpha, eng, answers)

        platform_zip = tmp_path / "platform.zip"
        path = export_to_file(str(platform_zip))
        assert path == str(platform_zip)
        assert Path(path).is_file()
        on_disk = Path(path).read_bytes()
        assert on_disk[:4] == b"PK\x03\x04"
        assert backup_size(on_disk) == platform_zip.stat().st_size
        assert validate_backup(on_disk)["ok"] is True
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        assert {"metadata.json", "users.json", "projects.json",
                "project_members.json", "report_templates.json",
                "dynamic_fields.json", "report_submissions.json",
                "legacy_reports.json", "attachments.json"} <= names
        assert "ops_records/site_inspections.json" in names
        assert "ops_records/safety_reports.json" in names

        db.session.delete(ReportSubmission.query.one())
        db.session.commit()
        assert ReportSubmission.query.count() == 0

        counts = import_from_file(path)
        assert counts["users"] == len(SEEDED_USERS)
        assert counts["report_submissions"] == 1
        assert ReportSubmission.query.one().data == answers

        # A project-scoped file threaded through import_from_file as well.
        alpha_zip = tmp_path / "alpha.zip"
        alpha_path = export_to_file(str(alpha_zip), project_id=alpha.id)
        db.session.delete(SiteInspection.query.filter_by(
            serial="SIR-000001").one())
        db.session.delete(ReportSubmission.query.one())
        db.session.commit()
        assert SiteInspection.query.count() == 0
        assert ReportSubmission.query.count() == 0

        scoped_counts = import_from_file(alpha_path, project_id=alpha.id)
        assert scoped_counts["site_inspections"] == 1
        assert scoped_counts["project_members"] == len(ALPHA_MEMBERS)
        assert scoped_counts["report_submissions"] == 1
        restored = SiteInspection.query.filter_by(serial="SIR-000001").one()
        assert restored.project_id == alpha.id
        assert restored.user_id == eng.id
        assert restored.test_type == "cube 7d"
        assert restored.result_value == 28.0
        assert restored.verdict == "pass"
        assert ReportSubmission.query.one().data == answers


# -------------------------------------------------------------------- models
def test_can_manage_users_and_templates_belong_to_platform_managers(app):
    with app.app_context():
        for name in ("t_owner", "t_admin"):
            manager = _user(name)
            assert manager.can_manage_users() is True
            assert manager.can_manage_templates() is True
            assert manager.has_perm("manage_users") is True
            assert manager.has_perm("manage_templates") is True
        for name in ("t_pm", "t_eng", "t_eng2", "t_safety"):
            member = _user(name)
            assert member.can_manage_users() is False
            assert member.can_manage_templates() is False
            assert member.has_perm("manage_users") is False
            assert member.has_perm("manage_templates") is False

        # The legacy "user" role normalises to site_engineer, which manages
        # neither users nor templates.
        legacy = User(username="t_legacy", email="legacy@t.com",
                      full_name="Legacy Role", role="user", password_hash="x")
        db.session.add(legacy)
        db.session.commit()
        assert legacy.norm_role == "site_engineer"
        assert legacy.can_manage_users() is False
        assert legacy.can_manage_templates() is False
        assert legacy.is_admin is False
        assert legacy.has_perm("manage_users") is False


def test_resolve_brand_returns_nothing_for_an_anonymous_caller(app):
    """There is no tenant to resolve for someone who is not signed in.

    The resolver used to be User.get_brand. It was removed as a second, dead
    copy of app.services.branding.resolve_brand; the behaviour it had is
    asserted here against the one that is actually used.
    """
    from app.services.branding import resolve_brand
    anonymous = AnonymousUserMixin()
    assert anonymous.is_authenticated is False
    with app.app_context():
        view = resolve_brand(anonymous)
    assert view.row is None
    assert view.company_ar == app.config["COMPANY_NAME_AR"]


def test_resolve_brand_finds_the_tenant_the_caller_belongs_to(app, client):
    """A retired row and a branding for another project are both ignored.

    Insert order matters: a platform manager with no membership falls back to
    the first active branding, and Beta is the first one, so a resolver that
    picked by table order would answer "Beta Hospitals" here.
    """
    from app.services.branding import resolve_brand
    with app.app_context():
        alpha = _project(ALPHA)
        beta = _project(BETA)
        retired = TenantBranding(project_id=alpha.id,
                                 company_name_en="Retired Brand",
                                 is_active=False)
        beta_brand = TenantBranding(project_id=beta.id,
                                    company_name_en="Beta Hospitals",
                                    is_active=True)
        alpha_brand = TenantBranding(project_id=alpha.id,
                                     company_name_en="Alpha Contracting",
                                     is_active=True)
        db.session.add_all([retired, beta_brand, alpha_brand])
        db.session.flush()
        alpha_brand.created_at = datetime(2026, 3, 5, 9, 0)
        retired.created_at = datetime(2026, 3, 1, 9, 0)
        db.session.commit()
        assert TenantBranding.query.count() == 3
        beta_brand_id = beta_brand.id

    with app.app_context():
        user = User.query.filter_by(username="t_eng").first()
        # t_eng is already a member of Alpha; a second membership row would
        # violate the unique constraint and is not needed to prove anything.
        view = resolve_brand(user)
        assert view.company_en == "Alpha Contracting", (
            "the caller is a member of Alpha, so Alpha's branding is theirs; "
            "got %r" % view.company_en)
        assert view.row.id != beta_brand_id
        assert view.row.is_active is True


def test_resolve_brand_picks_the_tenant_of_each_member(app, client):
    with app.app_context():
        alpha = _project(ALPHA)
        beta = _project(BETA)
        # Insert order matters: a platform manager with no membership falls
        # back to the first active branding, and Beta is the first one.
        retired = TenantBranding(project_id=alpha.id,
                                 company_name_en="Retired Brand",
                                 is_active=False)
        beta_brand = TenantBranding(project_id=beta.id,
                                    company_name_en="Beta Hospitals",
                                    is_active=True)
        alpha_brand = TenantBranding(project_id=alpha.id,
                                     company_name_en="Alpha Contracting",
                                     is_active=True)
        db.session.add_all([retired, beta_brand, alpha_brand])
        db.session.flush()
        alpha_brand.created_at = datetime(2026, 3, 5, 9, 0)
        retired.created_at = datetime(2026, 3, 1, 9, 0)
        db.session.commit()
        alpha_id = alpha.id
        alpha_brand_id, beta_brand_id = alpha_brand.id, beta_brand.id
        assert TenantBranding.query.count() == 3

    response = login_as(client, "t_eng")
    assert response.status_code == 302

    with app.app_context():
        from app.services.branding import resolve_brand
        engineer = _user("t_eng")
        with client.session_transaction() as http_session:
            assert str(http_session.get("_user_id")) == str(engineer.id)
        view = resolve_brand(engineer)
        assert view.row is not None
        assert view.row.id == alpha_brand_id
        assert view.row.project_id == alpha_id
        assert view.company_en == "Alpha Contracting"
        assert view.row.is_active is True

        # Each caller needs its own application context: resolve_brand caches
        # on g, which is right for one request and wrong for three users asked
        # in a row inside one test. Pushing a context is how a second request
        # would see the second user.
        def brand_of(username):
            with app.app_context():
                return resolve_brand(_user(username))

        # A member of the other tenant resolves to that tenant's brand, and
        # neither picks up the retired row.
        assert brand_of("t_eng2").row.id == beta_brand_id

        # Platform managers have no membership, so they get the most recently
        # updated active branding. Alpha's was set to the later timestamp
        # above, so it wins - ordering by recency, not by table order.
        assert brand_of("t_owner").row.id == alpha_brand_id

        # A non-manager with no tenant at all gets nothing.
        outsider = User(username="t_outsider", email="outsider@t.com",
                        full_name="No Tenant", role="site_engineer",
                        password_hash="x")
        db.session.add(outsider)
        db.session.commit()
        assert brand_of("t_outsider").row is None

        # A platform-wide branding is not attributed to a tenant member.
        db.session.add(TenantBranding(project_id=None,
                                      company_name_en="Platform Wide",
                                      is_active=True))
        db.session.commit()
        assert brand_of("t_outsider").row is None
        assert brand_of("t_eng").row.id == alpha_brand_id


def test_legacy_report_get_reads_stored_answers(app):
    with app.app_context():
        eng = _user("t_eng")
        report = Report(report_type="daily", project_name=ALPHA,
                        location="Riyadh", contractor="Alpha Main",
                        report_date=date(2026, 2, 1),
                        data={"weather": "clear", "labor_count": 10},
                        signatory_name=eng.full_name, user_id=eng.id)
        empty = Report(report_type="weekly", project_name=BETA,
                       location="Jeddah", contractor="Beta Main",
                       report_date=date(2026, 2, 2), data=None,
                       signatory_name=eng.full_name, user_id=eng.id)
        db.session.add_all([report, empty])
        db.session.commit()

        assert report.get("weather") == "clear"
        assert report.get("labor_count") == 10
        assert report.get("missing") == ""
        assert report.get("missing", "fallback") == "fallback"
        assert report.type_ar == REPORT_TYPES["daily"]
        # A row whose data column is NULL reads through the empty default.
        assert empty.get("weather", "fallback") == "fallback"
        assert empty.get("weather") == ""


def test_branding_and_override_reprs_name_their_row(app):
    with app.app_context():
        alpha = _project(ALPHA)
        branding = TenantBranding(project_id=alpha.id,
                                  company_name_en="Alpha Contracting")
        override = TenantTemplateOverride(template_key="daily",
                                          project_id=alpha.id,
                                          fields_config={"notes": "wide"})
        db.session.add_all([branding, override])
        db.session.commit()
        assert repr(branding) == f"<TenantBranding {branding.id} proj={alpha.id}>"
        # Scoped to a company, not a user: a customisation belongs to the
        # project, so it is the project the repr names.
        assert override.project_id == alpha.id
        assert repr(override) == f"<TenantTemplateOverride daily:{alpha.id}>"
        assert TenantTemplateOverride.query.filter_by(
            template_key="daily", tenant_id=override.tenant_id).count() == 1


def test_branding_repr_handles_a_platform_wide_row(app):
    with app.app_context():
        platform_brand = TenantBranding(project_id=None,
                                        company_name_en="Platform Wide")
        db.session.add(platform_brand)
        db.session.commit()
        assert platform_brand.project_id is None
        assert repr(platform_brand) == f"<TenantBranding {platform_brand.id} proj=None>"
