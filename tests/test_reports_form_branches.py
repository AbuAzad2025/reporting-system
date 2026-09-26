"""Branch coverage for the two report form engines in app/reports/routes.py.

Every test drives the blueprint through real HTTP requests on the shared
``app`` / ``client`` fixtures (tests/conftest.py) and asserts the exact
status code, the exact Arabic flash text and the resulting database rows.

Covered here (the validation / rejection branches the rest of the suite
never reaches):
  * LEGACY  /reports/new/<type>  + /reports/<id>/edit + /reports/<id>/delete
  * DYNAMIC /reports/dyn/new/<key> + /reports/dyn/<id>/edit + .../delete
  * _collect_dynamic / _extract_table_rows row, file-cell and tripwire rules
  * /reports/dyn/file/<key> serving guards (mime allow-list, key resolution)
"""
import html as htmllib
import io
import os
import re
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import login_as

# --------------------------------------------------------------------- data
LEGACY_PROJECT = "مشروع الفرع"
LEGACY_FORM = {
    "project_name": LEGACY_PROJECT,
    "location": "الرياض",
    "contractor": "شركة البناء",
    "report_date": "2026-03-01",
    "weather": "مشمس",
    "temp_c": "30",
    "work_hours": "8",
    "engineers_count": "3",
    "technicians_count": "2",
    "labor_count": "10",
    "notes": "يوم عمل جيد",
}
LEGACY_DAILY_AR = "التقرير اليومي"

PHOTOS_TABLE = "photos_esha"
PHOTOS_AR = "8.10 الصور التوثيقية مع التعليقات"
WEATHER_TABLE = "weather_esha"
EQUIPMENT_TABLE = "equipment_esha"
EQUIPMENT_AR = "2. قائمة المعدات والآلات في الموقع"
WASTE_TABLE = "waste_mgmt_esha"
WASTE_AR = "إجراءات إدارة النفايات (8.3)"


# ------------------------------------------------------------------ helpers
#: base.html renders every flash as `<div role="alert" class="... bg-<tone>-50 ...">
_ALERT_RE = re.compile(r'<div role="alert" class="([^"]*)"[^>]*>\s*<span>(.*?)</span>',
                       re.S)
_TONE_CATEGORY = (("bg-green-50", "success"), ("bg-red-50", "danger"),
                  ("bg-amber-50", "warning"), ("bg-blue-50", "info"))


def _flashes(client, response):
    """Exact (category, message) pairs the view emitted for the browser.

    A 200 re-render consumes the queue inside base.html, so the texts are read
    back out of the rendered alert boxes; an unfollowed redirect leaves them in
    the session cookie instead.
    """
    if response.status_code == 302:
        with client.session_transaction() as sess:
            return [tuple(item) for item in sess.pop("_flashes", [])]
    emitted = []
    for classes, message in _ALERT_RE.findall(response.get_data(as_text=True)):
        tone = next(cat for needle, cat in _TONE_CATEGORY if needle in classes)
        emitted.append((tone, htmllib.unescape(message.strip())))
    return emitted


def _login(client, username):
    """tests.conftest.login_as, minus the welcome flash.

    The greeting queued at login would otherwise be rendered as the first
    alert of the next page, so every assertion below reads only the flashes
    the view under test produced.
    """
    login_as(client, username)
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _user_id(app, username):
    from app.models import User
    with app.app_context():
        return User.query.filter_by(username=username).first().id


def _project_id(app, name):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name=name).first().id


def _report_count(app):
    from app.models import Report
    with app.app_context():
        return Report.query.count()


def _report(app, project_name):
    """Snapshot of the one legacy row carrying project_name."""
    from app.models import Report
    with app.app_context():
        row = Report.query.filter_by(project_name=project_name).first()
        if row is None:
            return None
        return {
            "id": row.id, "report_type": row.report_type,
            "location": row.location, "contractor": row.contractor,
            "report_date": row.report_date, "data": dict(row.data or {}),
            "user_id": row.user_id, "signatory_name": row.signatory_name,
        }


def _submission(app, project_name):
    """Snapshot of the one dynamic row carrying project_name."""
    from app.models import ReportSubmission
    with app.app_context():
        row = ReportSubmission.query.filter_by(project_name=project_name).first()
        if row is None:
            return None
        return {
            "id": row.id, "template_id": row.template_id,
            "project_id": row.project_id, "location": row.location,
            "contractor": row.contractor, "report_date": row.report_date,
            "data": dict(row.data or {}), "user_id": row.user_id,
            "signatory_name": row.signatory_name,
        }


def _stored_report_files(app):
    """Every file the engine wrote under UPLOAD_FOLDER/reports."""
    root = os.path.join(app.config["UPLOAD_FOLDER"], "reports")
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, _dirs, names in os.walk(root):
        found.extend(os.path.join(dirpath, n) for n in names)
    return sorted(found)


def _seed_submission(app, project_name, template_key="daily", data=None,
                     report_date=date(2026, 4, 1), username="t_eng"):
    """Insert a dynamic row straight into the per-test database."""
    from app.extensions import db
    from app.models import ReportSubmission, ReportTemplate, User
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key=template_key).first()
        user = User.query.filter_by(username=username).first()
        row = ReportSubmission(
            template_id=tpl.id, project_name=project_name,
            location="موقع مخزون", contractor="مقاول مخزون",
            report_date=report_date, data=data if data is not None else {},
            signatory_name=user.full_name, user_id=user.id)
        db.session.add(row)
        db.session.commit()
        return row.id


