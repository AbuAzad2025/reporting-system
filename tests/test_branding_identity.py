"""Brand identity: one resolver, one asset store, and the rules around them.

The tests here exist because the previous implementation had three resolvers
that disagreed with each other, and because an administrator editing branding
was told the change applied to every report when it applied to none.
"""
import io
import os

import pytest
from PIL import Image

from app.extensions import db
from app.models import Project, ReportTemplate, TenantBranding, User
from app.services import branding as branding_service


PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture(autouse=True)
def _app_context(app):
    # The shared `app` fixture yields outside its own context, so anything
    # touching current_app or db.session has to push one. Doing it here covers
    # every test in the file rather than only the ones that happened to fail.
    with app.app_context():
        yield


@pytest.fixture
def app_with_brand():
    project = Project(name="مشروع الهوية", location="غزة")
    db.session.add(project)
    db.session.commit()
    return project


# ------------------------------------------------------------------- colours
def test_a_colour_that_is_not_hex_is_refused():
    # The value reaches an inline <style> block, where autoescaping does not
    # apply. A CSS injection here would run for every user of the tenant.
    assert branding_service.normalise_hex("#1E3A5F", "#000000") == "#1e3a5f"
    assert branding_service.normalise_hex("red;} body{display:none",
                                          "#000000") == "#000000"
    assert branding_service.normalise_hex("", "#123456") == "#123456"
    assert branding_service.normalise_hex(None, "#123456") == "#123456"
    assert branding_service.normalise_hex("#fff", "#000000") == "#ffffff"
    assert branding_service.normalise_hex("url(javascript:alert(1))",
                                          "#000000") == "#000000"


# --------------------------------------------------------------------- logos
def test_svg_is_refused_because_it_is_a_program():
    with pytest.raises(branding_service.LogoRejected):
        branding_service.sniff_logo_format(SVG_BYTES)


def test_an_image_is_identified_by_its_bytes_not_its_name(app):
    # A .png extension on an SVG body must not be believed.
    with pytest.raises(branding_service.LogoRejected):
        branding_service.sniff_logo_format(SVG_BYTES)
    assert branding_service.sniff_logo_format(PNG_1PX) == "PNG"
    assert branding_service.sniff_logo_format(JPEG_BYTES) == "JPEG"


def test_a_logo_key_is_relative_so_the_database_outlives_the_machine():
    key = branding_service.store_logo("logo.png", PNG_1PX)
    assert not os.path.isabs(key), (
        "an absolute path in the database breaks on the next deploy")
    assert os.path.isfile(os.path.join(branding_service.asset_root(), key))
    assert branding_service.logo_url(key) == f"/uploads/branding/{key}"


def test_an_oversized_logo_is_refused():
    with pytest.raises(branding_service.LogoRejected):
        branding_service.store_logo("big.png",
                                     PNG_1PX + b"0" * (branding_service.MAX_LOGO_BYTES + 1))


