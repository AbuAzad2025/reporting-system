"""Restore-service contract: scope, atomicity, idempotency, type coercion.

These call app.services.backup directly so the guarantees the HTTP routes
rely on are pinned independently of Flask.
"""
import io
import json
import zipfile
from datetime import date, datetime

import pytest

from app.services import backup as backup_service
from app.services.backup import (BACKUP_VERSION, build_backup,
                                  restore_backup, validate_backup)


def _archive(payloads, version=BACKUP_VERSION, scope="project",
             project_id=1):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps({
            "version": version, "scope": scope, "project_id": project_id,
            "created_at": "2026-01-01T00:00:00",
            "generator": "hardening"}))
        for name, data in payloads.items():
            z.writestr(name, json.dumps(data))
    return buf.getvalue()


def _row(serial, project_id, **extra):
    row = {"id": 900 + len(serial), "serial": serial,
           "project_id": project_id, "user_id": 4,
           "status": "pending", "report_date": "2026-05-05",
           "signatory_name": "Engineer Name", "created_at":
           "2026-05-05T08:30:00", "updated_at": "2026-05-05T08:30:00"}
    row.update(extra)
    return row


class TestScopeEnforcement:

    def test_project_archive_cannot_restore_without_a_project(self, app):
        data = _archive({"ops_records/rfis.json": []})
        with app.app_context():
            with pytest.raises(ValueError, match="requires a target project"):
                restore_backup(data)

    def test_platform_archive_cannot_restore_into_a_project(self, app):
        with app.app_context():
            data = build_backup()
        with app.app_context():
            with pytest.raises(ValueError, match="cannot be restored"):
                restore_backup(data, project_id=1)

    def test_rows_of_another_project_are_dropped(self, app):
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            data = _archive({"ops_records/rfis.json": [
                _row("RFI-ALPHA-1", alpha.id, subject="mine",
                     question="q", ball_in_court="c", priority="normal"),
                _row("RFI-OTHER-1", alpha.id + 999, subject="theirs",
                     question="q", ball_in_court="c", priority="normal"),
            ]}, project_id=alpha.id)
            counts = restore_backup(data, project_id=alpha.id)
            assert counts["rfis"] == 1
            assert RFI.query.filter_by(serial="RFI-ALPHA-1").count() == 1
            assert RFI.query.filter_by(serial="RFI-OTHER-1").count() == 0


class TestTypeCoercion:

    def test_iso_strings_become_real_date_objects(self, app):
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            data = _archive({"ops_records/rfis.json": [
                _row("RFI-COERCE-1", alpha.id, subject="coerced",
                     question="q", ball_in_court="c", priority="normal",
                     report_date="2026-07-19", created_at="2026-07-19T14:05:06",
                     updated_at="2026-07-19T14:05:06")]},
                project_id=alpha.id)
            restore_backup(data, project_id=alpha.id)
            row = RFI.query.filter_by(serial="RFI-COERCE-1").one()
            assert row.report_date == date(2026, 7, 19)
            assert isinstance(row.created_at, datetime)
            assert row.created_at == datetime(2026, 7, 19, 14, 5, 6)
            assert row.updated_at == datetime(2026, 7, 19, 14, 5, 6)

    def test_unparseable_date_falls_back_instead_of_raising(self, app):
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            data = _archive({"ops_records/rfis.json": [
                _row("RFI-BADDATE-1", alpha.id, subject="x", question="q",
                     ball_in_court="c", priority="normal",
                     report_date="not-a-date",
                     created_at="also-not-a-date")]},
                project_id=alpha.id)
            restore_backup(data, project_id=alpha.id)
            row = RFI.query.filter_by(serial="RFI-BADDATE-1").one()
            assert row.report_date == date.today()


class TestAtomicity:

    def test_failure_rolls_back_everything_and_leaves_session_usable(
            self, app):
        from app.extensions import db
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            before = RFI.query.count()
            data = _archive({"ops_records/rfis.json": [
                _row("RFI-ATOMIC-1", alpha.id, subject="ok", question="q",
                     ball_in_court="c", priority="normal")]},
                version="9.9", project_id=alpha.id)
            with pytest.raises(ValueError, match="version mismatch"):
                restore_backup(data, project_id=alpha.id)
            assert RFI.query.count() == before
            db.session.add(RFI(project_id=alpha.id, user_id=4,
                               serial="RFI-AFTER-ROLLBACK", subject="after",
                               question="q"))
            db.session.commit()
            assert RFI.query.count() == before + 1

    def test_partial_failure_leaves_no_half_written_rows(self, app):
        from app.extensions import db
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            before = RFI.query.count()
            data = _archive({
                "project.json": [{"id": alpha.id, "name": None,
                                  "location": "Riyadh", "contractor": "",
                                  "client": "", "consultant": "",
                                  "logo_path": "", "logo2_path": "",
                                  "contract_no": "", "funding_source": "",
                                  "currency": "ILS", "is_active": True,
                                  "created_at": "2026-05-05T08:30:00"}],
                "ops_records/rfis.json": [
                    _row("RFI-PARTIAL-1", alpha.id, subject="x",
                         question="q", ball_in_court="c",
                         priority="normal")]},
                project_id=alpha.id)
            with pytest.raises(Exception):
                restore_backup(data, project_id=alpha.id)
            assert RFI.query.filter_by(serial="RFI-PARTIAL-1").count() == 0
            assert RFI.query.count() == before
            assert Project.query.filter_by(
                name="Alpha Tower").one() is not None
            db.session.rollback()
            db.session.add(RFI(project_id=alpha.id, user_id=4,
                               serial="RFI-PROBE-OK", subject="probe",
                               question="q"))
            db.session.commit()


