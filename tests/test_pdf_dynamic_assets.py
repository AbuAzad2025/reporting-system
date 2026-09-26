"""Dynamic-PDF content contract: photo gallery, EVM block, asset safety.

The HTML report view deliberately hides raw storage keys, but the PDF used to
print them verbatim in the table cell while the gallery section it referenced
was never populated. These tests decode the drawn page streams and assert what
a client actually receives.
"""
import io
import os
import sys

import pytest

from tests.conftest import login_as
from tests.pdf_tools import PdfDocument

MONTHLY_EVM = {"planned_value": 100000, "earned_value": 80000,
               "actual_cost": 64000, "budget_at_completion": 120000}


def _png_bytes(color=(200, 30, 30), size=(48, 32)):
    from PIL import Image as _PI
    buf = io.BytesIO()
    _PI.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _upload_photo(client, project, caption="صب الأعمدة", raw=None,
                  fname="site.png", field="f_photos_esha__0__photo",
                  caption_field="f_photos_esha__0__caption",
                  template="daily", report_date="2026-09-24"):
    login_as(client, "t_admin")
    data = {"project_name": project, "report_date": report_date,
            field: (io.BytesIO(raw if raw is not None else _png_bytes()),
                    fname)}
    if caption is not None:
        data[caption_field] = caption
    r = client.post(f"/reports/dyn/new/{template}", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    from app.models import ReportSubmission
    with client.application.app_context():
        s = ReportSubmission.query.filter_by(project_name=project).first()
        assert s is not None
        rows = (s.data or {}).get("photos_esha") or []
        assert rows
        return s.id, rows[0].get("photo", "")


def _render(app, submission_id):
    from app.extensions import db
    from app.models import ReportSubmission, ReportTemplate
    from app.services.pdf_dynamic import build_dynamic_pdf
    with app.app_context():
        s = db.session.get(ReportSubmission, submission_id)
        tpl = db.session.get(ReportTemplate, s.template_id)
        return PdfDocument(build_dynamic_pdf(s, tpl))


class TestGalleryWiring:

    def _baseline(self, app, client):
        login_as(client, "t_admin")
        r = client.post("/reports/dyn/new/daily",
                        data={"project_name": "No Photo Baseline",
                              "report_date": "2026-09-24"},
                        follow_redirects=True)
        assert r.status_code == 200
        from app.models import ReportSubmission
        with client.application.app_context():
            s = ReportSubmission.query.filter_by(
                project_name="No Photo Baseline").first()
            return _render(app, s.id)

    def test_storage_key_is_never_printed_in_the_pdf(self, app, client):
        sid, key = _upload_photo(client, "Gallery No Leak")
        assert key.startswith("reports/")
        document = _render(app, sid)
        assert document.problems == ()
        assert "reports/" not in document.latin_text
        assert key not in document.text
        assert key.split("/")[-1] not in document.latin_text

    def test_photo_is_embedded_as_an_image(self, app, client):
        baseline = self._baseline(app, client)
        sid, _key = _upload_photo(client, "Gallery Embedded")
        document = _render(app, sid)
        assert document.problems == ()
        assert document.image_count == baseline.image_count + 1

    def test_caption_sibling_column_is_resolved(self, app, client):
        from app.services.pdf_dynamic import _row_caption
        sid, _key = _upload_photo(client, "Gallery Caption",
                                  caption="صب الأعمدة الدائرة")
        document = _render(app, sid)
        assert document.problems == ()
        cols = [{"key": "photo", "type": "file", "label_ar": "p"},
                {"key": "caption", "type": "text", "label_ar": "c"}]
        assert _row_caption(cols, {"caption": "x"}) == "x"

    def test_photo_without_caption_still_embeds(self, app, client):
        baseline = self._baseline(app, client)
        sid, _key = _upload_photo(client, "Gallery No Caption", caption=None)
        document = _render(app, sid)
        assert document.problems == ()
        assert document.image_count == baseline.image_count + 1

    def test_corrupt_stored_bytes_degrade_to_a_placeholder(self, app, client):
        baseline = self._baseline(app, client)
        from app.extensions import db
        from app.models import ReportSubmission
        sid, key = _upload_photo(client, "Gallery Corrupt")
        with app.app_context():
            with open(os.path.join(app.config["UPLOAD_FOLDER"], key),
                      "wb") as fh:
                fh.write(b"definitely-not-an-image")
            assert db.session.get(ReportSubmission, sid) is not None
        document = _render(app, sid)
        assert document.problems == ()
        assert key not in document.text
        assert document.image_count == baseline.image_count

    def test_missing_stored_file_degrades_to_a_placeholder(self, app,
                                                            client):
        baseline = self._baseline(app, client)
        from app.extensions import db
        from app.models import ReportSubmission
        sid, key = _upload_photo(client, "Gallery Missing")
        with app.app_context():
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], key))
            assert db.session.get(ReportSubmission, sid) is not None
        document = _render(app, sid)
        assert document.problems == ()
        assert key not in document.text
        assert document.image_count == baseline.image_count

    def test_multiple_photos_are_all_embedded(self, app, client):
        baseline = self._baseline(app, client)
        from app.extensions import db
        from app.models import ReportSubmission
        login_as(client, "t_admin")
        data = {"project_name": "Gallery Three", "report_date": "2026-09-24"}
        for index, color in enumerate([(200, 30, 30), (30, 200, 30),
                                       (30, 30, 200)], start=1):
            data[f"f_photos_esha__{index - 1}__photo"] = (
                io.BytesIO(_png_bytes(color)), f"p{index}.png")
            data[f"f_photos_esha__{index - 1}__caption"] = f"caption {index}"
        r = client.post("/reports/dyn/new/daily", data=data,
                        content_type="multipart/form-data",
                        follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            s = ReportSubmission.query.filter_by(
                project_name="Gallery Three").first()
            assert len(s.data["photos_esha"]) == 3
            for row in s.data["photos_esha"]:
                assert "reports/" in row["photo"]
            sid = s.id
        document = _render(app, sid)
        assert document.problems == ()
        assert document.image_count == baseline.image_count + 3
        assert "reports/" not in document.latin_text


class TestResolveUploadAbs:

    def _inside(self, app, name="reports/probe.txt", body=b"x"):
        path = os.path.join(app.config["UPLOAD_FOLDER"], name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(body)
        return name

    def test_valid_key_resolves(self, app):
        from app.services.pdf_dynamic import _resolve_upload_abs
        with app.app_context():
            key = self._inside(app)
            assert _resolve_upload_abs(key) == os.path.abspath(
                os.path.join(app.config["UPLOAD_FOLDER"], key))

    @pytest.mark.parametrize("key", [
        "", None, "   ", "reports/../../etc/passwd",
        "..\\..\\secret.png", "/etc/passwd"])
    def test_unsafe_or_empty_key_is_rejected(self, app, key):
        from app.services.pdf_dynamic import _resolve_upload_abs
        with app.app_context():
            assert _resolve_upload_abs(key) is None

    def test_directory_and_missing_file_are_rejected(self, app):
        from app.services.pdf_dynamic import _resolve_upload_abs
        with app.app_context():
            os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"],
                                     "reports/adir"), exist_ok=True)
            assert _resolve_upload_abs("reports/adir") is None
            assert _resolve_upload_abs("reports/absent.png") is None

    def test_missing_upload_folder_config_is_rejected(self, app):
        from app.services import pdf_dynamic
        with app.test_request_context():
            app.config.pop("UPLOAD_FOLDER", None)
            assert pdf_dynamic._resolve_upload_abs("reports/x.png") is None

    def test_outside_app_context_is_rejected(self):
        from app.services.pdf_dynamic import _resolve_upload_abs
        assert _resolve_upload_abs("reports/x.png") is None


