"""Azadexa seed — tiers, projects, memberships, dynamic templates + samples.

Run:  python seed.py
Login: owner/owner123 | admin/admin123 | engineer/site123 | safety/safe123

Seeds the nine operational modules end to end:
  1. Site Inspection & Testing (concrete/soil/MEP + pour permits)
  2. Material Submittal & Inspection Log (consultant A/B/C/D actions)
  3. RFI Log (contractual cost/time impact)
  4. Cost Variance & Re-estimation (currency + VO linkage)
  5. Progress Billing & Cash Flow (measurement traceability)
  6. Subcontractor Performance & Payment (penalties + recommendation)
  7. Daily Site Diary (weather/manpower/plant/delays)
  8. Variation Orders (cost + time impact + recommendation)
  9. HSE Safety Reports (hazards, corrective actions, statistics)
"""
from datetime import date, timedelta
from app import create_app
from app.extensions import db
from app.models import User, Project, ReportTemplate, DynamicField, ReportSubmission
from app.ops import models as OPS
from app.ops.models import ProjectMember, OPS_MODULES
from app.services.default_templates import ensure_default_templates

app = create_app()
with app.app_context():
    db.create_all()

    def ensure_user(username, email, full, role, pw):
        u = User.query.filter_by(username=username).first()
        if not u:
            u = User(username=username, email=email, full_name=full, role=role,
                     company="شركة أزاد للأنظمة الذكية")
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
        return u

    owner = ensure_user("owner", "owner@platform.com", "مالك المنصة الرئيسي العام",
                        "superadmin", "owner123")
    admin = ensure_user("admin", "admin@site.com", "محمد أحمد علي حسن",
                        "admin", "admin123")
    eng = ensure_user("engineer", "eng@site.com", "خالد سعيد محمود عبدالله",
                      "site_engineer", "site123")
    safety = ensure_user("safety", "safety@site.com", "سارة علي محمد حسن",
                         "safety_officer", "safe123")
    # second engineer on a second project (tenant-isolation coverage)
    eng2 = ensure_user("engineer2", "eng2@site.com", "عمر خالد سعيد الحربي",
                       "site_engineer", "site123")

    ensure_default_templates(db, ReportTemplate, DynamicField, admin_id=owner.id)

    def ensure_project(name, **kw):
        p = Project.query.filter_by(name=name).first()
        if not p:
            p = Project(name=name, **kw)
            db.session.add(p)
            db.session.commit()
        return p

    proj = ensure_project("مشروع برج النخيل السكني",
                          location="الرياض — حي النرجس",
                          contractor="المقاول الرئيسي",
                          client="شركة التطوير العقاري")
    proj_b = ensure_project("مشروع مستشفى المدينة",
                            location="جدة — حي الروضة",
                            contractor="مقاول المستشفى",
                            client="وزارة الصحة")

    # ---- tenant grants (managers bypass via global role; field staff need rows)
    for u, p in ((eng, proj), (safety, proj), (eng2, proj_b)):
        if not ProjectMember.query.filter_by(user_id=u.id,
                                             project_id=p.id).first():
            db.session.add(ProjectMember(user_id=u.id, project_id=p.id))
    db.session.commit()

    # ---- generic dynamic-template samples (archive/PDF demo, unchanged)
    for i, tpl in enumerate(ReportTemplate.query.filter_by(is_active=True)
                            .filter(~ReportTemplate.key.in_(
                                ["site-inspections", "material-submittals",
                                 "rfis", "cost-variances", "progress-billings",
                                 "subcontractor-performances"])).all()):
        exists = ReportSubmission.query.filter_by(
            template_id=tpl.id, project_name=proj.name,
            report_date=date.today() - timedelta(days=i)).first()
        if not exists:
            data = {}
            for f in tpl.ordered_fields:
                if f.field_type == "table":
                    cols = f.sub_columns() if hasattr(f, "sub_columns") else []
                    row = {}
                    for c in cols:
                        if c["type"] == "dropdown" and c["options"]:
                            row[c["key"]] = c["options"][0]
                        elif c["type"] == "number":
                            row[c["key"]] = "3"
                        elif c["type"] == "date":
                            row[c["key"]] = str(date.today() - timedelta(days=i))
                        else:
                            row[c["key"]] = f"بيان — {c['label_ar']}"
                    data[f.field_key] = [row] if row else []
                elif f.field_type == "dropdown" and f.options_list():
                    data[f.field_key] = f.options_list()[0]
                elif f.field_type == "number":
                    data[f.field_key] = "45"
                elif f.field_type == "checkbox":
                    data[f.field_key] = "yes"
                else:
                    data[f.field_key] = f"بيانات تجريبية — {f.label_ar}"
            db.session.add(ReportSubmission(
                template_id=tpl.id, project_id=proj.id, project_name=proj.name,
                location=proj.location, contractor=proj.contractor,
                report_date=date.today() - timedelta(days=i), data=data,
                signatory_name=eng.full_name, user_id=eng.id))
    db.session.commit()

    # ============================================================ OPS SEED
    D = date.today()
    D2 = D - timedelta(days=4)  # second-tenant window (Beta Hospital)

    def add_if_missing(model, prefix, author=None, **kw):
        author = author or eng
        status = kw.pop("status", "pending")
        serial = OPS.next_serial(prefix, model)
        rec = model(serial=serial, status=status,
                    signatory_name=author.full_name, user_id=author.id, **kw)
        db.session.add(rec)
        db.session.flush()
        return rec

    # 1) Site inspections — one per test category
    if OPS.SiteInspection.query.count() == 0:
        add_if_missing(OPS.SiteInspection, "SIR", project_id=proj.id,
                       report_date=D, test_category="concrete",
                       test_type="مكعبات خرسانة 7 أيام",
                       location_detail="الدور الثالث — محور C",
                       spec_reference="ACI 318 / المخطط S-101",
                       result_value=28.5, result_unit="MPa",
                       acceptance_min=25.0, acceptance_max=None,
                       lab_name="مختبر الجودة المركزي", verdict="pass",
                       element="أعمدة الدور الثالث", axes="C-D / 3-4",
                       concrete_class="C30/37", slump=75.0,
                       cube_ids="C-231 حتى C-236",
                       pour_permit_ref="PP-2026-118",
                       witness="مقاول + استشاري",
                       standard_code="ACI 318-19",
                       follow_up="متابعة نتائج مكعبات 28 يوم",
                       attachments=6)
        add_if_missing(OPS.SiteInspection, "SIR", project_id=proj.id,
                       report_date=D - timedelta(days=1),
                       test_category="soil", test_type="اختبار الدمك الحقلي",
                       location_detail="أساسات البرج — طبقة 2",
                       spec_reference="ASTM D1556",
                       result_value=96.0, result_unit="%",
                       acceptance_min=95.0, acceptance_max=100.0,
                       lab_name="مختبر التربة", verdict="pass")
        add_if_missing(OPS.SiteInspection, "SIR", project_id=proj.id,
                       report_date=D - timedelta(days=2),
                       test_category="mep", test_type="اختبار ضغط مواسير التغذية",
                       location_detail="الدور الثاني — حمامات",
                       spec_reference="IPC 312 / المخطط P-201",
                       result_value=9.0, result_unit="bar",
                       acceptance_min=10.0, acceptance_max=None,
                       lab_name="فريق الكهروميكانيكا", verdict="fail",
                       notes="تسرب عند الوصلة J-14 — أعيد الاختبار بعد الإصلاح")

    # 2) Material submittals
    if OPS.MaterialSubmittal.query.count() == 0:
        add_if_missing(OPS.MaterialSubmittal, "MSR", project_id=proj.id,
                       report_date=D, material_name="حديد تسليح عالي المقاومة",
                       spec_section="03200", submittal_no="SUB-2026-041",
                       revision="R1", supplier="شركة الحديد الوطنية",
                       manufacturer="حديد سابك", quantity=40, unit="طن",
                       sample_location="مخزن الموقع",
                       origin_country="السعودية",
                       certificates="ISO 6935-2 + شهادة منشأ + اختبار شد",
                       test_report_ref="LAB-2026-1180",
                       consultant_action="B",
                       resubmit_due=D + timedelta(days=7))
        add_if_missing(OPS.MaterialSubmittal, "MSR", project_id=proj.id,
                       report_date=D - timedelta(days=3),
                       material_name="خلطة خرسانية C40",
                       spec_section="03300", submittal_no="SUB-2026-039",
                       revision="R0", supplier="الخرسانة الجاهزة المتحدة",
                       quantity=1200, unit="م³")

    # 3) RFI log
    if OPS.RFI.query.count() == 0:
        add_if_missing(OPS.RFI, "RFI", project_id=proj.id, report_date=D,
                       subject="تعارض بين مسار التكييف والجسر العلوي",
                       discipline="mep", question="مسار الدكت يتعارض مع الجسر "
                       "B-7 عند المحور D — يلزم توضيح الارتفاع الصافي المعتمد.",
                       drawing_ref="M-301 / S-104", ball_in_court="consultant",
                       reply_due=D + timedelta(days=3), priority="high",
                       spec_ref="23000-HVAC", cost_impact="pending",
                       delay_days=2, response_action="اجتماع تنسيق")
        add_if_missing(OPS.RFI, "RFI", project_id=proj.id,
                       report_date=D - timedelta(days=6),
                       subject="اعتماد بديل بلاط الواجهة",
                       discipline="architectural",
                       question="المورّد المعتمد توقف عن الإنتاج — هل البديل "
                       "المرفق (عينة S-88) مقبول؟",
                       drawing_ref="A-501", ball_in_court="client",
                       reply_due=D - timedelta(days=1),
                       date_replied=D - timedelta(days=1),
                       reply_summary="اعتمد المالك البديل مع خصم 2% من البند.",
                       priority="normal", status="approved",
                       reviewed_by_id=admin.id)

    # 4) Cost variance & re-estimation
    if OPS.CostVariance.query.count() == 0:
        add_if_missing(OPS.CostVariance, "CVR", project_id=proj.id,
                       report_date=D, boq_item="خرسانة مسلحة للأساسات",
                       boq_ref="BOQ-03.02", unit="م³",
                       budgeted_qty=1200, budgeted_rate=320,
                       actual_qty=1310, actual_rate=335,
                       reestimated_qty=1350, reestimated_rate=335,
                       reason="زيادة أعماق التأسيس حسب تقرير التربة النهائي",
                       corrective_action="اعتماد أمر تغيير VO-11 ومراجعة الكميات",
                       currency="ILS", vo_ref="VO-11",
                       schedule_impact_days=6)
        add_if_missing(OPS.CostVariance, "CVR", project_id=proj.id,
                       report_date=D - timedelta(days=9),
                       boq_item="أعمال المباني — بلوك أسمنتي",
                       boq_ref="BOQ-04.01", unit="م²",
                       budgeted_qty=8500, budgeted_rate=95,
                       actual_qty=8300, actual_rate=92,
                       reason="تحسين الإنتاجية + خصم توريد")

    # 5) Progress billing & cash flow (IPC)
    if OPS.ProgressBilling.query.count() == 0:
        add_if_missing(OPS.ProgressBilling, "PBR", project_id=proj.id,
                       report_date=D, cert_no="IPC-08",
                       period_from=D - timedelta(days=30), period_to=D,
                       work_item="الهيكل الخرساني — الدور الثالث",
                       qty_completed=420, rate=1450, retention_pct=10.0,
                       previously_certified=2850000,
                       notes="شامل اختبارات المكعبات المعتمدة",
                       boq_ref="BOQ-05.01", measurement_ref="H-08",
                       progress_pct=62.5)
        add_if_missing(OPS.ProgressBilling, "PBR", project_id=proj.id,
                       report_date=D - timedelta(days=30), cert_no="IPC-07",
                       period_from=D - timedelta(days=60),
                       period_to=D - timedelta(days=30),
                       work_item="الهيكل الخرساني — الدور الثاني",
                       qty_completed=410, rate=1450, retention_pct=10.0,
                       previously_certified=2300000, status="approved",
                       reviewed_by_id=admin.id)

    # 6) Subcontractor performance & payment
    if OPS.SubcontractorPerformance.query.count() == 0:
        add_if_missing(OPS.SubcontractorPerformance, "SPR",
                       project_id=proj.id, report_date=D,
                       subcontractor="مؤسسة الكهرباء المتقدمة",
                       trade="كهرباء", period="2026-09",
                       quality_score=92, schedule_score=85,
                       safety_score=78, compliance_score=90,
                       recommended_payment=340000,
                       remarks="أداء ممتاز فنياً — يلزم تحسين التزام السلامة",
                       delay_days=3, penalty=0, incidents=0,
                       recommendation="استمرار")
        add_if_missing(OPS.SubcontractorPerformance, "SPR",
                       project_id=proj.id, report_date=D - timedelta(days=30),
                       subcontractor="شركة السباكة الحديثة",
                       trade="سباكة", period="2026-08",
                       quality_score=55, schedule_score=48,
                       safety_score=60, compliance_score=52,
                       recommended_payment=120000,
                       remarks="تأخر متكرر — إنذار أول + حجب 15% حتى التعويض")

    # 7) Daily site diary (دفتر الورشة اليومي — UNRWA daily practice)
    if OPS.DailySiteReport.query.count() == 0:
        add_if_missing(OPS.DailySiteReport, "DSR", project_id=proj.id,
                       report_date=D, weather="مشمس", temp_c=31.0,
                       work_hours=9.0, engineers_count=2,
                       technicians_count=3, labor_count=28,
                       equipment="رافعة برجية ×1 — خلاطة ×2 — هزاز ×3",
                       works_executed="صب أعمدة الدور الثالث (محاور C-D) — "
                       "استلام حديد بلاطة المحور E",
                       deliveries="خرسانة جاهزة C30 — 8 خلاطات (48 م³)",
                       visitors="زيارة استشاري المشروع 11:00 — اعتماد عينات الدهان",
                       delays="تأخر خلاطتين 45 دقيقة — ازدحام طريق الموقع",
                       safety_notes="التزام جيد بالخوذ — تنبيه على أحزمة الدور الثالث",
                       day_progress_pct=3.0,
                       next_plan="فك شدات الأعمدة — بدء نجارة بلاطة المحور E")
        add_if_missing(OPS.DailySiteReport, "DSR", author=eng2,
                       project_id=proj_b.id, report_date=D2, weather="غائم",
                       temp_c=27.0, work_hours=8.0, engineers_count=1,
                       technicians_count=2, labor_count=16,
                       equipment="حفارة ×1 — مدحلة ×1 — شاحنات ×3",
                       works_executed="أعمال الحفر للقطاع الشمالي — نقل ناتج الحفر",
                       day_progress_pct=2.0,
                       next_plan="استكمال الحفر — اختبار دمك الطبقة الأولى")

    # 8) Variation orders (قاعدة بيانات الأوامر التغييرية — الأشغال)
    if OPS.VariationOrder.query.count() == 0:
        add_if_missing(OPS.VariationOrder, "VOR", project_id=proj.id,
                       report_date=D, vo_no="VO-11",
                       title="تعميق أساسات البرج حسب تقرير التربة النهائي",
                       category="ظروف موقع", boq_ref="BOQ-03.02",
                       description="زيادة عمق التأسيس 60 سم لكامل مساحة البرج "
                       "مع فرشة نظافة إضافية.",
                       reason="تقرير التربة النهائي أوصى بمنسوب تأسيس أعمق",
                       cost_impact=54850, currency="ILS",
                       time_impact_days=6, recommendation="اعتماد",
                       attachments=4)
        add_if_missing(OPS.VariationOrder, "VOR", author=eng2,
                       project_id=proj_b.id, report_date=D2, vo_no="VO-03",
                       title="تكسير صخور القطاع الشمالي",
                       category="ظروف موقع", boq_ref="BOQ-02.01",
                       description="طبقة صخرية غير متوقعة بسماكة ~1.2 م — "
                       "تكسير ونقل للمقالع المعتمدة.",
                       reason="طبيعة التربة الفعلية تخالف تقرير الجسات الأولي",
                       cost_impact=32700, currency="ILS",
                       time_impact_days=4, recommendation="دراسة",
                       attachments=3)

    # 9) HSE safety reports (السلامة والصحة المهنية)
    if OPS.SafetyReport.query.count() == 0:
        add_if_missing(OPS.SafetyReport, "HSR", project_id=proj.id,
                       report_date=D, area="الدور الثالث — الواجهة الجنوبية",
                       inspection_type="سقالات",
                       hazard="غياب حواجز الحماية عن جزء من السقالة + "
                       "عاملان بدون أحزمة أمان",
                       risk_level="مرتفع",
                       corrective_action="إيقاف العمل على الواجهة حتى استكمال "
                       "الحواجز — توفير أحزمة وإنذار كتابي للمقاول",
                       responsible="مقاول", target_date=D + timedelta(days=1),
                       incidents_count=0, lost_time_injuries=0,
                       toolbox_talks=2, ppe_compliance=82.0)
        add_if_missing(OPS.SafetyReport, "HSR", author=eng2,
                       project_id=proj_b.id, report_date=D2,
                       area="منطقة الحفريات — القطاع الشمالي",
                       inspection_type="حفريات",
                       hazard="ميول الحفر شديدة قرب الطريق المؤقت — "
                       "يلزم تدعيم وحواجز تحذيرية",
                       risk_level="مرتفع",
                       corrective_action="تدعيم جوانب الحفر + شريط تحذيري "
                       "وإضاءة ليلية",
                       responsible="مقاول", target_date=D2 + timedelta(days=2),
                       incidents_count=0, lost_time_injuries=0,
                       toolbox_talks=1, ppe_compliance=90.0)

    # ---- Beta Hospital: one realistic row per module (second-tenant demo)
    if not OPS.SiteInspection.query.filter_by(project_id=proj_b.id).first():
        add_if_missing(OPS.SiteInspection, "SIR", author=eng2,
                       project_id=proj_b.id, report_date=D2,
                       test_category="concrete",
                       test_type="مكعبات خرسانة 28 يوم",
                       location_detail="مبنى العيادات — قاعدة C-3",
                       spec_reference="ACI 318 / المخطط S-201",
                       result_value=31.0, result_unit="MPa",
                       acceptance_min=28.0, acceptance_max=None,
                       lab_name="مختبر الجودة المركزي", verdict="pass")
    if not OPS.MaterialSubmittal.query.filter_by(project_id=proj_b.id).first():
        add_if_missing(OPS.MaterialSubmittal, "MSR", author=eng2,
                       project_id=proj_b.id, report_date=D2,
                       material_name="أسمنت بورتلاندي عادي",
                       spec_section="03300", submittal_no="SUB-H-2026-012",
                       revision="R0", supplier="شركة أسمنت المنطقة",
                       quantity=800, unit="طن",
                       sample_location="مخزن مستشفى المدينة")
    if not OPS.RFI.query.filter_by(project_id=proj_b.id).first():
        add_if_missing(OPS.RFI, "RFI", author=eng2, project_id=proj_b.id,
                       report_date=D2,
                       subject="منسوب التأسيس النهائي لمبنى الطوارئ",
                       discipline="civil",
                       question="تقرير التربة يوصي بتعميق 40 سم إضافية — "
                       "هل يُعتمد المنسوب الجديد قبل صب القواعد؟",
                       drawing_ref="S-210", ball_in_court="consultant",
                       reply_due=D2 + timedelta(days=2), priority="critical")
    if not OPS.CostVariance.query.filter_by(project_id=proj_b.id).first():
        add_if_missing(OPS.CostVariance, "CVR", author=eng2,
                       project_id=proj_b.id, report_date=D2,
                       boq_item="أعمال الحفر والردم", boq_ref="BOQ-02.01",
                       unit="م³", budgeted_qty=9500, budgeted_rate=38,
                       actual_qty=10200, actual_rate=41,
                       reason="تربة صخرية غير متوقعة في القطاع الشمالي",
                       corrective_action="أمر تغيير VO-03 + كسارة صخور")
    if not OPS.ProgressBilling.query.filter_by(project_id=proj_b.id).first():
        add_if_missing(OPS.ProgressBilling, "PBR", author=eng2,
                       project_id=proj_b.id, report_date=D2, cert_no="IPC-03",
                       period_from=D2 - timedelta(days=30), period_to=D2,
                       work_item="أعمال الأساسات — مبنى العيادات",
                       qty_completed=260, rate=1180, retention_pct=10.0,
                       previously_certified=940000,
                       notes="شامل اختبارات الدمك المعتمدة")
    if not OPS.SubcontractorPerformance.query.filter_by(
            project_id=proj_b.id).first():
        add_if_missing(OPS.SubcontractorPerformance, "SPR", author=eng2,
                       project_id=proj_b.id, report_date=D2,
                       subcontractor="شركة التكييف المركزي المتحدة",
                       trade="تكييف", period="2026-09",
                       quality_score=84, schedule_score=88,
                       safety_score=91, compliance_score=86,
                       recommended_payment=210000,
                       remarks="التزام جيد بالبرنامج والسلامة")

    db.session.commit()

    from app.ops.routes import KIND_MODEL
    counts = {kind: KIND_MODEL[kind].query.count() for kind in OPS_MODULES}
    print("Seed OK: owner/owner123 | admin/admin123 | "
          "engineer/site123 | safety/safe123 | engineer2/site123")
    print("Ops counts:", counts)