class TestIdempotency:

    def test_restoring_the_same_archive_twice_is_stable(self, app):
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            payload = _archive({"ops_records/rfis.json": [
                _row("RFI-IDEMPOTENT-1", alpha.id, subject="x", question="q",
                     ball_in_court="c", priority="normal")]},
                project_id=alpha.id)
            restore_backup(payload, project_id=alpha.id)
            first = RFI.query.filter_by(serial="RFI-IDEMPOTENT-1").count()
            restore_backup(payload, project_id=alpha.id)
            second = RFI.query.filter_by(serial="RFI-IDEMPOTENT-1").count()
            assert first == second == 1

    def test_replace_true_removes_rows_missing_from_the_archive(self, app):
        from app.extensions import db
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            stale = RFI(project_id=alpha.id, user_id=4, serial="RFI-STALE-99",
                        subject="stale", question="q")
            db.session.add(stale)
            db.session.commit()
            payload = _archive({"ops_records/rfis.json": [
                _row("RFI-KEEP-1", alpha.id, subject="keep", question="q",
                     ball_in_court="c", priority="normal")]},
                project_id=alpha.id)
            restore_backup(payload, project_id=alpha.id, replace=True)
            assert RFI.query.filter_by(serial="RFI-STALE-99").count() == 0
            assert RFI.query.filter_by(serial="RFI-KEEP-1").count() == 1

    def test_replace_false_keeps_rows_missing_from_the_archive(self, app):
        from app.extensions import db
        from app.models import Project
        from app.ops.models import RFI
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            db.session.add(RFI(project_id=alpha.id, user_id=4,
                               serial="RFI-KEEP-77", subject="keep",
                               question="q"))
            db.session.commit()
            payload = _archive({"ops_records/rfis.json": []},
                               project_id=alpha.id)
            restore_backup(payload, project_id=alpha.id)
            assert RFI.query.filter_by(serial="RFI-KEEP-77").count() == 1


class TestSharedTables:

    def test_templates_and_fields_are_mapped_not_duplicated(self, app):
        from app.extensions import db
        from app.models import DynamicField, ReportTemplate
        with app.app_context():
            templates_before = ReportTemplate.query.count()
            fields_before = DynamicField.query.count()
            alpha = backup_service.Project.query.filter_by(
                name="Alpha Tower").one()
            payloads = {
                "report_templates.json": [{"id": 801, "key": "daily",
                                           "name_ar": "يومي",
                                           "name_en": "Daily",
                                           "description": "",
                                           "icon": "x", "gradient": "y",
                                           "is_active": True,
                                           "is_system": False,
                                           "created_by_id": None,
                                           "created_at": "2026-01-01T00:00:00"}],
                "dynamic_fields.json": [{"id": 802, "template_id": 801,
                                         "field_key": "hardening_probe",
                                         "label_ar": "probe",
                                         "field_type": "text",
                                         "options": [], "required": False,
                                         "rules": {}, "sub_fields": [],
                                         "position": 99,
                                         "placeholder": ""}],
            }
            payload = _archive(payloads, project_id=alpha.id)
            restore_backup(payload, project_id=alpha.id)
            assert ReportTemplate.query.count() == templates_before
            daily = ReportTemplate.query.filter_by(key="daily").one()
            probe = DynamicField.query.filter_by(
                field_key="hardening_probe").all()
            assert len(probe) == 1
            assert probe[0].template_id == daily.id

    def test_attachments_of_unknown_records_are_skipped(self, app):
        from app.models import Project
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            payload = _archive({"attachments.json": [{
                "id": 901, "record_kind": "site-inspections",
                "record_id": 424242, "project_id": alpha.id,
                "filename": "x.png", "storage_key": "reports/x.png",
                "mime_type": "image/png", "byte_size": 10,
                "uploaded_by": 4,
                "created_at": "2026-01-01T00:00:00"}]},
                project_id=alpha.id)
            counts = restore_backup(payload, project_id=alpha.id)
            assert counts["attachments"] == 0


class TestValidation:

    def test_export_is_always_importable_after_coercion(self, app):
        from app.models import Project
        with app.app_context():
            alpha = Project.query.filter_by(name="Alpha Tower").one()
            data = build_backup(alpha.id)
            report = validate_backup(data)
            assert report["ok"] is True
            counts = restore_backup(data, project_id=alpha.id, replace=True)
            assert counts["site_inspections"] == 1
            assert counts["project_members"] == 3
