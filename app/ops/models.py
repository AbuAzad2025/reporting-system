"""Azadexa operational modules — first-class construction & financial reports.

Nine production modules (each its own table, typed columns, serial numbers,
approval workflow) plus ProjectMember for tenant isolation:

  project_members            — user ↔ project access grants (tenant boundary)
  site_inspections           — concrete / soil / MEP tests (SIR-xxxxxx)
  material_submittals        — material submittal & inspection log (MSR-xxxxxx)
  rfis                       — request-for-information log (RFI-xxxxxx)
  cost_variances             — cost variance & re-estimation (CVR-xxxxxx)
  progress_billings          — progress billing & cash flow, IPC certs (PBR-xxxxxx)
  subcontractor_performances — subcontractor score & payment (SPR-xxxxxx)
  daily_reports              — site diary: weather/manpower/plant (DSR-xxxxxx)
  variation_orders           — contract change orders, cost+time impact (VOR-xxxxxx)
  safety_reports             — HSE inspections, hazards, incidents (HSR-xxxxxx)

Field content follows Palestinian MoPWH supervision practice (unified forms,
sample-approval committees, interim/final payment review, initial/final
handover) and the UNRWA/FMIS site-engineer remit (daily + weekly
technical/financial progress, measurements, variation orders, extension of
time, tests, shop/as-built drawings, HSE compliance, meeting minutes).

Tenant rule: every record belongs to exactly one project. Access is granted
by (a) platform-manager global roles, or (b) a ProjectMember row. No row is
ever visible without one of those — enforced in app/ops/isolation.py.
"""
from datetime import date, datetime
from sqlalchemy import func

from app.extensions import db

# ---------------------------------------------------------------- constants
#: approval workflow states shared by all nine modules.
#: Lifecycle: draft -> submitted -> approved (locked) | rejected -> draft.
#: 'pending' is the historic alias of 'submitted'; 'amended' marks a
#: superseded approved version (immutable trail, never deleted).
STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_PENDING = "pending"  # legacy alias of submitted
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_AMENDED = "amended"
STATUSES = (STATUS_DRAFT, STATUS_SUBMITTED, STATUS_PENDING, STATUS_APPROVED,
            STATUS_REJECTED, STATUS_AMENDED)
STATUS_AR = {"draft": "مسودة", "submitted": "قيد المراجعة",
             "pending": "قيد المراجعة", "approved": "معتمد / مغلق",
             "rejected": "مرفوض", "amended": "معدّل (نسخة تاريخية)"}

#: module registry: kind -> (Model name, serial prefix, Arabic title, English title)
OPS_MODULES = {
    "site-inspections": ("SiteInspection", "SIR", "تقرير فحص واختبار الموقع",
                         "Site Inspection & Testing Report"),
    "material-submittals": ("MaterialSubmittal", "MSR", "سجل اعتماد وفحص المواد",
                            "Material Submittal & Inspection Log"),
    "rfis": ("RFI", "RFI", "سجل طلبات الاستفسار",
             "RFI (Request for Information) Log"),
    "cost-variances": ("CostVariance", "CVR", "تقرير فروقات التكلفة وإعادة التقدير",
                       "Cost Variance & Re-estimation Report"),
    "progress-billings": ("ProgressBilling", "PBR", "تقرير المستخلصات والتدفق النقدي",
                          "Progress Billing & Cash Flow Report"),
    "subcontractor-performances": ("SubcontractorPerformance", "SPR",
                                   "تقرير أداء المقاولين والدفعات",
                                   "Subcontractor Performance & Payment Report"),
    "daily-reports": ("DailySiteReport", "DSR", "دفتر الورشة — التقرير اليومي",
                      "Daily Site Diary Report"),
    "variation-orders": ("VariationOrder", "VOR", "الأمر التغييري",
                         "Variation Order"),
    "safety-reports": ("SafetyReport", "HSR", "تقرير السلامة والصحة المهنية",
                       "HSE Safety Report"),
}