def _make_template(app, key, name_ar, fields):
    """Create an isolated template + field schema inside the test database."""
    from app.extensions import db
    from app.models import DynamicField, ReportTemplate
    with app.app_context():
        tpl = ReportTemplate(key=key, name_ar=name_ar, is_active=True)
        db.session.add(tpl)
        db.session.flush()
        for pos, f in enumerate(fields):
            db.session.add(DynamicField(
                template_id=tpl.id, field_key=f["key"], label_ar=f["label_ar"],
                field_type=f.get("type", "text"), options=f.get("options", []),
                required=f.get("required", False), rules=f.get("rules", {}),
                sub_fields=f.get("columns", []), position=pos))
        db.session.commit()


def _create_legacy(client, **overrides):
    """POST a legacy report; returns the response (flashes stay unread)."""
    form = dict(LEGACY_FORM)
    form.update(overrides)
    return client.post("/reports/new/daily", data=form)


def _save_legacy(client, app, **overrides):
    """Create a legacy report through HTTP and return its id."""
    created = _create_legacy(client, **overrides)
    assert created.status_code == 302
    assert _flashes(client, created) == [("success", "تم حفظ التقرير بنجاح.")]
    return _report(app, overrides.get("project_name", LEGACY_PROJECT))["id"]


# ------------------------------------------------------ stub form / uploads
class _KeysExplode:
    """files stub whose keys() is unavailable (defensive branch)."""

    def keys(self):
        raise RuntimeError("files.keys() unavailable")

    def get(self, key, default=None):
        return default


class _GetExplodes:
    """files stub that lists keys but refuses to hand the file over."""

    def __init__(self, keys):
        self._keys = list(keys)

    def keys(self):
        return list(self._keys)

    def get(self, key, default=None):
        raise RuntimeError("files.get() unavailable")


class _FlatForm:
    """Multi-dict stand-in: the engine only ever needs keys() and get()."""

    def __init__(self, values):
        self._values = dict(values)

    def keys(self):
        return list(self._values)

    def get(self, key, default=None):
        return self._values.get(key, default)


class _NoKeysForm(dict):
    """dict whose keys() is unavailable."""

    def keys(self):
        raise RuntimeError("form.keys() unavailable")


class _PassingForm:
    """Multi-dict stub whose keys() changes behaviour on every pass.

    _extract_table_rows() walks the form before _collect_dynamic's tripwire
    scan does, so a form whose contents (or whose keys()) change between the
    two iterations is exactly what the `except` / `if not _v` guards there
    exist for.
    """

    def __init__(self, keys, values=None, reveal_on=(2,), explode_on=0,
                 explode_get=()):
        self._keys = list(keys)
        self._values = dict(values or {})
        self._reveal_on = tuple(reveal_on)
        self._explode_on = explode_on
        self._explode_get = set(explode_get)
        self._passes = 0

    def keys(self):
        self._passes += 1
        if self._passes == self._explode_on:
            raise RuntimeError("form.keys() unavailable")
        return list(self._keys) if self._passes in self._reveal_on else []

    def get(self, key, default=None):
        if key in self._explode_get:
            raise RuntimeError("form.get() unavailable")
        return self._values.get(key, default)


class _UnseekableStream:
    def seek(self, *args, **kwargs):
        raise OSError("stream is not seekable")


class _UnseekableUpload:
    """File-upload stand-in whose stream cannot seek."""

    filename = "site.png"
    mimetype = "image/png"

    def __init__(self, payload=b"\x89PNG-fake"):
        self.stream = _UnseekableStream()
        self._payload = payload

    def read(self, *args, **kwargs):
        return self._payload

    def close(self):
        return None


