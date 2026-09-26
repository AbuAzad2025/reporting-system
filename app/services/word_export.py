"""Dependency-free Word (.docx) exporters for IPC and Variation Orders.

A .docx file is an OPC package (a ZIP of XML parts), so the official-format
writer here needs nothing beyond the standard library — no new runtime
dependency on a bankable deployment, and full control over the output.

The emitted package is a minimal but valid WordprocessingML document:
`[Content_Types].xml`, `_rels/.rels`, `word/_rels/document.xml.rels`,
`word/styles.xml` and `word/document.xml`.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Iterable, Sequence
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>
<w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
<w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>
<w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4"/><w:left w:val="single" w:sz="4"/>
<w:bottom w:val="single" w:sz="4"/><w:right w:val="single" w:sz="4"/>
<w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/>
</w:tblBorders></w:tblPr></w:style>
</w:styles>"""


def _core_props(title: str, author: str) -> str:
    stamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{escape(title)}</dc:title>"
        f"<dc:creator>{escape(author or '')}</dc:creator>"
        f'<dcterms:created xmlns:dcterms="http://purl.org/dc/terms/" '
        f'xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"{stamp}</dcterms:created></cp:coreProperties>")


def _run(text: str, bold: bool = False) -> str:
    safe = escape(str(text if text is not None else ""))
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return (f"<w:r>{props}<w:t xml:space=\"preserve\">{safe}</w:t></w:r>")


def _paragraph(text: str, style: str | None = None, bold: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_run(text, bold)}</w:p>"


def _cell(text: str, bold: bool = False) -> str:
    return ("<w:tc><w:tcPr><w:tcW w:w=\"3000\" w:type=\"dxa\"/></w:tcPr>"
            f"<w:p>{_run(text, bold)}</w:p></w:tc>")


def _table(rows: Sequence[Sequence[str]], header: bool = False) -> str:
    if not rows:
        return ""
    body = []
    for index, row in enumerate(rows):
        cells = "".join(_cell(v, bold=header and index == 0)
                        for v in row)
        body.append(f"<w:tr>{cells}</w:tr>")
    return ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
            '<w:tblW w:w="0" w:type="auto"/></w:tblPr>'
            + "".join(body) + "</w:tbl>")


def _pairs(items: Iterable[tuple]) -> list:
    return [[str(label), str(value if value not in (None, "") else "—")]
            for label, value in items]


def _fmt(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _build_document(body_parts: Sequence[str], title: str,
                    author: str) -> bytes:
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{W_NS}"><w:body>'
                + "".join(body_parts)
                + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                  '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134"'
                  ' w:left="1134" w:header="708" w:footer="708"'
                  ' w:gutter="0"/></w:sectPr></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("docProps/core.xml", _core_props(title, author))
        z.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def _identity_rows(record, project_name: str) -> list:
    status_ar = getattr(record, "status_ar", "") or getattr(record, "status", "")
    return [
        ["الرقم التسلسلي", str(getattr(record, "serial", "") or "—")],
        ["المشروع", project_name or "—"],
        ["رقم السجل", str(getattr(record, "id", "") or "—")],
        ["تاريخ التقرير", str(getattr(record, "report_date", "") or "—")],
        ["الحالة", str(status_ar or "—")],
        ["الموقّع", str(getattr(record, "signatory_name", "") or "—")],
        ["إصدار", f"v{getattr(record, 'version', None) or 1}"],
    ]


def _signoff_rows(record) -> list:
    reviewer = "مسجّل" if getattr(record, "reviewed_by_id", "") else "—"
    return [
        ["المراجع", str(reviewer)],
        ["تاريخ المراجعة", str(getattr(record, "reviewed_at", "") or "—")],
        ["ملاحظات المراجعة", str(getattr(record, "review_notes", "") or "—")],
    ]


def build_ipc_docx(record, project_name: str = "",
                   generated_at: str = "") -> bytes:
    """Interim Payment Certificate as an editable Word document."""
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    financial = [
        ["رقم الشهادة", str(getattr(record, "cert_no", "") or "—")],
        ["بند الأعمال", str(getattr(record, "work_item", "") or "—")],
        ["مرجع البند", str(getattr(record, "boq_ref", "") or "—")],
        ["الكميات المنفذة", _fmt(getattr(record, "qty_completed", None), 3)],
        ["سعر الوحدة", _fmt(getattr(record, "rate", None))],
        ["إجمالي المستخلص", _fmt(record.gross)],
        ["نسبة المحجوز", f"{getattr(record, 'retention_pct', 0) or 0:g}%"],
        ["قيمة المحجوز", _fmt(record.retention)],
        ["الصافي المستحق", _fmt(record.net_payable)],
        ["المصروف التراكمي", _fmt(record.cumulative)],
        ["نسبة الإنجاز", f"{getattr(record, 'progress_pct', 0) or 0:g}%"],
        ["مرجع القياس", str(getattr(record, "measurement_ref", "") or "—")],
    ]
    body = [
        _paragraph("مستخلص دفع مرحلي (IPC)", style="Title"),
        _paragraph(f"شركة أزاد للأنظمة الذكية — تاريخ الإصدار {stamp}"),
        _paragraph("بيانات المعرفة", style="Heading1"),
        _table(_identity_rows(record, project_name)),
        _paragraph("البنود المالية", style="Heading1"),
        _table(financial),
        _paragraph("الملاحظات", style="Heading1"),
        _paragraph(str(getattr(record, "notes", "") or "—")),
        _paragraph("التوقيع والاعتماد", style="Heading1"),
        _table(_signoff_rows(record)),
    ]
    return _build_document(body, f"IPC {record.serial}",
                           str(getattr(record, "signatory_name", "") or ""))


def build_variation_order_docx(record, project_name: str = "",
                               generated_at: str = "") -> bytes:
    """Variation Order as an editable Word document."""
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    impact = [
        ["رقم أمر التغيير", str(getattr(record, "vo_no", "") or "—")],
        ["العنوان", str(getattr(record, "title", "") or "—")],
        ["التصنيف", str(getattr(record, "category", "") or "—")],
        ["مرجع البند", str(getattr(record, "boq_ref", "") or "—")],
        ["الأثر المالي", f"{_fmt(record.cost_impact)} "
                         f"{getattr(record, 'currency', '') or ''}".strip()],
        ["الأثر الزمني (أيام)",
         f"{getattr(record, 'time_impact_days', 0) or 0:g}"],
        ["التوصية الهندسية", str(getattr(record, "recommendation", "") or "—")],
        ["عدد المرفقات", str(getattr(record, "attachments", 0) or 0)],
    ]
    body = [
        _paragraph("أمر تغيير (Variation Order)", style="Title"),
        _paragraph(f"شركة أزاد للأنظمة الذكية — تاريخ الإصدار {stamp}"),
        _paragraph("بيانات المعرفة", style="Heading1"),
        _table(_identity_rows(record, project_name)),
        _paragraph("وصف التغيير", style="Heading1"),
        _paragraph(str(getattr(record, "description", "") or "—")),
        _paragraph("المبرر", style="Heading1"),
        _paragraph(str(getattr(record, "reason", "") or "—")),
        _paragraph("الأثر والتوصية", style="Heading1"),
        _table(impact),
        _paragraph("التوقيع والاعتماد", style="Heading1"),
        _table(_signoff_rows(record)),
    ]
    return _build_document(body, f"VO {record.serial}",
                           str(getattr(record, "signatory_name", "") or ""))


__all__ = ["build_ipc_docx", "build_variation_order_docx"]
