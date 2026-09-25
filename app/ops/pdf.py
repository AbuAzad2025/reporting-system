"""Professional engineering PDFs for the nine Azadexa ops modules.

Every document carries: corporate branding header, unique serial number,
status watermark (DRAFT/APPROVED/REJECTED semantics), formatted data tables,
computed financial summaries, quad-name authentication + approval trail.
Retrieval is mapped 1:1 to serials via protected /ops/.../pdf endpoints.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)

from utils.pdf_generator import (_styles, _section_title, _kv_table, _footer,
                                 ar)
from app.ops.models import OPS_MODULES

NAVY = colors.HexColor("#1e3a5f")
GOLD = colors.HexColor("#c9a227")
LIGHT = colors.HexColor("#eef3f7")

#: attribute -> Arabic label per module (render order)
OPS_PDF_FIELDS = {
    "site-inspections": [
        ("test_category", "فئة الاختبار"), ("test_type", "نوع الاختبار"),
        ("element", "العنصر الإنشائي"), ("axes", "المحاور"),
        ("location_detail", "موقع العينة"), ("spec_reference", "المرجع / المواصفة"),
        ("standard_code", "الكود المرجعي (ASTM/ACI/BS)"),
        ("concrete_class", "رتبة الخرسانة"), ("slump", "الهبوط (مم)"),
        ("cube_ids", "أرقام المكعبات"),
        ("result_value", "نتيجة القياس"), ("result_unit", "الوحدة"),
        ("acceptance_min", "الحد الأدنى للقبول"), ("acceptance_max", "الحد الأقصى للقبول"),
        ("verdict", "الحكم"), ("lab_name", "المختبر"),
        ("pour_permit_ref", "مرجع إذن الصب"), ("witness", "جهة الحضور"),
        ("follow_up", "إجراء المتابعة"), ("attachments", "عدد المرفقات"),
        ("notes", "ملاحظات"),
    ],
    "material-submittals": [
        ("material_name", "اسم المادة"), ("spec_section", "بند المواصفة"),
        ("submittal_no", "رقم التقديم"), ("revision", "المراجعة"),
        ("supplier", "المورّد"), ("manufacturer", "المصنّع"),
        ("origin_country", "بلد المنشأ"),
        ("quantity", "الكمية"), ("unit", "الوحدة"),
        ("sample_location", "موقع العينة"),
        ("certificates", "شهادات المطابقة"),
        ("test_report_ref", "مرجع تقرير الفحص"),
        ("consultant_action", "رمز الاستشاري (A/B/C/D)"),
        ("resubmit_due", "مهلة إعادة التقديم"), ("notes", "ملاحظات"),
    ],
    "rfis": [
        ("subject", "الموضوع"), ("discipline", "التخصص"),
        ("question", "نص الاستفسار"), ("drawing_ref", "مرجع المخطط"),
        ("spec_ref", "مرجع المواصفة"),
        ("ball_in_court", "الكرة في ملعب"), ("priority", "الأولوية"),
        ("cost_impact", "الأثر المالي"), ("delay_days", "أيام التأخير"),
        ("reply_due", "الرد مستحق بتاريخ"), ("date_replied", "تاريخ الرد"),
        ("reply_summary", "ملخص الرد"), ("response_action", "الإجراء المتخذ"),
    ],
    "cost-variances": [
        ("boq_item", "بند جدول الكميات"), ("boq_ref", "مرجع البند"),
        ("unit", "الوحدة"), ("currency", "العملة"),
        ("budgeted_qty", "الكمية المعتمدة"),
        ("budgeted_rate", "السعر المعتمد"), ("actual_qty", "الكمية الفعلية"),
        ("actual_rate", "السعر الفعلي"), ("reestimated_qty", "كمية إعادة التقدير"),
        ("reestimated_rate", "سعر إعادة التقدير"), ("reason", "سبب الفرق"),
        ("corrective_action", "الإجراء التصحيحي"),
        ("vo_ref", "الأمر التغييري المرتبط"),
        ("schedule_impact_days", "الأثر الزمني (أيام)"),
    ],
    "progress-billings": [
        ("cert_no", "رقم المستخلص"), ("boq_ref", "مرجع البند"),
        ("period_from", "الفترة من"),
        ("period_to", "الفترة إلى"), ("work_item", "بند الأعمال"),
        ("qty_completed", "الكمية المنجزة"), ("rate", "السعر"),
        ("progress_pct", "نسبة إنجاز البند (%)"),
        ("measurement_ref", "مرجع الحصر/القياس"),
        ("retention_pct", "نسبة المحجوز (%)"),
        ("previously_certified", "المعتمد سابقاً"), ("notes", "ملاحظات"),
    ],
    "subcontractor-performances": [
        ("subcontractor", "المقاول من الباطن"), ("trade", "التخصص"),
        ("period", "الفترة"), ("quality_score", "الجودة /100"),
        ("schedule_score", "الالتزام الزمني /100"), ("safety_score", "السلامة /100"),
        ("compliance_score", "الالتزام التعاقدي /100"),
        ("delay_days", "أيام التأخير"), ("penalty", "غرامات / حسميات"),
        ("incidents", "حوادث السلامة"),
        ("recommended_payment", "الدفعة الموصى بها"),
        ("recommendation", "التوصية"), ("remarks", "ملاحظات التقييم"),
    ],
    "daily-reports": [
        ("weather", "الطقس"), ("temp_c", "درجة الحرارة (°م)"),
        ("work_hours", "ساعات العمل"),
        ("engineers_count", "عدد المهندسين"),
        ("technicians_count", "عدد الفنيين"), ("labor_count", "عدد العمال"),
        ("labor_table", "جدول القوى العاملة"),
        ("equipment_table", "جدول المعدات"),
        ("work_fronts", "جدول ميادين العمل"),
        ("review_notes", "ملاحظات المراجعة"),
    ],
    "variation-orders": [
        ("vo_no", "رقم الأمر"), ("title", "عنوان التغيير"),
        ("category", "تصنيف التغيير"), ("boq_ref", "البند المرتبط"),
        ("description", "الوصف الفني"), ("reason", "المبررات"),
        ("cost_impact", "الأثر المالي"), ("currency", "العملة"),
        ("time_impact_days", "الأثر الزمني (أيام)"),
        ("recommendation", "التوصية"), ("attachments", "عدد المرفقات"),
    ],
    "safety-reports": [
        ("area", "منطقة التفتيش"), ("inspection_type", "نوع التفتيش"),
        ("hazard", "الخطر المرصود"), ("risk_level", "درجة الخطورة"),
        ("corrective_action", "الإجراء التصحيحي"),
        ("responsible", "الجهة المسؤولة"), ("target_date", "تاريخ المعالجة"),
        ("closure_date", "تاريخ الإغلاق"),
        ("incidents_count", "عدد الحوادث"),
        ("lost_time_injuries", "إصابات مهدرة للوقت"),
        ("toolbox_talks", "محاضرات التوعية"),
        ("ppe_compliance", "الالتزام بمهمات الوقاية (%)"),
    ],
}

#: computed summary rows per module: (label, callable)
OPS_PDF_COMPUTED = {
    "site-inspections": [
        ("الحكم المحسوب من نافذة القبول",
         lambda r: "ناجح" if r.computed_pass is True
         else ("راسب" if r.computed_pass is False else "غير قابل للقياس")),
    ],
    "rfis": [("أيام الانفتاح", lambda r: str(r.days_open))],
    "cost-variances": [
        ("إجمالي المعتمد", lambda r: f"{r.budgeted_total:,.2f}"),
        ("إجمالي الفعلي", lambda r: f"{r.actual_total:,.2f}"),
        ("الفرق (فعلي − معتمد)", lambda r: f"{r.variance:,.2f}"),
        ("نسبة الفرق %", lambda r: f"{r.variance_pct:.2f} %"),
        ("إجمالي إعادة التقدير",
         lambda r: f"{r.reestimated_total:,.2f}"
         if r.reestimated_total is not None else "—"),
    ],
    "progress-billings": [
        ("الإجمالي (كمية × سعر)", lambda r: f"{r.gross:,.2f}"),
        ("المحجوز", lambda r: f"{r.retention:,.2f}"),
        ("الصافي المستحق", lambda r: f"{r.net_payable:,.2f}"),
        ("التراكمي (سابق + صافي)", lambda r: f"{r.cumulative:,.2f}"),
    ],
    "subcontractor-performances": [
        ("المتوسط الموزون", lambda r: f"{r.overall:.2f} / 100"),
        ("التقدير", lambda r: r.grade),
    ],
    "daily-reports": [
        ("إجمالي القوى العاملة", lambda r: str(r.manpower_total)),
    ],
    "variation-orders": [
        ("الأثر المالي الموقّع", lambda r: r.impact_signed),
    ],
    "safety-reports": [
        ("حالة الملاحظة",
         lambda r: "مغلقة" if r.is_closed else "مفتوحة"),
    ],
}


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    s = str(value).strip()
    return s if s else "—"


def _ops_header(project_owner, consultant, contractor, st):
    """Mandatory 3-party contractual header — zero branding."""
    data = [
        [Paragraph(ar("صاحب العمل / المالك"), st["cell_h"]),
         Paragraph(ar(project_owner or "—"), st["cell"]),
         Paragraph(ar("الاستشاري / الجهة المشرفة"), st["cell_h"]),
         Paragraph(ar(consultant or "—"), st["cell"]),
         Paragraph(ar("المقاول / شركة التنفيذ"), st["cell_h"]),
         Paragraph(ar(contractor or "—"), st["cell"])],
    ]
    t = Table(data, colWidths=[32 * mm, 30 * mm, 32 * mm, 30 * mm, 32 * mm, 34 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def build_ops_pdf(kind: str, record, project_name: str = "",
                  reviewer_name: str = "", generated_at: str = "",
                  project_owner: str = "", consultant: str = "",
                  contractor: str = "") -> bytes:
    """Render the professional A4 PDF for one ops record."""
    if kind not in OPS_MODULES:
        raise ValueError(f"unknown ops module: {kind}")
    _m, _prefix, name_ar, name_en = OPS_MODULES[kind]
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, rightMargin=10 * mm, leftMargin=10 * mm,
        topMargin=12 * mm, bottomMargin=36,
        title=f"{record.serial}-{kind}")

    watermark = "DRAFT" if record.status == "draft" else ""

    def _on_page(canvas, _doc):
        if watermark:
            canvas.saveState()
            canvas.setFillColor(colors.HexColor("#e3e9ef"))
            canvas.setFont("Helvetica-Bold", 64)
            canvas.rotate(30)
            canvas.drawCentredString(A4[0] * 0.85, A4[1] * 0.28, watermark)
            canvas.restoreState()
        _footer(canvas, _doc, serial=record.serial,
                timestamp=generated_at or datetime.now().strftime("%Y-%m-%d %H:%M"))

    story = []
    story.append(_ops_header(project_owner, consultant, contractor, st))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.2, color=GOLD))
    story.append(Spacer(1, 4 * mm))

    # identity grid: serial / project / date / status
    info_rows = [
        [Paragraph(ar(record.serial), st["cell"]),
         Paragraph(ar("الرقم التسلسلي"), st["cell_h"])],
        [Paragraph(ar(project_name or "—"), st["cell"]),
         Paragraph(ar("المشروع"), st["cell_h"])],
        [Paragraph(ar(str(record.report_date)), st["cell"]),
         Paragraph(ar("التاريخ"), st["cell_h"])],
        [Paragraph(ar(record.status_ar), st["cell"]),
         Paragraph(ar("الحالة"), st["cell_h"])],
    ]
    info = Table(info_rows, colWidths=[140 * mm, 50 * mm])
    info.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info)
    story.append(Spacer(1, 5 * mm))

    # details
    story.append(_section_title(f"تفاصيل {name_ar}", st))
    story.append(Spacer(1, 3 * mm))
    items = [(label, _fmt(getattr(record, attr, "")))
             for attr, label in OPS_PDF_FIELDS[kind]]
    story.append(_kv_table(items, st))
    story.append(Spacer(1, 4 * mm))

    # computed engineering/financial summary
    computed = OPS_PDF_COMPUTED.get(kind, [])
    if computed:
        story.append(_section_title("الملخص المحسوب", st))
        story.append(Spacer(1, 3 * mm))
        try:
            summary = [(label, fn(record)) for label, fn in computed]
        except Exception:
            summary = [(label, "—") for label, _fn in computed]
        story.append(_kv_table(summary, st))
        story.append(Spacer(1, 4 * mm))

    # evidence appendix: embedded uploaded attachments
    try:
        from app.ops.models import Attachment
        atts = Attachment.query.filter_by(
            record_kind=kind, record_id=record.id).order_by(
                Attachment.created_at.desc()).all()
    except Exception:
        atts = []
    if atts:
        story.append(_section_title("المرفقات والأدلة", st))
        story.append(Spacer(1, 3 * mm))
        first = atts[0]
        att_rows = [[Paragraph(ar(first.filename), st["cell"]),
                     Paragraph(ar(first.mime_type), st["cell"]),
                     Paragraph(first.created_at.strftime("%Y-%m-%d %H:%M")
                               if first.created_at else "—", st["cell"])]]
        for att in atts[1:]:
            att_rows.append([Paragraph(ar(att.filename), st["cell"]),
                             Paragraph(ar(att.mime_type), st["cell"]),
                             Paragraph(att.created_at.strftime("%Y-%m-%d %H:%M")
                                       if att.created_at else "—", st["cell"])])
        att_tbl = Table(att_rows, colWidths=[90 * mm, 50 * mm, 50 * mm])
        att_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(att_tbl)
        story.append(Spacer(1, 4 * mm))

    # approval + quad-name authentication block
    story.append(_section_title("التوقيع والاعتماد", st))
    story.append(Spacer(1, 3 * mm))
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    sig_rows = [
        [Paragraph(ar(record.signatory_name or "—"), st["cell"]),
         Paragraph(ar("مُعد التقرير (الاسم الرباعي)"), st["cell_h"])],
        [Paragraph(ar(reviewer_name
                      if record.status != "pending" else "بانتظار المراجعة"),
                   st["cell"]),
         Paragraph(ar("المراجع / المعتمد"), st["cell_h"])],
        [Paragraph(ar(record.review_notes or "—"), st["cell"]),
         Paragraph(ar("ملاحظات الاعتماد"), st["cell_h"])],
        [Paragraph(ar(stamp), st["cell"]),
         Paragraph(ar("تاريخ ووقت الإصدار"), st["cell_h"])],
    ]
    sig = Table(sig_rows, colWidths=[140 * mm, 50 * mm])
    sig.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#fff7dd")),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(sig)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        ar("أقر بأن البيانات المذكورة أعلاه صحيحة ومطابقة للواقع، وأن الأرقام "
           "المحسوبة ناتجة عن المعادلات المعتمدة في النظام."),
        st["cell_small"]))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
