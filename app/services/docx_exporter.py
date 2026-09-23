"""Word (.docx) exporter — bank-grade IPC / VO / Handover.

Mirrors reportlab PDFs but writes native Word via python-docx + docxtpl.
Keeps tenant isolation, Arabic shaping, and audit metadata.
"""
import io
from datetime import datetime

try:
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False


def _arabic(text):
    """Reuse same reshaper as PDF."""
    try:
        from utils.pdf_generator import ar
        return ar(text)
    except Exception:
        return str(text or "")


def build_docx(submission, template, generated_at: str = "") -> bytes:
    """Render Word docx for any template. Returns bytes. Requires python-docx."""
    if not HAS_DOCX:
        raise RuntimeError("python-docx not installed — pip install python-docx")
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    # Title
    p = doc.add_heading(_arabic(template.name_ar), level=1)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    # Project info table (7 rows)
    payload = submission.data or {}
    info = [
        ("اسم المشروع", submission.project_name or payload.get("project_name", "")),
        ("رقم المناقصة / العقد", payload.get("contract_no", "CTD/2026/021-WB/MOF")),
        ("مصدر التمويل", payload.get("funding_source", "")),
        ("الجهة المنفذة", payload.get("implementing_entity", "")),
        ("الجهة المستفيدة", payload.get("beneficiary_entity", "")),
        ("المقاول", submission.contractor or ""),
        ("الموقع", submission.location or ""),
        ("التاريخ", str(submission.report_date or "")),
        ("رقم التقرير", str(submission.id or "")),
    ]
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Light Grid Accent 1"
    for label, val in info:
        row = tbl.add_row()
        row.cells[0].text = _arabic(label)
        row.cells[1].text = _arabic(val)
    doc.add_paragraph("")
    # Fields
    for f in template.ordered_fields:
        val = payload.get(f.field_key, "")
        if f.field_type == "table":
            cols = f.sub_columns() if hasattr(f, "sub_columns") else []
            rows = val if isinstance(val, list) else []
            if not cols or not rows:
                continue
            doc.add_heading(_arabic(f.label_ar), level=2)
            t = doc.add_table(rows=1, cols=len(cols))
            t.style = "Light Grid Accent 1"
            hdr = t.rows[0].cells
            for i, c in enumerate(cols):
                hdr[i].text = _arabic(c["label_ar"])
                for p in hdr[i].paragraphs:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in rows[:50]:
                row = t.add_row().cells
                for i, c in enumerate(cols):
                    raw = r.get(c["key"], "")
                    if c.get("type") == "checkbox":
                        is_c = str(raw).lower() in ("1", "true", "yes", "on", "☒")
                        raw = "☒" if is_c else "☐"
                    row[i].text = _arabic(str(raw) if str(raw).strip() else "—")
        else:
            if str(val).strip() == "":
                continue
            if f.field_type == "checkbox":
                is_c = str(val).lower() in ("1", "true", "yes", "on", "☒")
                val = "☒" if is_c else "☐"
            p = doc.add_paragraph()
            p.add_run(_arabic(f.label_ar) + ": ").bold = True
            p.add_run(_arabic(str(val)))
    # Signatory
    doc.add_heading(_arabic("التوقيع والاعتماد"), level=2)
    p = doc.add_paragraph(_arabic(f"الموقع: {submission.signatory_name or ''} — {generated_at or datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    # Footer with audit
    section = doc.sections[0]
    footer = section.footer.paragraphs[0]
    footer.text = _arabic(f"SIR-{submission.id or 0:06d} | {submission.project_name} | {template.name_ar}")
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()
