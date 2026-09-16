"""Shared helpers: roles, report field specs, duplicate check."""
from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

from models import REPORT_TYPES


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("هذه الصفحة مخصصة لمديري المشاريع فقط.", "danger")
            return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)
    return wrapper


# Field specifications per report type: (key, arabic label, input kind)
FIELD_SPECS = {
    "daily": [
        ("weather", "حالة الطقس", "text"),
        ("manpower", "القوى العاملة (العدد والتخصصات)", "textarea"),
        ("equipment", "المعدات المستخدمة", "textarea"),
        ("materials", "المواد الموردة / المستلمة", "textarea"),
        ("works_completed", "الأعمال المنجزة اليوم", "textarea"),
        ("constraints", "المعوقات والتحديات", "textarea"),
        ("next_day_plan", "خطة عمل اليوم التالي", "textarea"),
        ("progress_percent", "نسبة الإنجاز التراكمية (%)", "number"),
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
    "manpower", "equipment", "materials", "works_completed", "constraints",
    "next_day_plan", "notes", "milestones", "manpower_summary", "look_ahead",
    "challenges", "decisions_needed", "financial_overview", "achievements",
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
