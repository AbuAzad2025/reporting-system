"""Regression: dynamic table line-items must persist from real HTML posts.

Guards against the critical data-loss bug where ImmutableMultiDict (a dict
subclass in Werkzeug) fell into the prefill-dict branch of
_extract_table_rows and every submitted table row was silently dropped.
Also guards ESHS done/not_done mutual exclusivity.
"""
from tests.conftest import login_as


def test_table_rows_persist(client, app):
    login_as(client, "t_admin")
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "Rows Persist",
        "report_date": "2026-09-24",
        "f_waste_mgmt_esha__0__proc": "فرز النفايات",
        "f_waste_mgmt_esha__0__done": "yes",
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
        assert waste and waste[0]["proc"] == "فرز النفايات"
        assert waste[0]["done"] == "yes"
        eq = s.data.get("equipment_esha")
        assert eq and eq[0]["eq_name"] == "خلاطة"


def test_contradictory_checklist_rejected(client, app):
    login_as(client, "t_admin")
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "Contradiction Check",
        "report_date": "2026-09-24",
        "f_waste_mgmt_esha__0__proc": "فرز النفايات",
        "f_waste_mgmt_esha__0__done": "yes",
        "f_waste_mgmt_esha__0__not_done": "yes",
    }, follow_redirects=True)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "واحداً فقط" in html
    with app.app_context():
        from app.models import ReportSubmission
        assert ReportSubmission.query.filter_by(
            project_name="Contradiction Check").first() is None