# =========================================================== LEGACY (v1)
class TestLegacyReportForm:
    def test_new_post_without_project_name_is_refused(self, client, app):
        _login(client, "t_eng")
        r = _create_legacy(client, project_name="   ")
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "اسم المشروع حقل مطلوب.")]
        assert _report_count(app) == 0

    def test_new_post_with_invalid_date_is_refused(self, client, app):
        _login(client, "t_eng")
        r = _create_legacy(client, report_date="2026-13-45")
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "تاريخ التقرير غير صالح.")]
        assert _report_count(app) == 0

    def test_new_post_rejects_duplicate_project_type_date(self, client, app):
        _login(client, "t_eng")
        _save_legacy(client, app)
        # surrounding whitespace is stripped, so this is the same key
        r = _create_legacy(client, project_name="  " + LEGACY_PROJECT + "  ")
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger",
            f"يوجد بالفعل {LEGACY_DAILY_AR} لنفس المشروع "
            f"({LEGACY_PROJECT}) بتاريخ 2026-03-01. لا يمكن تكراره.")]
        assert _report_count(app) == 1
        assert _report(app, LEGACY_PROJECT)["data"]["weather"] == "مشمس"

    def test_new_post_creates_the_report(self, client, app):
        _login(client, "t_eng")
        r = _create_legacy(client)
        assert r.status_code == 302
        row = _report(app, LEGACY_PROJECT)
        assert row is not None
        assert r.headers["Location"].endswith(f"/reports/{row['id']}")
        assert _flashes(client, r) == [("success", "تم حفظ التقرير بنجاح.")]
        assert row["report_type"] == "daily"
        assert row["report_date"] == date(2026, 3, 1)
        assert row["location"] == "الرياض"
        assert row["contractor"] == "شركة البناء"
        assert row["data"] == {
            "weather": "مشمس", "temp_c": "30", "work_hours": "8",
            "engineers_count": "3", "technicians_count": "2",
            "labor_count": "10", "notes": "يوم عمل جيد"}
        assert row["user_id"] == _user_id(app, "t_eng")
        assert row["signatory_name"] == "مهندس اختبار تجريبي عام"

    def test_new_post_survives_an_integrity_error(self, client, app, monkeypatch):
        from app.extensions import db
        _login(client, "t_eng")

        def boom():
            raise IntegrityError("INSERT", {}, Exception("uq_project_type_date"))

        monkeypatch.setattr(db.session, "commit", boom)
        r = _create_legacy(client)
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "تم رفض الحفظ: تقرير مكرر لنفس المشروع والنوع والتاريخ.")]
        assert _report_count(app) == 0

    def test_edit_post_updates_the_report(self, client, app):
        _login(client, "t_eng")
        row_id = _save_legacy(client, app)
        r = client.post(f"/reports/{row_id}/edit", data=dict(
            LEGACY_FORM, project_name="مشروع معدّل", location="جدة",
            contractor="مقاول جديد", notes="تحديث اليوم", labor_count="42"))
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/reports/{row_id}")
        assert _flashes(client, r) == [("success", "تم تحديث التقرير بنجاح.")]
        after = _report(app, "مشروع معدّل")
        assert after is not None
        assert after["id"] == row_id
        assert after["location"] == "جدة"
        assert after["contractor"] == "مقاول جديد"
        assert after["data"]["notes"] == "تحديث اليوم"
        assert after["data"]["labor_count"] == "42"
        assert _report_count(app) == 1

    def test_edit_post_without_name_or_date_is_refused(self, client, app):
        _login(client, "t_eng")
        row_id = _save_legacy(client, app)
        r = client.post(f"/reports/{row_id}/edit", data=dict(
            LEGACY_FORM, project_name="", notes="يجب ألا يُحفظ"))
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "تحقق من اسم المشروع والتاريخ.")]
        unchanged = _report(app, LEGACY_PROJECT)
        assert unchanged["location"] == "الرياض"
        assert unchanged["data"]["notes"] == "يوم عمل جيد"

    def test_edit_post_rejects_a_duplicate_of_another_report(self, client, app):
        _login(client, "t_eng")
        _save_legacy(client, app)
        second = _save_legacy(client, app, project_name="مشروع ثان",
                              report_date="2026-03-02")
        r = client.post(f"/reports/{second}/edit", data=dict(
            LEGACY_FORM, project_name=LEGACY_PROJECT, report_date="2026-03-01"))
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "يوجد تقرير آخر بنفس المشروع والنوع والتاريخ.")]
        still = _report(app, "مشروع ثان")
        assert still["report_date"] == date(2026, 3, 2)
        assert _report_count(app) == 2

    def test_edit_post_survives_an_integrity_error(self, client, app, monkeypatch):
        from app.extensions import db
        _login(client, "t_eng")
        row_id = _save_legacy(client, app)

        def boom():
            raise IntegrityError("UPDATE", {}, Exception("uq_project_type_date"))

        monkeypatch.setattr(db.session, "commit", boom)
        r = client.post(f"/reports/{row_id}/edit", data=dict(
            LEGACY_FORM, project_name="اسم لم يُحفظ"))
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "تعذر الحفظ بسبب قيد عدم التكرار.")]
        # the rolled-back row keeps its stored values, and the re-rendered
        # form is prefilled from them (never from the rejected submission)
        assert _report(app, LEGACY_PROJECT)["id"] == row_id
        html = r.get_data(as_text=True)
        assert LEGACY_PROJECT in html
        assert "اسم لم يُحفظ" not in html

    def test_delete_removes_the_row_and_redirects_to_the_archive(self, client, app):
        _login(client, "t_eng")
        row_id = _save_legacy(client, app)
        r = client.post(f"/reports/{row_id}/delete")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/archive?src=legacy")
        assert _flashes(client, r) == [("info", "تم حذف التقرير.")]
        assert _report_count(app) == 0
        archive = client.get("/archive?src=legacy").get_data(as_text=True)
        assert LEGACY_PROJECT not in archive

    def test_delete_of_another_users_report_is_404(self, client, app):
        _login(client, "t_eng")
        row_id = _save_legacy(client, app)
        _login(client, "t_eng2")
        r = client.post(f"/reports/{row_id}/delete")
        assert r.status_code == 404
        assert _flashes(client, r) == []
        assert _report_count(app) == 1


