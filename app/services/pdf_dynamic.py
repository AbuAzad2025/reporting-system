"""Dynamic PDF service — renders ANY ReportTemplate + submission answers.

Reuses the corporate styling of utils/pdf_generator (header, gold rule,
info grid, navy section titles, signatory block, footer) but builds the
body table from DynamicField rows instead of hardcoded FIELD_SPECS.
"""
from datetime import datetime

from utils.pdf_generator import (_styles, _info_table, _section_title,
                                 _kv_table, _header_table, ar, NAVY,
                                 _footer)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                Table, TableStyle, HRFlowable)
from reportlab.lib import colors
import io
import logging

log = logging.getLogger(__name__)


class _DynReportAdapter:
    """Duck-type shim so shared header/info helpers accept a submission."""

    def __init__(self, submission, template):
        self.report_type = template.key
        self.project_name = submission.project_name
        self.location = submission.location
        self.contractor = submission.contractor
        self.report_date = submission.report_date
        self.id = submission.id
        self.data = submission.data
        self.signatory_name = submission.signatory_name
        self._template = template

    @property
    def type_ar(self):
        return self._template.name_ar


def build_dynamic_pdf(submission, template, generated_at: str = "") -> bytes:
    """Render A4 PDF for a dynamic submission. Returns raw bytes."""
    st = _styles()
    adapter = _DynReportAdapter(submission, template)
    payload = submission.data or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10 * mm,
                            leftMargin=10 * mm, topMargin=12 * mm,
                            bottomMargin=36,
                            title=f"Azadexa-{template.key}-{submission.id}",
                            author="AZAD Intelligent Systems")
    story = []

    # ---- corporate header (shared: project owner / consultant / contractor)
    try:
        header_tbl = _header_table(adapter, st)
    except Exception:
        header_tbl = None
    story.append(header_tbl)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#c9a227")))
    story.append(Spacer(1, 4 * mm))
    # ---- project general data — production headers for all report types
    if template.key in ("daily", "weekly"):
        is_daily = template.key == "daily"
        title_ar = "تقرير الإنجاز اليومي" if is_daily else "تقرير التقدم الأسبوعي / نصف الشهري (Weekly / Biweekly Progress Report)"
        period = payload.get("report_period", f"{submission.report_date or ''}")
        if not is_daily:
            # weekly period overrides date
            period = payload.get("period_start", "") + " - " + payload.get("period_end", "") if payload.get("period_start") else period
        title_tbl = Table([
            [Paragraph(ar(f"رقم التقرير : {submission.id or '—'}"), st["cell"]),
             Paragraph(ar(f"{'التاريخ' if is_daily else 'الفترة'} : {period}"), st["cell"])],
        ], colWidths=[95 * mm, 95 * mm])
        title_tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(Paragraph(ar(title_ar), st["title"]))
        story.append(Spacer(1, 3 * mm))
        story.append(title_tbl)
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(ar("بيانات المشروع العامة" if is_daily else "البيانات التعريفية والتعاقدية للمشروع"), st["cell_h"]))
        story.append(Spacer(1, 2 * mm))
        # 7 rows for daily, 9 rows for weekly (adds engineers + date/type)
        proj_rows = [
            ("اسم المشروع", submission.project_name or payload.get("project_name", "إعادة تأهيل وصيانة صالة القادمين في استراحة أريحا")),
            ("رقم المناقصة / العقد", payload.get("contract_no", "CTD/2026/021-WB/MOF")),
            ("مصدر التمويل", payload.get("funding_source", "البنك الدولي - مشروع التعافي الاجتماعي والوظائف")),
            ("الجهة المنفذة", payload.get("implementing_entity", "وزارة المالية / CTD/MOF")),
            ("الجهة المستفيدة", payload.get("beneficiary_entity", "الإدارة العامة للمعابر والحدود (GABC)")),
            ("المقاول المنفذ", submission.contractor or payload.get("contractor", "شركة سمرقند للمقاولات")),
            ("الموقع", submission.location or payload.get("project_location", "استراحة أريحا - معبر الكرامة، أريحا")),
        ]
        if not is_daily:
            proj_rows += [
                ("مهندس المقاول / مدير المشروع", payload.get("pm_name", "م. محمد نسيم عرار")),
                ("مهندس السلامة", payload.get("safety_eng", "م. محمد قباجه")),
                ("تاريخ التقرير", str(submission.report_date or "")),
                ("نوع التقرير", payload.get("report_type_label", "تقرير تقدم عمل أسبوعي شامل")),
            ]
        proj_body = [[Paragraph(ar(v), st["cell"]), Paragraph(ar(k), st["cell_h"])] for k, v in proj_rows]
        proj_tbl = Table(proj_body, colWidths=[140 * mm, 50 * mm])
        proj_tbl.setStyle(TableStyle([
            ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#eef3f7")),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(proj_tbl)
        story.append(Spacer(1, 5 * mm))
    else:
        story.append(_info_table(adapter, st))
        story.append(Spacer(1, 5 * mm))
        story.append(_section_title(f"تفاصيل {template.name_ar}", st))
        story.append(Spacer(1, 3 * mm))

    items = []
    tables = []  # (field label, header labels, body rows) for line items
    for f in template.ordered_fields:
        val = payload.get(f.field_key, "")
        if f.field_type == "table":
            cols = f.sub_columns() if hasattr(f, "sub_columns") else []
            rows = val if isinstance(val, list) else []
            if cols and rows:
                # render checkbox cells as ☒/☐
                def _fmt_cell(c, raw):
                    if c.get("type") == "checkbox":
                        is_c = str(raw).lower() in ("1", "true", "yes", "on", "نعم", "☒", "checked")
                        return "☒" if is_c else "☐"
                    return str(raw) if str(raw).strip() else "—"
                body_rows = [[_fmt_cell(c, r.get(c["key"], "")) for c in cols]
                             for r in rows if isinstance(r, dict)]
                tables.append((f.label_ar, [c["label_ar"] for c in cols], body_rows))
            else:
                items.append((f.label_ar, "— لا بنود مسجلة —"))
            continue
        if f.field_type == "checkbox":
            # ESHS model uses ☒ / ☐ exactly as in PDF
            is_checked = str(val).lower() in ("1", "true", "yes", "on", "نعم", "checked", "☒")
            val = "☒" if is_checked else "☐"
        elif f.field_type == "number" and val not in ("", None):
            val = str(val)
        items.append((f.label_ar, val if str(val).strip() else "—"))
    if not items and not tables:
        items = [("لا توجد حقول معرفة لهذا القالب", "—")]
    story.append(_kv_table(items, st))
    story.append(Spacer(1, 6 * mm))

    # ---- line-item tables (alternating shading, repeat header)
    for idx, (label, header, body) in enumerate(tables):
        story.append(_section_title(f"{label} ({len(body)} بنود)", st))
        story.append(Spacer(1, 3 * mm))
        head = [Paragraph(ar(h), st["cell_h"]) for h in header]
        grid = [head] + [[Paragraph(ar(v), st["cell"]) for v in row]
                         for row in body]
        widths = [max(150 * mm / max(len(header), 1), 25 * mm)] * len(header)
        t = Table(grid, colWidths=widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]
        # alternating row shading for readability
        if len(body) > 1:
            alt = colors.HexColor("#f4f7fa")
            for r in range(1, len(grid)):
                if r % 2 == 0:
                    style_cmds.append(("BACKGROUND", (0, r), (-1, r), alt))
        t.setStyle(TableStyle(style_cmds))
        story.append(t)
        story.append(Spacer(1, 6 * mm))

    # ---- signatory block
    story.append(_section_title("التوقيع والاعتماد", st))
    story.append(Spacer(1, 3 * mm))
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    sig_rows = [
        [Paragraph(ar(stamp), st["cell"]),
         Paragraph(ar("تاريخ ووقت الإصدار"), st["cell_h"])],
        [Paragraph(ar(submission.signatory_name or "—"), st["cell"]),
         Paragraph(ar("مُعد التقرير / الموقّع الرسمي"), st["cell_h"])],
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
        ar("أقر بأن البيانات المذكورة أعلاه صحيحة ومطابقة للواقع في الموقع بتاريخ التقرير."),
        st["cell_small"]))

    serial = f"{submission.id:06d}" if submission.id else "000000"
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    def _foot(c, d):
        _footer(c, d, serial=serial, timestamp=stamp,
                project_name=submission.project_name,
                report_type=template.name_ar)
    doc.build(story, onFirstPage=_foot, onLaterPages=_foot)
    return buf.getvalue()
