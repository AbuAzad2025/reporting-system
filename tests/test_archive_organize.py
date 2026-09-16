"""Report organization UX: sorting, project filter, pagination, compat.

Covers the /archive enhancements:
- backward-compatible defaults (date desc)
- sort by date/project/type + asc/desc + invalid fallback
- project filter dropdown
- pagination metadata + page clamping
- base.html scripts block (share JS active)
- dashboard organize shortcuts
"""
from datetime import date

import pytest

from tests.conftest import login_as
from app.models import Report, ReportSubmission, ReportTemplate, Project, User


def _get_ids(app):
    with app.app_context():
        eng = User.query.filter_by(username="t_eng").first()
        pa = Project.query.filter_by(name="Alpha Tower").first()
        pb = Project.query.filter_by(name="Beta Hospital").first()
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        if tpl is None:
            tpl = ReportTemplate(key="daily", name_ar="التقرير اليومي")
            from app.extensions import db
            db.session.add(tpl)
            db.session.flush()
        return eng.id, pa.id, pb.id, tpl.id, pa.name, pb.name


def _make_dyn(app, project_name, report_date, template_id=None, user_id=None):
    from app.extensions import db
    eng_id, pa_id, pb_id, tpl_id, _, _ = _get_ids(app)
    with app.app_context():
        eng = User.query.filter_by(username="t_eng").first()
        s = ReportSubmission(
            template_id=template_id or tpl_id,
            project_name=project_name, location="",
            contractor="", report_date=report_date, data={},
            signatory_name=eng.full_name, user_id=user_id or eng.id)
        db.session.add(s)
        db.session.commit()
        return s.id


def _make_legacy(app, project_name, report_date, report_type="daily"):
    from app.extensions import db
    with app.app_context():
        eng = User.query.filter_by(username="t_eng").first()
        r = Report(report_type=report_type, project_name=project_name,
                   location="", contractor="", report_date=report_date,
                   data={}, signatory_name=eng.full_name, user_id=eng.id)
        db.session.add(r)
        db.session.commit()
        return r.id


# ---------------------------------------------------------------- defaults

def test_archive_defaults_date_desc(eng_client, app):
    """Backward compat: default sort is newest-first by date."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 12))
    r = eng_client.get("/archive?src=dyn")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert html.index("2026-09-12") < html.index("2026-09-10")


def test_archive_invalid_sort_falls_back(eng_client, app):
    """Unknown sort/order values fall back to date desc safely."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 12))
    r = eng_client.get("/archive?src=dyn&sort=bogus&order=sideways")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert html.index("2026-09-12") < html.index("2026-09-10")


# ---------------------------------------------------------------- sorting

def test_archive_sort_project_asc(eng_client, app):
    """sort=project&order=asc lists Alpha before Beta."""
    _make_dyn(app, "Beta Hospital", date(2026, 9, 12))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    r = eng_client.get("/archive?src=dyn&sort=project&order=asc")
    assert r.status_code == 200
    cards = _results(r.get_data(as_text=True))
    assert cards.index("Alpha Tower") < cards.index("Beta Hospital")


def _results(html: str) -> str:
    """Return only the results section (after filter form/dropdowns)."""
    marker = '<div class="mt-3 space-y-2">'
    return html.split(marker, 1)[1] if marker in html else html


def test_archive_sort_project_desc(eng_client, app):
    """sort=project&order=desc lists Beta before Alpha."""
    _make_dyn(app, "Beta Hospital", date(2026, 9, 12))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    r = eng_client.get("/archive?src=dyn&sort=project&order=desc")
    assert r.status_code == 200
    cards = _results(r.get_data(as_text=True))
    assert cards.index("Beta Hospital") < cards.index("Alpha Tower")


def test_archive_sort_date_asc(eng_client, app):
    """sort=date&order=asc lists oldest first."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 12))
    r = eng_client.get("/archive?src=dyn&sort=date&order=asc")
    html = r.get_data(as_text=True)
    assert html.index("2026-09-10") < html.index("2026-09-12")


def test_archive_legacy_sort_type(eng_client, app):
    """Legacy sort=type groups by report_type alphabetically."""
    _make_legacy(app, "Alpha Tower", date(2026, 9, 12), "weekly")
    _make_legacy(app, "Alpha Tower", date(2026, 9, 10), "daily")
    r = eng_client.get("/archive?src=legacy&sort=type&order=asc")
    assert r.status_code == 200
    cards = _results(r.get_data(as_text=True))
    assert "التقرير اليومي" in cards and "التقرير الأسبوعي" in cards
    assert cards.index("التقرير اليومي") < cards.index("التقرير الأسبوعي")


# ---------------------------------------------------------------- project filter

def test_archive_project_filter(eng_client, app):
    """project=<id> shows only that project's reports."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    _make_dyn(app, "Beta Hospital", date(2026, 9, 11))
    _, pa_id, _, _, _, _ = _get_ids(app)
    r = eng_client.get(f"/archive?src=dyn&project={pa_id}")
    html = r.get_data(as_text=True)
    assert "Alpha Tower" in html
    assert "Beta Hospital" not in html


