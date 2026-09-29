"""SQLAlchemy models for the Dynamic Reporting SaaS.

Tables:
  users              — all tiers (superadmin/admin/project_manager/
                       safety_officer/site_engineer + legacy user/admin)
  projects           — construction sites managed by admins
  report_templates   — DB-driven report types (Daily/Weekly/Monthly/Safety/...)
  dynamic_fields     — per-template field schema (text/number/dropdown/...)
  report_submissions — field answers (JSON) + auto-sign audit trail
  reports            — LEGACY static table (kept read/write compatible)
"""
from datetime import date, datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, login_manager


def _utcnow():
    """Naive UTC now (DB-compatible) — avoids datetime.utcnow() deprecation."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ---------------------------------------------------------------- constants
#: legacy static types (kept for old /reports/new/<type> flow)
REPORT_TYPES = {
    "daily": "التقرير اليومي",
    "weekly": "التقرير الأسبوعي",
    "monthly": "التقرير الشهري",
    "safety": "تقرير السلامة والصحة المهنية (HSE)",
}
REPORT_TYPE_KEYS = list(REPORT_TYPES.keys())

ROLES = {
    "superadmin": "مالك المنصة / مشرف عام",
    "admin": "مدير مشروع / مشرف",
    "project_manager": "مدير مشروع",
    "project_director": "مدير عام المشاريع",
    "qa_qc_inspector": "مفتش جودة / QC",
    "senior_consultant": "استشاري أول",
    "procurement_officer": "مسؤول المشتريات",
    "safety_officer": "مسؤول سلامة",
    "site_engineer": "مهندس موقع",
    # legacy alias
    "user": "مهندس موقع / مستخدم",
}
ROLE_KEYS = ["superadmin", "admin", "project_manager", "project_director",
             "qa_qc_inspector", "senior_consultant", "procurement_officer",
             "safety_officer", "site_engineer"]

FIELD_TYPES = {
    "text": "نص قصير",
    "textarea": "نص طويل",
    "number": "رقم",
    "dropdown": "قائمة منسدلة",
    "date": "تاريخ",
    "checkbox": "خانة اختيار (نعم/لا)",
    "table": "جدول بنود (صفوف متكررة)",
}
FIELD_TYPE_KEYS = list(FIELD_TYPES.keys())

# Permission flags for granular RBAC
PERMISSIONS = {
    "view_reports": "عرض التقارير",
    "create_reports": "إنشاء تقارير",
    "edit_own_reports": "تعديل التقارير الخاصة",
    "edit_all_reports": "تعديل جميع التقارير",
    "delete_own_reports": "حذف التقارير الخاصة",
    "delete_all_reports": "حذف جميع التقارير",
    "approve_reports": "اعتماد التقارير",
    "manage_templates": "إدارة القوالب",
    "manage_fields": "إدارة الحقول",
    "manage_projects": "إدارة المشاريع",
    "manage_users": "إدارة المستخدمين",
    "view_archive": "عرض الأرشيف",
    "export_pdf": "تصدير PDF",
    "share_reports": "مشاركة التقارير",
    "view_analytics": "عرض التحليلات",
    "manage_settings": "إدارة الإعدادات",
}

# Role -> Permissions mapping (fail-closed: explicit grants only)
ROLE_PERMISSIONS = {
    "superadmin": list(PERMISSIONS.keys()),
    "admin": ["view_reports", "create_reports", "edit_own_reports", "edit_all_reports",
              "delete_own_reports", "delete_all_reports", "approve_reports",
              "manage_templates", "manage_fields", "manage_projects", "manage_users",
              "view_archive", "export_pdf", "share_reports", "view_analytics"],
    "project_director": ["view_reports", "create_reports", "edit_own_reports", "edit_all_reports",
                         "delete_own_reports", "approve_reports", "manage_templates",
                         "manage_fields", "manage_projects", "view_archive",
                         "export_pdf", "share_reports", "view_analytics"],
    "project_manager": ["view_reports", "create_reports", "edit_own_reports",
                        "delete_own_reports", "approve_reports", "manage_projects",
                        "view_archive", "export_pdf", "share_reports"],
    "qa_qc_inspector": ["view_reports", "create_reports", "edit_own_reports",
                        "delete_own_reports", "view_archive", "export_pdf"],
    "senior_consultant": ["view_reports", "create_reports", "edit_own_reports",
                          "delete_own_reports", "approve_reports", "view_archive",
                          "export_pdf", "share_reports"],
    "procurement_officer": ["view_reports", "create_reports", "edit_own_reports",
                            "delete_own_reports", "view_archive", "export_pdf"],
    "safety_officer": ["view_reports", "create_reports", "edit_own_reports",
                       "delete_own_reports", "view_archive", "export_pdf"],
    "site_engineer": ["view_reports", "create_reports", "edit_own_reports",
                      "delete_own_reports", "view_archive", "export_pdf"],
    "user": ["view_reports", "create_reports", "edit_own_reports",
             "delete_own_reports", "view_archive", "export_pdf"],
}

MANAGER_ROLES = {"superadmin", "admin", "project_manager", "project_director"}

# ---------------------------------------------------------------- user


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    #: Full four-part name — stamped on every report + PDF signature block
    full_name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="site_engineer")
    phone = db.Column(db.String(40), default="")
    company = db.Column(db.String(120), default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    #: Advanced profile fields
    avatar = db.Column(db.String(260), default="")  # storage key for uploaded avatar
    job_title = db.Column(db.String(120), default="")  # المسمى الوظيفي
    department = db.Column(db.String(120), default="")  # القسم/الإدارة
    certification = db.Column(db.String(200), default="")  # الشهادات/التراخيص المهنية
    #: Notification preferences (JSON): email, sms, push, in_app
    notification_prefs = db.Column(db.JSON, default=lambda: {
        "email": True, "sms": False, "push": True, "in_app": True
    })

    submissions = db.relationship("ReportSubmission", backref="author",
                                  lazy="dynamic", cascade="all, delete-orphan")
    legacy_reports = db.relationship("Report", backref="author", lazy="dynamic",
                                     cascade="all, delete-orphan")

    # -- auth helpers
    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    # -- RBAC helpers (legacy-aware)
    @property
    def norm_role(self) -> str:
        return {"user": "site_engineer"}.get(self.role, self.role)

    @property
    def is_admin(self) -> bool:
        return self.norm_role in MANAGER_ROLES or self.role == "admin"

    @property
    def is_superadmin(self) -> bool:
        return self.norm_role == "superadmin"

    def can_manage_templates(self) -> bool:
        return self.norm_role in {"superadmin", "admin"}

    def can_manage_users(self) -> bool:
        return self.norm_role in {"superadmin", "admin"}

    # -- Granular permission system
    def has_perm(self, perm: str) -> bool:
        """Check if user has a specific permission (fail-closed)."""
        role = self.norm_role
        allowed = ROLE_PERMISSIONS.get(role, [])
        return perm in allowed

    def has_any_perm(self, *perms: str) -> bool:
        """Check if user has ANY of the given permissions."""
        return any(self.has_perm(p) for p in perms)

    def has_all_perms(self, *perms: str) -> bool:
        """Check if user has ALL of the given permissions."""
        return all(self.has_perm(p) for p in perms)

    @property
    def role_ar(self) -> str:
        return ROLES.get(self.role, ROLES.get(self.norm_role, self.role))

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ---------------------------------------------------------------- project


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False, index=True)
    location = db.Column(db.String(200), default="")
    contractor = db.Column(db.String(200), default="")
    client = db.Column(db.String(200), default="")
    consultant = db.Column(db.String(200), default="")
    logo_path = db.Column(db.String(500), default="")  # custom header logo (project)
    logo2_path = db.Column(db.String(500), default="")  # second header logo (ministry/client)
    contract_no = db.Column(db.String(120), default="")  # CTD/2026/021-WB/MOF
    funding_source = db.Column(db.String(200), default="")  # World Bank IPF
    currency = db.Column(db.String(10), default="ILS")  # ILS/USD
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    submissions = db.relationship("ReportSubmission", backref="project",
                                  lazy="dynamic")

    def __repr__(self):
        return f"<Project {self.name}>"

# ---------------------------------------------------------------- templates


class ReportTemplate(db.Model):
    __tablename__ = "report_templates"
    id = db.Column(db.Integer, primary_key=True)
    #: machine key: daily/weekly/monthly/safety/variation/...
    key = db.Column(db.String(60), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(200), nullable=False)
    name_en = db.Column(db.String(200), default="")
    description = db.Column(db.Text, default="")
    icon = db.Column(db.String(20), default="📋")
    gradient = db.Column(db.String(80), default="from-sky-500 to-blue-700")
    is_active = db.Column(db.Boolean, default=True)
    is_system = db.Column(db.Boolean, default=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=_utcnow)

    fields = db.relationship("DynamicField", backref="template", lazy="dynamic",
                             cascade="all, delete-orphan",
                             order_by="DynamicField.position")
    submissions = db.relationship("ReportSubmission", backref="template",
                                  lazy="dynamic", cascade="all, delete-orphan")

    @property
    def ordered_fields(self):
        return self.fields.order_by(DynamicField.position).all()

    def __repr__(self):
        return f"<ReportTemplate {self.key}: {self.name_ar}>"

# ---------------------------------------------------------------- fields


class DynamicField(db.Model):
    __tablename__ = "dynamic_fields"
    __table_args__ = (
        db.UniqueConstraint("template_id", "field_key",
                            name="uq_template_field_key"),
    )
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("report_templates.id"),
                            nullable=False, index=True)
    field_key = db.Column(db.String(60), nullable=False)
    label_ar = db.Column(db.String(200), nullable=False)
    field_type = db.Column(db.String(20), nullable=False, default="text")
    #: JSON list of strings for dropdown options
    options = db.Column(db.JSON, default=list)
    required = db.Column(db.Boolean, default=False)
    #: Lightweight JSON-schema rules configured from the dashboard, e.g.
    #: {"min": 0, "max": 100, "min_length": 3, "max_length": 500,
    #:  "options": [...], "pattern": "^[0-9]+$"}. Validated server-side by
    #: app/services/field_validation.py — no code changes needed per field.
    rules = db.Column(db.JSON, default=dict)
    #: Line-item columns for field_type == "table": list of
    #: {"key", "label_ar", "type" (text|number|dropdown|date),
    #:  "required" (bool), "options" (list, dropdown only)}.
    #: Answers are stored as a JSON list of row dicts under field_key.
    sub_fields = db.Column(db.JSON, default=list)
    position = db.Column(db.Integer, default=0)
    placeholder = db.Column(db.String(200), default="")

    def options_list(self):
        return self.options or []

    #: allowed cell types inside table fields (checkbox for ESHS checklists,
    #: file for image upload)
    CELL_TYPES = ("text", "textarea", "number", "dropdown", "date", "checkbox", "file")

    def sub_columns(self):
        cols = []
        for c in (self.sub_fields or []):
            if not isinstance(c, dict):
                continue
            key = str(c.get("key", "")).strip().lower().replace(" ", "_")
            if not key:
                continue
            t = c.get("type") if c.get("type") in self.CELL_TYPES else "text"
            cols.append({"key": key,
                         "label_ar": str(c.get("label_ar") or key),
                         "type": t,
                         "required": bool(c.get("required")),
                         "placeholder": str(c.get("placeholder") or ""),
                         "options": [str(o) for o in (c.get("options") or [])]})
        return cols

    def __repr__(self):
        return f"<DynamicField {self.field_key} ({self.field_type})>"

# ---------------------------------------------------------------- submission


class ReportSubmission(db.Model):
    """One filled dynamic report. Anti-duplicate: a project gets at most one
    submission per (template, project_name, report_date)."""
    __tablename__ = "report_submissions"
    __table_args__ = (
        db.UniqueConstraint("template_id", "project_name", "report_date",
                            name="uq_sub_template_project_date"),
        db.Index("ix_sub_template_date", "template_id", "report_date"),
    )
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("report_templates.id"),
                            nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    project_name = db.Column(db.String(200), nullable=False, index=True)
    location = db.Column(db.String(200), default="")
    contractor = db.Column(db.String(200), default="")
    report_date = db.Column(db.Date, nullable=False, default=date.today,
                            index=True)
    #: answers keyed by DynamicField.field_key
    data = db.Column(db.JSON, nullable=False, default=dict)
    #: auto-sign snapshot (immutable audit trail)
    signatory_name = db.Column(db.String(200), nullable=False, default="")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow,
                           onupdate=_utcnow)

    def get(self, key, default=""):
        return (self.data or {}).get(key, default)

    def __repr__(self):
        return (f"<Submission {self.template_id} | {self.project_name} | "
                f"{self.report_date}>")

# ---------------------------------------------------------------- legacy


class Report(db.Model):
    """LEGACY static table (v1: daily/weekly/monthly/safety with hardcoded
    FIELD_SPECS). Kept fully working; new work should use ReportSubmission."""
    __tablename__ = "reports"
    __table_args__ = (
        db.UniqueConstraint("project_name", "report_type", "report_date",
                            name="uq_project_type_date"),
        db.Index("ix_reports_type_date", "report_type", "report_date"),
    )
    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(20), nullable=False, index=True)
    project_name = db.Column(db.String(200), nullable=False, index=True)
    location = db.Column(db.String(200), default="")
    contractor = db.Column(db.String(200), default="")
    report_date = db.Column(db.Date, nullable=False, default=date.today,
                            index=True)
    data = db.Column(db.JSON, nullable=False, default=dict)
    signatory_name = db.Column(db.String(200), nullable=False, default="")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow,
                           onupdate=_utcnow)

    @property
    def type_ar(self) -> str:
        return REPORT_TYPES.get(self.report_type, self.report_type)

    def get(self, key, default=""):
        return (self.data or {}).get(key, default)

# ---------------------------------------------------------------- branding (tenant-scoped customization)

class TenantBranding(db.Model):
    __tablename__ = "tenant_branding"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), index=True)
    company_name_ar = db.Column(db.String(200), default="")
    company_name_en = db.Column(db.String(200), default="")
    logo_path = db.Column(db.String(500), default="")
    logo2_path = db.Column(db.String(500), default="")
    primary_color = db.Column(db.String(7), default="#1e3a5f")
    secondary_color = db.Column(db.String(7), default="#c9a227")
    custom_header_text_ar = db.Column(db.Text, default="")
    custom_header_text_en = db.Column(db.Text, default="")
    custom_footer_notes = db.Column(db.Text, default="")
    disclaimer_text = db.Column(db.Text, default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (db.Index("ix_branding_project_id", "project_id"),)

    def __repr__(self):
        return f"<TenantBranding {self.id} proj={self.project_id}>"


class TenantTemplateOverride(db.Model):
    __tablename__ = "tenant_template_overrides"
    id = db.Column(db.Integer, primary_key=True)
    template_key = db.Column(db.String(60), nullable=False, index=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    is_active = db.Column(db.Boolean, default=True)
    fields_config = db.Column(db.JSON, default=dict)
    deleted_fields = db.Column(db.JSON, default=list)
    added_fields = db.Column(db.JSON, default=list)
    reordered_fields = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("template_key", "tenant_id",
                            name="uq_tenant_tpl_tenant"),
    )

    def __repr__(self):
        return f"<TenantTemplateOverride {self.template_key}:{self.tenant_id}>"