TEST_CATEGORIES = {
    "concrete": {"label_ar": "خرسانة", "label_en": "Concrete"},
    "soil": {"label_ar": "تربة", "label_en": "Soil"},
    "mep": {"label_ar": "ميكانيكا وكهرباء وسباكة", "label_en": "MEP"},
}
BALL_IN_COURT = {
    "contractor": {"label_ar": "المقاول", "label_en": "Contractor"},
    "consultant": {"label_ar": "الاستشاري", "label_en": "Consultant"},
    "client": {"label_ar": "المالك", "label_en": "Client"},
}
#: daily diary weather (UNRWA/FMIS daily progress practice)
WEATHER = {
    "مشمس": {"label_ar": "مشمس", "label_en": "Sunny"},
    "غائم": {"label_ar": "غائم", "label_en": "Cloudy"},
    "ماطر": {"label_ar": "ماطر", "label_en": "Rainy"},
    "عاصف": {"label_ar": "عاصف", "label_en": "Stormy"},
    "حر جداً": {"label_ar": "حر جداً", "label_en": "Very Hot"},
}
#: variation-order taxonomy (MoPWH change-order database practice)
VO_CATEGORIES = {
    "تغيير تصميم": {"label_ar": "تغيير تصميم", "label_en": "Design Change"},
    "ظروف موقع": {"label_ar": "ظروف موقع", "label_en": "Site Conditions"},
    "طلب المالك": {"label_ar": "طلب المالك", "label_en": "Owner Request"},
    "أعمال إضافية": {"label_ar": "أعمال إضافية", "label_en": "Additional Works"},
    "حذف أعمال": {"label_ar": "حذف أعمال", "label_en": "Work Deletion"},
    "تمديد زمني": {"label_ar": "تمديد زمني", "label_en": "Extension of Time"},
}
VO_RECOMMENDATIONS = {
    "دراسة": {"label_ar": "دراسة", "label_en": "Study"},
    "اعتماد": {"label_ar": "اعتماد", "label_en": "Approve"},
    " rejection": {"label_ar": "رفض", "label_en": "Reject"},
}
#: HSE taxonomy
RISK_LEVELS = {
    "مرتفع": {"label_ar": "مرتفع", "label_en": "High"},
    "متوسط": {"label_ar": "متوسط", "label_en": "Medium"},
    "منخفض": {"label_ar": "منخفض", "label_en": "Low"},
}
SAFETY_INSPECTION_TYPES = {
    "دوري": {"label_ar": "دوري", "label_en": "Routine"},
    "طارئ": {"label_ar": "طارئ", "label_en": "Emergency"},
    "معدات": {"label_ar": "معدات", "label_en": "Equipment"},
    "حفر": {"label_ar": "حفر", "label_en": "Excavation"},
    "كهرباء": {"label_ar": "كهرباء", "label_en": "Electrical"},
    "سقالات": {"label_ar": "سقالات", "label_en": "Scaffolding"},
    "رافعات": {"label_ar": "رافعات", "label_en": "Cranes"},
}
SAFETY_RESPONSIBLE = {
    "مقاول": {"label_ar": "مقاول", "label_en": "Contractor"},
    "مقاول باطن": {"label_ar": "مقاول باطن", "label_en": "Subcontractor"},
    "استشاري": {"label_ar": "استشاري", "label_en": "Consultant"},
    "مالك": {"label_ar": "مالك", "label_en": "Owner"},
}
#: consultant sample-action codes (A: approved, B: approved as noted,
#: C: revise & resubmit, D: rejected) — MoPWH sample-approval committees
CONSULTANT_ACTIONS = {
    "A": {"label_ar": "معتمد", "label_en": "Approved"},
    "B": {"label_ar": "معتمد مع ملاحظات", "label_en": "Approved as Noted"},
    "C": {"label_ar": "تعديل وإعادة التقديم", "label_en": "Revise & Resubmit"},
    "D": {"label_ar": "مرفض", "label_en": "Rejected"},
}
#: subcontractor overall recommendation
SUB_RECOMMENDATIONS = {
    "استمرار": {"label_ar": "استمرار", "label_en": "Continue"},
    "إنذار": {"label_ar": "إنذار", "label_en": "Warning"},
    "استبعاد": {"label_ar": "استبعاد", "label_en": "Exclude"},
}
#: equipment row status taxonomy for the DSR plant log
EQUIPMENT_STATUS = {
    "operating": {"label_ar": "تعمل", "label_en": "Operating"},
    "idle": {"label_ar": "غير نشط", "label_en": "Idle"},
    "down": {"label_ar": "متعطل", "label_en": "Down"},
    "maintenance": {"label_ar": "صيانة", "label_en": "Maintenance"},
}
#: dual-party feedback: supervision side (consultant/management) vs
#: execution side (contractor/site team). Derived from the author's role.
SUPERVISION_ROLES = {"senior_consultant", "project_manager",
                     "project_director", "admin", "superadmin"}