def test_archive_project_dropdown_lists_projects(eng_client):
    """Filter dropdown renders for users with project memberships."""
    login_as(eng_client, "t_admin")
    r = eng_client.get("/archive?src=dyn")
    html = r.get_data(as_text=True)
    assert 'name="project"' in html
    assert "Alpha Tower" in html


def test_archive_unknown_project_shows_all(eng_client, app):
    """Unknown project id is ignored (shows everything)."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    r = eng_client.get("/archive?src=dyn&project=999999")
    assert r.status_code == 200
    assert "Alpha Tower" in r.get_data(as_text=True)


# ---------------------------------------------------------------- pagination

def test_archive_pagination(eng_client, app):
    """per_page + page slice results with correct metadata."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 11))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 12))
    r1 = eng_client.get("/archive?src=dyn&per_page=2&page=1")
    h1 = r1.get_data(as_text=True)
    assert "2026-09-12" in h1 and "2026-09-11" in h1
    assert "2026-09-10" not in h1
    assert "صفحة 1 من 2" in h1
    r2 = eng_client.get("/archive?src=dyn&per_page=2&page=2")
    h2 = r2.get_data(as_text=True)
    assert "2026-09-10" in h2
    assert "2026-09-12" not in h2
    assert "صفحة 2 من 2" in h2


def test_archive_page_clamped(eng_client, app):
    """Out-of-range page clamps to last page instead of empty crash."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    r = eng_client.get("/archive?src=dyn&per_page=10&page=99")
    assert r.status_code == 200
    assert "Alpha Tower" in r.get_data(as_text=True)


def test_archive_per_page_bounded(eng_client, app):
    """per_page is clamped to 1..100."""
    r = eng_client.get("/archive?src=dyn&per_page=9999")
    assert r.status_code == 200
    r = eng_client.get("/archive?src=dyn&per_page=0")
    assert r.status_code == 200


def test_archive_filters_preserved_across_pages(eng_client, app):
    """Pagination links keep active filters (sort/project/search)."""
    _make_dyn(app, "Beta Hospital", date(2026, 9, 11))
    _make_dyn(app, "Beta Hospital", date(2026, 9, 12))
    r = eng_client.get("/archive?src=dyn&sort=project&per_page=1&page=1")
    html = r.get_data(as_text=True)
    assert "sort=project" in html
    assert "page=2" in html


# ---------------------------------------------------------------- compat & UX

def test_archive_summary_bar(eng_client, app):
    """Summary bar shows total count and active sort."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    _make_dyn(app, "Alpha Tower", date(2026, 9, 11))
    r = eng_client.get("/archive?src=dyn")
    html = r.get_data(as_text=True)
    assert "الإجمالي:" in html
    assert "مرتب حسب" in html


def test_archive_reset_link(eng_client):
    """Reset link returns to unfiltered archive."""
    r = eng_client.get("/archive?src=dyn&q=test&sort=project")
    html = r.get_data(as_text=True)
    assert "إعادة ضبط" in html
    assert "/archive?src=dyn" in html


def test_archive_serial_badges(eng_client, app):
    """Cards show serial badges (DS-/RPT-)."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    r = eng_client.get("/archive?src=dyn")
    assert "DS-" in r.get_data(as_text=True)


def test_base_renders_scripts_block(eng_client):
    """base.html renders block scripts (share JS is active)."""
    r = eng_client.get("/archive?src=dyn")
    html = r.get_data(as_text=True)
    assert "shareArchive" in html


def test_dashboard_organize_shortcuts(eng_client):
    """Dashboard has organized archive shortcuts."""
    r = eng_client.get("/dashboard")
    html = r.get_data(as_text=True)
    assert "تصفح الأرشيف مصنفاً" in html
    assert "sort=project" in html
    assert "عرض كل التقارير في الأرشيف" in html


def test_dashboard_serial_badges(eng_client, app):
    """Dashboard recent list shows serial badges."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    r = eng_client.get("/dashboard")
    assert "DS-" in r.get_data(as_text=True)


def test_archive_combined_search_and_sort(eng_client, app):
    """Search + sort work together."""
    _make_dyn(app, "Alpha Tower", date(2026, 9, 10))
    _make_dyn(app, "Beta Hospital", date(2026, 9, 12))
    r = eng_client.get("/archive?src=dyn&q=Beta&sort=date&order=desc")
    cards = _results(r.get_data(as_text=True))
    assert "Beta Hospital" in cards
    assert "Alpha Tower" not in cards
