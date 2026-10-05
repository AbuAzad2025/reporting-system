"""Shared helpers: the legacy field specs, and the label lookups over them.

Only FIELD_SPECS is imported from here (by app/reports/routes.py and
app/services/default_templates.py). The rest of this module is the field
catalogue for the legacy static report tables, which the dynamic template
engine has since replaced.

This module used to define its own ``admin_required``. That was removed rather
than left in place: the real decorator is ``app.utils.decorators.admin_required``,
which resolves through roles_required("admin", "superadmin",
"project_manager"), and the copy here checked ``current_user.is_admin`` - the
single-tier model the platform moved off. Two definitions of a gate, one of them
weaker, in a file whose other contents nobody imports: exactly the pair where
someone eventually imports the wrong one and a project manager is quietly
administered by the old rule.
"""
from models import REPORT_TYPES  # noqa: F401


# Field specifications per report type: (key, arabic label, input kind)
FIELD_SPECS = {
    "daily": [
        ("weather", "حالة الطقس", "text"),
        ("temp_c", "درجة الحرارة (°م)", "number"),
        ("work_hours", "ساعات العمل", "number"),
        ("engineers_count", "عدد المهندسين", "number"),
        ("technicians_count", "عدد الفنيين", "number"),
        ("labor_count", "عدد العمال", "number"),
        ("notes", "ملاحظات إضافية", "textarea"),
    ],
    "weekly": [
        ("week_no", "رقم الأسبوع", "text"),
        ("progress_percent", "نسبة الإنجاز التراكمية (%)", "number"),
        ("milestones", "الإنجازات والمعالم المحققة خلال الأسبوع", "textarea"),
        ("manpower_summary", "ملخص القوى العاملة والمعدات", "textarea"),
        ("look_ahead", "البرنامج المستقبلي (Look-Ahead) للأسبوع القادم", "textarea"),
        ("challenges", "التحديات الرئيسية في الموقع", "textarea"),
        ("decisions_needed", "القرارات المطلوبة من الإدارة", "textarea"),
        ("notes", "ملاحظات إضافية", "textarea"),
    ],
    "monthly": [
        ("month", "الشهر / الفترة", "text"),
        ("progress_percent", "نسبة الإنجاز التراكمية (%)", "number"),
        ("planned_value", "القيمة المخططة PV", "number"),
        ("earned_value", "القيمة المكتسبة EV", "number"),
        ("actual_cost", "التكلفة الفعلية AC", "number"),
        ("budget_at_completion", "الميزانية عند الإكمال BAC", "number"),
        ("financial_overview", "الموجز المالي (التدفقات / المستخلصات / المصروفات)", "textarea"),
        ("achievements", "أبرز الإنجازات خلال الشهر", "textarea"),
        ("subcontractor_perf", "تقييم أداء المقاولين من الباطن", "textarea"),
        ("risks", "المخاطر والقضايا العالقة", "textarea"),
        ("next_month_plan", "خطة الشهر القادم", "textarea"),
        ("management_signoff", "اعتماد الإدارة / التوقيع", "text"),
        ("notes", "ملاحظات إضافية", "textarea"),
    ],
    "safety": [
        ("inspection_area", "منطقة التفتيش", "text"),
        ("ppe_compliance", "الالتزام بمعدات الوقاية الشخصية (PPE)", "textarea"),
        ("toolbox_talks", "محاضرات التوعية (Toolbox Talks) المنفذة", "textarea"),
        ("near_miss", "الحوادث الوشيكة / الحوادث المسجلة", "textarea"),
        ("hazards", "المخاطر المرصودة", "textarea"),
        ("corrective_actions", "الإجراءات التصحيحية الفورية المطلوبة", "textarea"),
        ("responsible", "المسؤول عن التنفيذ", "text"),
        ("deadline", "الموعد المستهدف للإغلاق", "text"),
        ("notes", "ملاحظات إضافية", "textarea"),
    ],
}

# Which keys render as full-width rows in PDF tables (long text)
LONG_TEXT_KEYS = {
    "works_completed", "constraints", "next_day_plan", "notes",
    "milestones", "manpower_summary", "look_ahead", "challenges",
    "decisions_needed", "financial_overview", "achievements",
    "subcontractor_perf", "risks", "next_month_plan", "ppe_compliance",
    "toolbox_talks", "near_miss", "hazards", "corrective_actions",
}

REQUIRED_COMMON = ["project_name", "report_date"]


def label_for(report_type: str, key: str) -> str:
    for k, label, _kind in FIELD_SPECS.get(report_type, []):
        if k == key:
            return label
    return key


def type_ar(report_type: str) -> str:
    return REPORT_TYPES.get(report_type, report_type)