COMMENT_PARTIES = {
    "contractor": {"label_ar": "المقاول", "label_en": "Contractor"},
    "consultant": {"label_ar": "الاستشاري", "label_en": "Consultant"},
}
#: feedback body length guard (mirrors review_notes discipline)
MAX_COMMENT_LEN = 2000
#: structured-table guard: max rows per DSR workflow table
MAX_TABLE_ROWS = 30


def next_serial(prefix: str, model, offset: int = 0) -> str:
    """Next serial like 'CVR-000123' derived from max(id)+1+offset.

    Uniqueness is guaranteed by the DB UNIQUE constraint; callers retry the
    whole insert with an increasing offset on IntegrityError, so concurrent
    inserts always make progress instead of regenerating the same serial.
    """
    max_id = db.session.query(func.max(model.id)).scalar() or 0
    return f"{prefix}-{(max_id + 1 + offset):06d}"


# ---------------------------------------------------------------- membership
class ProjectMember(db.Model):
    """Tenant grant: which users may see which projects (fail-closed)."""
    __tablename__ = "project_members"
    __table_args__ = (
        db.UniqueConstraint("user_id", "project_id", name="uq_member_user_project"),
        db.Index("ix_member_project", "project_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"),
                           nullable=False)
    role_in_project = db.Column(db.String(30), default="member")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------- base mixin
class OpsRecordMixin:
    """Shared audit/tenant/workflow columns for all nine modules."""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"),
                           nullable=False, index=True)
    serial = db.Column(db.String(30), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING,
                       index=True)
    report_date = db.Column(db.Date, nullable=False, default=date.today,
                            index=True)
    #: immutable audit trail — approved rows are never mutated; edits spawn
    #: a linked amendment (version+1). root_id anchors a version chain.
    version = db.Column(db.Integer, nullable=False, default=1)
    root_id = db.Column(db.Integer, index=True)
    supersedes_id = db.Column(db.Integer, index=True)
    #: immutable auto-sign snapshot (quad-name) + author link
    signatory_name = db.Column(db.String(200), nullable=False, default="")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    #: approval tracking (legally compliant trail)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    @property
    def status_ar(self) -> str:
        return STATUS_AR.get(self.status, self.status)

    def to_dict(self) -> dict:
        d = {c.key: getattr(self, c.key) for c in self.__table__.columns}
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat()
        d["status_ar"] = self.status_ar
        return d


# ---------------------------------------------------------------- 1. tests
class SiteInspection(OpsRecordMixin, db.Model):
    __tablename__ = "site_inspections"
    __table_args__ = (
        db.Index("ix_insp_project_status", "project_id", "status"),
        db.Index("ix_insp_project_date", "project_id", "report_date"),
    )
    test_category = db.Column(db.String(20), nullable=False, index=True)  # concrete|soil|mep
    test_type = db.Column(db.String(200), nullable=False)  # e.g. slump, cube 7d, compaction
    location_detail = db.Column(db.String(200), default="")
    spec_reference = db.Column(db.String(200), default="")  # spec clause / drawing no
    result_value = db.Column(db.Float)  # numeric outcome (nullable for pass/fail-only)
    result_unit = db.Column(db.String(40), default="")
    acceptance_min = db.Column(db.Float)  # acceptance window (nullable = unbounded)
    acceptance_max = db.Column(db.Float)
    lab_name = db.Column(db.String(200), default="")
    verdict = db.Column(db.String(20), default="pending")  # pass|fail|pending
    notes = db.Column(db.Text, default="")
    # ---- engineering enrichment (MoPWH lab accreditation + pour-permit practice)
    element = db.Column(db.String(200), default="")  # structural element (e.g. عمود C-3)
    axes = db.Column(db.String(120), default="")  # grid axes (e.g. C-D / 3-4)
    concrete_class = db.Column(db.String(40), default="")  # e.g. C30/37
    slump = db.Column(db.Float)  # slump test (mm)
    cube_ids = db.Column(db.String(200), default="")  # cube sample IDs
    pour_permit_ref = db.Column(db.String(120), default="")  # إذن الصب
    witness = db.Column(db.String(120), default="")  # attending party
    standard_code = db.Column(db.String(120), default="")  # ASTM / ACI / BS ref
    follow_up = db.Column(db.Text, default="")  # required follow-up action
    attachments = db.Column(db.Integer, nullable=False, default=0)  # photos/docs

    @property
    def computed_pass(self):
        """Auto verdict from the acceptance window; None if unmeasurable."""
        if self.result_value is None:
            return None
        if self.acceptance_min is not None and self.result_value < self.acceptance_min:
            return False
        if self.acceptance_max is not None and self.result_value > self.acceptance_max:
            return False
        return True


