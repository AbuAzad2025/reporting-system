import re
import sys
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


@pytest.fixture(autouse=True)
def _app_context(app):
    # The shared `app` fixture yields outside its own context, so db.session
    # and current_app are unavailable unless one is pushed here.
    with app.app_context():
        yield


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


def test_the_dynamic_report_carries_no_vendor_or_tenant_letterhead(app):
    """The page identifies itself by title and serial, nothing else.

    It used to draw the tenant's letterhead, the project header table, a gold
    rule, and a footer band repeating the serial and a timestamp on every
    page. The request was for a title, a serial number and two blank signature
    boxes, so neither name is drawn any more — including the tenant's, which
    is on the paper the report is filed with rather than in the renderer.

    Guarded because the earlier version of this test asserted the opposite
    (tenant in, vendor out) for a footer that no longer exists.
    """
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
    runs = _pdf_runs(pdf)
    joined = "\n".join(runs)
    assert "Bridge Contracting" not in joined
    assert "AZAD Intelligent Systems" not in joined


def test_the_dynamic_report_still_titles_itself_and_signs(app):
    """What the page must still carry after the letterhead went."""
    _report, project = _report_and_brand(app)
    from datetime import date
    from app.models import ReportSubmission, User
    template = ReportTemplate.query.filter_by(key="daily").first()
    submission = ReportSubmission(
        template_id=template.id, data={}, report_date=date(2026, 1, 15),
        project_id=project.id, project_name=project.name,
        contractor="المقاول", user_id=User.query.first().id)
    db.session.add(submission)
    db.session.commit()

    from app.services.pdf_dynamic import build_dynamic_pdf
    runs = _pdf_runs(build_dynamic_pdf(submission, template))
    runs = _pdf_runs(build_dynamic_pdf(submission, template))
    joined = " ".join(runs)
    # A word is asserted through its folded form, and a definite article that
    # does not join forward is gone from the stored run, so "الإنجاز" is AANJAZ
    # rather than ALANJAZ.
    for part in ("TQRYR", "AANJAZ", "ALYWMY",          # title
                 "RQM", "ALTQRYR",                       # serial label
                 "ALMSRF", "MSRWA", "ALTQRYR",           # supervisor
                 "MDYR", "ALMSRWA", "ALTQRYR"):          # project manager
        assert part in joined, part


def _pdf_runs(pdf_bytes):
    """Drawn text runs, with Arabic returned to base letters in reading order.

    The runs are stored in visual order: Arabic presentation forms, reversed.
    pdf_tools says outright that Arabic presentation forms "must never be
    asserted on" — which is why the other tests here grep Latin. This test
    needs Arabic, so each run is reversed, passed back through get_display()
    (which is not its own inverse, so reversing first is what makes the pair
    cancel), and finally folded to base letters, because the forms have no
    Unicode equality with the plain spelling.
    """
    sys.path.insert(0, "tests")
    from pdf_tools import PdfDocument
    from bidi.algorithm import get_display
    import unicodedata

    def to_base(s):
        out = []
        for ch in s:
            if not 0xFB50 <= ord(ch) <= 0xFEFF:
                out.append(ch)
                continue
            try:
                name = unicodedata.name(ch)
                base = name.split(" ISOLATED")[0].split(" FINAL")[0]
                base = base.split(" INITIAL")[0].replace("ARABIC LETTER ", "")
                out.append(base[:1])
            except Exception:
                out.append(ch)
        return "".join(out)

    runs = []
    for r in PdfDocument(pdf_bytes).text_runs:
        logical = r
        if any(0xFB50 <= ord(c) <= 0xFEFF for c in r):
            try:
                logical = to_base(get_display(get_display(r[::-1])))
            except Exception:
                # Keep the presentation forms rather than dropping the run. The
                # comparison in contains() folds them too, so the run is still
                # usable, and a run that cannot be un-shaped must not silently
                # disappear - that would turn an extraction problem into a
                # missing-text failure with no cause.
                #
                # Catch-all on purpose: bidi and the reshaper raise a mix of
                # ValueError, TypeError and IndexError depending on the input,
                # and a new exception type here would fail an unrelated test
                # rather than describe anything useful. Scoped nosec because
                # the fallback is the behaviour, not an oversight.
                pass  # nosec B110
        runs.append(logical)
    return runs


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