# ========================================================== DYNAMIC (v2)
class TestDynamicReportForm:
    def test_new_get_renders_the_template_form(self, client):
        _login(client, "t_eng")
        r = client.get("/reports/dyn/new/daily")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "التقرير اليومي" in html
        assert 'name="project_name"' in html
        assert f'name="f_{PHOTOS_TABLE}__0__photo"' in html
        assert "Alpha Tower" in html          # member project offered
        assert "Beta Hospital" not in html    # out-of-scope project withheld
        assert _flashes(client, r) == []

    def test_new_post_saves_text_and_table_answers(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "مشروع ديناميكي",
            "report_date": "2026-04-05",
            "location": "الدمام",
            "contractor": "مقاول الديناميكي",
            "f_eshs_desc_81": "وصف الأنشطة",
            f"f_{WASTE_TABLE}__0__proc": "فرز النفايات",
            f"f_{WASTE_TABLE}__0__done": "yes",
        })
        assert r.status_code == 302
        row = _submission(app, "مشروع ديناميكي")
        assert row is not None
        assert r.headers["Location"].endswith(f"/reports/dyn/{row['id']}")
        assert _flashes(client, r) == [("success", "تم حفظ التقرير الديناميكي بنجاح.")]
        assert row["report_date"] == date(2026, 4, 5)
        assert row["location"] == "الدمام"
        assert row["contractor"] == "مقاول الديناميكي"
        assert row["project_id"] is None
        assert row["data"]["eshs_desc_81"] == "وصف الأنشطة"
        assert row["data"][WASTE_TABLE] == [
            {"proc": "فرز النفايات", "done": "yes", "not_done": "", "notes": ""}]

    def test_new_post_links_a_project_and_adopts_its_name(self, client, app):
        _login(client, "t_eng")
        pid = _project_id(app, "Alpha Tower")
        r = client.post("/reports/dyn/new/daily", data={
            "project_id": str(pid),
            "project_name": "اسم يتجاهله الربط",
            "report_date": "2026-04-06",
            "f_eshs_desc_81": "وصف",
        })
        assert r.status_code == 302
        row = _submission(app, "Alpha Tower")
        assert row is not None
        assert row["project_id"] == pid
        assert _submission(app, "اسم يتجاهله الربط") is None

    def test_new_post_with_non_numeric_project_id_saves_unlinked(
            self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_id": "not-a-number",
            "project_name": "مشروع بلا ربط",
            "report_date": "2026-04-07",
            "f_eshs_desc_81": "وصف",
        })
        assert r.status_code == 302
        row = _submission(app, "مشروع بلا ربط")
        assert row is not None
        assert row["project_id"] is None
        assert _flashes(client, r) == [("success", "تم حفظ التقرير الديناميكي بنجاح.")]

    def test_new_post_with_out_of_scope_project_id_is_404(self, client, app):
        _login(client, "t_eng2")   # member of Beta Hospital only
        pid = _project_id(app, "Alpha Tower")
        r = client.post("/reports/dyn/new/daily", data={
            "project_id": str(pid),
            "project_name": "مشروع مسروق",
            "report_date": "2026-04-08",
        })
        assert r.status_code == 404
        assert _flashes(client, r) == []
        assert _submission(app, "مشروع مسروق") is None

    def test_new_post_without_project_name_is_refused(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "  ",
            "report_date": "2026-04-09",
            "f_eshs_desc_81": "وصف",
        })
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "اسم المشروع حقل مطلوب.")]
        assert _submission(app, "  ") is None

    def test_new_post_with_invalid_date_is_refused(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "تاريخ فاسد",
            "report_date": "2026-02-30",
            "f_eshs_desc_81": "وصف",
        })
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "تاريخ التقرير غير صالح.")]
        assert _submission(app, "تاريخ فاسد") is None

    def test_new_post_rejects_duplicate_template_project_date(self, client, app):
        _login(client, "t_eng")
        form = {"project_name": "مشروع مكرر",
                "report_date": "2026-04-10", "f_eshs_desc_81": "وصف"}
        first = client.post("/reports/dyn/new/daily", data=form)
        assert first.status_code == 302
        assert _flashes(client, first) == [
            ("success", "تم حفظ التقرير الديناميكي بنجاح.")]
        r = client.post("/reports/dyn/new/daily", data=dict(
            form, project_name=" مشروع مكرر "))
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger",
            "يوجد بالفعل «التقرير اليومي» لنفس المشروع "
            "(مشروع مكرر) بتاريخ 2026-04-10.")]
        with app.app_context():
            from app.models import ReportSubmission
            assert ReportSubmission.query.count() == 1

    def test_new_post_stores_truncated_geolocation_tags(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "مشروع محدد الموقع",
            "report_date": "2026-04-11",
            "f_eshs_desc_81": "وصف",
            "geo_lat": "2" * 30,
            "geo_lng": "  46.6753  ",
        })
        assert r.status_code == 302
        row = _submission(app, "مشروع محدد الموقع")
        assert row["data"]["geo_lat"] == "2" * 20
        assert row["data"]["geo_lng"] == "46.6753"

    def test_new_post_survives_an_integrity_error(self, client, app, monkeypatch):
        from app.extensions import db
        _login(client, "t_eng")

        def boom():
            raise IntegrityError(
                "INSERT", {}, Exception("uq_sub_template_project_date"))

        monkeypatch.setattr(db.session, "commit", boom)
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "مشروع مرفوض",
            "report_date": "2026-04-12",
            "f_eshs_desc_81": "وصف",
        })
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "تم رفض الحفظ: تقرير مكرر (القالب + المشروع + التاريخ).")]
        assert _submission(app, "مشروع مرفوض") is None

    def test_new_post_reports_every_missing_required_text_field(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/rfis", data={
            "project_name": "سجل استفسارات ناقص", "report_date": "2026-04-13"})
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "الحقل «الموضوع» مطلوب."),
            ("danger", "الحقل «نص الاستفسار» مطلوب."),
        ]
        assert _submission(app, "سجل استفسارات ناقص") is None

    def test_new_post_reports_a_field_rule_violation(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/monthly", data={
            "project_name": "تقرير شهري مخالف",
            "report_date": "2026-04-14",
            "f_ppe_pct": "150",
        })
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "«الالتزام بمعدات الوقاية (%)» يجب أن يكون ≤ 100.")]
        assert _submission(app, "تقرير شهري مخالف") is None

    def test_edit_get_prefills_saved_answers(self, client, app):
        sid = _seed_submission(
            app, "تعديل محمّل", data={"eshs_desc_81": "وصف محفوظ",
                                      WASTE_TABLE: [{"proc": "فرز"}]})
        _login(client, "t_eng")
        r = client.get(f"/reports/dyn/{sid}/edit")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "وصف محفوظ" in html
        assert "فرز" in html
        assert _flashes(client, r) == []

    def test_edit_post_updates_the_submission(self, client, app):
        sid = _seed_submission(
            app, "تعديل أصلي",
            data={"eshs_desc_81": "قبل", WASTE_TABLE: [{"proc": "بند قديم"}]})
        _login(client, "t_eng")
        r = client.post(f"/reports/dyn/{sid}/edit", data={
            "project_name": "تعديل جديد",
            "report_date": "2026-04-15",
            "location": "مكة",
            "contractor": "مقاول معدّل",
            "f_eshs_desc_81": "بعد",
            f"f_{WASTE_TABLE}__0__proc": "بند معدّل",
        })
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/reports/dyn/{sid}")
        assert _flashes(client, r) == [("success", "تم تحديث التقرير بنجاح.")]
        row = _submission(app, "تعديل جديد")
        assert row["id"] == sid
        assert row["location"] == "مكة"
        assert row["contractor"] == "مقاول معدّل"
        assert row["report_date"] == date(2026, 4, 15)
        assert row["data"]["eshs_desc_81"] == "بعد"
        assert row["data"][WASTE_TABLE] == [
            {"proc": "بند معدّل", "done": "", "not_done": "", "notes": ""}]
        assert _submission(app, "تعديل أصلي") is None

    def test_edit_post_with_invalid_date_is_refused(self, client, app):
        sid = _seed_submission(app, "تاريخ تعديل فاسد")
        _login(client, "t_eng")
        r = client.post(f"/reports/dyn/{sid}/edit", data={
            "project_name": "تاريخ تعديل فاسد", "report_date": "31/04/2026"})
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "تحقق من اسم المشروع والتاريخ.")]
        assert _submission(app, "تاريخ تعديل فاسد")["report_date"] == date(2026, 4, 1)

    def test_edit_post_without_project_name_is_refused(self, client, app):
        sid = _seed_submission(app, "اسم تعديل فارغ")
        _login(client, "t_eng")
        r = client.post(f"/reports/dyn/{sid}/edit", data={
            "project_name": "   ", "report_date": "2026-04-16"})
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "تحقق من اسم المشروع والتاريخ.")]
        assert _submission(app, "اسم تعديل فارغ") is not None

    def test_edit_post_rejects_a_duplicate_of_another_submission(self, client, app):
        first = _seed_submission(app, "تكرار أول", report_date=date(2026, 4, 17))
        second = _seed_submission(app, "تكرار ثان", report_date=date(2026, 4, 18))
        _login(client, "t_eng")
        r = client.post(f"/reports/dyn/{second}/edit", data={
            "project_name": "تكرار أول", "report_date": "2026-04-17"})
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "يوجد تقرير آخر بنفس القالب والمشروع والتاريخ.")]
        row = _submission(app, "تكرار ثان")
        assert row["id"] == second
        assert row["report_date"] == date(2026, 4, 18)
        assert _submission(app, "تكرار أول")["id"] == first
        assert "تكرار أول" in r.get_data(as_text=True)   # form re-rendered

    def test_edit_post_links_a_project_and_adopts_its_name(self, client, app):
        sid = _seed_submission(app, "تعديل بربط")
        pid = _project_id(app, "Alpha Tower")
        _login(client, "t_eng")
        r = client.post(f"/reports/dyn/{sid}/edit", data={
            "project_id": str(pid),
            "project_name": "اسم يتجاهله الربط",
            "report_date": "2026-04-30",
        })
        assert r.status_code == 302
        assert _flashes(client, r) == [("success", "تم تحديث التقرير بنجاح.")]
        row = _submission(app, "Alpha Tower")
        assert row["id"] == sid
        assert row["project_id"] == pid
        assert _submission(app, "تعديل بربط") is None
        assert _submission(app, "اسم يتجاهله الربط") is None

    def test_edit_post_with_invalid_project_id_is_404(self, client, app):
        sid = _seed_submission(app, "مشروع مرفوض للتعديل")
        _login(client, "t_eng")
        r = client.post(f"/reports/dyn/{sid}/edit", data={
            "project_id": "not-a-number",
            "project_name": "مشروع مرفوض للتعديل",
            "report_date": "2026-04-19",
        })
        assert r.status_code == 404
        assert _flashes(client, r) == []
        assert _submission(app, "مشروع مرفوض للتعديل")["report_date"] == date(2026, 4, 1)

    def test_edit_post_with_out_of_scope_project_id_is_404(self, client, app):
        sid = _seed_submission(app, "تعديل عبر حاجز", username="t_eng2")
        pid = _project_id(app, "Alpha Tower")
        _login(client, "t_eng2")
        r = client.post(f"/reports/dyn/{sid}/edit", data={
            "project_id": str(pid),
            "project_name": "تعديل عبر حاجز",
            "report_date": "2026-04-20",
        })
        assert r.status_code == 404
        assert _flashes(client, r) == []
        assert _submission(app, "تعديل عبر حاجز")["project_id"] is None

    def test_delete_removes_the_submission_and_its_file(self, client, app):
        _login(client, "t_eng")
        upload = client.post("/reports/dyn/new/daily", data={
            "project_name": "مشروع صورة",
            "report_date": "2026-04-21",
            f"f_{PHOTOS_TABLE}__0__photo": (io.BytesIO(_png_bytes()), "site.png"),
        }, content_type="multipart/form-data")
        assert upload.status_code == 302
        assert _flashes(client, upload) == [
            ("success", "تم حفظ التقرير الديناميكي بنجاح.")]
        row = _submission(app, "مشروع صورة")
        key = row["data"][PHOTOS_TABLE][0]["photo"]
        assert key.startswith("reports/daily/")
        served = client.get(f"/reports/dyn/file/{key}")
        assert served.status_code == 200
        assert served.mimetype == "image/png"

        r = client.post(f"/reports/dyn/{row['id']}/delete")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/archive?src=dyn")
        assert _flashes(client, r) == [("info", "تم حذف التقرير.")]
        assert _submission(app, "مشروع صورة") is None
        archive = client.get("/archive?src=dyn").get_data(as_text=True)
        assert "مشروع صورة" not in archive
        # the stored upload is no longer reachable for its owner: the tenant
        # guard requires a submission of theirs that still references the key
        assert client.get(f"/reports/dyn/file/{key}").status_code == 404
        # DEFECT (reported, not asserted as correct): dyn_delete never removes
        # the file from UPLOAD_FOLDER/reports/, and admins keep serving it.


