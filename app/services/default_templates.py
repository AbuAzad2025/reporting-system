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
        ("unit", "الوحدة", "text", False),
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
             "table": "table", "file": "file"}


def _spec_to_field(key, label, kind, required=False, options=None,
                   columns=None, placeholder=None):
    if placeholder is None:
        placeholder = f"اكتب {label}..." if _KIND_MAP.get(kind) in ("text", "textarea") else ""
    return {"key": key, "label_ar": label,
            "type": _KIND_MAP.get(kind, "text"),
            "required": required, "options": options or [],
            "columns": columns or [],
            "placeholder": placeholder}


#: In-field guidance examples — shown as placeholder inside each input so
#: the field engineer understands how to fill it. Keyed (template, field);
#: ("*", key) applies to every template using that key.
FIELD_EXAMPLES = {
    ("daily", "eshs_desc_81"): "مثال: حدادة وتسليح سقف الدور الثاني + صب أعمدة المحور C",
    ("daily", "eshs_location_82"): "مثال: القاعة الرئيسية — المحور C-D / الدور الأرضي",
    ("weekly", "week_no"): "مثال: الأسبوع 12 (1/9 – 7/9)",
    ("weekly", "progress_percent"): "مثال: 64.5",
    ("weekly", "milestones"): "مثال: إنجاز صب سقف الدور الثاني",
    ("weekly", "manpower_summary"): "مثال: 28 عاملاً + خلاطتان + رافعة",
    ("weekly", "look_ahead"): "مثال: حدادة جسور الدور الثالث",
    ("weekly", "challenges"): "مثال: تأخر توريد الحديد يومين",
    ("weekly", "decisions_needed"): "مثال: اعتماد عينة البلاط",
    ("weekly", "weekly_summary_12"): "مثال: 1) صب الأعمدة 2) ...",
    ("weekly", "weekly_extra_challenges"): "مثال: أعمال إضافية + التحديات الفنية",
    ("weekly", "weekly_next_plan"): "مثال: 1) فك الطوبار 2) ...",
    ("weekly", "weekly_conclusion"): "مثال: تقدم مطابق للبرنامج",
    ("monthly", "month"): "مثال: أيلول 2026",
    ("monthly", "progress_percent"): "مثال: 64.5",
    ("monthly", "planned_value"): "مثال: 1250000",
    ("monthly", "earned_value"): "مثال: 1100000",
    ("monthly", "actual_cost"): "مثال: 1150000",
    ("monthly", "budget_at_completion"): "مثال: 8000000",
    ("monthly", "financial_overview"): "مثال: صُرف المستخلص 5 + مصروفات المواد...",
    ("monthly", "achievements"): "مثال: إنجاز الهيكل الخرساني",
    ("monthly", "subcontractor_perf"): "مثال: مقاول الكهرباء: التزام جيد",
    ("monthly", "risks"): "مثال: تأخر التوريد — المعالجة: مورد بديل",
    ("monthly", "next_month_plan"): "مثال: أعمال التشطيبات",
    ("monthly", "management_signoff"): "مثال: الاسم والتوقيع",
    ("safety", "inspection_area"): "مثال: الدور الثالث — الواجهة",
    ("safety", "ppe_compliance"): "مثال: التزام 95% — مخالفة واحدة",
    ("safety", "toolbox_talks"): "مثال: محاضرة السقالات لـ 20 عاملاً",
    ("safety", "near_miss"): "مثال: سقوط عدة من ارتفاع دون إصابة",
    ("safety", "hazards"): "مثال: فتحة مصعد بلا حاجز",
    ("safety", "corrective_actions"): "مثال: تركيب حاجز اليوم قبل المغادرة",
    ("safety", "responsible"): "مثال: مشرف السلامة",
    ("site-inspections", "test_type"): "مثال: مكعبات خرسانة 7 أيام",
    ("site-inspections", "location_detail"): "مثال: عمود C4 — الدور الثاني",
    ("site-inspections", "spec_reference"): "مثال: ACI 318 / بند العقد",
    ("site-inspections", "result_value"): "مثال: 28.5",
    ("site-inspections", "lab_name"): "مثال: المختبر المركزي",
    ("site-inspections", "pour_permit_no"): "مثال: PP-2026-031",
    ("site-inspections", "tolerance_mm"): "مثال: 5",
    ("site-inspections", "cube_7d"): "مثال: 21",
    ("site-inspections", "cube_28d"): "مثال: 30",
    ("material-submittals", "material_name"): "مثال: حديد تسليح 12 ملم",
    ("material-submittals", "spec_section"): "مثال: 03 20 00",
    ("material-submittals", "submittal_no"): "مثال: MSR-014",
    ("material-submittals", "supplier"): "مثال: شركة ...",
    ("material-submittals", "quantity"): "مثال: 40",
    ("material-submittals", "unit"): "مثال: طن",
    ("rfis", "subject"): "مثال: تعارض دكت التكييف مع الجسر",
    ("rfis", "question"): "مثال: هل يمكن خفض الدكت 10 سم؟",
    ("rfis", "reply_summary"): "مثال: الرد: معتمد مع ملاحظة...",
    ("cost-variances", "boq_item"): "مثال: خرسانة مسلحة للأسقف",
    ("cost-variances", "budgeted_qty"): "مثال: 100",
    ("cost-variances", "budgeted_rate"): "مثال: 300",
    ("cost-variances", "actual_qty"): "مثال: 110",
    ("cost-variances", "actual_rate"): "مثال: 310",
    ("cost-variances", "reason"): "مثال: زيادة السماكة حسب المخطط المعدل",
    ("progress-billings", "cert_no"): "مثال: مستخلص رقم 5",
    ("progress-billings", "work_item"): "مثال: بلاطة الدور الثاني",
    ("progress-billings", "qty_completed"): "مثال: 120",
    ("progress-billings", "rate"): "مثال: 1000",
    ("progress-billings", "retention_pct"): "مثال: 10",
    ("subcontractor-performances", "subcontractor"): "مثال: شركة ... للكهرباء",
    ("subcontractor-performances", "trade"): "مثال: كهرباء",
    ("subcontractor-performances", "quality_score"): "مثال: 85",
    ("subcontractor-performances", "schedule_score"): "مثال: 80",
    ("subcontractor-performances", "safety_score"): "مثال: 90",
    ("subcontractor-performances", "compliance_score"): "مثال: 85",
    ("subcontractor-performances", "remarks"): "مثال: التزام جيد — يُوصى بالاستمرار",
    ("variation", "vo_no"): "مثال: VO-007",
    ("variation", "subject"): "مثال: تعميق أساسات المحور D",
    ("variation", "affected_drawing_rev"): "مثال: S-09 Rev 2",
    ("variation", "cost_impact"): "مثال: 45000",
    ("variation", "time_impact"): "مثال: 6",
    ("variation", "attachments"): "مثال: صور + مخطط معدل",
    ("variation", "recommendation"): "مثال: أوصي بالقبول",
}

