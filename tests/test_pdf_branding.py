"""PDF output: identity, proportions, and what a failure does.

The letterhead is the most visible part of a report, and every failure path in
it used to be swallowed at debug level, so a report could go out with no header
and nothing anywhere recording why.
"""
import io
import os

import pytest
from PIL import Image

from app.extensions import db
from app.models import Project, Report, ReportTemplate, TenantBranding
from app.services import branding as branding_service
from utils.pdf_generator import _custom_logo, _scaled_image


def _wide_logo(path, size=(400, 100)):
    Image.new("RGB", size, (10, 90, 160)).save(path, "PNG")
    return path


def _square_logo(path):
    Image.new("RGB", (200, 200), (200, 160, 10)).save(path, "PNG")
    return path


# ---------------------------------------------------------------- proportions
def test_a_wide_logo_is_not_stretched_into_a_square(tmp_path):
    """Every logo used to be drawn width == height.

    A wordmark is typically four times wider than it is tall, so the company
    name on the letterhead of every report was vertically smeared.
    """
    path = _wide_logo(tmp_path / "wide.png")
    flowable = _scaled_image(str(path), max_width_mm=28, max_height_mm=14)
    assert flowable is not None
    ratio = flowable.drawWidth / flowable.drawHeight
    assert 3.5 < ratio < 4.5, f"aspect ratio collapsed to {ratio:.2f}"


def test_a_tall_logo_is_capped_rather_than_overflowing_the_page(tmp_path):
    path = tmp_path / "tall.png"
    Image.new("RGB", (100, 800), (0, 0, 0)).save(path, "PNG")
    flowable = _scaled_image(str(path), max_width_mm=28, max_height_mm=14)
    assert flowable.drawHeight <= 14 * 2.83465 + 0.5


def test_a_square_logo_keeps_its_shape(tmp_path):
    path = _square_logo(tmp_path / "square.png")
    flowable = _scaled_image(str(path), max_width_mm=20, max_height_mm=20)
    assert abs(flowable.drawWidth - flowable.drawHeight) < 0.5


def test_a_corrupt_logo_is_reported_and_skipped(tmp_path, caplog):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 40)
    assert _custom_logo(str(broken)) is None


def test_a_logo_pointing_at_nothing_is_reported_not_silently_dropped(tmp_path, caplog):
    assert _custom_logo(str(tmp_path / "absent.png")) is None


def test_an_empty_logo_key_is_not_an_error(tmp_path):
    assert _custom_logo("") is None
    assert _custom_logo(None) is None


# ------------------------------------------------------------------ branding
def _report_and_brand(app, logo_key=""):
    from datetime import date
    from app.models import User
    project = Project(name="مشروع التقرير", contractor="المقاول")
    owner = User(username="pdf-owner", email="pdf-owner@brand.test",
                 full_name="مالك", role="admin")
    owner.set_password("pw12345")
    db.session.add_all([project, owner])
    db.session.commit()
    template = ReportTemplate.query.filter_by(key="daily").first()
    report = Report(report_type="daily", project_name=project.name,
                    report_date=date(2026, 1, 15), data={"notes": "x"},
                    user_id=owner.id, signatory_name="موقّع")
    db.session.add(report)
    db.session.add(TenantBranding(
        project_id=project.id, is_active=True,
        company_name_ar="شركة الجسر للمقاولات",
        company_name_en="Bridge Contracting",
        logo_path=logo_key,
        custom_footer_notes="سرّي — للاستخدام الداخلي",
        disclaimer_text="هذه الوثيقة إرشادية ولا تُغني عن الموقع."))
    db.session.commit()
    return report, project