# ============================ _collect_dynamic / _extract_table_rows rules
class TestDynamicCollectionBranches:
    def test_post_keeps_at_most_two_hundred_table_rows(self, client, app):
        _login(client, "t_eng")
        data = {"project_name": "جدول ضخم", "report_date": "2026-04-22"}
        for i in range(205):
            data[f"f_{WASTE_TABLE}__{i}__proc"] = f"بند {i}"
        r = client.post("/reports/dyn/new/daily", data=data)
        assert r.status_code == 302
        rows = _submission(app, "جدول ضخم")["data"][WASTE_TABLE]
        assert len(rows) == 200
        assert rows[0]["proc"] == "بند 0"
        assert rows[-1]["proc"] == "بند 199"
        assert _flashes(client, r) == [("success", "تم حفظ التقرير الديناميكي بنجاح.")]

    def test_post_refuses_when_the_only_filled_row_is_past_the_cap(self, client, app):
        _login(client, "t_eng")
        data = {"project_name": "بند خارج السقف", "report_date": "2026-04-23"}
        for i in range(200):
            data[f"f_{WASTE_TABLE}__{i}__proc"] = "   "     # whitespace = empty
        data[f"f_{WASTE_TABLE}__200__proc"] = "بند حقيقي"
        r = client.post("/reports/dyn/new/daily", data=data)
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger",
            f"«{WASTE_AR}»: تعذّر قراءة البنود المرسلة — لم يُحفظ شيء. "
            "حدّث الصفحة وحاول مجدداً.")]
        assert _submission(app, "بند خارج السقف") is None

    def test_post_ignores_malformed_table_cell_keys(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "مفاتيح مشوشة",
            "report_date": "2026-04-24",
            f"f_{PHOTOS_TABLE}__0x__caption": "فهرس غير رقمي",
            f"f_{PHOTOS_TABLE}__nodigits__caption": "فهرس بلا أرقام",
            f"f_{PHOTOS_TABLE}__0__caption": "تعليق صالح",
        })
        assert r.status_code == 302
        row = _submission(app, "مفاتيح مشوشة")
        assert row["data"][PHOTOS_TABLE] == [{"photo": "", "caption": "تعليق صالح"}]
        assert _flashes(client, r) == [("success", "تم حفظ التقرير الديناميكي بنجاح.")]

    def test_post_discards_uploads_matching_no_file_cell(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "مرفقات غير مطابقة",
            "report_date": "2026-04-25",
            f"f_{PHOTOS_TABLE}__0__caption": "تعليق",
            f"f_{PHOTOS_TABLE}__1__caption": (
                io.BytesIO(b"junk"), "cell.txt", "text/plain"),
            "stray_upload": (io.BytesIO(b"junk"), "stray.bin",
                             "application/octet-stream"),
        }, content_type="multipart/form-data")
        assert r.status_code == 302
        row = _submission(app, "مرفقات غير مطابقة")
        assert row["data"][PHOTOS_TABLE] == [{"photo": "", "caption": "تعليق"}]
        assert _stored_report_files(app) == []
        assert _flashes(client, r) == [("success", "تم حفظ التقرير الديناميكي بنجاح.")]

    def test_post_reports_an_empty_required_table_column(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "عمود مطلوب فارغ",
            "report_date": "2026-04-26",
            f"f_{EQUIPMENT_TABLE}__0__ownership": "ملك",
        })
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger", f"«{EQUIPMENT_AR}» — الصف 1: «اسم المعدة» مطلوب.")]
        assert _submission(app, "عمود مطلوب فارغ") is None

    def test_post_reports_an_invalid_number_in_a_table_cell(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "رقم غير صالح",
            "report_date": "2026-04-27",
            f"f_{EQUIPMENT_TABLE}__0__eq_name": "خلاطة",
            f"f_{EQUIPMENT_TABLE}__0__hours_work": "ثمانية",
        })
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger",
            f"«{EQUIPMENT_AR}» — الصف 1 «ساعات العمل» يجب أن يكون رقماً.")]
        assert _submission(app, "رقم غير صالح") is None

    def test_post_requires_one_row_in_a_required_table(self, client, app):
        _make_template(app, "t-req-table", "قالب جدول إلزامي", [{
            "key": "mandatory_items", "label_ar": "بنود إلزامية",
            "type": "table", "required": True,
            "columns": [{"key": "item", "label_ar": "البند", "type": "text",
                         "required": True}],
        }])
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/t-req-table", data={
            "project_name": "بلا بنود", "report_date": "2026-04-28"})
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "«بنود إلزامية» يتطلب بنداً واحداً على الأقل.")]
        assert _submission(app, "بلا بنود") is None

    def test_post_saves_a_table_field_that_has_no_columns(self, client, app):
        _make_template(app, "t-empty-table", "قالب جدول بلا أعمدة", [{
            "key": "blank_table", "label_ar": "جدول بلا أعمدة", "type": "table",
            "columns": [{"key": "", "label_ar": "بلا مفتاح"}],
        }])
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/t-empty-table", data={
            "project_name": "بلا أعمدة", "report_date": "2026-04-29"})
        assert r.status_code == 302
        row = _submission(app, "بلا أعمدة")
        assert row["data"] == {"blank_table": []}
        html = client.get("/reports/dyn/new/t-empty-table").get_data(as_text=True)
        assert "هذا الجدول بلا أعمدة بعد" in html

    def test_edit_get_tolerates_a_non_list_stored_table_value(self, client, app):
        sid = _seed_submission(
            app, "قيمة جدول غير قائمة",
            data={PHOTOS_TABLE: "ليست قائمة", "eshs_desc_81": "وصف"})
        _login(client, "t_eng")
        r = client.get(f"/reports/dyn/{sid}/edit")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "ليست قائمة" not in html
        assert f'name="f_{PHOTOS_TABLE}__0__photo"' in html


