"""
Production Reference/Lookup Data for Azadexa Reports.

This module contains all canonical reference data used across reports:
- Weather conditions
- Equipment types & statuses
- Test categories & verdicts
- Safety inspection types, risk levels, responsible parties
- Variation order categories & recommendations
- Consultant actions, Subcontractor recommendations
- Ball-in-court, Manpower roles
- Equipment statuses for daily reports
- And more...

All data is bilingual (AR/EN) with canonical keys.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RefItem:
    """Single reference item with AR/EN labels."""
    key: str
    label_ar: str
    label_en: str
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True)
class RefTable:
    """A reference table (list of items)."""
    name: str
    items: tuple[RefItem, ...]
    key_field: str = "key"
    label_ar_field: str = "label_ar"
    label_en_field: str = "label_en"

    def choices(self, lang: str = "ar") -> list[tuple[str, str]]:
        """Return [(key, label)] for dropdown choices."""
        field = self.label_ar_field if lang == "ar" else self.label_en_field
        return [(item.key, getattr(item, field)) for item in self.items if item.is_active]

    def keys(self) -> list[str]:
        """Return active keys only."""
        return [item.key for item in self.items if item.is_active]

    def get_label(self, key: str, lang: str = "ar") -> str:
        """Get label for a key."""
        field = self.label_ar_field if lang == "ar" else self.label_en_field
        for item in self.items:
            if item.key == key:
                return getattr(item, field)
        return key


# ============================================================
# WEATHER CONDITIONS (UNRWA/FMIS daily progress practice)
# ============================================================
WEATHER = RefTable(
    name="weather",
    items=(
        RefItem("مشمس", "مشمس", "Sunny", 1),
        RefItem("غائم", "غائم", "Cloudy", 2),
        RefItem("ماطر", "ماطر", "Rainy", 3),
        RefItem("عاصف", "عاصف", "Stormy", 4),
        RefItem("حر_جداً", "حر جداً", "Very Hot", 5),
        RefItem("بارد_جداً", "بارد جداً", "Very Cold", 6),
        RefItem("ضبابي", "ضبابي", "Foggy", 7),
        RefItem("رطب", "رطب", "Humid", 8),
    ),
)


# ============================================================
# TEST CATEGORIES (Site Inspections)
# ============================================================
TEST_CATEGORIES = RefTable(
    name="test_categories",
    items=(
        RefItem("concrete", "خرسانة", "Concrete", 1),
        RefItem("soil", "تربة", "Soil", 2),
        RefItem("mep", "ميكانيكا وكهرباء وسباكة", "MEP", 3),
        RefItem("asphalt", "أسفلت", "Asphalt", 4),
        RefItem("steel", "صلب/حديد", "Steel", 5),
        RefItem("waterproofing", "عزل مائي", "Waterproofing", 6),
    ),
)

TEST_VERDICTS = RefTable(
    name="test_verdicts",
    items=(
        RefItem("pass", "ناجح", "Pass", 1),
        RefItem("fail", "راسب", "Fail", 2),
        RefItem("pending", "بانتظار النتيجة", "Pending", 3),
        RefItem("conditional", "ناجح مشروط", "Conditional Pass", 4),
    ),
)


# ============================================================
# BALL IN COURT (RFI)
# ============================================================
BALL_IN_COURT = RefTable(
    name="ball_in_court",
    items=(
        RefItem("contractor", "المقاول", "Contractor", 1),
        RefItem("consultant", "الاستشاري", "Consultant", 2),
        RefItem("client", "المالك", "Client", 3),
        RefItem("shared", "مشترك", "Shared", 4),
    ),
)

RFI_PRIORITY = RefTable(
    name="rfi_priority",
    items=(
        RefItem("low", "منخفضة", "Low", 1),
        RefItem("normal", "عادية", "Normal", 2),
        RefItem("high", "عالية", "High", 3),
        RefItem("critical", "حرجة", "Critical", 4),
    ),
)

RFI_COST_IMPACT = RefTable(
    name="rfi_cost_impact",
    items=(
        RefItem("none", "لا يوجد", "None", 1),
        RefItem("pending", "قيد الدراسة", "Pending", 2),
        RefItem("confirmed", "مؤكد", "Confirmed", 3),
    ),
)

RFI_DISCIPLINE = RefTable(
    name="rfi_discipline",
    items=(
        RefItem("civil", "مدني", "Civil", 1),
        RefItem("architectural", "معماري", "Architectural", 2),
        RefItem("structural", "إنشائي", "Structural", 3),
        RefItem("mep", "ميكانيكا/كهرباء/سباكة", "MEP", 4),
        RefItem("other", "أخرى", "Other", 5),
    ),
)


# ============================================================
# VARIATION ORDERS
# ============================================================
VO_CATEGORIES = RefTable(
    name="vo_categories",
    items=(
        RefItem("تغيير_تصميم", "تغيير تصميم", "Design Change", 1),
        RefItem("ظروف_موقع", "ظروف موقع", "Site Conditions", 2),
        RefItem("طلب_المالك", "طلب المالك", "Owner Request", 3),
        RefItem("أعمال_إضافية", "أعمال إضافية", "Additional Works", 4),
        RefItem("حذف_أعمال", "حذف أعمال", "Work Deletion", 5),
        RefItem("تمديد_زمني", "تمديد زمني", "Extension of Time", 6),
        RefItem("تغيير_مواصفات", "تغيير مواصفات", "Specification Change", 7),
        RefItem("أخرى", "أخرى", "Other", 8),
    ),
)

VO_RECOMMENDATIONS = RefTable(
    name="vo_recommendations",
    items=(
        RefItem("دراسة", "دراسة", "Study", 1),
        RefItem("اعتماد", "اعتماد", "Approve", 2),
        RefItem("رفض", "رفض", "Reject", 3),
        RefItem("تعديل", "تعديل وإعادة تقديم", "Revise & Resubmit", 4),
    ),
)


# ============================================================
# MATERIAL SUBMITTALS
# ============================================================
CONSULTANT_ACTIONS = RefTable(
    name="consultant_actions",
    items=(
        RefItem("A", "معتمد", "Approved", 1),
        RefItem("B", "معتمد مع ملاحظات", "Approved as Noted", 2),
        RefItem("C", "تعديل وإعادة التقديم", "Revise & Resubmit", 3),
        RefItem("D", "مرفوض", "Rejected", 4),
    ),
)


# ============================================================
# SUBCONTRACTOR PERFORMANCE
# ============================================================
SUB_RECOMMENDATIONS = RefTable(
    name="sub_recommendations",
    items=(
        RefItem("استمرار", "استمرار", "Continue", 1),
        RefItem("إنذار", "إنذار", "Warning", 2),
        RefItem("استبعاد", "استبعاد", "Exclude", 3),
    ),
)


# ============================================================
# SAFETY / HSE
# ============================================================
SAFETY_INSPECTION_TYPES = RefTable(
    name="safety_inspection_types",
    items=(
        RefItem("دوري", "دوري", "Routine", 1),
        RefItem("طارئ", "طارئ", "Emergency", 2),
        RefItem("معدات", "معدات", "Equipment", 3),
        RefItem("حفر", "حفر", "Excavation", 4),
        RefItem("كهرباء", "كهرباء", "Electrical", 5),
        RefItem("سقالات", "سقالات", "Scaffolding", 6),
        RefItem("رافعات", "رافعات", "Cranes", 7),
        RefItem("ارتفاعات", "عمل في ارتفاعات", "Working at Heights", 8),
        RefItem("مواد_خطرة", "مواد خطرة", "Hazardous Materials", 9),
        RefItem("حرائق", "حماية من الحرائق", "Fire Protection", 10),
    ),
)

RISK_LEVELS = RefTable(
    name="risk_levels",
    items=(
        RefItem("مرتفع", "مرتفع", "High", 1),
        RefItem("متوسط", "متوسط", "Medium", 2),
        RefItem("منخفض", "منخفض", "Low", 3),
    ),
)

SAFETY_RESPONSIBLE = RefTable(
    name="safety_responsible",
    items=(
        RefItem("مقاول", "مقاول", "Contractor", 1),
        RefItem("مقاول_باطن", "مقاول باطن", "Subcontractor", 2),
        RefItem("استشاري", "استشاري", "Consultant", 3),
        RefItem("مالك", "مالك", "Owner", 4),
        RefItem("مشترك", "مشترك", "Shared", 5),
    ),
)


# ============================================================
# EQUIPMENT (Daily Reports)
# ============================================================
EQUIPMENT_TYPES = RefTable(
    name="equipment_types",
    items=(
        RefItem("رافعة_برجية", "رافعة برجية", "Tower Crane", 1),
        RefItem("رافعة_متحركة", "رافعة متحركة", "Mobile Crane", 2),
        RefItem("حفارة", "حفارة", "Excavator", 3),
        RefItem("مدحلة", "مدحلة", "Roller/Compactor", 4),
        RefItem("خلاطة", "خلاطة خرسانة", "Concrete Mixer", 5),
        RefItem("مضخة_خرسانة", "مضخة خرسانة", "Concrete Pump", 6),
        RefItem("شاحنة", "شاحنة قلابة", "Dump Truck", 7),
        RefItem("لوادر", "لوادر", "Loader", 8),
        RefItem("جرافة", "جرافة", "Bulldozer", 9),
        RefItem("هزاز", "هزاز خرسانة", "Concrete Vibrator", 10),
        RefItem("مقصورة", "مقصورة/منصة", "Man Lift", 11),
        RefItem("ضاغط", "ضاغط هواء", "Air Compressor", 12),
        RefItem("منشار", "منشار قص", "Cutting Saw", 13),
        RefItem("مولد", "مولد كهرباء", "Generator", 14),
        RefItem("أخرى", "أخرى", "Other", 99),
    ),
)

EQUIPMENT_STATUS = RefTable(
    name="equipment_status",
    items=(
        RefItem("operating", "تعمل", "Operating", 1),
        RefItem("idle", "غير نشط/وقوف", "Idle", 2),
        RefItem("down", "متعطل", "Down/Broken", 3),
        RefItem("maintenance", "صيانة", "Maintenance", 4),
        RefItem("standby", "احتياط/استعداد", "Standby", 5),
    ),
)


# ============================================================
# MANPOWER / LABOR ROLES (Daily Reports)
# ============================================================
MANPOWER_ROLES = RefTable(
    name="manpower_roles",
    items=(
        RefItem("مهندس_مدني", "مهندس مدني", "Civil Engineer", 1),
        RefItem("مهندس_معماري", "مهندس معماري", "Architect", 2),
        RefItem("مهندس_ميكانيكا", "مهندس ميكانيكا", "Mechanical Engineer", 3),
        RefItem("مهندس_كهرباء", "مهندس كهرباء", "Electrical Engineer", 4),
        RefItem("مساح", "مساح أراضٍ", "Surveyor", 5),
        RefItem("فني_مختبر", "فني مختبر", "Lab Technician", 6),
        RefItem("فني_كهرباء", "فني كهرباء", "Electrician", 7),
        RefItem("فني_ميكانيكا", "فني ميكانيكا", "Mechanic", 8),
        RefItem("حداد", "حداد", "Steel Fixer", 9),
        RefItem("نجار", "نجار", "Carpenter", 10),
        RefItem("بناء", "بناء/بناء حجر", "Mason", 11),
        RefItem("عامل_عام", "عامل عام", "General Laborer", 12),
        RefItem("سائق", "سائق معدات/شاحنات", "Driver/Operator", 13),
        RefItem("حارس", "حارس أمن", "Security Guard", 14),
        RefItem("مشرف", "مشرف موقع", "Site Supervisor", 15),
        RefItem("مراقب_جودة", "مراقب جودة", "QC Inspector", 16),
        RefItem("مسؤول_سلامة", "مسؤول سلامة", "Safety Officer", 17),
        RefItem("أخرى", "أخرى", "Other", 99),
    ),
)


# ============================================================
# WORK FRONT ACTIVITIES (Daily Reports)
# ============================================================
WORK_ACTIVITIES = RefTable(
    name="work_activities",
    items=(
        RefItem("حفر", "حفر", "Excavation", 1),
        RefItem("ردم", "ردم وضغط", "Backfill & Compaction", 2),
        RefItem("صب_خرسانة", "صب خرسانة", "Concrete Pouring", 3),
        RefItem("حديد_تسليح", "تركيب حديد تسليح", "Rebar Installation", 4),
        RefItem("نجارة_شدة", "نجارة شدات", "Formwork Carpentry", 5),
        RefItem("فك_شدة", "فك شدات", "Formwork Stripping", 6),
        RefItem("بناء_طوب", "بناء طوب/بلوك", "Masonry", 7),
        RefItem("عزل", "عزل مائي/حراري", "Waterproofing/Insulation", 8),
        RefItem("تشطيب", "أعمال تشطيب", "Finishing", 9),
        RefItem("دهان", "دهان", "Painting", 10),
        RefItem("أرضيات", "أرضيات/بلاط", "Flooring/Tiling", 11),
        RefItem("كهرباء", "تمديدات كهرباء", "Electrical Works", 12),
        RefItem("ميكانيكا", "تمديدات ميكانيكا", "Mechanical Works", 13),
        RefItem("سباكة", "سباكة/صرف", "Plumbing/Drainage", 14),
        RefItem("اختبارات", "اختبارات/فحوصات", "Testing/Inspection", 15),
        RefItem("نظافة", "تنظيف موقع", "Site Cleanup", 16),
        RefItem("أخرى", "أخرى", "Other", 99),
    ),
)


# ============================================================
# MATERIAL UNITS
# ============================================================
MATERIAL_UNITS = RefTable(
    name="material_units",
    items=(
        RefItem("م3", "م³", "m³", 1),
        RefItem("م2", "م²", "m²", 2),
        RefItem("م_ط", "م.ط", "lm", 3),
        RefItem("طن", "طن", "Ton", 4),
        RefItem("كغ", "كجم", "kg", 5),
        RefItem("قطعة", "قطعة", "Piece", 6),
        RefItem("مجموعة", "مجموعة", "Set", 7),
        RefItem("لفة", "لفة", "Roll", 8),
        RefItem("كيس", "كيس", "Bag", 9),
        RefItem("علبة", "علبة", "Can/Box", 10),
    ),
)


# ============================================================
# VISITOR PURPOSES
# ============================================================
VISITOR_PURPOSES = RefTable(
    name="visitor_purposes",
    items=(
        RefItem("تفتيش", "تفتيش/فحص", "Inspection", 1),
        RefItem("اجتماع", "اجتماع تنسيق", "Coordination Meeting", 2),
        RefItem("استلام", "استلام أعمال", "Handover/Acceptance", 3),
        RefItem("اعتماد_عينات", "اعتماد عينات", "Sample Approval", 4),
        RefItem("زيارة_إدارية", "زيارة إدارية", "Management Visit", 5),
        RefItem("تدريب", "تدريب/توعية", "Training/Awareness", 6),
        RefItem("أخرى", "أخرى", "Other", 99),
    ),
)


# ============================================================
# DAILY REPORT CONSTRAINTS / DELAY REASONS
# ============================================================
DELAY_REASONS = RefTable(
    name="delay_reasons",
    items=(
        RefItem("طقس", "سوء الأحوال الجوية", "Weather", 1),
        RefItem("مواد", "تأخر توريد المواد", "Material Delay", 2),
        RefItem("معدات", "تعطل/نقص المعدات", "Equipment Issue", 3),
        RefItem("عمالة", "نقص/إضراب العمالة", "Labor Shortage", 4),
        RefItem("تصميم", "تأخر/تعديل التصميم", "Design Delay", 5),
        RefItem("موافقات", "تأخر الموافقات", "Approval Delay", 6),
        RefItem("موقع", "ظروف موقع غير متوقعة", "Site Conditions", 7),
        RefItem("مرافق", "تداخل مرافق/خدمات", "Utility Conflict", 8),
        RefItem("أخرى", "أخرى", "Other", 99),
    ),
)


# ============================================================
# COST VARIANCE REASONS
# ============================================================
VARIANCE_REASONS = RefTable(
    name="variance_reasons",
    items=(
        RefItem("تغير_الكميات", "تغير الكميات", "Quantity Change", 1),
        RefItem("تغير_الأسعار", "تغير الأسعار", "Price Change", 2),
        RefItem("تغير_النطاق", "تغير نطاق العمل", "Scope Change", 3),
        RefItem("ظروف_موقع", "ظروف موقع", "Site Conditions", 4),
        RefItem("خطأ_تصميمي", "خطأ في التصميم", "Design Error", 5),
        RefItem("هدر", "هدر/فاقد", "Wastage", 6),
        RefItem("تسارع", "تسارع البرنامج", "Acceleration", 7),
        RefItem("أخرى", "أخرى", "Other", 99),
    ),
)


# ============================================================
# PROGRESS BILLING RETENTION
# ============================================================
RETENTION_TYPES = RefTable(
    name="retention_types",
    items=(
        RefItem("نسبة_مئوية", "نسبة مئوية (%)", "Percentage", 1),
        RefItem("مبلغ_ثابت", "مبلغ ثابت", "Fixed Amount", 2),
    ),
)


# ============================================================
# MASTER REGISTRY
# ============================================================
REFERENCE_TABLES = {
    "weather": WEATHER,
    "test_categories": TEST_CATEGORIES,
    "test_verdicts": TEST_VERDICTS,
    "ball_in_court": BALL_IN_COURT,
    "rfi_priority": RFI_PRIORITY,
    "rfi_cost_impact": RFI_COST_IMPACT,
    "rfi_discipline": RFI_DISCIPLINE,
    "vo_categories": VO_CATEGORIES,
    "vo_recommendations": VO_RECOMMENDATIONS,
    "consultant_actions": CONSULTANT_ACTIONS,
    "sub_recommendations": SUB_RECOMMENDATIONS,
    "safety_inspection_types": SAFETY_INSPECTION_TYPES,
    "risk_levels": RISK_LEVELS,
    "safety_responsible": SAFETY_RESPONSIBLE,
    "equipment_types": EQUIPMENT_TYPES,
    "equipment_status": EQUIPMENT_STATUS,
    "manpower_roles": MANPOWER_ROLES,
    "work_activities": WORK_ACTIVITIES,
    "material_units": MATERIAL_UNITS,
    "visitor_purposes": VISITOR_PURPOSES,
    "delay_reasons": DELAY_REASONS,
    "variance_reasons": VARIANCE_REASONS,
    "retention_types": RETENTION_TYPES,
}


def get_reference_table(name: str) -> Optional[RefTable]:
    """Get a reference table by name."""
    return REFERENCE_TABLES.get(name)


def get_choices(table_name: str, lang: str = "ar") -> list[tuple[str, str]]:
    """Get dropdown choices for a reference table."""
    table = get_reference_table(table_name)
    if table:
        return table.choices(lang)
    return []


def seed_reference_data(db) -> dict:
    """
    Seed all reference data into DynamicField options for dynamic templates.
    Called during app startup to populate dropdown options.
    """
    from app.models import DynamicField
    
    results = {"updated": 0, "skipped": 0, "errors": []}
    
    # Map reference tables to field keys in templates
    field_mapping = {
        # Site Inspections
        "test_category": "test_categories",
        "verdict": "test_verdicts",
        
        # Material Submittals
        "consultant_action": "consultant_actions",
        
        # RFIs
        "ball_in_court": "ball_in_court",
        "priority": "rfi_priority",
        "cost_impact": "rfi_cost_impact",
        "discipline": "rfi_discipline",
        
        # Cost Variances
        # (no dropdown fields in base spec, but could add variance_reason)
        
        # Progress Billings
        # (retention_pct is number)
        
        # Subcontractor Performance
        "recommendation": "sub_recommendations",
        
        # Daily Reports - structured tables use these
        # labor_table.role -> manpower_roles
        # equipment_table.eq_type -> equipment_types
        # equipment_table.status -> equipment_status
        # work_fronts.activity -> work_activities
        # materials_table.unit -> material_units
        # visitors_table.purpose -> visitor_purposes
        
        # Variation Orders
        "category": "vo_categories",
        "recommendation": "vo_recommendations",
        
        # Safety Reports
        "inspection_type": "safety_inspection_types",
        "risk_level": "risk_levels",
        "responsible": "safety_responsible",
    }
    
    for field_key, ref_table_name in field_mapping.items():
        try:
            table = get_reference_table(ref_table_name)
            if not table:
                results["errors"].append(f"Reference table not found: {ref_table_name}")
                continue
            
            # Find the dynamic field and update its options
            field = DynamicField.query.filter_by(field_key=field_key).first()
            if field:
                field.options = table.keys()
                results["updated"] += 1
            else:
                results["skipped"] += 1
                
        except Exception as e:
            results["errors"].append(f"{field_key}: {e}")
    
    db.session.commit()
    return results


# ============================================================
# COMPATIBILITY: Export the old dict format for existing code
# ============================================================
def _to_dict(table: RefTable) -> dict:
    return {item.key: {"label_ar": item.label_ar, "label_en": item.label_en} for item in table.items}


# Export for backward compatibility with existing code
TEST_CATEGORIES_DICT = _to_dict(TEST_CATEGORIES)
BALL_IN_COURT_DICT = _to_dict(BALL_IN_COURT)
WEATHER_DICT = _to_dict(WEATHER)
VO_CATEGORIES_DICT = _to_dict(VO_CATEGORIES)
VO_RECOMMENDATIONS_DICT = _to_dict(VO_RECOMMENDATIONS)
RISK_LEVELS_DICT = _to_dict(RISK_LEVELS)
SAFETY_INSPECTION_TYPES_DICT = _to_dict(SAFETY_INSPECTION_TYPES)
SAFETY_RESPONSIBLE_DICT = _to_dict(SAFETY_RESPONSIBLE)
CONSULTANT_ACTIONS_DICT = _to_dict(CONSULTANT_ACTIONS)
SUB_RECOMMENDATIONS_DICT = _to_dict(SUB_RECOMMENDATIONS)
EQUIPMENT_STATUS_DICT = _to_dict(EQUIPMENT_STATUS)
COMMENT_PARTIES_DICT = _to_dict(RefTable(
    name="comment_parties",
    items=(
        RefItem("contractor", "المقاول", "Contractor", 1),
        RefItem("consultant", "الاستشاري", "Consultant", 2),
    ),
))

# For code that expects list of keys
TEST_CATEGORIES_LIST = TEST_CATEGORIES.keys()
BALL_IN_COURT_LIST = BALL_IN_COURT.keys()
WEATHER_LIST = WEATHER.keys()
VO_CATEGORIES_LIST = VO_CATEGORIES.keys()
VO_RECOMMENDATIONS_LIST = VO_RECOMMENDATIONS.keys()
RISK_LEVELS_LIST = RISK_LEVELS.keys()
SAFETY_INSPECTION_TYPES_LIST = SAFETY_INSPECTION_TYPES.keys()
SAFETY_RESPONSIBLE_LIST = SAFETY_RESPONSIBLE.keys()
CONSULTANT_ACTIONS_LIST = CONSULTANT_ACTIONS.keys()
SUB_RECOMMENDATIONS_LIST = SUB_RECOMMENDATIONS.keys()
EQUIPMENT_STATUS_LIST = EQUIPMENT_STATUS.keys()
COMMENT_PARTIES_LIST = ["contractor", "consultant"]