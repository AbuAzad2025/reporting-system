"""Default DB-driven schema: 5 templates mirroring v1 FIELD_SPECS + Variation Order.

Used by seed + 'reset to defaults' admin action. Field dicts:
  key / label_ar / type / required / options / placeholder
"""
from utils.helpers import FIELD_SPECS

DEFAULT_TEMPLATES = [
    {"key": "daily", "name_ar": "التقرير اليومي", "name_en": "Daily Progress Report",
     "icon": "📋", "gradient": "from-sky-500 to-blue-700", "is_system": True,
     "description": "القوى العاملة، المعدات، المواد، المنجز، المعوقات وخطة الغد"},
    {"key": "weekly", "name_ar": "التقرير الأسبوعي", "name_en": "Weekly Summary Report",
     "icon": "📊", "gradient": "from-violet-500 to-purple-700", "is_system": True,
     "description": "النسبة التراكمية، المعالم، البرنامج المستقبلي والتحديات"},
    {"key": "monthly", "name_ar": "التقرير الشهري", "name_en": "Monthly Executive Report",
     "icon": "📈", "gradient": "from-amber-500 to-orange-600", "is_system": True,
     "description": "الموجز المالي، الإنجازات، أداء المقاولين والاعتماد"},
    {"key": "safety", "name_ar": "تقرير السلامة والصحة المهنية",
     "name_en": "HSE / Safety Inspection Report",
     "icon": "🦺", "gradient": "from-emerald-500 to-teal-700", "is_system": True,
     "description": "الامتثال، الحوادث الوشيكة، التوعية والإجراءات التصحيحية"},
    {"key": "variation", "name_ar": "أمر تغيير / أعمال إضافية",
     "name_en": "Variation Order",
     "icon": "📝", "gradient": "from-rose-500 to-red-600", "is_system": False,
     "description": "توثيق الأعمال المستجدة والتغييرات خارج نطاق العقد"},
    # ---- Azadexa operational modules (backed by dedicated tables in app/ops)
    {"key": "site-inspections", "name_ar": "تقرير فحص واختبار الموقع",
     "name_en": "Site Inspection & Testing Report",
     "icon": "🧪", "gradient": "from-cyan-500 to-blue-700", "is_system": True,
     "description": "اختبارات الخرسانة والتربة والكهروميكانيكا مع الحكم والقبول"},
    {"key": "material-submittals", "name_ar": "سجل اعتماد وفحص المواد",
     "name_en": "Material Submittal & Inspection Log",
     "icon": "📦", "gradient": "from-orange-500 to-amber-600", "is_system": True,
     "description": "اعتمادات المواد والمورّدين وحالات القبول"},
    {"key": "rfis", "name_ar": "سجل طلبات الاستفسار (RFI)",
     "name_en": "RFI Log",
     "icon": "❓", "gradient": "from-indigo-500 to-violet-700", "is_system": True,
     "description": "توثيق الاستفسارات الفنية ومتابعة الردود والمسؤول"},
    {"key": "cost-variances", "name_ar": "فروقات التكلفة وإعادة التقدير",
     "name_en": "Cost Variance & Re-estimation Report",
     "icon": "💰", "gradient": "from-emerald-500 to-green-700", "is_system": True,
     "description": "معتمد مقابل فعلي مقابل إعادة تقدير مع نسب الانحراف"},
    {"key": "progress-billings", "name_ar": "المستخلصات والتدفق النقدي",
     "name_en": "Progress Billing & Cash Flow Report",
     "icon": "🧾", "gradient": "from-teal-500 to-cyan-700", "is_system": True,
     "description": "المستخلصات المرحلية والمحجوز والصافي التراكمي"},
    {"key": "subcontractor-performances", "name_ar": "أداء المقاولين والدفعات",
     "name_en": "Subcontractor Performance & Payment Report",
     "icon": "👷", "gradient": "from-slate-500 to-slate-700", "is_system": True,
     "description": "تقييم موزون (جودة/زمن/سلامة/التزام) والتقدير والدفعة الموصى بها"},
]