# ============================================ file-cell upload gate (dyn)
class TestDynamicFileCells:
    def test_post_rejects_a_file_cell_with_a_forbidden_mime(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "نوع ملف ممنوع",
            "report_date": "2026-05-01",
            f"f_{PHOTOS_TABLE}__0__caption": "تعليق",
            f"f_{PHOTOS_TABLE}__0__photo": (
                io.BytesIO(b"#!/bin/sh\necho pwned\n"), "payload.sh", "text/plain"),
        }, content_type="multipart/form-data")
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger",
            f"«{PHOTOS_AR}» — الصف 1: نوع الملف غير مدعوم (text/plain).")]
        assert _submission(app, "نوع ملف ممنوع") is None
        assert _stored_report_files(app) == []

    def test_post_rejects_a_file_name_that_sanitizes_to_empty(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "اسم ملف غير صالح",
            "report_date": "2026-05-02",
            f"f_{PHOTOS_TABLE}__0__photo": (io.BytesIO(_png_bytes()), "..."),
        }, content_type="multipart/form-data")
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger", f"«{PHOTOS_AR}» — الصف 1: اسم الملف غير صالح.")]
        assert _submission(app, "اسم ملف غير صالح") is None
        assert _stored_report_files(app) == []

    def test_post_stores_an_extensionless_file_name(self, client, app):
        _login(client, "t_eng")
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "اسم بلا امتداد",
            "report_date": "2026-05-03",
            f"f_{PHOTOS_TABLE}__0__photo": (
                io.BytesIO(_png_bytes()), "sitephoto", "image/png"),
        }, content_type="multipart/form-data")
        assert r.status_code == 302
        row = _submission(app, "اسم بلا امتداد")
        key = row["data"][PHOTOS_TABLE][0]["photo"]
        assert key.startswith("reports/daily/")
        assert key.endswith("_sitephoto")
        assert len(_stored_report_files(app)) == 1
        # DEFECT (reported, not asserted as correct): with no extension the
        # stored key can never pass dyn_file's mime allow-list, so the saved
        # photo is permanently unviewable.

    def test_post_rejects_a_file_cell_over_four_megabytes(self, client, app):
        app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
        _login(client, "t_eng")
        oversized = b"\x89PNG" + b"0" * (4 * 1024 * 1024)
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "ملف ضخم",
            "report_date": "2026-05-04",
            f"f_{PHOTOS_TABLE}__0__photo": (
                io.BytesIO(oversized), "huge.png", "image/png"),
        }, content_type="multipart/form-data")
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger", f"«{PHOTOS_AR}» — الصف 1: الملف يتجاوز 4MB.")]
        assert _submission(app, "ملف ضخم") is None
        assert _stored_report_files(app) == []

    def test_body_over_the_configured_limit_is_refused_before_the_view(
            self, client, app):
        assert app.config["MAX_CONTENT_LENGTH"] == 4 * 1024 * 1024
        _login(client, "t_eng")
        oversized = b"\x89PNG" + b"0" * (4 * 1024 * 1024)
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "ملف أضخم",
            "report_date": "2026-05-05",
            f"f_{PHOTOS_TABLE}__0__photo": (
                io.BytesIO(oversized), "huge.png", "image/png"),
        }, content_type="multipart/form-data")
        assert r.status_code == 413
        assert _submission(app, "ملف أضخم") is None

    def test_post_reports_a_file_storage_failure(self, client, app, monkeypatch):
        from app.reports import routes
        _login(client, "t_eng")

        def boom(*args, **kwargs):
            raise OSError("no space left on device")

        monkeypatch.setattr(routes, "_store_dyn_file", boom)
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": "فشل الحفظ",
            "report_date": "2026-05-06",
            f"f_{PHOTOS_TABLE}__0__photo": (io.BytesIO(_png_bytes()), "site.png"),
        }, content_type="multipart/form-data")
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", f"«{PHOTOS_AR}» — الصف 1: فشل الحفظ.")]
        assert _submission(app, "فشل الحفظ") is None
        assert _stored_report_files(app) == []


