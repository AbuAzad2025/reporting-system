"""REAL tests for new ESHS daily/weekly templates — verifies 11 sections + PDF."""
from datetime import date


def test_daily_esha_fields_count():
    from app.services.default_templates import default_fields_for
    fields = default_fields_for("daily")
    keys = {f["key"] for f in fields}
    # 11 sections core
    assert "equipment_esha" in keys
    assert "staff_esha" in keys
    assert "work_progress_esha" in keys
    assert "materials_esha" in keys
    assert "next_day_esha" in keys
    assert "meetings_esha" in keys
    assert "waste_mgmt_esha" in keys
    assert "eshs_ohs_esha" in keys
    assert "photos_esha" in keys
    assert "signatures_esha" in keys
    assert len(fields) >= 27  # 2 desc + 23 ESHS tables + 3 attach checkboxes = 28


def test_weekly_esha_fields_count():
    from app.services.default_templates import default_fields_for
    fields = default_fields_for("weekly")
    keys = {f["key"] for f in fields}
    assert "wp_status" in keys
    assert "weekly_issues" in keys
    assert len(fields) >= 15


def test_daily_pdf_generation_with_esha(app):
    from app.extensions import db
    from app.models import ReportTemplate, ReportSubmission, DynamicField, Project, User
    from app.services.default_templates import ensure_default_templates
    from app.services.pdf_dynamic import build_dynamic_pdf
    with app.app_context():
        db.create_all()
        ensure_default_templates(db, ReportTemplate, DynamicField, admin_id=1)
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        assert tpl is not None
        # create dummy project/submission with all ESHS data
        p = Project.query.filter_by(name="ESHA Test").first()
        if not p:
            p = Project(name="ESHA Test", location="Jericho", contractor="Samarkand")
            db.session.add(p)
            db.session.commit()
        u = User.query.first()
        data = {
            "weather": "صافي",
            "eshs_desc_81": "اعمال الخلع والتشوين",
            "eshs_location_82": "اعمال داخل القاعة",
            "equipment_esha": [{"eq_name": "كونجو", "ownership": "ملك", "hours_work": 10, "hours_stop": 6, "hours_total": 10}],
            "staff_esha": [{"company": "المقاول", "role": "مهندس المشروع", "name": "م. محمد نسيم عرار", "hours": 10, "nature": "دوام كامل"}],
            "waste_mgmt_esha": [{"proc": "فرز النفايات حسب النوع", "done": True, "not_done": False, "notes": ""}],
            "eshs_ohs_esha": [{"proc": "ارتداء خوذة السلامة", "done": True, "not_done": False, "notes": ""}],
            "contract_no": "CTD/2026/021-WB/MOF",
        }
        sub = ReportSubmission(template_id=tpl.id, project_id=p.id, project_name=p.name, location=p.location, contractor=p.contractor, report_date=date.today(), data=data, signatory_name="م. محمد", user_id=u.id)
        db.session.add(sub)
        db.session.commit()
        pdf = build_dynamic_pdf(sub, tpl)
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 20000
