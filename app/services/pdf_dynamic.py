"""Dynamic PDF service — renders ANY ReportTemplate + submission answers.

Reuses the corporate styling of utils/pdf_generator (section titles, info grid,
kv rows) but builds the body table from DynamicField rows instead of hardcoded
FIELD_SPECS. The page itself carries only the report title, its serial number,
the content, two blank signature boxes, and the page number: no letterhead, no
running header, no footer band.
"""
from datetime import datetime

from utils.pdf_generator import (_styles, _info_table, _section_title,
                                 _kv_table, ar, NAVY)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                Table, TableStyle)
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
import io
import logging
import os

log = logging.getLogger(__name__)


def _resolve_upload_abs(key: str) -> str | None:
    """Absolute path for a stored relative upload key (traversal-safe).

    Returns None outside app context, on traversal, or when missing —
    callers then render a placeholder instead of a raw storage link.
    """
    rel = (key or "").replace("\\", "/").strip()
    if not rel or ".." in rel.split("/"):
        return None
    try:
        from flask import current_app
        base = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    except Exception:
        return None
    abs_path = os.path.abspath(os.path.join(base, rel))
    if abs_path != base and not abs_path.startswith(base + os.sep):
        return None
    return abs_path if os.path.isfile(abs_path) else None


def _branding_for(project_id):
    """The project's identity, with a usable fallback outside a request."""
    from flask import current_app, has_app_context
    if has_app_context():
        from app.services.branding import branding_for_project
        return branding_for_project(project_id)
    class _Fallback:
        company_ar = "جهة الإشراف / المالك"
        company_en = ""
        logo_path = None
        logo2_path = None
        header_ar = ""
        header_en = ""
        footer_notes = ""
        disclaimer = ""
    return _Fallback()


def _readable_image(abs_path: str) -> bool:
    """True when ReportLab will actually be able to draw the file.

    A corrupt/truncated upload must degrade to a placeholder note — never
    crash the whole PDF build at draw time (when RLImage only then decodes).
    """
    try:
        from PIL import Image as _PILImage
    except Exception:
        return True
    try:
        with _PILImage.open(abs_path) as im:
            im.load()
        return True
    except Exception:
        log.warning("unreadable gallery image skipped: %s", abs_path)
        return False


