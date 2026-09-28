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
                            bottomMargin=36, title=f"{brand.company_ar}-"
                            f"{template.key}-{submission.id}",
                            author=brand.company_en or brand.company_ar)
    story = []

    # ---- letterhead: the tenant's own logos, or the platform's if none.
    try:
        from app.models import Project
        from app.extensions import db as _db
        from utils.pdf_generator import _custom_logo, _brand_logo
        proj = _db.session.get(Project, submission.project_id) if submission.project_id else None
        img1 = _custom_logo(brand.logo_path)
        img2 = _custom_logo(brand.logo2_path)
        # Draw the letterhead whenever there is identity to show, not only
        # when a logo file happens to exist. A tenant who named their company
        # and added header text, but never uploaded a file, was getting a
        # report with no letterhead at all.
        if img1 or img2 or brand.company_ar or brand.header_ar or brand.header_en:
            contractor = (submission.contractor
                          or payload.get("contractor") or "").strip()
            rows = [[img1 or Paragraph("", st["cell"]),
                     img2 or Paragraph("", st["cell"])]]
            org = Paragraph(ar(brand.company_ar)
                            + ("<br/>" + brand.company_en if brand.company_en else ""),
                            st["cell_small"])
            other = Paragraph(
                ar(contractor or (proj.contractor if proj else "")
                   or "المقاول المنفذ"),
                st["cell_small"])
            rows.append([org, other])
            if brand.header_ar or brand.header_en:
                rows.append([Paragraph(ar(brand.header_ar), st["cell_small"]),
                             Paragraph(brand.header_en or "", st["cell_small"])])
            logo_tbl = Table(rows, colWidths=[95 * mm, 95 * mm])
            logo_tbl.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(logo_tbl)
            story.append(Spacer(1, 3 * mm))
    except Exception as exc:
        # The letterhead is the most visible part of the document. A failure
        # here used to be logged at debug level, so a report went out with no
        # header and nothing anywhere said why.
        log.warning("dynamic PDF letterhead failed: %s", exc, exc_info=True)

    # ---- corporate header (shared: project owner / consultant / contractor)
    try:
        header_tbl = _header_table(adapter, st)
    except Exception as exc:
        log.warning("dynamic PDF header table failed: %s", exc, exc_info=True)
        header_tbl = None
    if header_tbl is not None:
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

    # ---- line-item tables (alternating shading, repeat header) — with image embedding
    for idx, (label, cols, body) in enumerate(tables):
        header = [c["label_ar"] for c in cols]
        story.append(_section_title(f"{label} ({len(body)} بنود)", st))
        story.append(Spacer(1, 3 * mm))
        head = [Paragraph(ar(h), st["cell_h"]) for h in header]
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

    serial = f"DS-{submission.id:06d}" if submission.id else "DS-000000"
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")

    def _foot(c, d):
        _footer(c, d, serial=serial, timestamp=stamp,
                project_name=submission.project_name,
                report_type=template.name_ar,
                org_ar=brand.company_ar, org_en=brand.company_en,
                notes=brand.footer_notes,
                platform_line=(brand.disclaimer
                                or "Generated via Azadexa Reporting Platform"))
    doc.build(story, onFirstPage=_foot, onLaterPages=_foot)
    return buf.getvalue()
