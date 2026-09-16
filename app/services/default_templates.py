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


#: Line-item tables appended to the daily site diary (UNRWA daily practice):
#: manpower tiers, plant, deliveries, visitors/meetings.
DAILY_TABLES = [
    ("manpower_table", "جدول القوى العاملة", [
        {"key": "name", "label_ar": "الاسم", "type": "text",
         "required": True, "options": []},
        {"key": "role", "label_ar": "المهنة", "type": "dropdown",
         "required": True,
         "options": ["مهندس", "فني", "عامل", "سائق", "حارس"]},
        {"key": "count", "label_ar": "العدد", "type": "number",
         "required": True, "options": []},
        {"key": "notes", "label_ar": "ملاحظات", "type": "text",
         "required": False, "options": []},
    ]),
    ("equipment_table", "جدول المعدات والآليات", [
        {"key": "type", "label_ar": "نوع المعدة", "type": "text",
         "required": True, "options": []},
        {"key": "count", "label_ar": "العدد", "type": "number",
         "required": True, "options": []},
        {"key": "hours", "label_ar": "ساعات التشغيل", "type": "number",
         "required": False, "options": []},
        {"key": "status", "label_ar": "الحالة", "type": "dropdown",
         "required": False, "options": ["عاملة", "معطلة", "احتياط"]},
    ]),
    ("materials_table", "جدول المواد المستلمة", [
        {"key": "material", "label_ar": "المادة", "type": "text",
         "required": True, "options": []},
        {"key": "qty", "label_ar": "الكمية", "type": "number",
         "required": True, "options": []},
        {"key": "unit", "label_ar": "الوحدة", "type": "text",
         "required": False, "options": []},
        {"key": "supplier", "label_ar": "المورّد", "type": "text",
         "required": False, "options": []},
    ]),
    ("visitors_table", "جدول الزوار والاجتماعات", [
        {"key": "name", "label_ar": "الاسم", "type": "text",
         "required": True, "options": []},
        {"key": "org", "label_ar": "الجهة", "type": "text",
         "required": False, "options": []},
        {"key": "purpose", "label_ar": "الغرض", "type": "text",
         "required": False, "options": []},
        {"key": "time", "label_ar": "الوقت", "type": "text",
         "required": False, "options": []},
    ]),
]


def default_fields_for(template_key):
    """Return ordered field dicts for a template key."""
    if template_key in EXTRA_SPECS:
        return [_spec_to_field(k, lb, kd, req, opts if len(r) > 4 else [])
                for r in EXTRA_SPECS[template_key]
                for (k, lb, kd, req, *opts) in [r]]
    # v1 static specs -> required only for the two most critical daily fields
    out = []
    for k, label, kind in FIELD_SPECS.get(template_key, []):
        req = template_key == "daily" and k in ("manpower", "works_completed")
        out.append(_spec_to_field(k, label, kind, req))
    if template_key == "daily":
        out += [_spec_to_field(k, lb, "table", False, [], cols)
                for k, lb, cols in DAILY_TABLES]
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
