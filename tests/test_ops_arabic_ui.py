"""Verify ops UI form uses Arabic labels (never raw English keys as text)."""
from tests.conftest import login_as


def test_ops_form_arabic_labels(client):
    login_as(client, "t_eng")
    html = client.get("/ops/ui/rfis/new").get_data(as_text=True)
    assert "الكرة في ملعب" in html
    assert "نص الاستفسار" in html
    assert "الموضوع" in html
    # raw keys must not appear as visible label text
    assert ">project_id<" not in html
    assert ">ball_in_court<" not in html
    assert ">test_category<" not in html
    # enums render as selects with allowed-values hint
    assert "القيم المسموحة" in html


def test_ops_validation_arabic(client):
    login_as(client, "t_eng")
    r = client.post("/ops/ui/rfis/new", data={
        "project_name": "",
        "report_date": "2026-09-24",
    }, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "«المشروع» حقل مطلوب" in html
    assert "الحقل project_id" not in html


def test_ops_detail_arabic(client, app):
    from app.ops.models import RFI
    login_as(client, "t_eng")
    with app.app_context():
        rec = RFI.query.filter_by(serial="RFI-000001").first()
        rid = rec.id
    html = client.get(f"/ops/ui/rfis/{rid}").get_data(as_text=True)
    assert "Alpha Tower" in html  # project name, not numeric id
    assert "الكرة في ملعب" in html
    assert ">ball_in_court<" not in html
    assert ">test_category<" not in html
    assert "user_id" not in html


def test_ops_list_names(client):
    login_as(client, "t_eng")
    html = client.get("/ops/ui/rfis").get_data(as_text=True)
    assert "Alpha Tower" in html
    assert "tenant-scoped" not in html