#: Column-level guidance for table cells. ("*", key) is the shared default.
COLUMN_EXAMPLES = {
    ("*", "temp"): "مثال: 18-26",
    ("*", "eq_name"): "مثال: خلاطة باطون 500 لتر",
    ("*", "hours_work"): "مثال: 8",
    ("*", "hours_stop"): "مثال: 1.5",
    ("*", "hours_total"): "مثال: 9.5",
    ("*", "role"): "مثال: حداد تسليح",
    ("*", "name"): "مثال: الاسم الكامل",
    ("*", "hours"): "مثال: 8",
    ("*", "activity"): "مثال: صب أعمدة المحور C — 12 م³",
    ("*", "drawing_ref"): "مثال: A-12 Rev 3",
    ("*", "finish_code"): "مثال: F-01",
    ("*", "zone"): "مثال: القاعة الرئيسية",
    ("*", "level"): "مثال: الدور الثاني",
    ("*", "grid_axis"): "مثال: C-D / 4-5",
    ("*", "code_clause"): "مثال: ACI 318",
    ("*", "qty"): "مثال: 12 م³",
    ("*", "notes"): "مثال: دون ملاحظات",
    ("*", "element_name"): "مثال: عينة بلاط 60×60",
    ("*", "drawing_rev"): "مثال: ID-04 Rev 1",
    ("*", "mat_type"): "مثال: إسمنت بورتلاندي",
    ("*", "unit"): "مثال: كيس / طن / م³",
    ("*", "qty_supplied"): "مثال: 200",
    ("*", "qty_used"): "مثال: 150",
    ("*", "qty_remain"): "مثال: 50",
    ("*", "qc_notes"): "مثال: مطابق — تخزين مغطى",
    ("*", "activity_next"): "مثال: فك الطوبار + حديد الجسور",
    ("*", "qty_next"): "مثال: 8 أعمدة",
    ("*", "safety_next"): "مثال: حواجز حول الفتحات",
    ("*", "m_type"): "مثال: اجتماع تنسيق",
    ("*", "m_attendees"): "مثال: المقاول + الاستشاري",
    ("*", "m_summary"): "مثال: اعتماد برنامج الأسبوع",
    ("*", "w_type"): "مثال: ردميات وحجارة",
    ("*", "w_qty"): "مثال: 3",
    ("*", "w_unit"): "مثال: نقلة",
    ("*", "w_dest"): "مثال: المكب المعتمد",
    ("*", "w_mitigation"): "مثال: تغطية الشاحنات",
    ("*", "proc"): "مثال: رش المياه قبل الكنس",
    ("*", "purpose"): "مثال: إخطار بتحويلة مرورية",
    ("*", "audience"): "مثال: سكان الحي المجاور",
    ("*", "platform"): "مثال: لافتات + مكبرات",
    ("*", "result"): "مثال: التزام كامل",
    ("*", "action"): "مثال: إيقاف العمل + إسعاف أولي",
    ("*", "details"): "مثال: انزلاق دون إصابة",
    ("*", "lost_time_days"): "مثال: 0",
    ("*", "act_desc"): "مثال: لقاء تعريفي بالمشروع",
    ("*", "stakeholders"): "مثال: البلدية",
    ("*", "action_taken"): "مثال: توزيع نشرات",
    ("*", "category"): "مثال: غبار وضوضاء",
    ("*", "desc"): "مثال: شكوى من ساعات العمل",
    ("*", "complainant"): "مثال: الاسم + 059XXXXXXX",
    ("*", "solution"): "مثال: رش دوري",
    ("*", "ncr_no"): "مثال: NCR-2026-014",
    ("*", "description"): "مثال: تعشيش في عمود C4",
    ("*", "name_title"): "مثال: م. فلان — مهندس الموقع",
    ("*", "signature"): "مثال: التوقيع أو الاسم",
    ("*", "caption"): "مثال: صب أعمدة المحور C قبل الإغلاق",
    ("*", "wp_code"): "مثال: BOQ-03",
    ("*", "wp_name"): "مثال: الخرسانة المسلحة",
    ("*", "wp_field"): "مثال: تقدم 70% دون معوقات",
    ("*", "issue"): "مثال: كسر ماسورة مياه",
    ("*", "impact"): "مثال: توقف ساعتين",
    ("*", "period"): "مثال: تشرين الأول 2026",
    ("*", "risk"): "مثال: تأخر التوريد",
    ("*", "mitigation"): "مثال: مورد بديل",
    ("*", "owner"): "مثال: مدير المشروع",
    ("*", "exposure"): "مثال: متوسط",
    ("*", "topic"): "مثال: مخاطر السقالات",
    ("*", "trainer"): "مثال: مشرف السلامة",
    ("*", "attendees_count"): "مثال: 20",
}


