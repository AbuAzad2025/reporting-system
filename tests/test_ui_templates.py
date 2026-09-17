"""WORKSTREAM 4b: every template + interface renders (no Jinja 500s).

Sweeps all GET pages as anonymous / engineer / owner, seeds one dynamic
and one legacy submission via DB, and asserts brand markers site-wide.
"""

from tests.conftest import login_as

BRAND = "أزاد"


def _html(client, url, user=None, expect=200):
    if user:
        login_as(client, user)
    r = client.get(url)
    assert r.status_code == expect, f"{user} GET {url}: {r.status_code}"
    return r.get_data(as_text=True)


# ---- public pages ----------------------------------------------------------

def test_public_pages_render(client):
    for url in ["/", "/auth/login", "/auth/register"]:
        text = _html(client, url)
        assert BRAND in text, f"{url} missing brand"


def test_login_form_fields(client):
    text = _html(client, "/auth/login")
    assert "username" in text and "password" in text


# ---- engineer pages ----------------------------------------------------------

def test_engineer_pages_render(client):
    for url in ["/dashboard", "/archive", "/profile",
                "/reports/dyn", "/reports/dyn/new/daily",
                "/reports/new/daily"]:
        text = _html(client, url, user="t_eng")
        assert BRAND in text, f"{url} missing brand"


def test_engineer_gated_pages_deny_cleanly(client):
    # no traceback: explicit 302/403, never 500
    assert _html(client, "/ops/batch", user="t_eng", expect=403) is not None
    assert _html(client, "/admin/", user="t_eng", expect=302) is not None
    assert _html(client, "/admin/analytics", user="t_eng",
                 expect=302) is not None


# ---- owner/admin pages ---------------------------------------------------------

def test_owner_admin_pages_render(client):
    from app.models import ReportTemplate
    with client.application.app_context():
        tpl_id = ReportTemplate.query.order_by(
            ReportTemplate.id).first().id
    for url in ["/admin/", "/admin/templates", "/admin/templates/new",
                f"/admin/templates/{tpl_id}/edit",
                f"/admin/templates/{tpl_id}/fields",
                "/admin/projects", "/admin/users", "/admin/analytics",
                "/ops/batch"]:
        text = _html(client, url, user="t_owner")
        assert BRAND in text, f"{url} missing brand"


# ---- seeded dynamic + legacy submissions -----------------------------------------

def _seed_submissions(client):
    from datetime import date
    from app.models import (ReportTemplate, ReportSubmission, Report,
                            Project, User)
    from app.extensions import db
    with client.application.app_context():
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        eng = User.query.filter_by(username="t_eng").first()
        pa = Project.query.filter_by(name="Alpha Tower").first()
        sub = ReportSubmission(
            template_id=tpl.id, project_id=pa.id,
            project_name=pa.name, report_date=date.today(),
            data={"note": "sweep"}, signatory_name=eng.full_name,
            user_id=eng.id)
        rep = Report(report_type="daily", project_name=pa.name,
                     report_date=date.today(), data={"note": "sweep"},
                     signatory_name=eng.full_name, user_id=eng.id)
        db.session.add_all([sub, rep])
        db.session.commit()
        return sub.id, rep.id


def test_dynamic_submission_pages_render(client):
    sub_id, _ = _seed_submissions(client)
    for url in [f"/reports/dyn/{sub_id}",
                f"/reports/dyn/{sub_id}/edit"]:
        text = _html(client, url, user="t_eng")
        assert BRAND in text, f"{url} missing brand"
    # share endpoint is a JSON API by design (links, not HTML)
    login_as(client, "t_eng")
    r = client.get(f"/reports/share/dynamic/{sub_id}")
    assert r.status_code == 200
    assert "email_url" in r.get_json()
    r = client.get(f"/reports/dyn/{sub_id}/pdf")
    assert r.status_code == 200 and r.data[:5] == b"%PDF-"


def test_legacy_report_pages_render(client):
    _, rep_id = _seed_submissions(client)
    for url in [f"/reports/{rep_id}", f"/reports/{rep_id}/edit"]:
        text = _html(client, url, user="t_eng")
        assert BRAND in text, f"{url} missing brand"
    login_as(client, "t_eng")
    r = client.get(f"/reports/share/legacy/{rep_id}")
    assert r.status_code == 200
    assert "email_url" in r.get_json()
    r = client.get(f"/reports/{rep_id}/pdf")
    assert r.status_code == 200 and r.data[:5] == b"%PDF-"