# ================================================ /reports/dyn/file guards
class TestDynamicFileEndpoint:
    def _upload_photo(self, client, project, filename, mimetype="image/png"):
        r = client.post("/reports/dyn/new/daily", data={
            "project_name": project,
            "report_date": "2026-05-07",
            f"f_{PHOTOS_TABLE}__0__photo": (
                io.BytesIO(_png_bytes()), filename, mimetype),
        }, content_type="multipart/form-data")
        assert r.status_code == 302
        return _submission(client.application, project)["data"][PHOTOS_TABLE][0]["photo"]

    def test_refuses_a_stored_file_whose_mime_is_not_allowed(self, client, app):
        _login(client, "t_eng")
        key = self._upload_photo(client, "امتداد ممنوع", "evidence.txt")
        assert key.startswith("reports/daily/") and key.endswith("_evidence.txt")
        assert os.path.isfile(os.path.join(app.config["UPLOAD_FOLDER"], key))
        assert client.get(f"/reports/dyn/file/{key}").status_code == 404

    def test_refuses_a_key_that_is_not_stored(self, client, app):
        # an admin passes the tenant guard, so the missing file itself 404s
        _login(client, "t_admin")
        r = client.get("/reports/dyn/file/reports/daily/does-not-exist.png")
        assert r.status_code == 404
        assert _flashes(client, r) == []

    def test_refuses_a_key_that_resolves_outside_the_upload_folder(
            self, client, app, monkeypatch):
        from app.reports import routes

        def boom(key):
            raise ValueError("storage key escapes upload folder")

        monkeypatch.setattr(routes, "_abs_dyn_file", boom)
        _login(client, "t_admin")
        r = client.get("/reports/dyn/file/reports/daily/whatever.png")
        assert r.status_code == 404
        assert _flashes(client, r) == []

    def test_abs_dyn_file_raises_for_keys_escaping_the_upload_folder(self, app):
        from app.reports.routes import _abs_dyn_file
        with app.test_request_context():
            inside = _abs_dyn_file("reports/daily/ok.png")
            assert inside.startswith(
                os.path.abspath(app.config["UPLOAD_FOLDER"]) + os.sep)
            with pytest.raises(ValueError):
                _abs_dyn_file("../../etc/passwd")
            with pytest.raises(ValueError):
                _abs_dyn_file("reports/../../escape.png")

    def test_store_dyn_file_raises_for_keys_escaping_the_upload_folder(self, app):
        from app.reports.routes import _store_dyn_file
        uploads = os.path.abspath(app.config["UPLOAD_FOLDER"])
        with app.test_request_context():
            with pytest.raises(ValueError):
                _store_dyn_file("../../..", "evil.txt", b"x")
            with pytest.raises(ValueError):
                _store_dyn_file("daily", "../../../../../evil.txt", b"x")
        # nothing landed outside the isolated per-test upload folder
        assert not os.path.exists(os.path.join(os.path.dirname(uploads), "evil.txt"))
        assert not os.path.exists(os.path.join(
            os.path.dirname(os.path.dirname(uploads)), "evil.txt"))