EXTRA_SPECS = {
    "site-inspections": [
        ("test_category", "فئة الاختبار", "dropdown", True,
         ["concrete", "soil", "mep"]),
        ("test_type", "نوع الاختبار", "text", True),
        ("location_detail", "موقع العينة", "text", False),
        ("spec_reference", "المرجع / المواصفة", "text", False),
        ("result_value", "نتيجة القياس", "number", False),
        ("verdict", "الحكم", "dropdown", False, ["pass", "fail", "pending"]),
        ("lab_name", "المختبر", "text", False),
        ("notes", "ملاحظات", "textarea", False),
        # architectural & structural traceability (Lead Architect / Civil)
        ("drawing_ref", "مرجع المخطط", "text", False),
        ("finish_code", "رمز التشطيب", "text", False),
        ("zone", "المنطقة / الحيز", "text", False),
        ("level", "المنسوب / الطابق", "text", False),
        ("grid_axis", "المحور الشبكي", "text", False),
        ("code_clause", "بند الكود", "text", False),
        ("structural_element", "العنصر الإنشائي (بلاطة/جسر/عمود)", "dropdown", False, ["slab", "beam", "column", "wall", "foundation", "other"]),
        ("tolerance_mm", "التفاوت المسموح (مم)", "number", False),
        ("pour_permit_no", "رقم إذن الصب", "text", False),
        ("cube_7d", "مقاومة 7 أيام (MPa)", "number", False),
        ("cube_28d", "مقاومة 28 يوم (MPa)", "number", False),
    ],
    "material-submittals": [
        ("material_name", "اسم المادة", "text", True),
        ("spec_section", "بند المواصفة", "text", False),
        ("submittal_no", "رقم التقديم", "text", False),
        ("supplier", "المورّد", "text", False),
        ("quantity", "الكمية", "number", False),
        ("notes", "ملاحظات", "textarea", False),
    ],
    "rfis": [
        ("subject", "الموضوع", "text", True),
        ("discipline", "التخصص", "dropdown", False,
         ["civil", "architectural", "structural", "mep", "other"]),
        ("question", "نص الاستفسار", "textarea", True),
        ("ball_in_court", "الكرة في ملعب", "dropdown", False,
         ["contractor", "consultant", "client"]),
        ("priority", "الأولوية", "dropdown", False,
         ["low", "normal", "high", "critical"]),
        ("reply_summary", "ملخص الرد", "textarea", False),
    ],
    "cost-variances": [
        ("boq_item", "بند جدول الكميات", "text", True),
        ("budgeted_qty", "الكمية المعتمدة", "number", False),
        ("budgeted_rate", "السعر المعتمد", "number", False),
        ("actual_qty", "الكمية الفعلية", "number", False),
        ("actual_rate", "السعر الفعلي", "number", False),
        ("reason", "سبب الفرق", "textarea", False),
    ],
    "progress-billings": [
        ("cert_no", "رقم المستخلص", "text", False),
        ("work_item", "بند الأعمال", "text", True),
        ("qty_completed", "الكمية المنجزة", "number", False),
        ("rate", "السعر", "number", False),
        ("retention_pct", "نسبة المحجوز (%)", "number", False),
        ("notes", "ملاحظات", "textarea", False),
    ],
    "subcontractor-performances": [
        ("subcontractor", "المقاول من الباطن", "text", True),
        ("trade", "التخصص", "text", False),
        ("quality_score", "الجودة /100", "number", False),
        ("schedule_score", "الالتزام الزمني /100", "number", False),
        ("safety_score", "السلامة /100", "number", False),
        ("compliance_score", "الالتزام التعاقدي /100", "number", False),
        ("remarks", "ملاحظات التقييم", "textarea", False),
    ],
    "variation": [
        ("vo_no", "رقم أمر التغيير", "text", True),
        ("subject", "موضوع التغيير", "textarea", True),
        ("reason", "سبب التغيير", "dropdown", True,
         ["طلب المالك", "خطأ تصميمي", "ظروف موقع", "متطلبات جهة حكومية", "أخرى"]),
        ("affected_drawing_rev", "المخطط المتأثر / المراجعة", "text", False),
        ("cost_impact", "الأثر المالي التقديري", "number", False),
        ("time_impact", "الأثر الزمني (أيام)", "number", False),
        ("attachments", "المرفقات / المرجعيات", "text", False),
        ("recommendation", "توصية المهندس", "textarea", False),
        ("notes", "ملاحظات إضافية", "textarea", False),
    ]
}

