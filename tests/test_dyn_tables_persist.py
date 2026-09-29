"""Regression: dynamic table line-items must persist from real HTML posts.

Guards against the critical data-loss bug where ImmutableMultiDict (a dict
subclass in Werkzeug) fell into the prefill-dict branch of
_extract_table_rows and every submitted table row was silently dropped.

The ESHS checklists carry a single applied checkbox rather than the old
mutually-exclusive done/not_done pair, so there is no contradiction left to
reject — what must still hold is that a value arriving under a column the
table does not have is refused loudly instead of being dropped.
"""
from tests.conftest import login_as


def test_table_rows_persist(client, app):
    login_as(client, "t_admin")
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "Rows Persist",
        "report_date": "2026-09-24",
        "f_waste_mgmt_esha__0__action": "فرز النفايات حسب النوع",
        "f_waste_mgmt_esha__0__applied": "yes",
        "f_equipment_esha__0__eq_name": "خلاطة",
        "f_equipment_esha__0__hours_work": "8",
    }, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.models import ReportSubmission
        s = ReportSubmission.query.filter_by(
            project_name="Rows Persist").first()
        assert s is not None
        waste = s.data.get("waste_mgmt_esha")
        assert waste and waste[0]["action"] == "فرز النفايات حسب النوع"
        assert waste[0]["applied"] == "yes"
        eq = s.data.get("equipment_esha")
        assert eq and eq[0]["eq_name"] == "خلاطة"


def test_a_contradictory_flag_column_no_longer_exists(client, app):
    """done/not_done were removed with the checklist rework.

    A stale form posting both must not resurrect the old pair, and must not
    save a row that carries either: neither column belongs to the table any
    more, so both are values under unknown columns.
    """
    login_as(client, "t_admin")
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "Stale Flags",
        "report_date": "2026-09-24",
        "f_waste_mgmt_esha__0__action": "فرز النفايات حسب النوع",
        "f_waste_mgmt_esha__0__done": "yes",
        "f_waste_mgmt_esha__0__not_done": "yes",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "غير معروفة" in r.get_data(as_text=True)
    with app.app_context():
        from app.models import ReportSubmission
        assert ReportSubmission.query.filter_by(
            project_name="Stale Flags").first() is None


def test_edit_prefills_saved_data(client, app):
    """Edit form must show previously saved simple + table data."""
    from app.models import ReportSubmission
    login_as(client, "t_admin")
    client.post("/reports/dyn/new/daily", data={
        "project_name": "Prefill Check",
        "report_date": "2026-09-24",
        "location": "موقع الحفظ",
        "f_eshs_desc_81": "وصف محفوظ للاختبار",
        "f_waste_mgmt_esha__0__action": "فرز النفايات حسب النوع",
        "f_waste_mgmt_esha__0__applied": "yes",
        "f_equipment_esha__0__eq_name": "خلاطة",
    }, follow_redirects=True)
    with app.app_context():
        s = ReportSubmission.query.filter_by(
            project_name="Prefill Check").first()
        assert s is not None
        sid = s.id
    html = client.get(f"/reports/dyn/{sid}/edit").get_data(as_text=True)
    for expected in ("وصف محفوظ للاختبار", "فرز النفايات حسب النوع",
                     "خلاطة", "موقع الحفظ"):
        assert expected in html


def test_edit_opens_sections_with_data(client, app):
    """Sections holding saved rows auto-open even past the first three."""
    from app.models import ReportSubmission
    login_as(client, "t_admin")
    client.post("/reports/dyn/new/daily", data={
        "project_name": "Open Check",
        "report_date": "2026-09-24",
        "f_waste_mgmt_esha__0__action": "فرز النفايات حسب النوع",
        "f_waste_mgmt_esha__0__applied": "yes",
    }, follow_redirects=True)
    with app.app_context():
        s = ReportSubmission.query.filter_by(
            project_name="Open Check").first()
        sid = s.id
    html = client.get(f"/reports/dyn/{sid}/edit").get_data(as_text=True)
    assert "فرز النفايات حسب النوع" in html
    idx = html.find("waste_mgmt_esha")
    assert idx != -1
    details_start = html.rfind("<details", 0, idx)
    tag = html[details_start:html.find(">", details_start) + 1]
    assert "open" in tag


def test_unknown_table_column_refuses_loudly(client, app):
    """Tripwire: values under unknown columns must block the save loudly,
    never be silently dropped."""
    from app.models import ReportSubmission
    login_as(client, "t_admin")
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "Tripwire Check",
        "report_date": "2026-09-24",
        "f_waste_mgmt_esha__0__action": "فرز النفايات حسب النوع",
        "f_waste_mgmt_esha__0__no_such_col": "قيمة دخيلة",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "غير معروفة" in r.get_data(as_text=True)
    with app.app_context():
        assert ReportSubmission.query.filter_by(
            project_name="Tripwire Check").first() is None


def test_an_action_outside_the_reference_list_is_refused(client, app):
    """The mitigations are a closed list, not free text.

    A dropdown that accepts anything is a text box, and the point of the
    rework was that a site retypes its own compliance actions every day.
    """
    from app.models import ReportSubmission
    login_as(client, "t_admin")
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "Off List",
        "report_date": "2026-09-24",
        "f_waste_mgmt_esha__0__action": "إجراء من وحي الخيال",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "قيمة غير مسموحة" in r.get_data(as_text=True)
    with app.app_context():
        assert ReportSubmission.query.filter_by(
            project_name="Off List").first() is None