# ---------------------------------------------------------------- 2. materials
class MaterialSubmittal(OpsRecordMixin, db.Model):
    __tablename__ = "material_submittals"
    __table_args__ = (
        db.Index("ix_msub_project_status", "project_id", "status"),
        db.Index("ix_msub_project_date", "project_id", "report_date"),
    )
    material_name = db.Column(db.String(200), nullable=False)
    spec_section = db.Column(db.String(120), default="")
    submittal_no = db.Column(db.String(80), default="")  # contractor reference
    revision = db.Column(db.String(20), default="R0")
    supplier = db.Column(db.String(200), default="")
    manufacturer = db.Column(db.String(200), default="")
    quantity = db.Column(db.Float)
    unit = db.Column(db.String(40), default="")
    sample_location = db.Column(db.String(200), default="")
    notes = db.Column(db.Text, default="")
    # ---- enrichment (MoPWH sample-approval committees: action codes + origin)
    origin_country = db.Column(db.String(120), default="")  # بلد المنشأ
    certificates = db.Column(db.Text, default="")  # شهادات المطابقة
    test_report_ref = db.Column(db.String(120), default="")  # مرجع فحص العينة
    consultant_action = db.Column(db.String(5), default="")  # A|B|C|D
    resubmit_due = db.Column(db.Date)  # مهلة إعادة التقديم


# ---------------------------------------------------------------- 3. RFI
class RFI(OpsRecordMixin, db.Model):
    __tablename__ = "rfis"
    __table_args__ = (
        db.Index("ix_rfi_project_status", "project_id", "status"),
        db.Index("ix_rfi_project_date", "project_id", "report_date"),
    )
    subject = db.Column(db.String(250), nullable=False)
    discipline = db.Column(db.String(80), default="")  # civil|architectural|mep|structural
    question = db.Column(db.Text, nullable=False, default="")
    drawing_ref = db.Column(db.String(200), default="")
    ball_in_court = db.Column(db.String(20), default="consultant")
    reply_due = db.Column(db.Date)
    date_replied = db.Column(db.Date)
    reply_summary = db.Column(db.Text, default="")
    priority = db.Column(db.String(20), default="normal")  # low|normal|high|critical
    # ---- enrichment (contractual impact tracking)
    spec_ref = db.Column(db.String(200), default="")  # مرجع المواصفة
    cost_impact = db.Column(db.String(20), default="none")  # none|pending|confirmed
    delay_days = db.Column(db.Float, nullable=False, default=0)  # أيام التأخير
    response_action = db.Column(db.String(120), default="")  # رد كتابي|اجتماع|مخطط معدل

    @property
    def days_open(self):
        end = self.date_replied or date.today()
        start = self.report_date or end
        return max((end - start).days, 0)


