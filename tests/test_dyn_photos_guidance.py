"""Photos render as images with captions (view + PDF), never raw links;
every input carries an in-field guidance example."""
import io
from tests.conftest import login_as


def _png_bytes(color=(200, 30, 30)):
    from PIL import Image as _PI
    buf = io.BytesIO()
    _PI.new("RGB", (32, 32), color).save(buf, format="PNG")
    return buf.getvalue()


def _upload_daily_photo(client, project="Photo Report", caption="صب الأعمدة",
                        fname="site.png", raw=None):
    login_as(client, "t_admin")
    data = {
        "project_name": project,
        "report_date": "2026-09-24",
        "f_photos_esha__0__photo": (io.BytesIO(raw or _png_bytes()), fname),
    }
    if caption is not None:
        data["f_photos_esha__0__caption"] = caption
    r = client.post("/reports/dyn/new/daily", data=data,
                    content_type="multipart/form-data",
                    follow_redirects=True)
    assert r.status_code == 200
    from app.models import ReportSubmission
    from app.extensions import db
    with client.application.app_context():
        s = ReportSubmission.query.filter_by(project_name=project).first()
        assert s is not None, "photo submission must persist"
        rows = (s.data or {}).get("photos_esha") or []
        assert rows, "photo row must persist even without caption text"
        assert rows[0].get("photo", "").startswith("reports/daily/")
        return s.id, rows[0]["photo"]


def test_view_shows_image_not_link(client, app):
    sid, key = _upload_daily_photo(client)
    html = client.get(f"/reports/dyn/{sid}").get_data(as_text=True)
    assert "<img" in html
    assert "صب الأعمدة" in html
    assert f"/reports/dyn/file/{key}" in html
    assert key.split("/")[-1] not in html.replace(f"/reports/dyn/file/{key}", "")


def test_photo_only_row_persists(client, app):
    sid, key = _upload_daily_photo(
        client, project="Photo Only", caption=None)
    html = client.get(f"/reports/dyn/{sid}").get_data(as_text=True)
    assert "<img" in html


def test_dyn_file_serves_and_guards(client, app):
    sid, key = _upload_daily_photo(client)
    # author + admin may view
    assert client.get(f"/reports/dyn/file/{key}").status_code == 200
    # unrelated engineer refused (tenant guard mirrors report visibility)
    login_as(client, "t_eng2")
    assert client.get(f"/reports/dyn/file/{key}").status_code == 404
    login_as(client, "t_admin")
    # traversal + missing refused
    assert client.get("/reports/dyn/file/../app.py").status_code == 404
    assert client.get("/reports/dyn/file/reports/nope.png").status_code == 404
    # anonymous refused (same client after logout — harness shares session)
    client.get("/auth/logout")
    assert client.get(f"/reports/dyn/file/{key}").status_code == 401


def test_pdf_builds_with_gallery(client, app):
    from app.extensions import db
    sid, _key = _upload_daily_photo(client)
    with app.app_context():
        from app.models import ReportSubmission, ReportTemplate
        from app.services.pdf_dynamic import build_dynamic_pdf
        s = db.session.get(ReportSubmission, sid)
        tpl = db.session.get(ReportTemplate, s.template_id)
        pdf = build_dynamic_pdf(s, tpl)
    assert pdf.startswith(b"%PDF")


def test_pdf_survives_corrupt_image(client, app):
    from app.extensions import db
    sid, key = _upload_daily_photo(
        client, project="Corrupt Photo", raw=b"not-an-image",
        fname="bad.png")
    # corrupt bytes fail MIME gate at upload; force a stored key instead
    import os
    with app.app_context():
        from app.models import ReportSubmission, ReportTemplate
        from app.services.pdf_dynamic import build_dynamic_pdf
        s = db.session.get(ReportSubmission, sid)
        tpl = db.session.get(ReportTemplate, s.template_id)
        pdf = build_dynamic_pdf(s, tpl)
    assert pdf.startswith(b"%PDF")
    assert os.path.isfile(
        os.path.join(app.config["UPLOAD_FOLDER"], key))


def test_guidance_examples_render(client):
    login_as(client, "t_admin")
    html = client.get("/reports/dyn/new/daily").get_data(as_text=True)
    assert "مثال:" in html
    assert "خلاطة باطون" in html
    html2 = client.get("/reports/dyn/new/rfis").get_data(as_text=True)
    assert "مثال:" in html2
