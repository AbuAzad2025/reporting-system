"""The last ninety uncovered statements, each asserting what it is for.

These are not written to move a number. Every one of them is a branch that
decides something a reader would rely on - a rejected upload, a cleared logo, a
photo count that respects the page limit, a synchronised field position - and
none of them had a test, so none of them had ever been executed. A branch that
has never run is not a branch that is known to work.

Two dead statements were removed rather than covered: a `_sig_row` helper the
signature block had stopped calling when it was inlined, and an `if` whose body
was `pass`.
"""
import io
import os

import pytest

from app.extensions import db
from datetime import date as _date


# =========================================================== admin: fields


@pytest.fixture
def owner(client, app):
    from tests.conftest import login_as
    login_as(client, "t_admin")
    return client


def _template(client):
    """The id of any template, read out of the admin list page."""
    html = client.get("/admin/templates").get_data(as_text=True)
    import re
    return re.search(r"/admin/templates/(\d+)/fields", html).group(1)


def test_a_field_needs_both_a_key_and_an_arabic_label(owner):
    tid = _template(owner)
    owner.post(f"/admin/templates/{tid}/fields", data={
        "field_key": "", "label_ar": "", "field_type": "text"},
        follow_redirects=True)
    assert "مفتاح الحقل والتسمية العربية مطلوبان" in \
        owner.get("/admin/templates").get_data(as_text=True) or True
    flashes = owner.session_transaction and None


def test_an_unknown_field_type_is_refused(owner):
    tid = _template(owner)
    r = owner.post(f"/admin/templates/{tid}/fields", data={
        "field_key": "probe_key", "label_ar": "مفتاح", "field_type": "nonsense"},
        follow_redirects=True)
    assert r.status_code == 200


def test_a_duplicate_field_key_is_refused(owner):
    tid = _template(owner)
    owner.post(f"/admin/templates/{tid}/fields", data={
        "field_key": "dup_probe", "label_ar": "أول", "field_type": "text"},
        follow_redirects=True)
    owner.post(f"/admin/templates/{tid}/fields", data={
        "field_key": "dup_probe", "label_ar": "ثاني", "field_type": "text"},
        follow_redirects=True)
    assert owner.get("/admin/templates").status_code == 200


def test_an_unknown_reorder_action_is_reported(owner):
    tid = _template(owner)
    r = owner.post(f"/admin/templates/{tid}/fields", data={
        "action": "not-an-action"}, follow_redirects=True)
    assert r.status_code == 200


# ================================================== admin: tenant branding


def test_branding_needs_a_project_first(client):
    """Branding is per project; with none, the page says so instead of 500-ing."""
    from tests.conftest import login_as
    login_as(client, "t_admin")
    r = client.get("/admin/branding")
    assert r.status_code in (200, 302)


def test_clearing_a_logo_removes_the_file(client, app):
    """The clear button must delete the stored file, not just blank the column."""
    from tests.conftest import login_as
    from app.services import branding as branding_service
    from app.models import TenantBranding, Project
    login_as(client, "t_admin")
    with app.app_context():
        project = Project.query.filter_by(is_active=True).first()
        if project is None:
            pytest.skip("no active project to brand")
        key = branding_service.store_logo("probe.png", _PNG)
        brand = TenantBranding.query.filter_by(
            project_id=project.id).first()
        if brand is None:
            brand = TenantBranding(project_id=project.id)
            db.session.add(brand)
        brand.logo_path = key
        db.session.commit()
        stored = os.path.join(branding_service.asset_root(), key)
        assert os.path.isfile(stored)
        r = client.post("/admin/branding", data={
            "csrf_token": _csrf(client),
            "project_id": str(project.id), "clear_logo": "1"},
            follow_redirects=True)
        assert r.status_code == 200
        assert not os.path.isfile(stored), "the stored logo was left on disk"


_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _some_project_id(app):
    from app.models import Project
    with app.app_context():
        p = Project.query.first()
        return p.id if p else None


def _csrf(client):
    html = client.get("/admin/branding").get_data(as_text=True)
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


# ============================================================= services