# ---------------------------------------------------------------- 4. cost
class CostVariance(OpsRecordMixin, db.Model):
    __tablename__ = "cost_variances"
    __table_args__ = (
        db.Index("ix_cvar_project_status", "project_id", "status"),
        db.Index("ix_cvar_project_date", "project_id", "report_date"),
    )
    boq_item = db.Column(db.String(250), nullable=False)  # BOQ line description
    boq_ref = db.Column(db.String(80), default="")
    unit = db.Column(db.String(40), default="")
    budgeted_qty = db.Column(db.Float, nullable=False, default=0)
    budgeted_rate = db.Column(db.Float, nullable=False, default=0)
    actual_qty = db.Column(db.Float, nullable=False, default=0)
    actual_rate = db.Column(db.Float, nullable=False, default=0)
    reestimated_qty = db.Column(db.Float)
    reestimated_rate = db.Column(db.Float)
    reason = db.Column(db.Text, default="")
    corrective_action = db.Column(db.Text, default="")
    # ---- enrichment (contract currency + VO linkage + time impact)
    currency = db.Column(db.String(10), nullable=False, default="ILS")
    vo_ref = db.Column(db.String(80), default="")  # ربط أمر تغييري
    schedule_impact_days = db.Column(db.Float, nullable=False, default=0)

    # -- financial accuracy core (mirrored in app/ops/finance.py for pure tests)
    @property
    def budgeted_total(self):
        return (self.budgeted_qty or 0) * (self.budgeted_rate or 0)

    @property
    def actual_total(self):
        return (self.actual_qty or 0) * (self.actual_rate or 0)

    @property
    def variance(self):
        return self.actual_total - self.budgeted_total

    @property
    def variance_pct(self):
        base = self.budgeted_total
        return (self.variance / base * 100.0) if base else 0.0

    @property
    def reestimated_total(self):
        if self.reestimated_qty is None or self.reestimated_rate is None:
            return None
        return self.reestimated_qty * self.reestimated_rate


# ---------------------------------------------------------------- 5. billing
class ProgressBilling(OpsRecordMixin, db.Model):
    __tablename__ = "progress_billings"
    __table_args__ = (
        db.Index("ix_pbil_project_status", "project_id", "status"),
        db.Index("ix_pbil_project_date", "project_id", "report_date"),
    )
    cert_no = db.Column(db.String(80), default="")  # IPC number
    period_from = db.Column(db.Date)
    period_to = db.Column(db.Date)
    work_item = db.Column(db.String(250), nullable=False)
    qty_completed = db.Column(db.Float, nullable=False, default=0)
    rate = db.Column(db.Float, nullable=False, default=0)
    retention_pct = db.Column(db.Float, nullable=False, default=10.0)
    previously_certified = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, default="")
    # ---- enrichment (measurement traceability + item progress)
    boq_ref = db.Column(db.String(80), default="")  # مرجع البند
    measurement_ref = db.Column(db.String(120), default="")  # مرجع الحصر/القياس
    progress_pct = db.Column(db.Float, nullable=False, default=0)  # نسبة إنجاز البند %

    @property
    def gross(self):
        return (self.qty_completed or 0) * (self.rate or 0)

    @property
    def retention(self):
        return self.gross * (self.retention_pct or 0) / 100.0

    @property
    def net_payable(self):
        return self.gross - self.retention

    @property
    def cumulative(self):
        return (self.previously_certified or 0) + self.net_payable


# ---------------------------------------------------------------- 6. subs
class SubcontractorPerformance(OpsRecordMixin, db.Model):
    __tablename__ = "subcontractor_performances"
    __table_args__ = (
        db.Index("ix_sper_project_status", "project_id", "status"),
        db.Index("ix_sper_project_date", "project_id", "report_date"),
    )
    subcontractor = db.Column(db.String(200), nullable=False)
    trade = db.Column(db.String(120), default="")
    period = db.Column(db.String(80), default="")  # e.g. 2026-09
    quality_score = db.Column(db.Float, nullable=False, default=0)
    schedule_score = db.Column(db.Float, nullable=False, default=0)
    safety_score = db.Column(db.Float, nullable=False, default=0)
    compliance_score = db.Column(db.Float, nullable=False, default=0)
    recommended_payment = db.Column(db.Float, default=0)
    remarks = db.Column(db.Text, default="")
    # ---- enrichment (commercial + HSE consequences)
    delay_days = db.Column(db.Float, nullable=False, default=0)  # أيام التأخير
    penalty = db.Column(db.Float, nullable=False, default=0)  # غرامات / حسميات
    incidents = db.Column(db.Integer, nullable=False, default=0)  # حوادث سلامة
    recommendation = db.Column(db.String(20), nullable=False,
                               default="استمرار")  # استمرار|إنذار|استبعاد

    @property
    def overall(self):
        from app.ops.finance import performance_overall
        return performance_overall(self.quality_score, self.schedule_score,
                                   self.safety_score, self.compliance_score)

    @property
    def grade(self):
        from app.ops.finance import performance_grade
        return performance_grade(self.overall)


