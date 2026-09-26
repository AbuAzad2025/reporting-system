"""WORKSTREAM 2: physical attachment storage + template guarantees.

Covers: bytes persisted under UPLOAD_FOLDER, download round-trip,
file removal on attachment/record delete, path-traversal safety,
orphan-cleanup CLI, template idempotency + uq_template_field_key.
"""
import io
import os

import pytest

from tests.conftest import login_as


def _upload(client, kind, oid, filename="test.jpg",
            content=b"\xff\xd8\xff\xe0" + b"\x00" * 32):
    data = {"file": (io.BytesIO(content), filename)}
    return client.post(f"/ops/{kind}/{oid}/attachments",
                       data=data, content_type="multipart/form-data")


def _first_id(client, kind):
    r = client.get(f"/ops/{kind}")
    assert r.status_code == 200
    return r.get_json()["results"][0]["id"]


def _abs_key(client, storage_key):
    root = client.application.config["UPLOAD_FOLDER"]
    return os.path.abspath(os.path.join(root, storage_key))


# ---- physical persistence ----------------------------------------------

def test_upload_persists_bytes_to_disk(client):
    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    payload = b"\xff\xd8\xff\xe0" + b"real-jpeg-body"
    r = _upload(client, "site-inspections", oid, content=payload)
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["byte_size"] == len(payload)
    assert body["storage_key"].startswith("ops/site-inspections/")
    assert len(body["storage_key"]) <= 120  # DB column bound
    abs_path = _abs_key(client, body["storage_key"])
    assert os.path.isfile(abs_path)
    with open(abs_path, "rb") as f:
        assert f.read() == payload


def test_download_round_trip(client):
    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    payload = b"\xff\xd8\xff-e2e-bytes"
    r = _upload(client, "site-inspections", oid, content=payload)
    att_id = r.get_json()["id"]
    r = client.get(f"/ops/site-inspections/{oid}/attachments/{att_id}/download")
    assert r.status_code == 200
    assert r.content_type == "image/jpeg"
    assert r.data == payload


def test_download_cross_tenant_404(client):
    """Beta-only engineer cannot download Alpha's attachment bytes."""
    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    att_id = _upload(client, "site-inspections", oid).get_json()["id"]
    login_as(client, "t_eng2")  # Beta Hospital only
    r = client.get(
        f"/ops/site-inspections/{oid}/attachments/{att_id}/download")
    assert r.status_code == 404


def test_download_missing_file_404(client):
    """Row survives, bytes gone --> explicit 404 (not 500)."""
    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    body = _upload(client, "site-inspections", oid).get_json()
    os.remove(_abs_key(client, body["storage_key"]))
    r = client.get(
        f"/ops/site-inspections/{oid}/attachments/{body['id']}/download")
    assert r.status_code == 404
    assert r.get_json()["error"] == "file missing from storage"


def test_attachment_delete_removes_file(client):
    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    body = _upload(client, "site-inspections", oid).get_json()
    abs_path = _abs_key(client, body["storage_key"])
    assert os.path.isfile(abs_path)
    r = client.delete(
        f"/ops/site-inspections/{oid}/attachments/{body['id']}")
    assert r.status_code == 200
    assert not os.path.exists(abs_path)


def test_record_delete_cascades_attachments(client):
    """DELETE record removes attachment rows AND bytes."""
    from app.ops.models import Attachment
    login_as(client, "t_eng")
    r = client.post("/ops/rfis", json={
        "project_id": _alpha_pid(client), "subject": "cascade-me",
        "question": "q?", "ball_in_court": "consultant"})
    assert r.status_code == 201
    oid = r.get_json()["id"]
    body = _upload(client, "rfis", oid).get_json()
    abs_path = _abs_key(client, body["storage_key"])
    assert os.path.isfile(abs_path)

    r = client.delete(f"/ops/rfis/{oid}")
    assert r.status_code == 200
    assert not os.path.exists(abs_path)
    with client.application.app_context():
        assert Attachment.query.filter_by(
            record_kind="rfis", record_id=oid).count() == 0


def _alpha_pid(client):
    from app.models import Project
    with client.application.app_context():
        return Project.query.filter_by(name="Alpha Tower").first().id


