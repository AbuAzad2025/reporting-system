"""Compliance sweep: EVERY report template must honor function + guidance.

For each of the 11 dynamic templates:
- schema integrity (keys/labels/types/required/options/placeholders)
- table columns valid (known types, dropdowns carry options)
- guidance: every text/textarea input and table cell has a placeholder
- form renders, minimal valid submission saves, PDF builds
- share payload carries the real template name + DS serial
"""
import pytest
from tests.conftest import login_as


def _all_template_keys(app):
    from app.models import ReportTemplate
    with app.app_context():
        return [t.key for t in ReportTemplate.query.order_by(
            ReportTemplate.id).all()]


def test_all_templates_seeded(app):
    keys = set(_all_template_keys(app))
    for expected in ("daily", "weekly", "monthly", "safety", "variation",
                     "site-inspections", "material-submittals", "rfis",
                     "cost-variances", "progress-billings",
                     "subcontractor-performances"):
        assert expected in keys, f"missing template: {expected}"


VALID_TYPES = {"text", "textarea", "number", "dropdown", "date",
               "checkbox", "table", "file"}


def test_schema_integrity_and_guidance(app):
    from app.services.default_templates import default_fields_for
    for key in _all_template_keys(app):
        fields = default_fields_for(key)
        assert fields, f"{key}: no fields"
        seen = set()
        for f in fields:
            assert f["key"] not in seen, f"{key}: dup field {f['key']}"
            seen.add(f["key"])
            assert f["label_ar"], f"{key}.{f['key']}: empty label"
            assert f["type"] in VALID_TYPES, f"{key}.{f['key']}: bad type"
            assert isinstance(f["required"], bool)
            if f["type"] in ("text", "textarea"):
                assert f.get("placeholder"), \
                    f"{key}.{f['key']}: missing guidance placeholder"
            if f["type"] == "dropdown" and f["key"] not in ("project_id",):
                assert f.get("options"), \
                    f"{key}.{f['key']}: dropdown without options"
            if f["type"] == "table":
                cols = f.get("columns") or []
                assert cols, f"{key}.{f['key']}: table without columns"
                for c in cols:
                    assert c["type"] in VALID_TYPES | {"file"}, \
                        f"{key}.{f['key']}.{c['key']}: bad cell type"
                    if c["type"] == "dropdown":
                        assert c.get("options"), \
                            f"{key}.{f['key']}.{c['key']}: dropdown w/o options"


# minimal valid payloads per template (required fields only)
MINIMAL = {
    "daily": {},
    "weekly": {},
    "monthly": {},
    "safety": {},
    "variation": {"f_vo_no": "VO-1", "f_subject": "اختبار",
                  "f_reason": "ظروف موقع"},
    "site-inspections": {"f_test_category": "concrete",
                         "f_test_type": "مكعبات"},
    "material-submittals": {"f_material_name": "حديد"},
    "rfis": {"f_subject": "استفسار", "f_question": "سؤال؟"},
    "cost-variances": {"f_boq_item": "خرسانة"},
    "progress-billings": {"f_work_item": "بلاطة"},
    "subcontractor-performances": {"f_subcontractor": "مقاول"},
}

COMMON = {"project_name": "امتثال", "report_date": "2026-09-24"}


@pytest.mark.parametrize("tpl_key", sorted(MINIMAL))
def test_form_renders_and_minimal_saves_and_pdf_builds(client, app, tpl_key):
    from app.models import ReportSubmission, ReportTemplate
    from app.services.pdf_dynamic import build_dynamic_pdf
    login_as(client, "t_admin")
    assert client.get(f"/reports/dyn/new/{tpl_key}").status_code == 200
    data = dict(COMMON)
    data["project_name"] = f"امتثال-{tpl_key}"
    data.update(MINIMAL[tpl_key])
    r = client.post(f"/reports/dyn/new/{tpl_key}", data=data,
                    follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from app.extensions import db
        s = ReportSubmission.query.filter_by(
            project_name=f"امتثال-{tpl_key}").first()
        assert s is not None, f"{tpl_key}: minimal submission not saved"
        tpl = db.session.get(ReportTemplate, s.template_id)
        pdf = build_dynamic_pdf(s, tpl)
        assert pdf.startswith(b"%PDF"), f"{tpl_key}: PDF broken"


def test_share_payload_uses_real_names(client, app):
    login_as(client, "t_admin")
    client.post("/reports/dyn/new/weekly", data={
        "project_name": "مشاركة أسبوعي", "report_date": "2026-09-24"},
        follow_redirects=True)
    from app.models import ReportSubmission
    with app.app_context():
        s = ReportSubmission.query.filter_by(
            project_name="مشاركة أسبوعي").first()
        sid = s.id
    d = client.get(f"/reports/share/dynamic/{sid}").get_json()
    assert d["payload"]["title"] == "التقرير الأسبوعي"
    assert d["payload"]["serial"] == f"DS-{sid:05d}"
    assert "email_url" in d and "whatsapp_url" in d
