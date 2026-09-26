"""Attachment lifecycle: delete guards, byte removal, orphan reconciliation.

Covers the filesystem-facing branches that only run on failure or during
maintenance: a tampered storage key, a vanished file, a row whose record was
deleted underneath it, a stray file with no row, and the empty-directory prune.
"""
import io
import os

import pytest

from tests.conftest import login_as

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _rid(app, serial="SIR-000001", model="SiteInspection"):
    from app.ops import models as M
    with app.app_context():
        return getattr(M, model).query.filter_by(serial=serial).one().id


def _attach(client, app, payload=JPEG, name="evidence.jpg", rid=None):
    rid = rid or _rid(app)
    login_as(client, "t_eng")
    r = client.post(f"/ops/site-inspections/{rid}/attachments",
                    data={"file": (io.BytesIO(payload), name)})
    assert r.status_code == 201, r.get_json()
    return rid, r.get_json()


def _alpha(app):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name="Alpha Tower").one().id


class TestAbsPathGuard:

    def test_traversal_key_raises(self, app):
        from app.ops.routes import _abs_path
        with app.app_context():
            with pytest.raises(ValueError, match="escapes upload folder"):
                _abs_path("../../config.py")
            with pytest.raises(ValueError):
                _abs_path("/etc/passwd")

    def test_valid_key_resolves_inside_the_upload_root(self, app):
        from app.ops.routes import _abs_path
        with app.app_context():
            resolved = _abs_path("ops/rfis/1/a.jpg")
            assert resolved.startswith(
                os.path.realpath(app.config["UPLOAD_FOLDER"]))

    def test_delete_file_is_best_effort(self, app):
        from app.ops.routes import _delete_file
        with app.app_context():
            assert _delete_file("ops/does/not/exist.jpg") is False
            assert _delete_file("../../config.py") is False


class TestAttachmentDownload:

    def test_tampered_storage_key_is_404_not_500(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        rid, att = _attach(client, app)
        with app.app_context():
            row = db.session.get(Attachment, att["id"])
            row.storage_key = "../../../app.py"
            db.session.commit()
        login_as(client, "t_eng")
        r = client.get(
            f"/ops/site-inspections/{rid}/attachments/{att['id']}/download")
        assert r.status_code == 404
        assert r.get_json() == {"error": "not found"}

    def test_missing_bytes_still_returns_404(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        rid, att = _attach(client, app)
        with app.app_context():
            row = db.session.get(Attachment, att["id"])
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"],
                                   row.storage_key))
            db.session.commit()
        login_as(client, "t_eng")
        r = client.get(
            f"/ops/site-inspections/{rid}/attachments/{att['id']}/download")
        assert r.status_code == 404

    def test_wrong_record_pair_is_404(self, app, client):
        rid, att = _attach(client, app)
        other = _rid(app, "RFI-000001", "RFI")
        login_as(client, "t_eng")
        r = client.get(
            f"/ops/rfis/{other}/attachments/{att['id']}/download")
        assert r.status_code == 404

    def test_cross_tenant_download_is_404(self, app, client):
        rid, att = _attach(client, app)
        login_as(client, "t_eng2")
        r = client.get(
            f"/ops/site-inspections/{rid}/attachments/{att['id']}/download")
        assert r.status_code == 404


