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
    story.append(_info_table(adapter, st))
    story.append(Spacer(1, 5 * mm))

    # ---- template fields
    story.append(_section_title(f"تفاصيل {template.name_ar}", st))
    story.append(Spacer(1, 3 * mm))

    payload = submission.data or {}
    items = []
    tables = []  # (field label, header labels, body rows) for line items
    for f in template.ordered_fields:
        val = payload.get(f.field_key, "")
        if f.field_type == "table":
            cols = f.sub_columns() if hasattr(f, "sub_columns") else []
            rows = val if isinstance(val, list) else []
            if cols and rows:
                tables.append((f.label_ar, [c["label_ar"] for c in cols],
                               [[str(r.get(c["key"], "") or "—") for c in cols]
                                for r in rows if isinstance(r, dict)]))
            else:
                items.append((f.label_ar, "— لا بنود مسجلة —"))
            continue
        if f.field_type == "checkbox":
            val = "نعم ✔" if str(val).lower() in ("1", "true", "yes", "on", "نعم") else "لا"
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
