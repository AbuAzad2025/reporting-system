"""Batch PDF aggregation — one indexed multi-report document per export.

Cover page (project, date range, generated-by/at) + summary page (counts per
module, billing totals, variance totals, approval split) + numbered index +
one condensed section per record. Managers pick project + date range (+module
filter) and download a single print-ready file.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable, PageBreak)

from utils.pdf_generator import (_styles, _section_title, _kv_table, _brand_logo,
                                 ar)
from app.ops.models import OPS_MODULES

NAVY = colors.HexColor("#1e3a5f")
GOLD = colors.HexColor("#c9a227")
LIGHT = colors.HexColor("#eef3f7")

#: condensed per-record rows: (attribute, Arabic label)
CONDENSED = {
    "site-inspections": [("test_type", "الاختبار"), ("result_value", "النتيجة"),
                         ("verdict", "الحكم")],
    "material-submittals": [("material_name", "المادة"),
                            ("submittal_no", "رقم التقديم"),
                            ("quantity", "الكمية")],
    "rfis": [("subject", "الموضوع"), ("ball_in_court", "المسؤول"),
             ("priority", "الأولوية")],
    "cost-variances": [("boq_item", "البند"), ("variance", "الفرق"),
                       ("variance_pct", "النسبة %")],
    "progress-billings": [("work_item", "البند"), ("gross", "الإجمالي"),
                          ("net_payable", "الصافي")],
    "subcontractor-performances": [("subcontractor", "المقاول"),
                                   ("overall", "المتوسط"),
                                   ("grade", "التقدير")],
    "daily-reports": [("weather", "الطقس"),
                      ("manpower_total", "القوى العاملة"),
                      ("equipment_hours_total", "ساعات المعدات")],
    "variation-orders": [("title", "التغيير"),
                         ("impact_signed", "الأثر المالي"),
                         ("recommendation", "التوصية")],
    "safety-reports": [("area", "المنطقة"), ("risk_level", "الخطورة"),
                       ("responsible", "المسؤول")],
}


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    s = str(v).strip()
    return s if s else "—"


def collect_batch(model_map, user, project_id=None, date_from=None,
                  date_to=None, kinds=None):
    """Tenant-scoped collection across modules, oldest first. Pure query
    helper shared by the endpoint and tests."""
    from app.ops.isolation import scope_to_tenant
    kinds = kinds or list(model_map)
    out = []
    for kind in kinds:
        if kind not in model_map:
            continue
        model = model_map[kind]
        q = scope_to_tenant(model.query, model, user)
        if project_id:
            q = q.filter_by(project_id=int(project_id))
        if date_from:
            q = q.filter(model.report_date >= date_from)
        if date_to:
            q = q.filter(model.report_date <= date_to)
        for r in q.order_by(model.report_date, model.id).all():
            out.append((kind, r))
    out.sort(key=lambda kr: (str(kr[1].report_date), kr[1].id))
    return out


def batch_summary(records) -> dict:
    """Aggregate counts + financial totals for the summary page."""
    by_module: dict = {}
    by_status: dict = {}
    billing_net = billing_gross = variance = 0.0
    for kind, r in records:
        by_module[kind] = by_module.get(kind, 0) + 1
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if kind == "progress-billings":
            billing_net += r.net_payable or 0
            billing_gross += r.gross or 0
        if kind == "cost-variances":
            variance += r.variance or 0
    return {"total": len(records), "by_module": by_module,
            "by_status": by_status,
            "billing_gross": round(billing_gross, 2),
            "billing_net": round(billing_net, 2),
            "cost_variance": round(variance, 2)}


def build_batch_pdf(records, project_name: str, date_from: str, date_to: str,
                    generated_by: str, generated_at: str = "") -> bytes:
    """Render the aggregated document. `records` = [(kind, record)]."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10 * mm,
                            leftMargin=10 * mm, topMargin=12 * mm,
                            bottomMargin=36, title="Azadexa-Batch-Export")
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    story = []

    # ---- cover
    story.append(Spacer(1, 22 * mm))
    _logo = _brand_logo(width_mm=34)
    if _logo is not None:
        story.append(_logo)
        story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(ar("شركة المقاولات العامة"), st["subtitle"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(ar("منصة أزادكسا — مجمع التقارير التشغيلية"),
                           st["title"]))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.2, color=GOLD))
    story.append(Spacer(1, 6 * mm))
    story.append(_kv_table([
        ("المشروع", project_name or "كل المشاريع المتاحة"),
        ("الفترة", f"{date_from or '—'} ← {date_to or '—'}"),
        ("عدد التقارير", str(len(records))),
        ("أُعد بواسطة", generated_by),
        ("تاريخ الإصدار", stamp),
    ], st))
    story.append(PageBreak())

    # ---- summary
    summary = batch_summary(records)
    story.append(_section_title("صفحة الملخص", st))
    story.append(Spacer(1, 3 * mm))
    story.append(_kv_table(
        [("إجمالي التقارير", str(summary["total"]))]
        + [(f"تقارير: {OPS_MODULES[k][2]}", str(c))
           for k, c in summary["by_module"].items()]
        + [(f"الحالة: {s}", str(c))
           for s, c in summary["by_status"].items()]
        + [("إجمالي المستخلصات (إجمالي)", f"{summary['billing_gross']:,.2f}"),
           ("إجمالي المستخلصات (صافي)", f"{summary['billing_net']:,.2f}"),
           ("صافي فروقات التكلفة", f"{summary['cost_variance']:,.2f}")], st))
    story.append(PageBreak())

    # ---- index
    story.append(_section_title("الفهرس", st))
    story.append(Spacer(1, 3 * mm))
    index_rows = []
    for i, (kind, r) in enumerate(records, 1):
        _m, _p, name_ar, _e = OPS_MODULES[kind]
        index_rows.append([
            Paragraph(ar(f"{i}. {r.serial} — {name_ar} — {r.report_date} — "
                         f"{r.status_ar}"), st["cell"])])
    if not index_rows:
        index_rows = [[Paragraph(ar("لا توجد تقارير ضمن النطاق المحدد."),
                                 st["cell"])]]
    index = Table(index_rows, colWidths=[190 * mm])
    index.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(index)
    story.append(PageBreak())

    # ---- one condensed section per record
    for i, (kind, r) in enumerate(records, 1):
        _m, _p, name_ar, _e = OPS_MODULES[kind]
        story.append(_section_title(f"{i}. {r.serial} — {name_ar}", st))
        story.append(Spacer(1, 3 * mm))
        rows = [("التاريخ", str(r.report_date)), ("الحالة", r.status_ar),
                ("الموقّع", r.signatory_name or "—"),
                ("الإصدار", f"v{r.version or 1}")]
        for attr, label in CONDENSED.get(kind, []):
            try:
                rows.append((label, _fmt(getattr(r, attr, ""))))
            except Exception:
                rows.append((label, "—"))
        story.append(_kv_table(rows, st))
        story.append(Spacer(1, 5 * mm))

    # ---- footer branding (company header; AZAD brand in footer strip)
    def _batch_footer(canvas, doc):
        from utils.pdf_generator import _footer
        # company strip (MoPWH official document practice)
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#1a1610"))
        canvas.rect(0, 0, A4[0], 22, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#a67c00"))
        canvas.setLineWidth(2)
        canvas.line(0, 22, A4[0], 22)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(A4[0] / 2, 14,
                                 "شركة المقاولات العامة  —  منصة تقارير المشاريع الإنشائية")
        canvas.setFont("Helvetica", 7)
        canvas.drawString(10 * mm, 5,
                          "منصة أزادكسا | AZAD Intelligent Systems  •  م. أحمد غنيم")
        canvas.drawRightString(A4[0] - 10 * mm, 5,
                               f"صفحة {doc.page}")
        canvas.restoreState()
        # shared footer (page number + branding)
        _footer(canvas, doc)

    doc.build(story, onFirstPage=_batch_footer, onLaterPages=_batch_footer)
    return buf.getvalue()