class TestAttachmentDelete:

    def test_author_deletes_row_and_bytes(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        rid, att = _attach(client, app)
        login_as(client, "t_eng")
        with app.app_context():
            path = os.path.join(app.config["UPLOAD_FOLDER"],
                                db.session.get(Attachment,
                                               att["id"]).storage_key)
        assert os.path.isfile(path)
        r = client.delete(
            f"/ops/site-inspections/{rid}/attachments/{att['id']}")
        assert r.status_code == 200
        assert r.get_json() == {"deleted": "evidence.jpg"}
        assert not os.path.exists(path)
        with app.app_context():
            assert db.session.get(Attachment, att["id"]) is None

    def test_delete_is_tenant_scoped(self, app, client):
        rid, att = _attach(client, app)
        login_as(client, "t_eng2")
        r = client.delete(
            f"/ops/site-inspections/{rid}/attachments/{att['id']}")
        assert r.status_code == 404

    def test_delete_unknown_id_is_404(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        r = client.delete(f"/ops/site-inspections/{rid}/attachments/999999")
        assert r.status_code == 404

    def test_delete_survives_vanished_bytes(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        rid, att = _attach(client, app)
        with app.app_context():
            row = db.session.get(Attachment, att["id"])
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"],
                                   row.storage_key))
            db.session.commit()
        login_as(client, "t_eng")
        r = client.delete(
            f"/ops/site-inspections/{rid}/attachments/{att['id']}")
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(Attachment, att["id"]) is None

    def test_attachment_list_is_ordered_newest_first(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        for name in ("one.jpg", "two.jpg", "three.jpg"):
            client.post(f"/ops/site-inspections/{rid}/attachments",
                        data={"file": (io.BytesIO(JPEG), name)})
        r = client.get(f"/ops/site-inspections/{rid}/attachments")
        assert r.status_code == 200
        names = [a["filename"] for a in r.get_json()["attachments"]]
        assert sorted(names) == ["one.jpg", "three.jpg", "two.jpg"]
        assert names == ["three.jpg", "two.jpg", "one.jpg"]

    def test_attachment_list_is_empty_for_a_fresh_record(self, app, client):
        login_as(client, "t_eng")
        r = client.get(f"/ops/rfis/{_rid(app, 'RFI-000001', 'RFI')}"
                       "/attachments")
        assert r.get_json()["attachments"] == []


class TestOrphanCleanup:

    def _ops_root(self, app):
        return os.path.join(app.config["UPLOAD_FOLDER"], "ops")

    def _plant(self, app, rel, body=b"stray"):
        path = os.path.join(app.config["UPLOAD_FOLDER"], rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(body)
        return path

    def test_dry_run_reports_without_deleting(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        from app.ops.routes import cleanup_orphaned_attachments
        rid, att = _attach(client, app)
        with app.app_context():
            row = db.session.get(Attachment, att["id"])
            row.record_id = 999999
            db.session.commit()
        stray = self._plant(app, "ops/rfis/1/stray.jpg")
        login_as(client, "t_admin")
        with app.app_context():
            stats = cleanup_orphaned_attachments(dry_run=True)
        assert stats["orphan_rows"] == 1
        assert stats["orphan_files"] == 1
        assert os.path.isfile(stray)
        with app.app_context():
            assert db.session.get(Attachment, att["id"]) is not None

    def test_real_run_deletes_orphan_rows_and_files(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        from app.ops.routes import cleanup_orphaned_attachments
        rid, att = _attach(client, app)
        with app.app_context():
            row = db.session.get(Attachment, att["id"])
            row.record_id = 999999
            db.session.commit()
        stray = self._plant(app, "ops/rfis/1/stray.jpg")
        login_as(client, "t_admin")
        with app.app_context():
            stats = cleanup_orphaned_attachments()
        assert stats["orphan_rows"] == 1
        assert not os.path.exists(stray)
        with app.app_context():
            assert db.session.get(Attachment, att["id"]) is None

    def test_rows_with_vanished_bytes_are_reported_not_deleted(self, app,
                                                               client):
        from app.extensions import db
        from app.ops.models import Attachment
        from app.ops.routes import cleanup_orphaned_attachments
        rid, att = _attach(client, app)
        with app.app_context():
            row = db.session.get(Attachment, att["id"])
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"],
                                   row.storage_key))
            db.session.commit()
            stats = cleanup_orphaned_attachments()
        assert stats["missing_files"] == 1
        assert stats["orphan_rows"] == 0
        with app.app_context():
            assert db.session.get(Attachment, att["id"]) is not None

    def test_live_attachments_are_left_alone(self, app, client):
        from app.ops.routes import cleanup_orphaned_attachments
        rid, att = _attach(client, app)
        login_as(client, "t_admin")
        with app.app_context():
            stats = cleanup_orphaned_attachments()
        assert stats == {"orphan_rows": 0, "missing_files": 0,
                         "orphan_files": 0}

    def test_files_outside_the_ops_tree_are_untouched(self, app, client):
        from app.ops.routes import cleanup_orphaned_attachments
        avatar = self._plant(app, "avatars/keep.png", b"avatar-bytes")
        login_as(client, "t_admin")
        with app.app_context():
            stats = cleanup_orphaned_attachments()
        assert stats["orphan_files"] == 0
        assert os.path.isfile(avatar)
        with open(avatar, "rb") as fh:
            assert fh.read() == b"avatar-bytes"

    def test_unknown_record_kind_row_is_orphaned(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        from app.ops.routes import cleanup_orphaned_attachments
        with app.app_context():
            db.session.add(Attachment(
                record_kind="not-a-kind", record_id=1, project_id=1,
                filename="x.jpg", storage_key="ops/not-a-kind/1/x.jpg",
                mime_type="image/jpeg", byte_size=1, uploaded_by=1))
            db.session.commit()
            stats = cleanup_orphaned_attachments()
        assert stats["orphan_rows"] == 1
        with app.app_context():
            assert Attachment.query.filter_by(
                record_kind="not-a-kind").count() == 0

    def test_empty_directories_are_pruned(self, app, client):
        from app.ops.routes import cleanup_orphaned_attachments
        empty = self._plant(app, "ops/rfis/424242/gone.jpg")
        os.remove(empty)
        login_as(client, "t_admin")
        with app.app_context():
            cleanup_orphaned_attachments()
        assert not os.path.isdir(os.path.dirname(empty))

    def test_cli_wrapper_prints_the_counters(self, app, client):
        login_as(client, "t_admin")
        runner = app.test_cli_runner()
        result = runner.invoke(args=["cleanup-orphaned-attachments",
                                     "--dry-run"])
        assert result.exit_code == 0
        assert "DRY-RUN orphan rows:" in result.output
        assert "orphan files:" in result.output
        assert "rows missing files:" in result.output

    def test_cleanup_is_idempotent(self, app, client):
        from app.ops.routes import cleanup_orphaned_attachments
        rid, att = _attach(client, app)
        self._plant(app, "ops/rfis/1/stray2.jpg")
        login_as(client, "t_admin")
        with app.app_context():
            first = cleanup_orphaned_attachments()
            second = cleanup_orphaned_attachments()
        assert first["orphan_files"] == 1
        assert second == {"orphan_rows": 0, "missing_files": 0,
                          "orphan_files": 0}


class TestCommentGuards:

    def test_json_contract_is_preserved(self, app, client):
        rid, _att = _attach(client, app)
        login_as(client, "t_eng")
        r = client.post(f"/ops/site-inspections/{rid}/comments",
                        json={"body": "ملاحظة JSON"})
        assert r.status_code == 201
        body = r.get_json()
        assert body["body"] == "ملاحظة JSON"
        assert body["id"] > 0

    def test_empty_body_is_422(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        r = client.post(f"/ops/site-inspections/{rid}/comments",
                        json={"body": "   "})
        assert r.status_code == 422
        assert r.get_json()["error"] == "validation failed"

    def test_oversized_body_is_422(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        r = client.post(f"/ops/site-inspections/{rid}/comments",
                        json={"body": "x" * 5000})
        assert r.status_code == 422
        assert "details" in r.get_json()

    def test_comment_on_missing_record_is_404(self, app, client):
        login_as(client, "t_eng")
        r = client.post("/ops/site-inspections/999999/comments",
                        json={"body": "x"})
        assert r.status_code == 404

    def test_comment_list_is_tenant_scoped(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        client.post(f"/ops/site-inspections/{rid}/comments",
                    json={"body": "ملاحظة"})
        login_as(client, "t_eng2")
        r = client.get(f"/ops/site-inspections/{rid}/comments")
        assert r.status_code == 404

    def test_delete_requires_author_or_manager(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        cmt = client.post(f"/ops/site-inspections/{rid}/comments",
                          json={"body": "ملاحظة"}).get_json()
        login_as(client, "t_safety")
        r = client.delete(f"/ops/site-inspections/{rid}/comments/{cmt['id']}")
        assert r.status_code == 403
        with app.app_context():
            from app.ops.models import OpsRecordComment
            assert OpsRecordComment.query.filter_by(
                id=cmt["id"]).count() == 1

    def test_delete_unknown_comment_is_404(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        r = client.delete(f"/ops/site-inspections/{rid}/comments/999999")
        assert r.status_code == 404

    def test_manager_may_delete_someone_elses_comment(self, app, client):
        rid = _rid(app)
        login_as(client, "t_eng")
        cmt = client.post(f"/ops/site-inspections/{rid}/comments",
                          json={"body": "ملاحظة"}).get_json()
        login_as(client, "t_admin")
        r = client.delete(f"/ops/site-inspections/{rid}/comments/{cmt['id']}")
        assert r.status_code == 200
        with app.app_context():
            from app.ops.models import OpsRecordComment
            assert OpsRecordComment.query.filter_by(
                id=cmt["id"]).count() == 0

    def test_record_delete_cascades_comments_and_attachments(self, app,
                                                              client):
        from app.extensions import db
        from app.ops.models import (Attachment, OpsRecordComment, SiteInspection)
        rid, att = _attach(client, app)
        login_as(client, "t_eng")
        client.post(f"/ops/site-inspections/{rid}/comments",
                    json={"body": "ملاحظة"})
        with app.app_context():
            row = db.session.get(SiteInspection, rid)
            row.status = "draft"
            db.session.commit()
            path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                db.session.get(Attachment, att["id"]).storage_key)
        r = client.delete(f"/ops/site-inspections/{rid}")
        assert r.status_code == 200
        assert not os.path.exists(path)
        with app.app_context():
            assert Attachment.query.filter_by(record_id=rid).count() == 0
            assert OpsRecordComment.query.filter_by(record_id=rid).count() == 0


class TestBatchAndAnalyticsBranches:

    def test_batch_accepts_repeated_form_types(self, app, client):
        login_as(client, "t_admin")
        r = client.post("/ops/batch-export", data={
            "from": "2000-01-01", "to": "2999-12-31",
            "types": ["rfis", "cost-variances"]})
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"

    def test_batch_rejects_non_numeric_project(self, app, client):
        login_as(client, "t_admin")
        r = client.post("/ops/batch-export",
                        json={"project_id": "abc", "types": ["rfis"]})
        assert r.status_code == 422
        assert "integer" in r.get_json()["error"]

    def test_batch_permission_gate_precedes_project_scope(self, app, client):
        from app.models import Project
        with app.app_context():
            beta = Project.query.filter_by(name="Beta Hospital").one().id
        login_as(client, "t_eng")
        r = client.post("/ops/batch-export",
                        json={"project_id": beta, "types": ["rfis"]})
        assert r.status_code == 403
        assert r.get_json() == {"error": "insufficient permissions"}

    def test_batch_rejects_a_project_outside_the_tenant(self, app, client):
        from app.models import Project
        with app.app_context():
            beta = Project.query.filter_by(name="Beta Hospital").one().id
        login_as(client, "t_pm")
        r = client.post("/ops/batch-export",
                        json={"project_id": beta, "types": ["rfis"]})
        assert r.status_code in (403, 404)

    def test_batch_page_renders_module_picker(self, app, client):
        login_as(client, "t_admin")
        r = client.get("/ops/batch")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        for kind in ("rfis", "cost-variances", "daily-reports"):
            assert kind in html, kind

    def test_batch_page_is_manager_gated(self, app, client):
        login_as(client, "t_eng")
        assert client.get("/ops/batch").status_code in (302, 403)

    def test_ui_list_status_filter_narrows_results(self, app, client):
        login_as(client, "t_eng")
        everything = client.get("/ops/ui/rfis").get_data(as_text=True)
        filtered = client.get("/ops/ui/rfis?status=approved").get_data(
            as_text=True)
        assert "RFI-000001" in everything
        assert filtered.count("RFI-000001") <= everything.count("RFI-000001")

    def test_registry_lists_every_module(self, app, client):
        login_as(client, "t_eng")
        r = client.get("/ops/")
        assert r.status_code == 200
        modules = r.get_json()["modules"]
        assert len(modules) == 9
        for module in modules:
            assert set(module) == {"kind", "prefix", "name_ar", "name_en"}
            assert module["prefix"]

    def test_meta_endpoint_describes_a_module(self, app, client):
        login_as(client, "t_eng")
        r = client.get("/ops/rfis/meta")
        assert r.status_code == 200
        body = r.get_json()
        assert body["kind"] == "rfis"
        assert isinstance(body["schema"], dict)
        assert isinstance(body["statuses"], (list, dict))

    def test_serial_conflict_is_retried_then_409(self, app, client, monkeypatch):
        from app.ops import models as M
        login_as(client, "t_eng")
        monkeypatch.setattr(M, "next_serial", lambda *a, **k: "RFI-000001")
        r = client.post("/ops/rfis", json={
            "project_id": _alpha(app), "subject": "s", "question": "q",
            "ball_in_court": "consultant", "priority": "normal"})
        assert r.status_code == 409
        assert "serial" in r.get_json()["error"].lower()
