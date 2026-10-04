"""Dynamic PDF service — renders ANY ReportTemplate + submission answers.

Reuses the corporate styling of utils/pdf_generator (section titles, info grid,
kv rows) but builds the body table from DynamicField rows instead of hardcoded
FIELD_SPECS. The page itself carries only the report title, its serial number,
the content, two blank signature boxes, and the page number: no letterhead, no
running header, no footer band.
"""
from utils.pdf_generator import (_styles, _info_table, _section_title,
                                 _kv_table, ar, NAVY, DOC_TEXT, DOC_TINT,
                                 DOC_RULE, CONTENT_W, PAGE_MARGIN,
                                 PAGE_MARGIN_BOTTOM, fit_column_widths)
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

#: Photographs printed per report. Seven is not arbitrary: the site's approved
#: daily report sets the maximum at seven precisely so the photo table and the
#: signature table share one page. Beyond that the report grows a page of
#: photographs, which is the cost the cap exists to avoid.
MAX_REPORT_PHOTOS = 7


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
    from flask import has_app_context
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


def build_dynamic_pdf(submission, template, generated_at: str = "",
                      fields=None) -> bytes:
    """Render A4 PDF for a dynamic submission. Returns raw bytes.

    `fields` is the company's custom field list, resolved by the caller. The
    printout is the deliverable, so it has to be built from the same list the
    form was: a PDF that carried the platform order beside a custom form would
    show sections the user never filled in and omit the ones they did.
    """
    st = _styles()
    adapter = _DynReportAdapter(submission, template)
    payload = submission.data or {}
    brand = _branding_for(submission.project_id)
    if fields is None:
        fields = template.ordered_fields
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=PAGE_MARGIN,
                            leftMargin=PAGE_MARGIN,
                            topMargin=PAGE_MARGIN,
                            bottomMargin=PAGE_MARGIN_BOTTOM,
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
        ], colWidths=[CONTENT_W / 2, CONTENT_W / 2])
        title_tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.6, DOC_RULE),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(Paragraph(ar(title_ar), st["title"]))
        story.append(Spacer(1, 3 * mm))
        story.append(title_tbl)
        story.append(Spacer(1, 4 * mm))

        # ---- the project-data table.
        #
        # Sourced from the Project record, not from the report. These are
        # facts about the project, not about the day: the contract number, the
        # owner, the funding source and the supervising party do not change
        # between Monday and Tuesday, so asking for them on every report is a
        # question with exactly one right answer that somebody has to retype
        # each morning. The submission still wins where it has something
        # specific - a report can name a different location for one day - and
        # the empty value prints as a dash rather than an invented value.
        project = None
        try:
            from app.extensions import db
            from app.models import Project
            if submission.project_id:
                project = db.session.get(Project, submission.project_id)
            elif submission.project_name:
                project = Project.query.filter_by(
                    name=submission.project_name).first()
        except Exception as exc:  # never let the header break the report
            log.debug("project lookup for PDF header failed: %s", exc)

        def _pget(attr, *fallbacks):
            """Project attribute, then the payload's own key, then a dash."""
            if project is not None:
                value = str(getattr(project, attr, "") or "").strip()
                if value:
                    return value
            for key in fallbacks:
                value = str(payload.get(key, "") or "").strip()
                if value:
                    return value
            return "—"

        covered = payload.get("report_period_label") or ""
        if not covered and submission.report_date:
            covered = f"يوم واحد – {submission.report_date}"

        proj_rows = [
            ("اسم المشروع", submission.project_name or _pget("name", "project_name")),
            ("رمز العقد / المناقصة", _pget("contract_no", "contract_no")),
            ("المالك", _pget("client", "client", "owner")),
            ("جهة التمويل", _pget("funding_source", "funding_source")),
            ("المقاول المنفذ", submission.contractor or _pget("contractor", "contractor")),
            ("الجهة المشرفة", _pget("consultant", "consultant",
                                     "supervising_authority")),
            ("الموقع", submission.location or _pget("location", "project_location")),
            ("الفترة المشمولة بالتقرير", covered or "—"),
        ]
        if not is_daily:
            proj_rows += [
                ("إدارة المشروع", _pget("managing_agency", "managing_agency",
                                         "implementing_entity")),
                ("مهندس المقاول / مدير المشروع", _pget("pm_name", "pm_name")),
                ("مهندس السلامة", _pget("safety_eng", "safety_eng")),
                ("تاريخ التقرير", str(submission.report_date or "")),
                ("نوع التقرير", payload.get("report_type_label", template.name_ar)),
            ]
        proj_body = [[Paragraph(ar(v), st["cell"]), Paragraph(ar(k), st["cell_h"])] for k, v in proj_rows]
        proj_label = "البيانات التعريفية والتعاقدية للمشروع" if not is_daily \
            else "بيانات المشروع العامة"
        proj_body.insert(0, [
            Paragraph(ar("التفاصيل"), st["cell_h"]),
            Paragraph(ar(proj_label), st["cell_h"]),
        ])
        proj_tbl = Table(proj_body, colWidths=[CONTENT_W - 50 * mm, 50 * mm])
        proj_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DOC_TINT),
            ("BACKGROUND", (1, 1), (1, -1), DOC_TINT),
            ("GRID", (0, 0), (-1, -1), 0.6, DOC_RULE),
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

    # Sections are emitted in the order the template declares them, not
    # "every scalar field, then every table".
    #
    # It used to collect them into two lists and print the scalars first, which
    # put the two descriptive fields the template declares before item 1
    # ("8.1 وصف أنشطة البناء") physically above item 1 in the document, so the
    # printed order did not match the order the form and the field manager show.
    # One ordered list of blocks fixes it and lets the template own the order.
    blocks = []  # ("kv", [(label, value), ...]) | ("table", label, cols, rows)
    gallery = []  # (abs image path, caption) for the photo gallery section
    _pending_kv = []

    def _flush_kv():
        if _pending_kv:
            blocks.append(("kv", list(_pending_kv)))
            _pending_kv.clear()

    for f in fields:
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
                # A table is a block of its own, so the scalars declared before
                # it have to be flushed first or they would print after it.
                _flush_kv()
                blocks.append(("table", f.label_ar, cols, body_rows))
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
        _pending_kv.append((f.label_ar, val))

    _flush_kv()
    if not blocks:
        # Every field is hidden when empty, so a report where nothing was
        # filled in would otherwise be a sheet of letterhead and nothing else.
        # Say so rather than emit a blank page.
        blocks = [("kv", [("تعذّر طباعة أي قسم",
                           "لم تُملأ أي من الأقسام في هذا التقرير.")])]

    # ---- the sections, in the order the template declares them
    for block in blocks:
        if block[0] == "kv":
            story.append(_kv_table(block[1], st))
            story.append(Spacer(1, 5 * mm))
            continue

        _kind, label, cols, body = block
        header = [c["label_ar"] for c in cols]
        story.append(_section_title(f"{label} ({len(body)} بنود)", st))
        story.append(Spacer(1, 2 * mm))
        # Deep blue column titles on the pale tint. This was a navy band with
        # white text, which had a bug behind it: cell_h is navy because it is
        # meant for labels on a pale background, so reusing it here first drew
        # navy on navy - the titles were in the file and invisible on the page -
        # and the fix was a one-off white override. Both the colour and the
        # override are gone now that the band is light and the text is dark.
        head_style = ParagraphStyle("dyn_th", parent=st["cell_h"],
                                    textColor=DOC_TEXT, fontSize=9,
                                    leading=13)
        head = [Paragraph(ar(h), head_style) for h in header]
        # grid cells are pre-formatted text (photos live in the gallery below)
        grid_rows = [[Paragraph(ar(v), st["cell"]) for v in row]
                     for row in body]
        grid = [head] + grid_rows
        widths = fit_column_widths(header, total=CONTENT_W)
        t = Table(grid, colWidths=widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), DOC_TINT),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, DOC_TEXT),
            ("GRID", (0, 0), (-1, -1), 0.6, DOC_RULE),
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

    # ---- photo gallery: a two-up grid, caption beside each photograph
    if gallery:
        from reportlab.platypus import Image as RLImage
        from reportlab.lib.utils import ImageReader

        shown = gallery[:MAX_REPORT_PHOTOS]
        omitted = len(gallery) - len(shown)
        story.append(_section_title(
            f"الصور التوثيقية ({len(shown)}"
            + (f" من {len(gallery)}" if omitted else "") + ")", st))
        story.append(Spacer(1, 2 * mm))

        # The approved document lays the photographs out two-up with the caption
        # in the second column, so a full set of seven sits on one page beside
        # the signature table. They were one 150x90mm image per flowable with
        # the caption underneath, which gave each photograph a hundred
        # millimetres of page: seven photos, two and a half pages of nothing
        # else, and the signature block pushed off the end.
        photo_w = 46 * mm
        photo_h = 30 * mm
        caption_w = CONTENT_W - photo_w - 4 * mm

        cap_style = ParagraphStyle("gal_cap", parent=st["cell_small"],
                                   leading=13)

        #: No inline markup in a caption. ar() runs bidi reordering, which moves
        #: the characters of a tag apart - "<b>صورة 1</b>" comes back as
        #: "</b>1 صورة<b>" and ReportLab's parser then reads it as an unclosed
        #: tag. That is not a caption problem: it raises while the document is
        #: being built, so the whole report fails to produce a PDF.
        pairs = []
        number = 0
        for n in range(0, len(shown), 2):
            cells = []
            for abs_path, caption in shown[n:n + 2]:
                number += 1
                try:
                    reader = ImageReader(str(abs_path))
                    iw, ih = reader.getSize()
                    # Fit inside the cell rather than filling it: a 4:3 site
                    # photo scaled to 46x30 is cropped by nothing, but a long
                    # panorama would distort if forced to both edges.
                    scale = min(photo_w / iw, photo_h / ih)
                    img = RLImage(str(abs_path), width=iw * scale,
                                  height=ih * scale)
                    img.hAlign = "CENTER"
                    img.valign = "MIDDLE"
                    text = f"صورة {number}"
                    if caption:
                        text += f" — {caption}"
                    cells.append([img, Paragraph(ar(text), cap_style)])
                except Exception:
                    log.warning("gallery image skipped: %s", abs_path)
            if len(cells) == 1:
                # A row of two, padded to the pair. The filler has to be a
                # flowable: a Table cell that is a plain string has no
                # wrapOn to call and the build fails on it.
                cells.append([Spacer(1, 1), Spacer(1, 1)])
            pairs.append(cells)

        grid = Table(pairs,
                     colWidths=[photo_w, caption_w, photo_w, caption_w])
        grid.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, DOC_RULE),
        ]))
        story.append(grid)
        if omitted:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(ar(
                f"لم تُدرج {omitted} صورة إضافية لتجاوز العدد المعتمد "
                f"({MAX_REPORT_PHOTOS} صور في الصفحة الواحدة مع جدول التوقيع)."),
                st["cell_small"]))
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
    #
    # The grid is the approved one: a header row naming the four things being
    # signed (date, signature, name and role, party) over one row per party, so
    # the page says who is expected to sign rather than leaving two anonymous
    # boxes. It was two columns of blank cells labelled only underneath, which
    # reads as a form to fill in rather than a document to sign.
    story.append(_section_title("إعداد المقاول، والتدقيق والاعتماد", st))
    story.append(Spacer(1, 3 * mm))

    sig_head = ParagraphStyle("sig_h", parent=st["cell_h"],
                              fontSize=9, leading=13)
    sig_body = ParagraphStyle("sig_b", parent=st["cell"], fontSize=9,
                              leading=13)

    def _sig_row(date_label, entity_label):
        return [
            Paragraph(ar(date_label), sig_body),
            "",  # the wet signature, deliberately blank
            Paragraph(ar(entity_label), sig_body),
            Paragraph(ar(""), sig_body),
        ]

    header_row = [
        Paragraph(ar("التاريخ"), sig_head),
        Paragraph(ar("التوقيع"), sig_head),
        Paragraph(ar("المسمى الوظيفي / الاسم"), sig_head),
        Paragraph(ar("الصفة / الجهة"), sig_head),
    ]

    entity = payload.get("supervising_authority") or ""
    parties = [
        # (date shown, name+role shown, party shown)
        (submission.report_date or "", "مدير المشروع", "إعداد المقاول"),
        ("", "المهندس المشرف والتدقيق", entity or "الجهة المشرفة"),
    ]
    rows = [header_row]
    for date_label, who, party in parties:
        rows.append([
            Paragraph(ar(date_label), sig_body),
            "",
            Paragraph(ar(who), sig_body),
            Paragraph(ar(party), sig_body),
        ])

    sig = Table(rows,
                colWidths=[30 * mm, 45 * mm, 55 * mm, CONTENT_W - 130 * mm],
                rowHeights=[7 * mm] + [16 * mm] * len(parties))
    sig.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DOC_TINT),
        ("GRID", (0, 0), (-1, -1), 0.6, DOC_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # the signature column stays empty, with a rule to sign on
        ("LINEBELOW", (1, 1), (1, -1), 0.4, colors.HexColor("#d8dee4")),
    ]))
    story.append(sig)

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