class TestReadableImage:

    def test_valid_png_is_readable(self, app, tmp_path):
        from app.services.pdf_dynamic import _readable_image
        target = tmp_path / "ok.png"
        target.write_bytes(_png_bytes())
        assert _readable_image(str(target)) is True

    @pytest.mark.parametrize("body", [b"", b"not-an-image", b"\x89PNG\r\n\x1a\ntrunc"])
    def test_corrupt_file_is_skipped(self, app, tmp_path, body, caplog):
        from app.services.pdf_dynamic import _readable_image
        target = tmp_path / "bad.png"
        target.write_bytes(body)
        assert _readable_image(str(target)) is False
        assert "unreadable gallery image skipped" in caplog.text

    def test_absent_file_is_skipped(self, tmp_path):
        from app.services.pdf_dynamic import _readable_image
        assert _readable_image(str(tmp_path / "nope.png")) is False

    def test_pil_unavailable_still_allows_drawing(self, app, tmp_path,
                                                  monkeypatch):
        from app.services.pdf_dynamic import _readable_image
        target = tmp_path / "x.png"
        target.write_bytes(_png_bytes())
        monkeypatch.setitem(sys.modules, "PIL.Image", None)
        assert _readable_image(str(target)) is True


class TestRowCaption:

    def test_caption_is_read_from_the_sibling_column(self):
        from app.services.pdf_dynamic import _row_caption
        cols = [{"key": "photo", "type": "file", "label_ar": "صورة"},
                {"key": "caption", "type": "text", "label_ar": "تعليق"}]
        assert _row_caption(cols, {"caption": "  frente الموقع  "}) == \
            "frente الموقع"

    def test_arabic_label_is_matched(self):
        from app.services.pdf_dynamic import _row_caption
        cols = [{"key": "note", "type": "text", "label_ar": "تعليق الموقع"}]
        assert _row_caption(cols, {"note": "ملاحظة"}) == "ملاحظة"

    def test_blank_and_missing_caption_return_empty(self):
        from app.services.pdf_dynamic import _row_caption
        cols = [{"key": "caption", "type": "text", "label_ar": "تعليق"}]
        assert _row_caption(cols, {"caption": "   "}) == ""
        assert _row_caption(cols, {}) == ""
        assert _row_caption([], {"caption": "x"}) == ""

    def test_file_columns_are_never_treated_as_captions(self):
        from app.services.pdf_dynamic import _row_caption
        cols = [{"key": "photo", "type": "file", "label_ar": "caption"}]
        assert _row_caption(cols, {"photo": "reports/x.png"}) == ""