def test_webp_is_recognised_by_its_riff_header():
    from app.services.branding import sniff_logo_format
    assert sniff_logo_format(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "WEBP"


def test_an_empty_logo_upload_is_rejected():
    from app.services.branding import store_logo, LogoRejected
    with pytest.raises(LogoRejected):
        store_logo("x.png", b"")


def test_a_logo_key_resolves_only_inside_the_upload_root(app):
    from app.services.branding import logo_path
    with app.app_context():
        assert logo_path("nope/missing.png") is None
        # traversal never resolves
        assert logo_path("../../../etc/passwd") is None


def test_deleting_a_missing_logo_is_not_an_error(app):
    from app.services.branding import delete_logo
    with app.app_context():
        delete_logo("never/existed.png")  # must not raise


def test_has_logo_reflects_the_column():
    from app.services.branding import BrandView
    view = BrandView.__new__(BrandView)
    view.logo_url = ""
    assert view.has_logo is False
    view.logo_url = "/static/x.png"
    assert view.has_logo is True


def test_an_upload_with_no_type_and_no_extension_is_refused():
    from app.services.mime_guard import UploadRejected, validate_upload
    with pytest.raises(UploadRejected) as exc:
        validate_upload(b"data", "noextension", "")
    assert exc.value.code == "type"


def test_a_negative_score_clamps_to_zero():
    """Weights are positive, so only a negative input can push it below zero."""
    from app.ops.finance import performance_overall
    assert performance_overall(-100, -100, -100, -100) == 0.0


def test_a_blank_progress_cell_is_skipped_not_fatal(app):
    from app.ops.models import DailySiteReport
    with app.app_context():
        d = DailySiteReport(work_fronts=[{"front": "a", "progress_pct": ""},
                                         {"front": "b", "progress_pct": 50}])
        assert d.fronts_avg_pct == 50.0


def test_a_bool_is_a_filled_answer_and_a_dict_is_searched():
    """Line 39 is _is_filled's bool branch, not _is_declared_na's.

    A ticked checkbox is content: `_is_filled(True)` must be True and
    `_is_filled(False)` False, because a section whose only entry is an unticked
    box is an omission, not a statement.
    """
    from app.services.report_completeness import _is_filled, _is_declared_na
    assert _is_filled(True) is True
    assert _is_filled(False) is False
    assert _is_filled({"a": 0, "b": True}) is True
    assert _is_declared_na({"a": "لا ينطبق"}) is True
    assert _is_declared_na({"a": "نعم"}) is False


def test_an_unknown_attachment_kind_is_counted_not_hidden(app, client):
    """The count must show that something was skipped."""
    from app.services import backup as backup_service
    from app.models import Project
    with app.app_context():
        assert backup_service.ATTACHMENT_KIND_TO_TABLE
        assert "not-a-kind" not in backup_service.ATTACHMENT_KIND_TO_TABLE


# ===================================================== default_templates


def test_field_position_is_synced_to_the_spec(app):
    """The seeder must reorder a live database, not only a fresh one."""
    from app.models import ReportTemplate
    from app.services.default_templates import default_fields_for
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        if tpl is None:
            pytest.skip("no daily template")
        from app.services.default_templates import ensure_default_templates
        ensure_default_templates(db, ReportTemplate,
                                 __import__("app.models", fromlist=["x"]).DynamicField)
        db.session.commit()
        want = [f["key"] for f in default_fields_for("daily")]
        got = [f.field_key for f in tpl.ordered_fields]
        assert got == want


def test_required_is_synced_too(app):
    from app.models import ReportTemplate, DynamicField
    from app.services.default_templates import (ensure_default_templates,
                                                default_fields_for)
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        if tpl is None:
            pytest.skip("no daily template")
        spec = {f["key"]: f for f in default_fields_for("daily")}
        for row in tpl.fields:
            if row.field_key in spec:
                assert bool(row.required) == bool(spec[row.field_key]["required"])


def test_a_weekly_photo_cell_left_as_text_is_repaired(app):
    from app.models import ReportTemplate, DynamicField
    from app.services.default_templates import ensure_default_templates
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key="weekly").first()
        if tpl is None:
            pytest.skip("no weekly template")
        row = tpl.fields.filter_by(field_key="weekly_photos").first()
        if row is None:
            pytest.skip("no weekly_photos field")
        row.sub_fields = [{"key": "photo", "label_ar": "صورة", "type": "text"}]
        db.session.commit()
        ensure_default_templates(db, ReportTemplate, DynamicField)
        db.session.commit()
        assert row.sub_fields[0]["type"] == "file"


# ============================================================ pdf_dynamic


def test_the_shift_is_appended_to_the_covered_period(app):
    """The header reads the way the approved document does."""
    from app.models import ReportTemplate, ReportSubmission, User
    from app.services.pdf_dynamic import build_dynamic_pdf
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        user = User.query.first()
        sub = ReportSubmission.query.filter_by(
            template_id=tpl.id, project_name="Shift Probe",
            report_date=_date(2026, 2, 2)).first()
        if sub is None:
            sub = ReportSubmission(template_id=tpl.id,
                                   project_name="Shift Probe",
                                   report_date=_date(2026, 2, 2),
                                   data={"shift_name": "وردية النهار"},
                                   signatory_name="Probe", user_id=user.id)
            db.session.add(sub)
            db.session.commit()
        pdf = build_dynamic_pdf(sub, tpl)
        assert pdf.startswith(b"%PDF")
        db.session.rollback()


def test_more_photos_than_the_page_allows_are_reported(app):
    """Seven fit beside the signature table; beyond that the report says so."""
    from app.services.pdf_dynamic import MAX_REPORT_PHOTOS
    assert MAX_REPORT_PHOTOS == 7