def test_a_disk_that_cannot_be_written_is_a_rejection_not_a_crash(monkeypatch):
    """The caller handles one kind of failure, so there should be one kind.

    A full disk raised OSError out of store_logo and past the route's
    except LogoRejected, which is a 500 on the form that submitted the logo.
    """
    def refuse(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(branding_service.os, "makedirs", refuse)
    with pytest.raises(branding_service.LogoRejected):
        branding_service.store_logo("logo.png", PNG_1PX)


def test_a_logo_cannot_escape_its_directory():
    assert branding_service.logo_path("../../../etc/passwd") is None
    assert branding_service.logo_url("../secret.png") is not None
    assert branding_service.logo_url("") is None


def test_a_legacy_absolute_path_still_resolves():
    # Logos stored before the move are absolute. They must keep working until
    # they are re-uploaded, or every existing project loses its letterhead.
    key = branding_service.store_logo("old.png", PNG_1PX)
    absolute = os.path.join(branding_service.asset_root(), key)
    assert branding_service.logo_path(absolute) == absolute
    # ... but an absolute path is never handed to a browser as a URL.
    assert branding_service.logo_url(absolute) is None


def test_a_stored_logo_is_served_with_nosniff(client):
    key = branding_service.store_logo("served.png", PNG_1PX)
    response = client.get(f"/uploads/branding/{key}")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_asset_route_refuses_to_escape_the_directory(client):
    assert client.get("/uploads/branding/..%2f..%2fapp.py").status_code in (400, 404)


# ------------------------------------------------------------------ resolver
def test_the_header_and_the_footer_resolve_to_the_same_tenant(app, client, app_with_brand):
    """One identity per request, not one per region of the page.

    base.html used to read the brand by project membership while the footer
    read the newest row in the whole table, so a page could carry one company's
    logo above another company's name.
    """
    project = app_with_brand
    active = TenantBranding(project_id=project.id, company_name_ar="شركة الشمال",
                            company_name_en="North Co", is_active=True)
    db.session.add(active)
    db.session.commit()
    # A retired row for the same project. Two active rows is not a state the
    # UI can produce, but the resolver has to pick one deterministically rather
    # than whichever the database returned first.
    db.session.add(TenantBranding(project_id=project.id,
                                  company_name_ar="هوية قديمة", is_active=False))
    db.session.commit()

    user = _member(app, project)
    html = _render_dashboard(client, user)
    assert "شركة الشمال" in html, "the active identity did not reach the page"
    assert "هوية قديمة" not in html, "a retired identity was rendered"
    assert html.count("شركة الشمال") >= 2, (
        "the header and the footer resolved to different rows")


def test_falls_back_to_the_configuration_when_a_tenant_set_nothing(app, client, app_with_brand):
    html = _render_dashboard(client, _member(app, app_with_brand))
    assert app.config["COMPANY_NAME_AR"] in html


def test_a_tenant_colour_reaches_the_document_as_a_custom_property(app, client, app_with_brand):
    project = app_with_brand
    db.session.add(TenantBranding(project_id=project.id, is_active=True,
                                   primary_color="#112233",
                                   secondary_color="#445566"))
    db.session.commit()
    html = _render_dashboard(client, _member(app, project))
    assert "--brand-primary: #112233" in html
    assert "--brand-secondary: #445566" in html


def test_injected_css_never_reaches_the_style_block(app, client, app_with_brand):
    project = app_with_brand
    db.session.add(TenantBranding(
        project_id=project.id, is_active=True,
        primary_color="#000;} body{display:none} .x{color:red",
        secondary_color="#c9a227"))
    db.session.commit()
    html = _render_dashboard(client, _member(app, project))
    assert "body{display:none}" not in html
    assert "--brand-primary: #1e3a5f" in html


def test_a_tenant_without_a_logo_falls_back_to_the_platform_mark(app, app_with_brand):
    project = app_with_brand
    row = TenantBranding(project_id=project.id, is_active=True,
                         company_name_ar="بلا شعار")
    view = branding_service.BrandView(row, app.config)
    assert view.is_default_logo
    assert view.logo_url.endswith("azad-logo.png")
    assert view.company_ar == "بلا شعار"


def test_tenant_text_reaches_the_header_and_the_footer(app, client, app_with_brand):
    project = app_with_brand
    db.session.add(TenantBranding(
        project_id=project.id, is_active=True,
        custom_header_text_ar="ترويسة|своя",
        custom_footer_notes="ملاحظة الذيل",
        disclaimer_text="إخلاء المسؤولية"))
    db.session.commit()
    html = _render_dashboard(client, _member(app, project))
    assert "ترويسة|своя" in html
    assert "ملاحظة الذيل" in html
    assert "إخلاء المسؤولية" in html


# ----------------------------------------------------------------- the admin
def test_saving_branding_binds_it_to_the_project_not_the_template(app, client, app_with_brand):
    """The old route stored tpl.id in TenantBranding.project_id.

    Those are different identifiers, so the row landed on an unrelated project
    and the resolver - which looks up the projects a user belongs to - never
    found it. The admin page claimed the change applied to every report.
    """
    project = app_with_brand
    template = ReportTemplate(key="brand-daily", name_ar="يومي", is_active=True)
    db.session.add(template)
    db.session.commit()

    _login(client, _admin(app))

    response = client.post(
        "/admin/branding",
        data={"project_id": str(project.id), "company_name_ar": "شركة الجسر",
              "company_name_en": "Bridge Co", "primary_color": "#0a0b0c",
              "custom_footer_notes": "notes", "disclaimer_text": "disclaimer"},
        follow_redirects=True)
    assert response.status_code == 200

    row = TenantBranding.query.filter_by(project_id=project.id).first()
    assert row is not None, "branding was not saved against the chosen project"
    assert row.company_name_ar == "شركة الجسر"
    assert row.primary_color == "#0a0b0c"
    assert row.custom_footer_notes == "notes"
    assert row.disclaimer_text == "disclaimer"


def test_a_save_never_wipes_the_disclaimer(app, client, app_with_brand):
    """The form had no disclaimer field, so the handler wrote an empty string
    over whatever was there on every save."""
    project = app_with_brand
    db.session.add(TenantBranding(project_id=project.id, is_active=True,
                                  disclaimer_text="نص محفوظ"))
    db.session.commit()

    _login(client, _admin(app))
    template = ReportTemplate(key="brand-weekly", name_ar="أسبوعي", is_active=True)
    db.session.add(template)
    db.session.commit()

    client.post("/admin/branding",
                data={"project_id": str(project.id), "company_name_ar": "س",
                      "disclaimer_text": "نص محفوظ"},
                follow_redirects=True)

    row = TenantBranding.query.filter_by(project_id=project.id).first()
    assert row.disclaimer_text == "نص محفوظ"


def test_a_rejected_logo_does_not_abort_the_save(app, client, app_with_brand):
    project = app_with_brand
    template = ReportTemplate(key="brand-monthly", name_ar="شهري", is_active=True)
    db.session.add(template)
    db.session.commit()

    _login(client, _admin(app))
    client.post("/admin/branding",
                data={"project_id": str(project.id), "company_name_ar": "س",
                      "logo": (io.BytesIO(SVG_BYTES), "logo.svg")},
                follow_redirects=True)

    row = TenantBranding.query.filter_by(project_id=project.id).first()
    assert row.company_name_ar == "س"
    assert not row.logo_path, "an SVG must never be stored as a logo"


def test_a_png_upload_becomes_a_served_key(app, client, app_with_brand):
    project = app_with_brand
    template = ReportTemplate(key="brand-safety", name_ar="سلامة", is_active=True)
    db.session.add(template)
    db.session.commit()

    _login(client, _admin(app))
    client.post("/admin/branding",
                data={"project_id": str(project.id), "company_name_ar": "س",
                      "logo": (io.BytesIO(PNG_1PX), "logo.png")},
                follow_redirects=True)

    row = TenantBranding.query.filter_by(project_id=project.id).first()
    assert row.logo_path and not os.path.isabs(row.logo_path)
    assert client.get(f"/uploads/branding/{row.logo_path}").status_code == 200


# ------------------------------------------------------------------- helpers
def _member(app, project):
    from app.ops.models import ProjectMember
    user = User(username=f"member-{project.id}", role="engineer",
                full_name="عضو",
                email=f"member-{project.id}@branding.test")
    user.set_password("pw12345")
    db.session.add(user)
    db.session.commit()
    db.session.add(ProjectMember(project_id=project.id, user_id=user.id,
                                 role_in_project="member"))
    db.session.commit()
    return user


def _admin(app):
    user = User(username="brand-admin", role="admin",
                full_name="مدير",
                email="brand-admin@branding.test")
    user.set_password("pw12345")
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    client.post("/auth/login",
                data={"username": user.username, "password": "pw12345"},
                follow_redirects=True)


def _render_dashboard(client, user):
    _login(client, user)
    return client.get("/dashboard").get_data(as_text=True)