class TestMonthlyEvmBlock:

    def _monthly(self, client, app, evm=None, project="EVM Report"):
        login_as(client, "t_admin")
        data = {"project_name": project, "report_date": "2026-09-24"}
        for key, value in (evm or MONTHLY_EVM).items():
            data[f"f_{key}"] = value
        r = client.post("/reports/dyn/new/monthly", data=data,
                        follow_redirects=True)
        assert r.status_code == 200
        from app.models import ReportSubmission
        with app.app_context():
            s = ReportSubmission.query.filter_by(project_name=project).first()
            assert s is not None, "monthly submission must persist"
            for key, value in (evm or MONTHLY_EVM).items():
                assert str(s.data.get(key)) == str(value)
            return s.id

    def test_evm_metrics_are_rendered(self, app, client):
        sid = self._monthly(client, app)
        document = _render(app, sid)
        assert document.problems == ()
        latin = document.latin_text
        for row in ("100000", "80000", "64000", "1.25", "0.8"):
            assert row in latin, row
        assert "EVM" in document.text

    def test_bac_drives_the_forecast(self, app, client):
        sid = self._monthly(client, app, project="EVM BAC",
                            evm={"planned_value": 100000,
                                 "earned_value": 80000,
                                 "actual_cost": 64000,
                                 "budget_at_completion": 160000})
        document = _render(app, sid)
        assert document.problems == ()
        # EAC = AC + (BAC - EV) / CPI = 64000 + (160000-80000)/1.25 = 128000
        assert "128000" in document.latin_text

    def test_forecast_without_bac_uses_ac_over_cpi(self, app, client):
        sid = self._monthly(client, app, project="EVM No BAC",
                            evm={"planned_value": 100000,
                                 "earned_value": 50000,
                                 "actual_cost": 40000})
        document = _render(app, sid)
        assert document.problems == ()
        assert "EVM" in document.text
        # CPI = 50000/40000 = 1.25, so EAC = AC / CPI = 40000/1.25
        assert "32000" in document.latin_text

    def test_zero_cost_denominator_keeps_the_block_renderable(
            self, app, client):
        sid = self._monthly(client, app, project="EVM Zero AC",
                            evm={"planned_value": 100000,
                                 "earned_value": 50000,
                                 "actual_cost": 0,
                                 "budget_at_completion": 120000})
        document = _render(app, sid)
        assert document.problems == ()
        assert "EVM" in document.text
        # CPI collapses to 0 and the EAC fallback adds the remaining budget
        assert "120000" in document.latin_text

    def test_non_numeric_stored_evm_does_not_break_the_document(self, app,
                                                                client):
        from app.extensions import db
        from app.models import ReportSubmission
        sid = self._monthly(client, app, project="EVM Garbage",
                            evm={"planned_value": 100000,
                                 "earned_value": 50000,
                                 "actual_cost": 40000})
        with app.app_context():
            row = db.session.get(ReportSubmission, sid)
            row.data = dict(row.data, planned_value={"bad": "shape"},
                            earned_value=["list"], actual_cost="not-a-number")
            db.session.commit()
        document = _render(app, sid)
        assert document.problems == ()
        assert document.page_count >= 1
        assert "DS-" in document.latin_text
        with app.app_context():
            assert db.session.get(ReportSubmission, sid) is not None

    def test_non_monthly_template_has_no_evm_block(self, app, client):
        sid, _key = _upload_photo(client, "Weekly Photo Only",
                                  template="daily")
        document = _render(app, sid)
        assert document.problems == ()
        assert "EVM" not in document.text
