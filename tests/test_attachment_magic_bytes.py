"""Attachment upload must verify bytes, not just the client's Content-Type.

A declared `image/jpeg` wrapping a shell script is the canonical upload
attack; the allow-list alone stops nothing. These tests post real payloads
through the endpoint and assert the stored bytes, mime column and file on
disk.
"""
import io
import os

import pytest

from tests.conftest import login_as

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3" + b"\x00" * 64


def _record_id(app, serial="SIR-000001", model="SiteInspection"):
    from app.ops import models as M
    with app.app_context():
        return getattr(M, model).query.filter_by(serial=serial).one().id


def _upload(client, app, payload, filename, record_id=None):
    rid = record_id or _record_id(app)
    return client.post(
        f"/ops/site-inspections/{rid}/attachments",
        data={"file": (io.BytesIO(payload), filename)})


class TestSniffingHelper:

    @pytest.mark.parametrize("payload,mime,expected", [
        (JPEG, "image/jpeg", "image/jpeg"),
        (PNG, "image/png", "image/png"),
        (GIF, "image/gif", "image/gif"),
        (WEBP, "image/webp", "image/webp"),
        (b"RIFF\x00\x00\x00\x00WAVE", "image/webp", None),
        (PDF, "application/pdf", "application/pdf"),
        (b"", "image/png", None),
        (b"MZ\x90\x00", "image/jpeg", None),
    ])
    def test_signature_matching(self, payload, mime, expected):
        from app.ops.routes import _sniff_mime
        assert _sniff_mime(payload, mime) == expected

    def test_declared_type_must_match_the_bytes(self):
        from app.ops.routes import _sniff_mime
        assert _sniff_mime(PNG, "application/pdf") is None
        assert _sniff_mime(PDF, "image/png") is None


class TestUploadAcceptsRealFiles:

    @pytest.mark.parametrize("payload,filename,mime", [
        (PNG, "shot.png", "image/png"),
        (JPEG, "shot.jpg", "image/jpeg"),
        (GIF, "shot.gif", "image/gif"),
        (WEBP, "shot.webp", "image/webp"),
        (PDF, "report.pdf", "application/pdf"),
    ])
    def test_matching_bytes_are_stored_with_real_metadata(self, app, client,
                                                          payload, filename,
                                                          mime):
        from app.extensions import db
        from app.ops.models import Attachment
        login_as(client, "t_eng")
        r = _upload(client, app, payload, filename)
        assert r.status_code == 201, r.get_json()
        att_id = r.get_json()["id"]
        with app.app_context():
            att = db.session.get(Attachment, att_id)
            assert att.mime_type == mime
            assert att.byte_size == len(payload)
            assert att.filename == filename
            on_disk = os.path.join(app.config["UPLOAD_FOLDER"], att.storage_key)
            assert os.path.isfile(on_disk)
            with open(on_disk, "rb") as fh:
                assert fh.read() == payload

    def test_download_returns_the_exact_bytes(self, app, client):
        login_as(client, "t_eng")
        r = _upload(client, app, PNG, "shot.png")
        assert r.status_code == 201
        att_id = r.get_json()["id"]
        rid = _record_id(app)
        d = client.get(
            f"/ops/site-inspections/{rid}/attachments/{att_id}/download")
        assert d.status_code == 200
        assert d.data == PNG


class TestUploadRejectsSpoofedContent:

    @pytest.mark.parametrize("payload,filename,declared", [
        (b"MZ\x90\x00 this is a windows exe", "evil.jpg", "image/jpeg"),
        (b"#!/bin/sh\nrm -rf /", "evil.png", "image/png"),
        (b"<html><script>alert(1)</script></html>", "x.html", "image/png"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "x.webp", "image/webp"),
        (PNG, "x.gif", "image/gif"),
        (PDF, "x.png", "image/png"),
    ])
    def test_spoofed_payload_is_refused_with_415(self, app, client, payload,
                                                 filename, declared):
        from app.extensions import db
        from app.ops.models import Attachment
        login_as(client, "t_eng")
        before = _record_id(app)
        with app.app_context():
            count = Attachment.query.count()
        r = _upload(client, app, payload, filename, before)
        assert r.status_code == 415, (filename, declared, r.get_json())
        if filename.rsplit(".", 1)[-1].lower() in {
                "jpg", "jpeg", "png", "gif", "webp", "pdf"}:
            assert "does not match" in r.get_json()["error"]
        else:
            assert "unsupported type" in r.get_json()["error"]
        with app.app_context():
            assert Attachment.query.count() == count

    def test_no_file_is_written_for_a_refused_payload(self, app, client):
        login_as(client, "t_eng")
        rid = _record_id(app)
        ops_root = os.path.join(app.config["UPLOAD_FOLDER"], "ops")
        before = set()
        for root, _dirs, names in os.walk(ops_root):
            before.update(os.path.join(root, n) for n in names)
        r = _upload(client, app, b"MZ\x90\x00exe", "evil.jpg", rid)
        assert r.status_code == 415
        after = set()
        for root, _dirs, names in os.walk(ops_root):
            after.update(os.path.join(root, n) for n in names)
        assert after == before

    def test_unsupported_declared_type_is_still_415(self, app, client):
        login_as(client, "t_eng")
        r = _upload(client, app, PNG, "x.txt")
        assert r.status_code == 415
        assert "unsupported type" in r.get_json()["error"]


class TestUploadGuardsStillApply:

    def test_empty_filename_is_400(self, app, client):
        login_as(client, "t_eng")
        rid = _record_id(app)
        r = client.post(
            f"/ops/site-inspections/{rid}/attachments",
            data={"file": (io.BytesIO(PNG), "")},
            content_type="multipart/form-data")
        assert r.status_code == 400
        assert r.get_json()["error"] == "empty filename"

    def test_missing_file_part_is_400(self, app, client):
        login_as(client, "t_eng")
        rid = _record_id(app)
        r = client.post(f"/ops/site-inspections/{rid}/attachments",
                        data={}, content_type="multipart/form-data")
        assert r.status_code == 400
        assert r.get_json()["error"] == "no file part"

    def test_oversized_valid_image_is_refused(self, app, client):
        login_as(client, "t_eng")
        big = PNG + b"\x00" * (4 * 1024 * 1024 + 16)
        r = _upload(client, app, big, "big.png")
        assert r.status_code == 413
        assert b"4 MB" in r.data or b"413" in r.data

    def test_traversal_filename_is_neutralised(self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        login_as(client, "t_eng")
        r = _upload(client, app, PNG, "../../evil.png")
        assert r.status_code == 201, r.get_json()
        with app.app_context():
            att = db.session.get(Attachment, r.get_json()["id"])
            assert "/" not in att.filename
            assert ".." not in att.storage_key
            resolved = os.path.realpath(
                os.path.join(app.config["UPLOAD_FOLDER"], att.storage_key))
            assert resolved.startswith(
                os.path.realpath(app.config["UPLOAD_FOLDER"]))
            assert os.path.isfile(resolved)

    def test_cross_tenant_upload_is_404(self, app, client):
        login_as(client, "t_eng2")
        r = _upload(client, app, PNG, "x.png")
        assert r.status_code == 404

    def test_anonymous_upload_is_401(self, app, client):
        rid = _record_id(app)
        r = client.post(
            f"/ops/site-inspections/{rid}/attachments",
            data={"file": (io.BytesIO(PNG), "x.png")},
            content_type="multipart/form-data")
        assert r.status_code == 401