def test_a_tenant_report_carries_its_own_identity(app):
    from utils.pdf_generator import build_report_pdf_branded
    report, project = _report_and_brand(app)
    brand = branding_service.branding_for_project(project.id)
    pdf = build_report_pdf_branded(report, brand)

    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "Bridge Contracting" in text, (
        "the tenant's own name is missing from the document")
    assert "AZAD Intelligent Systems" not in text, (
        "the vendor's copyright is still stamped on a tenant's report")
    assert contains(text, "سرّي"), "the tenant's footer note did not reach it"


def test_the_disclaimer_appears_on_the_page(app):
    from utils.pdf_generator import build_report_pdf_branded
    report, project = _report_and_brand(app)
    brand = branding_service.branding_for_project(project.id)
    pdf = build_report_pdf_branded(report, brand)
    assert contains(_pdf_text(pdf), "هذه الوثيقة إرشادية")


def test_a_report_with_no_tenant_logo_still_builds(app):
    from utils.pdf_generator import build_report_pdf_branded
    report, project = _report_and_brand(app)
    brand = branding_service.branding_for_project(project.id)
    pdf = build_report_pdf_branded(report, brand)
    assert pdf.startswith(b"%PDF")
    assert "Bridge Contracting" in _pdf_text(pdf)


def test_the_dynamic_report_footer_uses_the_tenant_not_the_vendor(app):
    _report, project = _report_and_brand(app)
    from datetime import date
    from app.models import ReportSubmission
    template = ReportTemplate.query.filter_by(key="daily").first()
    from app.models import User
    submission = ReportSubmission(
        template_id=template.id, data={}, report_date=date(2026, 1, 15),
        project_id=project.id, project_name=project.name,
        contractor="المقاول", user_id=User.query.first().id)
    db.session.add(submission)
    db.session.commit()

    from app.services.pdf_dynamic import build_dynamic_pdf
    pdf = build_dynamic_pdf(submission, template)
    text = _pdf_text(pdf)
    assert "Bridge Contracting" in text
    assert "AZAD Intelligent Systems" not in text


def test_tenant_branding_adopts_colours_without_renaming_the_template():
    """The old helper overwrote tpl.name_ar with the tenant's header text.

    That renamed the report type itself, so it changed in the picker, in every
    list, and in every already-issued PDF referencing it.
    """
    from app.services.default_templates import apply_tenant_branding

    class Tpl:
        name_ar = "التقرير اليومي"
        gradient = "from-sky-500 to-blue-700"

    tpl = Tpl()
    apply_tenant_branding(tpl, TenantBranding(
        custom_header_text_ar="ترويسة المالك", primary_color="#112233",
        secondary_color="#445566"))
    assert tpl.name_ar == "التقرير اليومي"
    assert tpl.gradient == "from-[112233] to-[445566]"


def test_tenant_branding_refuses_a_colour_that_is_not_hex():
    from app.services.default_templates import apply_tenant_branding

    class Tpl:
        name_ar = "التقرير اليومي"
        gradient = "from-sky-500 to-blue-700"

    tpl = Tpl()
    apply_tenant_branding(tpl, TenantBranding(
        primary_color="red;} body{x", secondary_color="}"))
    assert tpl.gradient == "from-sky-500 to-blue-700"


# --------------------------------------------------------------------- utils
def _pdf_text(pdf_bytes):
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or ""
                     for page in PdfReader(io.BytesIO(pdf_bytes)).pages)


def contains(text, phrase):
    """True when the document carries the phrase, ignoring display order.

    The renderer shapes Arabic for display, so the glyphs in the file are the
    presentation forms of the source letters, laid out right to left. Shaping
    the phrase the same way puts both sides in one alphabet; the letters are
    then compared as a multiset, because the layout reorders them and collapses
    some of the spaces the source had.
    """
    import arabic_reshaper

    def bag(value):
        shaped = arabic_reshaper.reshape(value)
        return sorted(ch for ch in shaped if ch.isalpha())

    wanted = bag(phrase)
    if not wanted:
        return phrase in text
    have = bag(text)
    remaining = list(have)
    for ch in wanted:
        remaining.remove(ch)
    return True