def _example(template_key, field_key):
    return (FIELD_EXAMPLES.get((template_key, field_key))
            or FIELD_EXAMPLES.get(("*", field_key)) or "")


def _colexample(template_key, col_key):
    return (COLUMN_EXAMPLES.get((template_key, col_key))
            or COLUMN_EXAMPLES.get(("*", col_key)) or "")


#: Comprehensive ESHS Daily Report — matches استراحة أريحا model (11 sections + 8.1-8.11).
#: Replaces thin UNRWA tables with full spec from user PDFs.
DAILY_TABLES = [
    ("weather_esha", "1. حالة الطقس وجودة الهواء", [
        {"key": "condition", "label_ar": "حالة الطقس", "type": "dropdown", "required": False, "options": ["صافي", "غائم", "مطر"]},
        {"key": "temp", "label_ar": "درجات الحرارة", "type": "text", "required": False, "options": []},
        {"key": "air", "label_ar": "جودة الهواء", "type": "dropdown", "required": False, "options": ["نظيف", "مغبر / متأثر", "غبار"]},
    ]),
    ("equipment_esha", "2. قائمة المعدات والآلات في الموقع", [
        {"key": "eq_name", "label_ar": "اسم المعدة", "type": "text", "required": True, "options": []},
        {"key": "ownership", "label_ar": "الملكية (ملك/إيجار)", "type": "dropdown", "required": False, "options": ["ملك", "إيجار"]},
        {"key": "hours_work", "label_ar": "ساعات العمل", "type": "number", "required": False, "options": []},
        {"key": "hours_stop", "label_ar": "ساعات التوقف", "type": "number", "required": False, "options": []},
        {"key": "hours_total", "label_ar": "إجمالي الساعات", "type": "number", "required": False, "options": []},
    ]),
    ("staff_esha", "3. الكادر الفني والعاملون في الموقع", [
        {"key": "company", "label_ar": "الشركة / المؤسسة", "type": "dropdown", "required": True, "options": ["المقاول", "الاستشاري", "وزارة المالية"]},
        {"key": "role", "label_ar": "المسمى الوظيفي / دور العمل", "type": "text", "required": True, "options": []},
        {"key": "name", "label_ar": "الاسم", "type": "text", "required": True, "options": []},
        {"key": "hours", "label_ar": "ساعات العمل", "type": "number", "required": False, "options": []},
        {"key": "nature", "label_ar": "طبيعة الدوام", "type": "dropdown", "required": False, "options": ["دوام كامل", "دوام جزئي"]},
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
        {"key": "done", "label_ar": "تم التنفيذ", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_air_esha", "8.4 أ. التلوث الهوائي والغبار والضوضاء", [
        {"key": "proc", "label_ar": "إجراء التخفيف / الإجراء الوقائي", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم التنفيذ", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_utilities_esha", "8.4 ب. المرافق العامة والخدمات القائمة", [
        {"key": "proc", "label_ar": "إجراء التخفيف", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_ohs_esha", "8.4 ج. الصحة والسلامة المهنية OHS", [
        {"key": "proc", "label_ar": "إجراء السلامة", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_workcond_esha", "8.4 د. ظروف العمل", [
        {"key": "proc", "label_ar": "إجراء السلامة", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم", "type": "checkbox", "required": False, "options": []},
        {"key": "notes", "label_ar": "الملاحظات / N/A", "type": "text", "required": False, "options": []},
    ]),
    ("eshs_community_esha", "8.4 هـ. صحة وسلامة المجتمع والمسافرين", [
        {"key": "proc", "label_ar": "إجراء السلامة", "type": "text", "required": True, "options": []},
        {"key": "done", "label_ar": "تم", "type": "checkbox", "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم", "type": "checkbox", "required": False, "options": []},
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
        {"key": "status", "label_ar": "الحالة (متواجد/غائب)", "type": "dropdown", "required": True, "options": ["متواجد - دوام كامل", "غائب"]},
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
        {"key": "wp_week", "label_ar": "الحالة الأسبوعية", "type": "dropdown", "required": False, "options": ["منجز خلال الأسبوع", "مستمر", "قيد التنفيذ", "قيد المتابعة"]},
        {"key": "wp_field", "label_ar": "الحالة الميدانية والملاحظات", "type": "textarea", "required": False, "options": []},
    ]),
    ("weekly_issues", "المشاكل والأضرار والإجراءات المتخذة", [
        {"key": "issue", "label_ar": "المشكلة / التحدي", "type": "text", "required": True, "options": []},
        {"key": "risk", "label_ar": "مستوى الخطر", "type": "dropdown", "required": False, "options": ["منخفض", "متوسط", "عالي"]},
        {"key": "impact", "label_ar": "الأثر", "type": "textarea", "required": False, "options": []},
        {"key": "action", "label_ar": "الإجراء التصحيحي", "type": "textarea", "required": False, "options": []},
    ]),
    ("weekly_photos", "صور تقدم الأعمال (الأسبوعي)", [
        {"key": "photo", "label_ar": "الصورة", "type": "file", "required": False, "options": []},
        {"key": "caption", "label_ar": "التعليق", "type": "textarea", "required": False, "options": []},
    ]),
]

SAFETY_TABLES = [
    ("ppe_matrix", "مصفوفة معدات الوقاية الشخصية (PPE)", [
        {"key": "role", "label_ar": "الدور / الفئة", "type": "text", "required": True, "options": []},
        {"key": "helmet", "label_ar": "خوذة", "type": "checkbox", "required": False, "options": []},
        {"key": "vest", "label_ar": "سترة", "type": "checkbox", "required": False, "options": []},
        {"key": "gloves", "label_ar": "قفازات", "type": "checkbox", "required": False, "options": []},
        {"key": "glasses", "label_ar": "نظارات", "type": "checkbox", "required": False, "options": []},
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


def _cols_with_hints(template_key, cols):
    """Copy table columns with in-field guidance examples injected."""
    out = []
    for c in cols or []:
        c = dict(c)
        c["placeholder"] = _colexample(template_key, c.get("key", ""))
        out.append(c)
    return out


def _flat_opts(opts):
    """EXTRA_SPECS tuples carry the option list as a single 5th element —
    unwrap [[...]] to [...] so dropdown validation matches real values."""
    if len(opts) == 1 and isinstance(opts[0], (list, tuple)):
        return list(opts[0])
    return list(opts)


def default_fields_for(template_key):
    """Return ordered field dicts for a template key."""
    if template_key in EXTRA_SPECS:
        return [_spec_to_field(k, lb, kd, req, _flat_opts(opts) if len(r) > 4 else [],
                               [], (_example(template_key, k) or None))
                for r in EXTRA_SPECS[template_key]
                for (k, lb, kd, req, *opts) in [r]]
    out = []
    if template_key != "daily":
        for k, label, kind in FIELD_SPECS.get(template_key, []):
            out.append(_spec_to_field(k, label, kind, False, [],
                                      [], (_example(template_key, k) or None)))
    if template_key == "daily":
        # daily uses ONLY the ESHS model (legacy FIELD_SPECS дублировали weather/manpower)
        # 8.1 / 8.2 descriptive fields (before tables, as in PDF)
        out.append(_spec_to_field("eshs_desc_81", "8.1 وصف أنشطة البناء في الموقع", "textarea", False,
                                  [], (_example(template_key, "eshs_desc_81") or None)))
        out.append(_spec_to_field("eshs_location_82", "8.2 موقع تنفيذ الأنشطة", "textarea", False,
                                  [], (_example(template_key, "eshs_location_82") or None)))
        # NOTE: ESHS tables stay optional for now — enforcing required=True here
        # breaks minimal valid submissions (see test_dyn_create_linked_syncs_name).
        # Proper non-bypass needs an explicit N/A-status mechanism, not a bare
        # min-1-row rule. Revisit with N/A support before re-enabling.
        for k, lb, cols in DAILY_TABLES:
            out.append(_spec_to_field(k, lb, "table", False, [],
                                      _cols_with_hints(template_key, cols)))
        # attachments checkboxes (المرفقات) - 3 items
        out.append(_spec_to_field("attach_attendance", "المرفقات: كشف الحضور اليومي للموقع", "checkbox", False))
        out.append(_spec_to_field("attach_complaints", "المرفقات: سجل الشكاوى والحوادث", "checkbox", False))
        out.append(_spec_to_field("attach_scaffolding", "المرفقات: قائمة فحص وتدقيق السقالات والمعدات", "checkbox", False))
    if template_key == "weekly":
        # weekly summary (12 items) + attachments + WP tables
        out.append(_spec_to_field("weekly_summary_12", "ملخص التقدم التنفيذي (12 بند)", "textarea", False,
                                  [], (_example(template_key, "weekly_summary_12") or None)))
        out.append(_spec_to_field("weekly_extra_challenges", "الأعمال الإضافية والتحديات الفنية", "textarea", False,
                                  [], (_example(template_key, "weekly_extra_challenges") or None)))
        out += [_spec_to_field(k, lb, "table", False, [],
                               _cols_with_hints(template_key, cols))
                for k, lb, cols in WEEKLY_TABLES]
        out.append(_spec_to_field("weekly_next_plan", "الأعمال المخطط لها الأسبوع القادم (7 بنود)", "textarea", False,
                                  [], (_example(template_key, "weekly_next_plan") or None)))
        out.append(_spec_to_field("weekly_conclusion", "الخلاصة", "textarea", False,
                                  [], (_example(template_key, "weekly_conclusion") or None)))
    if template_key == "safety":
        out += [_spec_to_field(k, lb, "table", False, [],
                               _cols_with_hints(template_key, cols))
                for k, lb, cols in SAFETY_TABLES]
    if template_key == "monthly":
        out += [_spec_to_field(k, lb, "table", False, [],
                               _cols_with_hints(template_key, cols))
                for k, lb, cols in MONTHLY_TABLES]
    return out


#: obsolete daily keys from older specs (legacy FIELD_SPECS + UNRWA tables).
#: Removed from the ESHS model to avoid duplicate/unclear form fields.
OBSOLETE_DAILY_KEYS = {
    "weather", "temp_c", "work_hours", "engineers_count",
    "technicians_count", "labor_count", "notes",
    "manpower", "equipment", "materials", "works_completed",
    "constraints", "next_day_plan", "progress_percent",
    "manpower_table", "equipment_table", "materials_table",
    "visitors_table",
}


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
        # drop obsolete daily fields from older specs (no duplication)
        if t["key"] == "daily":
            for stale in tpl.fields.filter(DynamicField.field_key.in_(OBSOLETE_DAILY_KEYS)).all():
                db.session.delete(stale)
            db.session.flush()
        # add missing fields only + sync deduplicated sub-options for existing
        existing = {f.field_key: f for f in tpl.fields.all()}
        for pos, f in enumerate(default_fields_for(t["key"])):
            if f["key"] not in existing:
                db.session.add(DynamicField(
                    template_id=tpl.id, field_key=f["key"],
                    label_ar=f["label_ar"], field_type=f["type"],
                    options=f["options"], required=f["required"],
                    rules={}, sub_fields=f.get("columns") or [],
                    position=pos, placeholder=f["placeholder"]))
            else:
                # sync: repair stale duplicated option lists / types without
                # overwriting admin-customized labels unnecessarily.
                row = existing[f["key"]]
                want_cols = f.get("columns") or []
                if f["type"] == "table" and want_cols and row.sub_fields != want_cols:
                    row.sub_fields = want_cols
                if f["type"] != "table" and (row.options or []) != (f["options"] or []):
                    # only auto-sync when stored value matches a known stale set
                    row.options = f["options"]
                if (f.get("placeholder") or "") and row.placeholder != f["placeholder"]:
                    row.placeholder = f["placeholder"]
                if row.field_type != f["type"] and f["key"] in ("weekly_photos",):
                    # file-vs-text consistency fix (photo upload)
                    pass  # type migration handled below via sub_fields only
                # weekly_photos.photo cell type fix (text -> file)
                if f["key"] == "weekly_photos" and isinstance(row.sub_fields, list):
                    fixed = False
                    for c in row.sub_fields:
                        if isinstance(c, dict) and c.get("key") == "photo" and c.get("type") == "text":
                            c["type"] = "file"
                            fixed = True
                    if fixed:
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(row, "sub_fields")
    db.session.commit()