def test_path_traversal_filename_contained(client):
    """'../../evil.jpg' must land inside UPLOAD_FOLDER, sanitized."""
    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    r = _upload(client, "site-inspections", oid,
                filename="../../evil.jpg",
                content=b"\xff\xd8\xff\xe0" + b"x")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert ".." not in body["storage_key"].split("/")[-1]
    assert body["filename"] == "evil.jpg"
    abs_path = _abs_key(client, body["storage_key"])
    root = os.path.abspath(client.application.config["UPLOAD_FOLDER"])
    assert abs_path.startswith(root + os.sep)
    assert os.path.isfile(abs_path)


def test_dotdot_bare_filename_rejected(client):
    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    r = _upload(client, "site-inspections", oid,
                filename="..", content=b"x")
    assert r.status_code == 400


# ---- orphan cleanup CLI --------------------------------------------------

def test_cleanup_orphans_cli(client):
    """Orphan rows + stray files removed; counts reported; avatars kept."""
    from click.testing import CliRunner
    from app.ops.models import Attachment
    from app.extensions import db

    login_as(client, "t_eng")
    oid = _first_id(client, "site-inspections")
    body = _upload(client, "site-inspections", oid).get_json()
    att_id, key = body["id"], body["storage_key"]
    assert os.path.isfile(_abs_key(client, key))

    # Orphan the row: delete the parent record bypassing the endpoint.
    with client.application.app_context():
        from app.ops.models import SiteInspection
        rec = db.session.get(SiteInspection, oid)
        db.session.delete(rec)
        db.session.commit()

    # Stray file with no DB row + a fake avatar file (must survive).
    root = client.application.config["UPLOAD_FOLDER"]
    stray = os.path.join(root, "ops", "site-inspections", "9999",
                         "deadbeef1234_stray.jpg")
    os.makedirs(os.path.dirname(stray), exist_ok=True)
    with open(stray, "wb") as f:
        f.write(b"stray")
    avatar_dir = os.path.join(root, "avatars")
    os.makedirs(avatar_dir, exist_ok=True)
    avatar = os.path.join(avatar_dir, "keep.jpg")
    with open(avatar, "wb") as f:
        f.write(b"avatar")

    runner = CliRunner()
    # Dry run first: reports, deletes nothing.
    res = runner.invoke(client.application.cli,
                        ["cleanup-orphaned-attachments", "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "orphan rows: 1" in res.output
    assert "orphan files: 1" in res.output
    with client.application.app_context():
        assert db.session.get(Attachment, att_id) is not None
    assert os.path.isfile(stray)

    res = runner.invoke(client.application.cli,
                        ["cleanup-orphaned-attachments"])
    assert res.exit_code == 0, res.output
    assert "orphan rows: 1" in res.output
    with client.application.app_context():
        assert db.session.get(Attachment, att_id) is None
    assert not os.path.exists(_abs_key(client, key))
    assert not os.path.exists(stray)
    assert os.path.isfile(avatar)  # outside ops/ prefix: untouched


# ---- templates -------------------------------------------------------------

def test_ensure_default_templates_idempotent(client):
    """Second seed run adds nothing."""
    from app.models import ReportTemplate, DynamicField
    from app.services.default_templates import ensure_default_templates
    from app.extensions import db
    with client.application.app_context():
        n_tpl = ReportTemplate.query.count()
        n_fld = DynamicField.query.count()
        ensure_default_templates(db, ReportTemplate, DynamicField)
        assert ReportTemplate.query.count() == n_tpl
        assert DynamicField.query.count() == n_fld


def test_uq_template_field_key_enforced(client):
    """Duplicate (template_id, field_key) violates the unique constraint."""
    from sqlalchemy.exc import IntegrityError
    from app.models import ReportTemplate, DynamicField
    from app.extensions import db
    with client.application.app_context():
        tpl = ReportTemplate.query.first()
        assert tpl is not None
        existing = DynamicField.query.filter_by(
            template_id=tpl.id).first()
        assert existing is not None
        db.session.add(DynamicField(
            template_id=tpl.id, field_key=existing.field_key,
            label_ar="مكرر", field_type="text"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