_KIND_MAP = {"text": "text", "textarea": "textarea", "number": "number",
             "dropdown": "dropdown", "date": "date", "checkbox": "checkbox",
             "table": "table"}


def _spec_to_field(key, label, kind, required=False, options=None,
                   columns=None):
    return {"key": key, "label_ar": label,
            "type": _KIND_MAP.get(kind, "text"),
            "required": required, "options": options or [],
            "columns": columns or [],
            "placeholder": f"اكتب {label}..." if _KIND_MAP.get(kind) in ("text", "textarea") else ""}


#: Comprehensive ESHS Daily Report — matches استراحة أريحا model (11 sections + 8.1-8.11).
#: Replaces thin UNRWA tables with full spec from user PDFs.
DAILY_TABLES = [
    ("equipment_esha", "2. قائمة المعدات والآلات في الموقع", [
        {"key": "eq_name", "label_ar": "اسم المعدة", "type": "text", "required": True, "options": []},
        {"key": "ownership", "label_ar": "الملكية (ملك/إيجار)", "type": "dropdown", "required": False, "options": ["ملك", "إيجار"]},
        {"key": "hours_work", "label_ar": "ساعات العمل", "type": "number", "required": False, "options": []},
        {"key": "hours_stop", "label_ar": "ساعات التوقف", "type": "number", "required": False, "options": []},
        {"key": "hours_total", "label_ar": "إجمالي الساعات", "type": "number", "required": False, "options": []},
    ]),
    ("staff_esha", "3. الكادر الفني والعاملون في الموقع", [
        {"key": "company", "label_ar": "الشركة / المؤسسة", "type": "dropdown", "required": True, "options": ["المقاول", "الاستشاري / وزارة المالية", "وزارة المالية"]},
        {"key": "role", "label_ar": "المسمى الوظيفي / دور العمل", "type": "text", "required": True, "options": []},
        {"key": "name", "label_ar": "الاسم", "type": "text", "required": True, "options": []},
        {"key": "hours", "label_ar": "ساعات العمل", "type": "number", "required": False, "options": []},
        {"key": "nature", "label_ar": "طبيعة الدوام", "type": "dropdown", "required": False, "options": ["دوام كامل", "دوام كامل/", "كامل"]},
    ]),
    ("work_progress_esha", "4. تقدم الأشغال والتنفيذ", [
        {"key": "activity", "label_ar": "الأنشطة والأعمال", "type": "textarea", "required": True, "options": []},
        {"key": "drawing_ref", "label_ar": "مرجع المخطط", "type": "text", "required": False, "options": []},
        {"key": "finish_code", "label_ar": "رمز التشطيب", "type": "text", "required": False, "options": []},
        {"key": "zone", "label_ar": "المنطقة / الحيز", "type": "text", "required": False, "options": []},
        {"key": "level", "label_ar": "المنسوب / الطابق", "type": "text", "required": False, "options": []},
        {"key": "grid_axis", "label_ar": "المحور الشبكي", "type": "text", "required": False, "options": []},
        {"key": "code_clause", "label_ar": "بند الكود", "type": "text", "required": False, "options": []},
        {"key": "qty", "label_ar": "الكميات المنجزة مع الوحدات", "type": "text", "required": False, "options": []},
        {"key": "notes", "label_ar": "ملاحظات", "type": "text", "required": False, "options": []},
    ]),
    ("mockup_approval_esha", "4.ب اعتماد العينات والنماذج (Mockup)", [
        {"key": "element_name", "label_ar": "العنصر / العينة", "type": "text", "required": True, "options": []},
        {"key": "status", "label_ar": "الحالة", "type": "dropdown", "required": True, "options": ["قيد المراجعة", "معتمد", "معتمد بملاحظات", "مرفوض"]},
        {"key": "approval_date", "label_ar": "تاريخ الاعتماد", "type": "date", "required": False, "options": []},
        {"key": "drawing_rev", "label_ar": "مرجع المخطط / المراجعة", "type": "text", "required": False, "options": []},
    ]),
    ("materials_esha", "5. المواد الموردة للموقع", [
        {"key": "mat_type", "label_ar": "النوع", "type": "text", "required": True, "options": []},
        {"key": "unit", "label_ar": "الوحدة", "type": "text", "required": False, "options": []},
        {"key": "qty_supplied", "label_ar": "الكميات الموردة", "type": "number", "required": False, "options": []},
        {"key": "qty_used", "label_ar": "الكميات المستهلكة", "type": "number", "required": False, "options": []},
        {"key": "qty_remain", "label_ar": "المتبقي", "type": "number", "required": False, "options": []},
        {"key": "qc_notes", "label_ar": "الملاحظات / فحص الجودة والسلامة", "type": "text", "required": False, "options": []},
    ]),
    ("next_day_esha", "6. الأنشطة المخطط لها لليوم التالي", [
        {"key": "activity_next", "label_ar": "الأنشطة المخطط لها", "type": "textarea", "required": True, "options": []},
        {"key": "qty_next", "label_ar": "الكميات المخطط لها مع الوحدات", "type": "text", "required": False, "options": []},
        {"key": "safety_next", "label_ar": "الملاحظات / إجراءات السلامة والبيئة المطلوبة", "type": "textarea", "required": False, "options": []},
    ]),
    ("meetings_esha", "7. الاجتماعات والزيارات بالموقع", [
        {"key": "m_type", "label_ar": "نوع الاجتماع / الزيارة", "type": "text", "required": True, "options": []},
        {"key": "m_date", "label_ar": "التاريخ", "type": "date", "required": False, "options": []},
        {"key": "m_attendees", "label_ar": "الحضور", "type": "text", "required": False, "options": []},
        {"key": "m_summary", "label_ar": "الملخص", "type": "textarea", "required": False, "options": []},
    ]),
    ("waste_daily_esha", "8.3 سجل النفايات اليومية", [
        {"key": "w_type", "label_ar": "نوع النفايات / المادة", "type": "text", "required": True, "options": []},
        {"key": "w_qty", "label_ar": "الكمية", "type": "number", "required": False, "options": []},
        {"key": "w_unit", "label_ar": "الوحدة", "type": "text", "required": False, "options": []},
        {"key": "w_dest", "label_ar": "الوجهة / موقع التفريغ", "type": "text", "required": False, "options": []},
        {"key": "w_mitigation", "label_ar": "إجراءات التخفيف أثناء النقل", "type": "text", "required": False, "options": []},
    ]),
    ("waste_mgmt_esha", "إجراءات إدارة النفايات (8.3)", [
        {"key": "proc", "label_ar": "إجراء إدارة النفايات", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم التنفيذ ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم ☐", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_air_esha", "8.4 أ. التلوث الهوائي والغبار والضوضاء", [
        {"key": "proc", "label_ar": "إجراء التخفيف / الإجراء الوقائي", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم التنفيذ ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم ☐", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_utilities_esha", "8.4 ب. المرافق العامة والخدمات القائمة", [
        {"key": "proc", "label_ar": "إجراء التخفيف", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم ☐", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_ohs_esha", "8.4 ج. الصحة والسلامة المهنية OHS", [
        {"key": "proc", "label_ar": "إجراء السلامة", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم ☐", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_workcond_esha", "8.4 د. ظروف العمل", [
        {"key": "proc", "label_ar": "إجراء السلامة", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم ☐", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_community_esha", "8.4 هـ. صحة وسلامة المجتمع والمسافرين", [
        {"key": "proc", "label_ar": "إجراء السلامة", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم ☐", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("announcements_esha", "8.5 الإعلانات وإخطارات أصحاب المصلحة", [
        {"key": "purpose", "label_ar": "الغرض من الإعلان", "type": "textarea", "required": True, "options": []},
        {"key": "audience", "label_ar": "الجمهور / الفئة المستهدفة", "type": "text", "required": False, "options": []},
        {"key": "platform", "label_ar": "المنصة / طريقة الإخطار", "type": "text", "required": False, "options": []},
        {"key": "date", "label_ar": "تاريخ الإعلان", "type": "date", "required": False, "options": []},
        {"key": "result", "label_ar": "الوصف / النتيجة", "type": "textarea", "required": False, "options": []},
    ]),
    ("incidents_esha", "8.6 حوادث الموقع ومتابعة إجراءات السلامة", [
        {"key": "inc_type", "label_ar": "نوع الحادث / العارض", "type": "dropdown", "required": True, "options": ["عارض", "حادث", "لا يوجد اليوم"]},
        {"key": "incident_severity", "label_ar": "خطورة الحادث (1-5)", "type": "dropdown", "required": False, "options": ["1", "2", "3", "4", "5"]},
        {"key": "lost_time_days", "label_ar": "أيام العمل المفقودة", "type": "number", "required": False, "options": []},
        {"key": "level", "label_ar": "مستوى الحادث", "type": "text", "required": False, "options": []},
        {"key": "action", "label_ar": "الإجراء المتخذ في الموقع", "type": "textarea", "required": False, "options": []},
        {"key": "details", "label_ar": "تفاصيل إضافية", "type": "text", "required": False, "options": []},
        {"key": "notes", "label_ar": "ملاحظات", "type": "text", "required": False, "options": []},
    ]),
    ("stakeholder_activities_esha", "8.7 أنشطة مشاركة أصحاب المصلحة", [
        {"key": "act_desc", "label_ar": "وصف النشاط", "type": "textarea", "required": True, "options": []},
        {"key": "stakeholders", "label_ar": "أصحاب المصلحة المستهدفون", "type": "text", "required": False, "options": []},
        {"key": "action_taken", "label_ar": "الإجراء المتخذ في الموقع", "type": "textarea", "required": False, "options": []},
    ]),
    ("complaints_esha", "8.8 آلية الشكاوى والاعتراضات", [
        {"key": "category", "label_ar": "فئة الشكوى", "type": "text", "required": True, "options": []},
        {"key": "desc", "label_ar": "الوصف", "type": "textarea", "required": False, "options": []},
        {"key": "complainant", "label_ar": "المشتكي / وسيلة التواصل", "type": "text", "required": False, "options": []},
        {"key": "status", "label_ar": "الحالة", "type": "dropdown", "required": False, "options": ["مفتوحة", "مغلقة", "لا يوجد"]},
        {"key": "solution", "label_ar": "الحلول / الملاحظات", "type": "textarea", "required": False, "options": []},
    ]),
    ("safety_team_esha", "8.9 فريق البيئة والسلامة للمقاول", [
        {"key": "role", "label_ar": "الكادر الفني للسلامة والبيئة", "type": "text", "required": True, "options": []},
        {"key": "status", "label_ar": "الحالة (متواجد/غائب)", "type": "dropdown", "required": True, "options": ["متواجد ☒ دوام كامل", "غائب ☐", "متواجد ☒", "غائب"]},
    ]),
    ("photos_esha", "8.10 الصور التوثيقية مع التعليقات", [
        {"key": "photo", "label_ar": "الصورة (ارفع ملف JPG/PNG)", "type": "file", "required": False, "options": []},
        {"key": "caption", "label_ar": "التعليق", "type": "textarea", "required": False, "options": []},
    ]),
    ("ncr_esha", "سجل عدم المطابقة (NCR) — يُنشأ تلقائياً عند فشل الاختبار", [
        {"key": "ncr_no", "label_ar": "رقم NCR", "type": "text", "required": True, "options": []},
        {"key": "description", "label_ar": "وصف عدم المطابقة", "type": "textarea", "required": True, "options": []},
        {"key": "disposition", "label_ar": "التصرف (إصلاح/استبدال/قبول)", "type": "dropdown", "required": False, "options": ["إصلاح", "استبدال", "قبول مشروط", "رفض"]},
        {"key": "closure_date", "label_ar": "تاريخ الإغلاق", "type": "date", "required": False, "options": []},
    ]),
    ("signatures_esha", "8.11 الإعداد والتدقيق والاعتماد", [
        {"key": "entity", "label_ar": "الصفة / الجهة", "type": "dropdown", "required": True, "options": ["اعداد المقاول", "وزارة المالية / المهندس المشرف (اعتماد)"]},
        {"key": "name_title", "label_ar": "المسمى الوظيفي / الاسم", "type": "text", "required": True, "options": []},
        {"key": "signature", "label_ar": "التوقيع", "type": "text", "required": False, "options": []},
        {"key": "date", "label_ar": "التاريخ", "type": "date", "required": False, "options": []},
    ]),
]

#: Weekly — matches Biweekly Progress Report (MOF/CTD)
WEEKLY_TABLES = [
    ("wp_status", "الموقف التنفيذي التفصيلي حسب حزم العمل", [
        {"key": "wp_code", "label_ar": "رمز البند", "type": "text", "required": True, "options": []},
        {"key": "wp_name", "label_ar": "حزمة العمل", "type": "text", "required": True, "options": []},
        {"key": "wp_week", "label_ar": "الحالة الأسبوعية", "type": "dropdown", "required": False, "options": ["منجز خلال الأسبوع", "منجز / مستمر", "مستمر", "قيد التنفيذ", "قيد المتابعة"]},
        {"key": "wp_field", "label_ar": "الحالة الميدانية والملاحظات", "type": "textarea", "required": False, "options": []},
    ]),
    ("weekly_issues", "المشاكل والأضرار والإجراءات المتخذة", [
        {"key": "issue", "label_ar": "المشكلة / التحدي", "type": "text", "required": True, "options": []},
        {"key": "risk", "label_ar": "مستوى الخطر", "type": "dropdown", "required": False, "options": ["منخفض", "متوسط", "عالي"]},
        {"key": "impact", "label_ar": "الأثر", "type": "textarea", "required": False, "options": []},
        {"key": "action", "label_ar": "الإجراء التصحيحي", "type": "textarea", "required": False, "options": []},
    ]),
    ("weekly_photos", "صور تقدم الأعمال (الأسبوعي)", [
        {"key": "photo", "label_ar": "الصورة", "type": "text", "required": False, "options": []},
        {"key": "caption", "label_ar": "التعليق", "type": "textarea", "required": False, "options": []},
    ]),
]

SAFETY_TABLES = [
    ("ppe_matrix", "مصفوفة معدات الوقاية الشخصية (PPE)", [
        {"key": "role", "label_ar": "الدور / الفئة", "type": "text", "required": True, "options": []},
        {"key": "helmet", "label_ar": "خوذة ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "vest", "label_ar": "سترة ☐", "type": "checkbox", "required": False, "options": []},
        {"key": "gloves", "label_ar": "قفازات ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "glasses", "label_ar": "نظارات ☒", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "ملاحظات", "type": "text", "required": False, "options": []},
    ]),
    ("toolbox_talk", "سجل محاضرات التوعية (Toolbox Talks)", [
        {"key": "talk_date", "label_ar": "التاريخ", "type": "date", "required": True, "options": []},
        {"key": "attendees_count", "label_ar": "عدد الحضور", "type": "number", "required": True, "options": []},
        {"key": "topic", "label_ar": "الموضوع", "type": "textarea", "required": True, "options": []},
        {"key": "trainer", "label_ar": "المدرب", "type": "text", "required": False, "options": []},
    ]),
]

MONTHLY_TABLES = [
    ("cashflow_forecast", "توقع التدفق النقدي", [
        {"key": "period", "label_ar": "الفترة", "type": "text", "required": True, "options": []},
        {"key": "planned_cash", "label_ar": "التدفق المخطط", "type": "number", "required": False, "options": []},
        {"key": "actual_cash", "label_ar": "التدفق الفعلي", "type": "number", "required": False, "options": []},
        {"key": "variance", "label_ar": "الانحراف", "type": "number", "required": False, "options": []},
    ]),
    ("risk_register", "سجل المخاطر", [
        {"key": "risk", "label_ar": "الخطر", "type": "textarea", "required": True, "options": []},
        {"key": "probability", "label_ar": "الاحتمالية", "type": "dropdown", "required": False, "options": ["منخفض", "متوسط", "عالي"]},
        {"key": "impact", "label_ar": "التأثير", "type": "dropdown", "required": False, "options": ["منخفض", "متوسط", "عالي"]},
        {"key": "mitigation", "label_ar": "إجراء التخفيف", "type": "textarea", "required": False, "options": []},
        {"key": "owner", "label_ar": "المسؤول", "type": "text", "required": False, "options": []},
        {"key": "exposure", "label_ar": "التعرض", "type": "text", "required": False, "options": []},
    ]),
]


def default_fields_for(template_key):
    """Return ordered field dicts for a template key."""
    if template_key in EXTRA_SPECS:
        return [_spec_to_field(k, lb, kd, req, opts if len(r) > 4 else [])
                for r in EXTRA_SPECS[template_key]
                for (k, lb, kd, req, *opts) in [r]]
    out = []
    for k, label, kind in FIELD_SPECS.get(template_key, []):
        out.append(_spec_to_field(k, label, kind, False))
    if template_key == "daily":
        # 8.1 / 8.2 descriptive fields (before tables, as in PDF)
        out.append(_spec_to_field("eshs_desc_81", "8.1 وصف أنشطة البناء في الموقع", "textarea", False))
        out.append(_spec_to_field("eshs_location_82", "8.2 موقع تنفيذ الأنشطة", "textarea", False))
        _required_esha = {"waste_mgmt_esha", "eshs_air_esha", "eshs_utilities_esha", "eshs_ohs_esha", "eshs_workcond_esha", "eshs_community_esha"}
        for k, lb, cols in DAILY_TABLES:
            req = k in _required_esha
            out.append(_spec_to_field(k, lb, "table", req, [], cols))
        # attachments checkboxes (المرفقات) - 3 items
        out.append(_spec_to_field("attach_attendance", "المرفقات: كشف الحضور اليومي للموقع", "checkbox", False))
        out.append(_spec_to_field("attach_complaints", "المرفقات: سجل الشكاوى والحوادث", "checkbox", False))
        out.append(_spec_to_field("attach_scaffolding", "المرفقات: قائمة فحص وتدقيق السقالات والمعدات", "checkbox", False))
    if template_key == "weekly":
        # weekly summary (12 items) + attachments + WP tables
        out.append(_spec_to_field("weekly_summary_12", "ملخص التقدم التنفيذي (12 بند)", "textarea", False))
        out.append(_spec_to_field("weekly_extra_challenges", "الأعمال الإضافية والتحديات الفنية", "textarea", False))
        out += [_spec_to_field(k, lb, "table", False, [], cols)
                for k, lb, cols in WEEKLY_TABLES]
        out.append(_spec_to_field("weekly_next_plan", "الأعمال المخطط لها الأسبوع القادم (7 بنود)", "textarea", False))
        out.append(_spec_to_field("weekly_conclusion", "الخلاصة", "textarea", False))
    if template_key == "safety":
        out += [_spec_to_field(k, lb, "table", False, [], cols)
                for k, lb, cols in SAFETY_TABLES]
    if template_key == "monthly":
        out += [_spec_to_field(k, lb, "table", False, [], cols)
                for k, lb, cols in MONTHLY_TABLES]
    return out


def ensure_default_templates(db, ReportTemplate, DynamicField, admin_id=None):
    """Idempotent: create missing system templates + their fields."""
    for t in DEFAULT_TEMPLATES:
        tpl = ReportTemplate.query.filter_by(key=t["key"]).first()
        if not tpl:
            tpl = ReportTemplate(key=t["key"], name_ar=t["name_ar"],
                                 name_en=t.get("name_en", ""),
                                 description=t.get("description", ""),
                                 icon=t.get("icon", "📋"),
                                 gradient=t.get("gradient", ""),
                                 is_system=t.get("is_system", False),
                                 created_by_id=admin_id)
            db.session.add(tpl)
            db.session.flush()
        # add missing fields only
        existing = {f.field_key for f in tpl.fields.all()}
        for pos, f in enumerate(default_fields_for(t["key"])):
            if f["key"] not in existing:
                db.session.add(DynamicField(
                    template_id=tpl.id, field_key=f["key"],
                    label_ar=f["label_ar"], field_type=f["type"],
                    options=f["options"], required=f["required"],
                    rules={}, sub_fields=f.get("columns") or [],
                    position=pos, placeholder=f["placeholder"]))
    db.session.commit()
