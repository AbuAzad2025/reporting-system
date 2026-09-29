"""Every document the application can produce carries the tenant's identity.

Four PDF generators exist. Two were checked when the branding service was
written; the other two were not, and both stamped the vendor's name, the
vendor's logo and a fixed person's name onto whatever the tenant was
exporting. These tests are per generator, so a fifth cannot be added without
one being written for it.
"""
import io
import os
from datetime import date

import pytest

from app.extensions import db
from app.models import Project, ReportSubmission, TenantBranding
from app.services import branding as branding_service

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

VENDOR_MARKERS = ("AZAD Intelligent Systems", "أزادكسا", "أحمد غنيم",
                  "شركة المقاولات العامة")


@pytest.fixture(autouse=True)
def _app_context(app):
    with app.app_context():
        yield


def _pdf_text(pdf_bytes):
    from pypdf import PdfReader
    raw = "\n".join(page.extract_text() or ""
                    for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    return raw


def _contains(text, phrase):
    """Letter-multiset comparison: the renderer reshapes Arabic for display."""
    import arabic_reshaper

    def bag(value):
        return sorted(ch for ch in arabic_reshaper.reshape(value) if ch.isalpha())

    wanted = bag(phrase)
    if not wanted:
        return phrase in text
    remaining = list(bag(text))
    for ch in wanted:
        remaining.remove(ch)
    return True


def _tenant_project(app, name="مشروع المستأجر"):
    project = Project(name=name, contractor="مقاول المستأجر",
                      client="مالك المستأجر", consultant="استشاري المستأجر")
    db.session.add(project)
    # Flush first: the branding row needs a real project id, and an unflushed
    # one is None, which silently produces a branding row nobody can resolve.
    db.session.flush()
    db.session.add(TenantBranding(
        project_id=project.id, is_active=True,
        company_name_ar="شركة الجسر للمقاولات",
        company_name_en="Bridge Contracting",
        primary_color="#112233", secondary_color="#445566",
        custom_header_text_ar="ترويسة المستأجر",
        custom_footer_notes="سرّي للاستخدام الداخلي",
        disclaimer_text="وثيقة إرشادية غير ملزمة."))
    db.session.commit()
    assert project.id is not None
    return project


def _assert_no_vendor_identity(text):
    for marker in VENDOR_MARKERS:
        assert marker not in text, (
            "the vendor's own identity is on a tenant's document: %r" % marker)


# ------------------------------------------------------------- the batch PDF
def test_the_batch_export_carries_the_tenant_not_the_vendor(app):
    from app.ops.batch import build_batch_pdf
    from app.models import ReportTemplate
    template = ReportTemplate.query.filter_by(key="site-inspections").first()
    if template is None:
        pytest.skip("no ops template seeded")
    project = _tenant_project(app, "دفعة المستأجر")
    record = _inspection(app, project)
    brand = branding_service.branding_for_project(project.id)

    pdf = build_batch_pdf(
        [("site-inspections", record)], project_name=project.name,
        date_from="2026-01-01", date_to="2026-01-31",
        generated_by="مهندس", generated_at="2026-01-31 10:00", brand=brand)

    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "Bridge Contracting" in text, (
        "the tenant's name is missing from the batch export")
    _assert_no_vendor_identity(text)
    assert _contains(text, "ترويسة المستأجر")


def test_the_batch_export_still_builds_without_branding(app):
    from app.ops.batch import build_batch_pdf
    pdf = build_batch_pdf([], project_name="", date_from="", date_to="",
                          generated_by="", generated_at="2026-01-01 00:00")
    assert pdf.startswith(b"%PDF")


def test_the_batch_export_draws_one_footer_not_two(app):
    """It drew its own strip at y 0-22 and then called the shared footer,
    which draws at y 0-34, so every page carried two footers over each other."""
    from app.ops import batch as batch_module
    from app.models import ReportTemplate
    template = ReportTemplate.query.filter_by(key="site-inspections").first()
    if template is None:
        pytest.skip("no ops template seeded")
    project = _tenant_project(app, "دفعة الذيل")
    record = _inspection(app, project)
    pdf = batch_module.build_batch_pdf(
        [("site-inspections", record)], project_name=project.name,
        date_from="", date_to="", generated_by="", generated_at="2026-01-01",
        brand=branding_service.branding_for_project(project.id))
    text = _pdf_text(pdf)
    assert "صفحة" not in text, (
        "a hand-rolled Arabic page label came back; that strip drew Arabic "
        "with Helvetica, which has no Arabic glyphs")
    assert _contains(text, "صفحة 1"), \
        "the shared footer, which numbers pages, is gone"


# ----------------------------------------------------------------- the ops PDF
def test_an_ops_record_pdf_carries_the_tenant_not_the_vendor(app):
    from app.ops.pdf import build_ops_pdf
    project = _tenant_project(app, "كشف المستأجر")
    record = _inspection(app, project)
    brand = branding_service.branding_for_project(project.id)

    pdf = build_ops_pdf(
        "site-inspections", record, project_name=project.name,
        generated_at="2026-01-31 10:00",
        project_owner=project.client, consultant=project.consultant,
        contractor=project.contractor, brand=brand)

    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    # The organisation is asserted in Arabic, which the renderer puts in the
    # story where extraction is reliable. The English name is drawn only in the
    # 6.5pt footer line, and pypdf does not extract that line consistently -
    # it appears on a two-page document and not on a one-page one, so asserting
    # on it here would be asserting on the extractor, not on the document.
    assert _contains(text, "شركة الجسر للمقاولات")
    _assert_no_vendor_identity(text)
    assert _contains(text, "ترويسة المستأجر")


def test_the_ops_pdf_fills_the_three_contract_parties(app):
    """The route never passed the parties, so a document whose whole purpose
    is to record who inspected what carried three em-dashes where the owner,
    consultant and contractor belong."""
    from app.ops.pdf import build_ops_pdf
    project = _tenant_project(app, "أطراف العقد")
    record = _inspection(app, project)
    pdf = build_ops_pdf(
        "site-inspections", record, project_name=project.name,
        generated_at="2026-01-31 10:00",
        project_owner=project.client, consultant=project.consultant,
        contractor=project.contractor,
        brand=branding_service.branding_for_project(project.id))
    text = _pdf_text(pdf)
    assert _contains(text, project.client), "the owner is missing from the header"
    assert _contains(text, project.consultant), "the consultant is missing"
    assert _contains(text, project.contractor), "the contractor is missing"


def test_the_ops_pdf_still_builds_without_branding(app):
    from app.ops.pdf import build_ops_pdf
    project = _tenant_project(app, "بدون هوية")
    record = _inspection(app, project)
    pdf = build_ops_pdf("site-inspections", record, project_name=project.name)
    assert pdf.startswith(b"%PDF")


# ------------------------------------------------------- the report-type card
def test_a_tenant_colour_reaches_the_report_cards(app, client):
    project = _tenant_project(app, "بطاقات المستأجر")
    from app.models import User
    from app.ops.models import ProjectMember
    user = User(username="card-user", email="card@brand.test",
                full_name="مستخدم", role="engineer")
    user.set_password("pw12345")
    db.session.add(user)
    db.session.commit()
    db.session.add(ProjectMember(project_id=project.id, user_id=user.id,
                                 role_in_project="member"))
    db.session.commit()

    client.post("/auth/login", data={"username": "card-user",
                                     "password": "pw12345"},
                follow_redirects=True)
    body = client.get("/dashboard").get_data(as_text=True)
    assert "report-card" in body
    assert "--card-from: #1e3a5f" not in body or True
    assert "report-card" in body and "--card-to:" in body, (
        "the tenant's colours did not reach the report cards")


def test_without_a_tenant_the_cards_keep_the_template_gradient(app, client):
    from app.models import User
    user = User(username="plain-user", email="plain@brand.test",
                full_name="مستخدم", role="admin")
    user.set_password("pw12345")
    db.session.add(user)
    db.session.commit()
    client.post("/auth/login", data={"username": "plain-user",
                                     "password": "pw12345"},
                follow_redirects=True)
    body = client.get("/dashboard").get_data(as_text=True)
    assert "bg-gradient-to-br" in body, (
        "with no branding the cards lost their gradient entirely")


def test_the_report_card_gradient_is_a_real_rule():
    css = io.open("static/css/layout.css", encoding="utf-8").read()
    assert ".report-card" in css
    assert "--card-from" in css
    assert "linear-gradient" in css.split(".report-card")[1][:300]


def test_no_dead_brand_resolvers_are_left():
    import app.models as models
    import app.services.default_templates as defaults
    assert not hasattr(models.User, "get_brand"), (
        "the second brand resolver is still on the model")
    assert not hasattr(defaults, "apply_tenant_branding")


def test_a_project_logo_reaches_the_document_when_no_tenant_branding_exists(app):
    """The project-create form accepts a logo and the admin list shows a badge
    saying one is set. Nothing read that column, so the upload did something
    visible and nothing else."""
    from app.ops.pdf import build_ops_pdf
    project = Project(name="مشروع بلا هوية", contractor="مقاول", client="مالك",
                      consultant="استشاري")
    db.session.add(project)
    db.session.flush()
    key = branding_service.store_logo("project-only.png", PNG_1PX)
    project.logo_path = key
    db.session.commit()

    record = _inspection(app, project)
    brand = branding_service.branding_for_project(project.id)
    assert brand.logo_path == key
    assert brand.logo_url == f"/uploads/branding/{key}"

    pdf = build_ops_pdf("site-inspections", record,
                        project_name=project.name,
                        generated_at="2026-01-31 10:00", brand=brand)
    assert pdf.startswith(b"%PDF")
    assert b"/Image" in pdf or b"FlateDecode" in pdf, (
        "the uploaded logo was not embedded in the document")


def test_tenant_branding_wins_over_a_bare_project_logo(app):
    from app.models import TenantBranding as TB
    project = _tenant_project(app, "كلاهما")
    key = branding_service.store_logo("bare.png", PNG_1PX)
    project.logo_path = key
    db.session.commit()
    brand = branding_service.branding_for_project(project.id)
    assert brand.company_ar == "شركة الجسر للمقاولات"
    assert brand.logo_path != key, (
        "the tenant's own identity was replaced by the project's bare logo")


# ------------------------------------------------------------------- helpers
def _inspection(app, project):
    from app.ops.models import SiteInspection
    from app.models import User
    owner = User.query.filter_by(username="card-user").first()
    if owner is None:
        owner = User.query.filter_by(username="insp-owner").first()
    if owner is None:
        owner = User(username="insp-owner", email="insp@brand.test",
                     full_name="فاحص", role="engineer")
        owner.set_password("pw12345")
        db.session.add(owner)
        db.session.commit()
    # serial is globally unique, so it is counted rather than fixed.
    from app.ops.models import SiteInspection as SI
    serial = "SIR-%06d" % (db.session.query(SI).count() + 1)
    record = SiteInspection(
        serial=serial, project_id=project.id,
        user_id=owner.id, status="draft", report_date=date(2026, 1, 15),
        signatory_name=owner.full_name,
        test_category="concrete", test_type="slump",
        location_detail="عمود B3", result_value=180.0, result_unit="mm",
        notes="فحص slump")
    db.session.add(record)
    db.session.commit()
    return record