# ---------------------------------------------------------------- 7. diary
class DailySiteReport(OpsRecordMixin, db.Model):
    """دفتر الورشة اليومي — UNRWA daily technical progress practice.

    Weather, manpower by tier, plant, works executed, deliveries, visitors,
    delays, safety notes, day progress and tomorrow's plan. Signed daily by
    the site engineer; countersigned in the approval workflow.
    """
    __tablename__ = "daily_reports"
    __table_args__ = (
        db.Index("ix_drep_project_status", "project_id", "status"),
        db.Index("ix_drep_project_date", "project_id", "report_date"),
    )
    weather = db.Column(db.String(20), nullable=False, default="مشمس")
    temp_c = db.Column(db.Float)  # درجة الحرارة
    work_hours = db.Column(db.Float, nullable=False, default=8)  # ساعات العمل
    engineers_count = db.Column(db.Integer, nullable=False, default=0)
    technicians_count = db.Column(db.Integer, nullable=False, default=0)
    labor_count = db.Column(db.Integer, nullable=False, default=0)
    #: structured daily workflows (advanced staging): labor breakdown by
    #: trade, plant/equipment log, and work-front staging across site areas.
    #: Each is a JSON list of row dicts, validated in routes.TABLE_SPECS.
    labor_table = db.Column(db.JSON, default=list)      # [{trade, count}]
    equipment_table = db.Column(db.JSON, default=list)  # [{eq_type, qty, hours, status}]
    work_fronts = db.Column(db.JSON, default=list)      # [{area, activity, progress_pct}]

    @property
    def manpower_total(self):
        from app.ops.finance import manpower_total
        return manpower_total(self.engineers_count, self.technicians_count,
                              self.labor_count)

    @staticmethod
    def _rows(value):
        return [r for r in (value or []) if isinstance(r, dict)]

    @property
    def labor_table_total(self) -> int:
        """Headcount summed across trades (structured breakdown)."""
        total = 0
        for r in self._rows(self.labor_table):
            try:
                total += int(float(r.get("count", 0) or 0))
            except (TypeError, ValueError):
                continue
        return total

    @property
    def equipment_hours_total(self) -> float:
        """Plant-hours of the day: Σ qty × hours per equipment row."""
        total = 0.0
        for r in self._rows(self.equipment_table):
            try:
                total += float(r.get("qty", 0) or 0) * float(r.get("hours", 0) or 0)
            except (TypeError, ValueError):
                continue
        return round(total, 2)

    @property
    def fronts_avg_pct(self):
        """Mean progress across staged work fronts (None when unstaged)."""
        pcts = []
        for r in self._rows(self.work_fronts):
            try:
                pcts.append(float(r.get("progress_pct", 0) or 0))
            except (TypeError, ValueError):
                continue
        return round(sum(pcts) / len(pcts), 2) if pcts else None


# ---------------------------------------------------------------- 8. VO
class VariationOrder(OpsRecordMixin, db.Model):
    """الأمر التغييري — MoPWH change-order database practice.

    Every out-of-scope change with reason taxonomy, signed cost impact,
    time impact and an engineering recommendation feeding the approval
    workflow (study → approve / reject).
    """
    __tablename__ = "variation_orders"
    __table_args__ = (
        db.Index("ix_vord_project_status", "project_id", "status"),
        db.Index("ix_vord_project_date", "project_id", "report_date"),
    )
    vo_no = db.Column(db.String(80), default="")  # رقم الأمر لدى المقاول
    title = db.Column(db.String(250), nullable=False)  # عنوان التغيير
    category = db.Column(db.String(30), nullable=False,
                         default="أعمال إضافية")  # تصنيف التغيير
    boq_ref = db.Column(db.String(80), default="")  # البند المرتبط
    description = db.Column(db.Text, nullable=False, default="")  # الوصف الفني
    reason = db.Column(db.Text, default="")  # المبررات
    cost_impact = db.Column(db.Float, nullable=False, default=0)  # الأثر المالي (+/−)
    currency = db.Column(db.String(10), nullable=False, default="ILS")
    time_impact_days = db.Column(db.Float, nullable=False, default=0)  # الأثر الزمني
    recommendation = db.Column(db.String(20), nullable=False,
                               default="دراسة")  # دراسة|اعتماد|رفض
    attachments = db.Column(db.Integer, nullable=False, default=0)

    @property
    def impact_signed(self):
        from app.ops.finance import signed_amount
        return signed_amount(self.cost_impact)


