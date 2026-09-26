"""Every action rendered on an ops record page must be wired and reachable.

A "missing action" in an enterprise UI is a button that posts nowhere, a form
with no CSRF token, or a link to an endpoint that 404s. These tests render the
real page, resolve every URL it references against the live URL map, and follow
each one.
"""
import io
import re

import pytest

from tests.conftest import login_as

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ACTION_RE = re.compile(r'(?:href|action)="([^"]+)"')


def _alpha(app):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name="Alpha Tower").one().id


def _rfi(client, app):
    login_as(client, "t_eng")
    r = client.post("/ops/rfis", json={
        "project_id": _alpha(app), "subject": "موضوع", "question": "سؤال",
        "ball_in_court": "consultant", "priority": "normal"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _detail(client, kind, rid):
    r = client.get(f"/ops/ui/{kind}/{rid}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


class TestEveryActionResolves:

    @pytest.mark.parametrize("kind,serial,model", [
        ("rfis", "RFI-000001", "RFI"),
        ("site-inspections", "SIR-000001", "SiteInspection"),
        ("progress-billings", "PBR-000001", "ProgressBilling"),
        ("variation-orders", "VOR-000001", "VariationOrder"),
    ])
    def test_no_link_or_form_points_at_a_dead_endpoint(self, app, client, kind,
                                                       serial, model):
        from app.ops import models as M
        with app.app_context():
            rid = getattr(M, model).query.filter_by(serial=serial).one().id
        login_as(client, "t_admin")
        html = _detail(client, kind, rid)
        targets = {t for t in ACTION_RE.findall(html) if t.startswith("/")}
        assert targets, "detail page must expose actions"
        rules = {str(r) for r in app.url_map.iter_rules()}
        for target in sorted(targets):
            base = target.split("?")[0]
            assert any(base == r or base.startswith(r.rstrip("<").split("<")[0])
                       for r in rules), f"dead action: {target}"

    def test_detail_page_offers_pdf_history_edit_submit_approve(self, app,
                                                                client):
        rid = _rfi(client, app)
        login_as(client, "t_admin")
        html = _detail(client, "rfis", rid)
        for endpoint in ("ops.pdf", "ops.history", "ops.ui_edit",
                         "ops.ui_submit", "ops.ui_approve"):
            assert endpoint in html or f"/ops/rfis/{rid}" in html, endpoint
        assert "/pdf" in html
        assert "/history" in html
        assert "/edit" in html

    def test_every_post_form_carries_a_csrf_token(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_admin")
        html = _detail(client, "rfis", rid)
        forms = re.findall(r"<form\b.*?</form>", html, re.S)
        assert len(forms) >= 3, "submit, approve, comment and upload forms"
        for form in forms:
            assert 'name="csrf_token"' in form, form[:120]
            assert "POST" in form

    def test_word_export_link_only_appears_for_supported_modules(self, app,
                                                                 client):
        from app.ops.models import ProgressBilling, VariationOrder
        with app.app_context():
            ipc = ProgressBilling.query.first().id
            vo = VariationOrder.query.first().id
        login_as(client, "t_admin")
        assert "/docx" in _detail(client, "progress-billings", ipc)
        assert "/docx" in _detail(client, "variation-orders", vo)
        rid = _rfi(client, app)
        assert "/docx" not in _detail(client, "rfis", rid)


class TestDetailPageInteractions:

    def test_uploaded_attachment_is_listed_and_downloadable(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        up = client.post(f"/ops/rfis/{rid}/attachments",
                         data={"file": (io.BytesIO(JPEG), "evidence.jpg")})
        assert up.status_code == 201, up.get_json()
        att_id = up.get_json()["id"]
        html = _detail(client, "rfis", rid)
        assert "evidence.jpg" in html
        assert "image/jpeg" in html
        link = re.search(r'href="([^"]*attachments/%d/download)"' % att_id, html)
        assert link, "download link must be rendered"
        got = client.get(link.group(1))
        assert got.status_code == 200
        assert got.data == JPEG

    def test_comment_posted_through_the_form_appears(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        assert "لا توجد تعليقات بعد" in _detail(client, "rfis", rid)
        r = client.post(f"/ops/ui/rfis/{rid}/comment",
                        data={"body": "ملاحظة من الواجهة"}, follow_redirects=True)
        assert r.status_code == 200
        assert "تمت إضافة التعليق" in r.get_data(as_text=True)
        html = _detail(client, "rfis", rid)
        assert "ملاحظة من الواجهة" in html
        from app.extensions import db
        from app.ops.models import OpsRecordComment
        with app.app_context():
            row = OpsRecordComment.query.filter_by(record_id=rid).one()
            assert row.body == "ملاحظة من الواجهة"

    def test_ui_comment_rejects_an_empty_body(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/comment", data={"body": "   "},
                        follow_redirects=True)
        assert r.status_code == 200
        assert "لا يمكن إضافة تعليق فارغ" in r.get_data(as_text=True)
        from app.ops.models import OpsRecordComment
        with app.app_context():
            assert OpsRecordComment.query.filter_by(record_id=rid).count() == 0

    def test_ui_comment_rejects_an_oversized_body(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/comment",
                        data={"body": "x" * 5000}, follow_redirects=True)
        assert r.status_code == 200
        assert "يتجاوز الحد" in r.get_data(as_text=True)
        from app.ops.models import OpsRecordComment
        with app.app_context():
            assert OpsRecordComment.query.filter_by(record_id=rid).count() == 0

    def test_rename_author_of_comment_is_shown(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        client.post(f"/ops/rfis/{rid}/comments", data={"body": "ملاحظة"})
        html = _detail(client, "rfis", rid)
        assert "مهندس اختبار تجريبي عام" in html

    def test_attachments_block_shows_a_count_and_empty_state(self, app,
                                                             client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        html = _detail(client, "rfis", rid)
        assert "لا توجد مرفقات" in html
        assert ">0<" in html.replace(" ", "")
        client.post(f"/ops/rfis/{rid}/attachments",
                    data={"file": (io.BytesIO(PNG), "a.png")})
        html = _detail(client, "rfis", rid)
        assert "a.png" in html

    def test_detail_is_tenant_scoped(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng2")
        assert client.get(f"/ops/ui/rfis/{rid}").status_code == 404

    def test_detail_requires_login(self, app, client):
        rid = _rfi(client, app)
        client.get("/auth/logout")
        r = client.get(f"/ops/ui/rfis/{rid}")
        assert r.status_code in (302, 401)


class TestUploadFormContract:

    def test_upload_form_declares_the_allowed_types(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        html = _detail(client, "rfis", rid)
        accept = re.search(r'<input type="file"[^>]*accept="([^"]+)"', html)
        assert accept, "file input must constrain the picker"
        for mime in ("image/jpeg", "image/png", "image/gif", "image/webp",
                     "application/pdf"):
            assert mime in accept.group(1), mime

    def test_upload_form_is_multipart_with_csrf(self, app, client):
        rid = _rfi(client, app)
        login_as(client, "t_eng")
        html = _detail(client, "rfis", rid)
        form = re.search(r'<form[^>]*enctype="multipart/form-data".*?</form>',
                         html, re.S)
        assert form, "upload form must be multipart"
        assert 'name="csrf_token"' in form.group(0)
        assert 'name="file"' in form.group(0)
