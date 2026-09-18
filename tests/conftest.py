"""Shared fixtures: isolated file-DB app, tiered users, two tenant projects.

Tenant map (fail-closed world):
  * Project A «Alpha Tower»   — engineer + safety are members
  * Project B «Beta Hospital» — engineer2 is the only field member
  * owner(superadmin)/admin   — platform managers (global bypass)
"""
import os

import pytest

from config import Config


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "pytest-secret"
    # resolved per-test in the fixture (tmp file); placeholder only
    SQLALCHEMY_DATABASE_URI = "sqlite://"


#: Optional PostgreSQL run:
#:   set TEST_DATABASE_URL=postgresql://postgres:123@localhost:5432/azadexa_test
#:   python -m pytest -n0
#: Default (unset) stays on isolated per-test SQLite files. PG mode rebuilds
#: the shared test schema per test, so it must run single-worker (-n0).
PG_TEST_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


@pytest.fixture()
def app(tmp_path):
    if PG_TEST_URL:
        TestConfig.SQLALCHEMY_DATABASE_URI = PG_TEST_URL
    else:
        TestConfig.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/t.db"
    from app import create_app
    from app.extensions import db
    from app.models import User, Project
    from app.ops.models import (ProjectMember, SiteInspection, MaterialSubmittal,
                                RFI, CostVariance, ProgressBilling,
                                SubcontractorPerformance, DailySiteReport,
                                VariationOrder, SafetyReport)

    app = create_app(TestConfig)
    # Isolate file storage per test: uploads (attachments/avatars) land in
    # tmp, never in the repo working tree.
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    with app.app_context():
        db.create_all()
        # Hermetic template seed: CI runs with AZADEXA_AUTO_CREATE=0, so
        # seed here explicitly — tests must not depend on boot seeding.
        from app.models import ReportTemplate, DynamicField
        from app.services.default_templates import ensure_default_templates
        ensure_default_templates(db, ReportTemplate, DynamicField)

        def user(username, role, full):
            u = User(username=username, email=f"{username}@t.com",
                     full_name=full, role=role)
            u.set_password("pw12345")
            db.session.add(u)
            return u

        user("t_owner", "superadmin", "مالك اختبار تجريبي عام")
        admin = user("t_admin", "admin", "مدير اختبار تجريبي عام")
        pm = user("t_pm", "project_manager", "مدير مشروع اختبار عام")
        eng = user("t_eng", "site_engineer", "مهندس اختبار تجريبي عام")
        eng2 = user("t_eng2", "site_engineer", "مهندس ثان اختبار تجريبي")
        safety = user("t_safety", "safety_officer", "مسؤول سلامة اختبار عام")
        db.session.flush()

        pa = Project(name="Alpha Tower", location="Riyadh",
                     contractor="Alpha Main")
        pb = Project(name="Beta Hospital", location="Jeddah",
                     contractor="Beta Main")
        db.session.add_all([pa, pb])
        db.session.flush()

        db.session.add_all([
            ProjectMember(user_id=eng.id, project_id=pa.id),
            ProjectMember(user_id=safety.id, project_id=pa.id),
            ProjectMember(user_id=pm.id, project_id=pa.id,
                          role_in_project="owner"),
            ProjectMember(user_id=eng2.id, project_id=pb.id),
        ])

        def mk(model, serial, project, author, **kw):
            rec = model(serial=serial, project_id=project.id,
                        user_id=author.id,
                        signatory_name=author.full_name, **kw)
            db.session.add(rec)
            return rec

        mk(SiteInspection, "SIR-000001", pa, eng,
           test_category="concrete", test_type="cube 7d",
           result_value=28.0, acceptance_min=25.0, verdict="pass")
        mk(MaterialSubmittal, "MSR-000001", pa, eng,
           material_name="rebar", quantity=40, unit="ton")
        mk(RFI, "RFI-000001", pa, eng, subject="clash",
           question="duct vs beam?", ball_in_court="consultant")
        mk(CostVariance, "CVR-000001", pa, eng, boq_item="concrete",
           budgeted_qty=100, budgeted_rate=300,
           actual_qty=110, actual_rate=310)
        mk(CostVariance, "CVR-000002", pb, eng2, boq_item="blockwork",
           budgeted_qty=50, budgeted_rate=100,
           actual_qty=55, actual_rate=105)
        mk(ProgressBilling, "PBR-000001", pa, eng, work_item="slab",
           qty_completed=10, rate=1000, retention_pct=10.0,
           previously_certified=5000, status="approved",
           reviewed_by_id=admin.id)
        mk(SubcontractorPerformance, "SPR-000001", pa, eng,
           subcontractor="ACME Electric", quality_score=90,
           schedule_score=80, safety_score=70, compliance_score=85)
        mk(DailySiteReport, "DSR-000001", pa, eng, weather="مشمس",
           works_executed="صب أعمدة", engineers_count=2,
           technicians_count=3, labor_count=28, day_progress_pct=3.0)
        mk(VariationOrder, "VOR-000001", pa, eng, title="تعميق الأساسات",
           category="ظروف موقع", description="زيادة العمق 60 سم",
           cost_impact=54850, time_impact_days=6)
        mk(SafetyReport, "HSR-000001", pa, eng, area="الدور الثالث",
           hazard="غياب حواجز", risk_level="مرتفع")
        db.session.commit()
    yield app
    if PG_TEST_URL:  # leave no residue in the shared PG test database
        with app.app_context():
            db.session.remove()
            db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login_as(client, username, password="pw12345"):
    # reset the session first: the app ignores login while authenticated.
    client.get("/auth/logout")
    return client.post("/auth/login",
                       data={"username": username, "password": password},
                       follow_redirects=False)


@pytest.fixture()
def eng_client(client):
    login_as(client, "t_eng")
    return client