# ---------------------------------------------------------------- 9. HSE
class SafetyReport(OpsRecordMixin, db.Model):
    """تقرير السلامة والصحة المهنية — HSE inspection practice.

    Hazard findings with risk level, corrective action, responsible party
    and target/closure dates, plus period safety statistics (incidents,
    lost-time injuries, toolbox talks, PPE compliance).
    """
    __tablename__ = "safety_reports"
    __table_args__ = (
        db.Index("ix_hrep_project_status", "project_id", "status"),
        db.Index("ix_hrep_project_date", "project_id", "report_date"),
    )
    area = db.Column(db.String(200), nullable=False)  # منطقة التفتيش
    inspection_type = db.Column(db.String(20), nullable=False,
                                default="دوري")  # نوع التفتيش
    hazard = db.Column(db.Text, nullable=False, default="")  # الخطر المرصود
    risk_level = db.Column(db.String(20), nullable=False,
                           default="متوسط")  # مرتفع|متوسط|منخفض
    corrective_action = db.Column(db.Text, default="")  # الإجراء التصحيحي
    responsible = db.Column(db.String(20), nullable=False,
                            default="مقاول")  # الجهة المسؤولة
    target_date = db.Column(db.Date)  # تاريخ المعالجة المستهدف
    closure_date = db.Column(db.Date)  # تاريخ الإغلاق (فارغ = مفتوح)
    incidents_count = db.Column(db.Integer, nullable=False, default=0)
    lost_time_injuries = db.Column(db.Integer, nullable=False, default=0)
    toolbox_talks = db.Column(db.Integer, nullable=False, default=0)  # محاضرات توعية
    ppe_compliance = db.Column(db.Float, nullable=False, default=0)  # الالتزام بمهمات الوقاية %

    @property
    def is_closed(self) -> bool:
        return self.closure_date is not None


# ---------------------------------------------------------------- attachments
class Attachment(db.Model):
    """Real file/image attachment linked to any ops record."""
    __tablename__ = "ops_attachments"
    __table_args__ = (
        db.Index("ix_att_kind_record", "record_kind", "record_id"),
        db.Index("ix_att_project", "project_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    record_kind = db.Column(db.String(40), nullable=False, index=True)
    record_id = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"),
                           nullable=False, index=True)
    filename = db.Column(db.String(260), nullable=False)
    storage_key = db.Column(db.String(120), nullable=False, unique=True,
                            index=True)
    mime_type = db.Column(db.String(80), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"),
                            nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Attachment {self.storage_key} ({self.record_kind}/{self.record_id})>"


# ---------------------------------------------------------------- feedback
def comment_party(role: str) -> str:
    """Map an author role onto the dual-party feedback side."""
    role = {"user": "site_engineer"}.get(role or "", role or "")
    return "consultant" if role in SUPERVISION_ROLES else "contractor"


class OpsRecordComment(db.Model):
    """Dual-party feedback thread on any ops record.

    Contractor/site team and consultant/supervision exchange review notes
    without touching the immutable record itself. Tenant-scoped via
    project_id (same fail-closed rule as attachments); author identity +
    role are snapshotted for the audit trail.
    """
    __tablename__ = "ops_record_comments"
    __table_args__ = (
        db.Index("ix_cmt_kind_record", "record_kind", "record_id"),
        db.Index("ix_cmt_project", "project_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    record_kind = db.Column(db.String(40), nullable=False, index=True)
    record_id = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"),
                           nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False)
    author_name = db.Column(db.String(200), nullable=False, default="")
    author_role = db.Column(db.String(30), nullable=False, default="")
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def party(self) -> str:
        return comment_party(self.author_role)

    def to_dict(self) -> dict:
        return {"id": self.id, "record_kind": self.record_kind,
                "record_id": self.record_id, "project_id": self.project_id,
                "author_id": self.author_id, "author_name": self.author_name,
                "author_role": self.author_role, "party": self.party,
                "body": self.body,
                "created_at": self.created_at.isoformat()
                if self.created_at else ""}

    def __repr__(self):
        return (f"<OpsRecordComment {self.id} "
                f"({self.record_kind}/{self.record_id} by {self.author_name})>")