def _row_caption(cols, row) -> str:
    """Caption sibling for photo cells (caption/comment column, same row)."""
    for c in cols:
        if c.get("type") == "file":
            continue
        if "caption" in c.get("key", "") or "تعليق" in c.get("label_ar", ""):
            val = str(row.get(c.get("key", ""), "") or "").strip()
            if val:
                return val
    return ""


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
    brand = _branding_for(submission.project_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10 * mm,
                            leftMargin=10 * mm, topMargin=12 * mm,
                            bottomMargin=36,
                            # Latin and machine-readable: a non-Latin /Title is
                            # written as UTF-16 with a byte-order mark, which
                            # hides the serial and renders as mojibake. The
                            # organisation goes in /Author and on the page.
                            title=f"{template.key}-"
                            f"{getattr(submission, 'serial', None) or submission.id}",
                            author=brand.company_en or brand.company_ar,
                            subject=template.name_en or template.name_ar)
    story = []

    # The letterhead that used to be drawn here (tenant logos, company
    # name, contractor line, the corporate header table and the gold rule)
    # is gone on purpose: the report opens with its own title and serial
    # number. A tenant's letterhead belongs on the paper the report is
    # filed with, and re-drawing it pushed a third of the first page above
    # the content on every single report.

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
        # Professional default: empty (—) when no project data — never invent
        # a specific site/contractor inside a generic platform renderer.
        proj_rows = [
            ("اسم المشروع", submission.project_name or payload.get("project_name", "—")),
            ("رقم المناقصة / العقد", payload.get("contract_no", "—")),
            ("مصدر التمويل", payload.get("funding_source", "—")),
            ("الجهة المنفذة", payload.get("implementing_entity", "—")),
            ("الجهة المستفيدة", payload.get("beneficiary_entity", "—")),
            ("المقاول المنفذ", submission.contractor or payload.get("contractor", "—")),
            ("الموقع", submission.location or payload.get("project_location", "—")),
        ]
        if not is_daily:
            proj_rows += [
                ("مهندس المقاول / مدير المشروع", payload.get("pm_name", "—")),
                ("مهندس السلامة", payload.get("safety_eng", "—")),
                ("تاريخ التقرير", str(submission.report_date or "")),
                ("نوع التقرير", payload.get("report_type_label", template.name_ar)),
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
    tables = []  # (field label, cols, body rows) for line items — cols kept for image handling
    gallery = []  # (abs image path, caption) for the photo gallery section
    for f in template.ordered_fields:
        val = payload.get(f.field_key, "")
        if f.field_type == "table":
            cols = f.sub_columns() if hasattr(f, "sub_columns") else []
            rows = val if isinstance(val, list) else []
            if cols and rows:
                def _fmt_cell(c, raw, _row=None, _cols=None):
                    if c.get("type") == "checkbox":
                        is_c = str(raw).lower() in ("1", "true", "yes", "on", "نعم", "☒", "checked")
                        return "☒" if is_c else "☐"
                    if c.get("type") == "file":
                        v = str(raw or "").strip()
                        if not v:
                            return "—"
                        abs_path = _resolve_upload_abs(v)
                        if abs_path is not None and _readable_image(abs_path):
                            gallery.append(
                                (abs_path, _row_caption(_cols or [], _row or {})))
                            return f"صورة {len(gallery)}"
                        return "—"
                    return str(raw) if str(raw).strip() else "—"
                body_rows = [[_fmt_cell(c, r.get(c["key"], ""), r, cols)
                              for c in cols]
                             for r in rows if isinstance(r, dict)]
                tables.append((f.label_ar, cols, body_rows))
            # An empty table is not printed at all. It used to print
            # «لا بنود مسجلة», which put a heading and a line on every page for
            # a section that does not apply: a reader could not tell "not
            # applicable" from "someone forgot". The daily report the site
            # fills in on paper simply has no such section when nothing applies.
            continue
        if f.field_type == "checkbox":
            # ESHS model uses ☒ / ☐ exactly as in PDF
            is_checked = str(val).lower() in ("1", "true", "yes", "on", "نعم", "checked", "☒")
            if not is_checked:
                # An unticked box is a statement that something was not done.
                # Printing it for every optional attachment turns a filled
                # report into a list of things nobody did.
                continue
            val = "☒"
        elif f.field_type == "number" and val not in ("", None):
            val = str(val)
        if not str(val).strip():
            # Same rule for scalars: absent, not «—».
            continue
        items.append((f.label_ar, val))
    if not items and not tables:
        # Every field is hidden when empty, so a report where nothing was
        # filled in would otherwise be a sheet of letterhead and nothing else.
        # Say so rather than emit a blank page.
        items = [("تعذّر طباعة أي قسم",
                  "لم تُملأ أي من الأقسام في هذا التقرير.")]
    if items:
        story.append(_kv_table(items, st))
        story.append(Spacer(1, 6 * mm))

    # ---- line-item tables (alternating shading, repeat header) — with image embedding
    for idx, (label, cols, body) in enumerate(tables):
        header = [c["label_ar"] for c in cols]
        story.append(_section_title(f"{label} ({len(body)} بنود)", st))
        story.append(Spacer(1, 3 * mm))
        # The header band is navy, so its text must be white. cell_h is navy —
        # it is meant for labels on a pale background (_info_table) — and a
        # Paragraph's own colour beats the table's TEXTCOLOR, so reusing it
        # here drew navy on navy: the column titles were there in the file and
        # invisible on the page. Verified by reading the generated PDF back.
        head_style = ParagraphStyle("dyn_th", parent=st["cell_h"],
                                    textColor=colors.white, fontSize=9,
                                    leading=13)
        head = [Paragraph(ar(h), head_style) for h in header]
        # grid cells are pre-formatted text (photos live in the gallery below)
        grid_rows = [[Paragraph(ar(v), st["cell"]) for v in row]
                     for row in body]
        grid = [head] + grid_rows
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

    # ---- photo gallery: each image with its caption below it
    if gallery:
        from reportlab.platypus import Image as RLImage
        story.append(_section_title(f"الصور التوثيقية ({len(gallery)})", st))
        story.append(Spacer(1, 3 * mm))
        for n, (abs_path, caption) in enumerate(gallery, 1):
            try:
                img = RLImage(abs_path, width=150 * mm, height=90 * mm,
                              kind="proportional", hAlign="CENTER")
                img.hAlign = "CENTER"
                story.append(img)
            except Exception:
                log.warning("gallery image skipped: %s", abs_path)
                continue
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(
                ar(f"صورة {n}" + (f" — {caption}" if caption else "")), st["cell"]))
            story.append(Spacer(1, 5 * mm))

    # ---- monthly EVM (PV/EV/AC/CPI/SPI) — auto if monthly
    if template.key == "monthly":
        try:
            from app.ops.finance import evm_metrics
            evm = evm_metrics(payload.get("planned_value"), payload.get("earned_value"),
                              payload.get("actual_cost"), payload.get("budget_at_completion"))
            evm_rows = [
                ("القيمة المخططة PV", str(evm["pv"])),
                ("القيمة المكتسبة EV", str(evm["ev"])),
                ("التكلفة الفعلية AC", str(evm["ac"])),
                ("مؤشر الأداء CPI", str(evm["cpi"])),
                ("مؤشر الجدولة SPI", str(evm["spi"])),
                ("انحراف التكلفة CV", str(evm["cv"])),
                ("انحراف الجدولة SV", str(evm["sv"])),
                ("التكلفة المتوقعة عند الإكمال EAC", str(evm["forecast_final_cost"])),
            ]
            story.append(_section_title("تحليل القيمة المكتسبة (EVM)", st))
            story.append(Spacer(1, 3 * mm))
            story.append(_kv_table(evm_rows, st))
            story.append(Spacer(1, 6 * mm))
        except Exception as exc:
            log.debug("EVM block skipped in dynamic PDF: %s", exc)

    # ---- signatory block: left blank on purpose, for wet signatures.
    # A printed daily report is signed by hand on site. Filling the printed
    # form with names and a timestamp turns a signature box into a form field
    # nobody signs, so the space is reserved and left empty; the engineer's own
    # name travels in the submission's signatory field for the record, not on
    # the page that has to be signed.
    story.append(_section_title("التوقيع والاعتماد", st))
    story.append(Spacer(1, 4 * mm))
    sig_cell = ParagraphStyle("sig_blank", parent=st["cell"],
                              textColor=colors.black, alignment=2, leading=18)
    sig_head = ParagraphStyle("sig_h", parent=st["cell_h"],
                              alignment=1, leading=16)
    signers = ["المهندس المشرف", "مدير المشروع"]
    sig = Table([["" for _ in signers],
                 ["" for _ in signers],
                 [Paragraph(ar(n), sig_head) for n in signers]],
                colWidths=[95 * mm] * len(signers), rowHeights=[16 * mm, 16 * mm, 8 * mm])
    sig.setStyle(TableStyle([
        # an empty rule to sign on, not a filled box
        ("LINEBELOW", (0, 1), (-1, 1), 0.8, colors.black),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#b9c6d2")),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(sig)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        ar(f"تاريخ التقرير: {submission.report_date or '—'}"),
        sig_cell))

    # The report identifies itself once, at the top. The old running header
    # repeated the company, the project, the serial and a gold rule on every
    # page, and the footer repeated the serial and a timestamp again — so a
    # three-page daily report carried its title nine times and pushed the body
    # down by a third of a page on every sheet. Only the page number stays, so
    # a loose page can still be put back in order.
    def _page_no(c, d):
        c.saveState()
        c.setFont(st["footer"].fontName, 8)
        c.setFillColor(colors.black)
        c.drawCentredString(297 * mm / 2, 10 * mm, f"{c.getPageNumber()}")
        c.restoreState()

    doc.build(story, onFirstPage=_page_no, onLaterPages=_page_no)
    return buf.getvalue()