# ================================================= defensive degrade paths
class TestCollectionDefensiveGuards:
    def test_extract_table_rows_tolerates_files_whose_keys_explode(self, app):
        from app.models import ReportTemplate
        from app.reports.routes import _extract_table_rows
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            field = [f for f in tpl.ordered_fields
                     if f.field_key == PHOTOS_TABLE][0]
            assert field.sub_columns()
            assert _extract_table_rows(field, {}, files=_KeysExplode()) == []

    def test_extract_table_rows_tolerates_files_whose_get_explodes(self, app):
        from app.models import ReportTemplate
        from app.reports.routes import _extract_table_rows
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            field = [f for f in tpl.ordered_fields
                     if f.field_key == PHOTOS_TABLE][0]
            form = _FlatForm({f"f_{PHOTOS_TABLE}__0__caption": "تعليق"})
            rows = _extract_table_rows(
                field, form, files=_GetExplodes(
                    [f"f_{PHOTOS_TABLE}__0__photo"]), indexed=True)
            # the unreadable upload is dropped, the submitted cell survives
            assert rows == [(0, {"photo": "", "caption": "تعليق"})]

    def test_collect_dynamic_tolerates_a_form_whose_keys_explode(self, app):
        from app.models import ReportTemplate
        from app.reports.routes import _collect_dynamic
        _make_template(app, "t-colless", "قالب بمفتاح واحد", [
            {"key": "blank_table", "label_ar": "جدول بلا أعمدة",
             "type": "table", "columns": [{"key": "", "label_ar": "بلا مفتاح"}]},
            {"key": "note", "label_ar": "ملاحظة", "type": "text"},
        ])
        with app.test_request_context("/reports/dyn/new/t-colless", method="POST"):
            tpl = ReportTemplate.query.filter_by(key="t-colless").first()
            payload, errors = _collect_dynamic(tpl, _NoKeysForm({"f_note": "نص"}))
        assert errors == []
        assert payload == {"blank_table": [], "note": "نص"}

    def test_collect_dynamic_tolerates_a_tripwire_scan_whose_keys_explode(
            self, app):
        """The tripwire scan degrades to 'no keys' instead of a 500."""
        from app.models import ReportTemplate
        from app.reports.routes import _collect_dynamic
        cell = f"f_{WEATHER_TABLE}__0__condition"
        with app.test_request_context("/reports/dyn/new/daily", method="POST"):
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            form = _PassingForm([cell], values={cell: "صافي"},
                                reveal_on=(1,), explode_on=2)
            payload, errors = _collect_dynamic(tpl, form)
        assert errors == []
        assert payload[WEATHER_TABLE] == [
            {"condition": "صافي", "temp": "", "air": ""}]

    def test_collect_dynamic_tolerates_a_tripwire_value_that_raises(
            self, app):
        from app.models import ReportTemplate
        from app.reports.routes import _collect_dynamic
        cell = f"f_{WEATHER_TABLE}__0__condition"
        with app.test_request_context("/reports/dyn/new/daily", method="POST"):
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            form = _PassingForm([cell], explode_get={cell})
            payload, errors = _collect_dynamic(tpl, form)
        assert errors == []
        assert payload[WEATHER_TABLE] == []

    def test_collect_dynamic_tolerates_an_empty_tripwire_value(self, app):
        from app.models import ReportTemplate
        from app.reports.routes import _collect_dynamic
        cell = f"f_{WEATHER_TABLE}__0__condition"
        with app.test_request_context("/reports/dyn/new/daily", method="POST"):
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            form = _PassingForm([cell], values={cell: None})
            payload, errors = _collect_dynamic(tpl, form)
        assert errors == []
        assert payload[WEATHER_TABLE] == []

    def test_file_cell_survives_an_unseekable_upload_stream(self, app):
        """The upload is still read + stored when its stream cannot seek."""
        from werkzeug.datastructures import MultiDict
        from app.models import ReportTemplate
        from app.reports.routes import _collect_dynamic
        photo_key = f"f_{PHOTOS_TABLE}__0__photo"
        with app.test_request_context(
                "/reports/dyn/new/daily", method="POST",
                data={photo_key: (io.BytesIO(_png_bytes()), "site.png",
                                  "image/png"),
                      f"f_{PHOTOS_TABLE}__0__caption": "تعليق"},
                content_type="multipart/form-data") as ctx:
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            req = ctx.request
            # swap the parsed upload for one whose stream raises on seek()
            uploads = MultiDict(req.files)
            uploads[photo_key] = _UnseekableUpload()
            setattr(req, "files", uploads)
            payload, errors = _collect_dynamic(tpl, req.form)
        assert errors == []
        key = payload[PHOTOS_TABLE][0]["photo"]
        assert key.startswith("reports/daily/") and key.endswith("_site.png")
        assert payload[PHOTOS_TABLE][0]["caption"] == "تعليق"
        assert len(_stored_report_files(app)) == 1
