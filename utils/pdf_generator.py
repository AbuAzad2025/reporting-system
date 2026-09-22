"""Professional A4 PDF engine — ReportLab + Arabic RTL + embedded fonts.

- Arabic shaping via arabic_reshaper + python-bidi.
- Tries to use Amiri / Cairo fonts (auto-downloaded once into ./fonts).
- Falls back to Helvetica so PDFs still generate without network.
- 4 dedicated layouts sharing one corporate header/footer + signatory block.
"""
import io
import os
import urllib.request
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")

FONT_SOURCES = {
    # Amiri has excellent Arabic coverage and works well with ReportLab.
    "Amiri-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf",
    "Amiri-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Bold.ttf",
}

FONT_NORMAL = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
_ARABIC_FONT_READY = False


def ensure_fonts() -> None:
    """Download Arabic TTFs once if missing. Never raises — offline safe."""
    global _ARABIC_FONT_READY
    if _ARABIC_FONT_READY:
        return
    try:
        os.makedirs(FONTS_DIR, exist_ok=True)
        for filename, url in FONT_SOURCES.items():
            dest = os.path.join(FONTS_DIR, filename)
            if not os.path.exists(dest) or os.path.getsize(dest) < 10_000:
                try:
                    urllib.request.urlretrieve(url, dest)
                except Exception:
                    pass  # offline — keep fallback font
        _register_fonts()
    except Exception:
        pass


def _register_fonts() -> None:
    global FONT_NORMAL, FONT_BOLD, _ARABIC_FONT_READY
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        reg = os.path.join(FONTS_DIR, "Amiri-Regular.ttf")
        bold = os.path.join(FONTS_DIR, "Amiri-Bold.ttf")
        if os.path.exists(reg) and os.path.getsize(reg) > 10_000:
            pdfmetrics.registerFont(TTFont("Amiri", reg))
            FONT_NORMAL = "Amiri"
            _ARABIC_FONT_READY = True
        if os.path.exists(bold) and os.path.getsize(bold) > 10_000:
            pdfmetrics.registerFont(TTFont("Amiri-Bold", bold))
            FONT_BOLD = "Amiri-Bold" if _ARABIC_FONT_READY else FONT_BOLD
        elif _ARABIC_FONT_READY:
            FONT_BOLD = "Amiri"  # no synthetic bold available; reuse regular
    except Exception:
        pass


def ar(text) -> str:
    """Shape Arabic text for ReportLab (RTL). Safe for None/numbers/mixed."""
    if text is None:
        return ""
    s = str(text)
    if not s.strip():
        return ""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        # Only reshape when Arabic chars present; keeps latin/numbers stable.
        if any("\u0600" <= ch <= "\u06FF" for ch in s):
            s = get_display(arabic_reshaper.reshape(s))
        return s
    except Exception:
        return s


# ---------------------------------------------------------------- layout
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)

NAVY = colors.HexColor("#1e3a5f")
TEAL = colors.HexColor("#0e7c7b")
LIGHT = colors.HexColor("#eef3f7")
GREY = colors.HexColor("#5b6b7c")
GOLD = colors.HexColor("#c9a227")

#: AZAD Intelligent Systems corporate identity for all documents.
BRAND_AR = "شركة أزاد للأنظمة الذكية"
BRAND_EN = "AZAD Intelligent Systems"
BRAND_LOGO = os.path.join(BASE_DIR, "static", "img", "brand", "azad-logo.png")


def _brand_logo(width_mm=30):
    """Company logo flowable, or None when the asset is missing."""
    try:
        from reportlab.platypus import Image
        if os.path.isfile(BRAND_LOGO):
            return Image(BRAND_LOGO, width=width_mm * mm,
                         height=width_mm * mm, hAlign="CENTER")
    except Exception:
        pass
    return None


def _custom_logo(path, width_mm=28):
    """User-uploaded logo — returns Image flowable or None."""
    if not path:
        return None
    try:
        from reportlab.platypus import Image
        if os.path.isfile(str(path)):
            return Image(str(path), width=width_mm * mm, height=width_mm * mm, hAlign="CENTER")
    except Exception:
        pass
    return None

TYPE_META = {
    "daily": ("التقرير اليومي للتقدم", "Daily Progress Report"),
    "weekly": ("التقرير الأسبوعي", "Weekly Summary Report"),
    "monthly": ("التقرير الشهري التنفيذي", "Monthly Executive Report"),
    "safety": ("تقرير السلامة والصحة المهنية", "HSE / Safety Inspection Report"),
}


def _styles():
    ensure_fonts()
    base_kwargs = dict(fontName=FONT_NORMAL, alignment=2,  # RIGHT for RTL
                       textColor=colors.black, leading=16, fontSize=10)
    return {
        "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=18,
                                textColor=NAVY, alignment=1, leading=24),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT_NORMAL, fontSize=11,
                                   textColor=GREY, alignment=1, leading=16),
        "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=13,
                             textColor=colors.white, alignment=2, leading=18),
        "cell_h": ParagraphStyle("cell_h", fontName=FONT_BOLD, fontSize=10,
                                 textColor=NAVY, alignment=2, leading=15),
        "cell": ParagraphStyle("cell", **base_kwargs),
        "cell_small": ParagraphStyle("cell_small", fontName=FONT_NORMAL,
                                     fontSize=9, textColor=colors.black,
                                     alignment=2, leading=14),
        "footer": ParagraphStyle("footer", fontName=FONT_NORMAL, fontSize=9,
                                 textColor=colors.white, alignment=1, leading=13),
        "sign": ParagraphStyle("sign", fontName=FONT_NORMAL, fontSize=10,
                               textColor=colors.black, alignment=2, leading=16),
    }


def _header_table(report, st):
    title_ar, title_en = TYPE_META.get(report.report_type,
                                        (report.report_type, report.report_type))
    project_owner = "—"
    consultant = "—"
    contractor = report.contractor or "—"
    try:
        from app.models import Project
        proj = Project.query.filter_by(name=report.project_name).first()
        if proj:
            project_owner = proj.client or "—"
            consultant = proj.consultant or "—"
            if not contractor or contractor == "—":
                contractor = proj.contractor or "—"
    except Exception:
        pass
    header_data = [
        [Paragraph(ar("صاحب العمل / المالك"), st["cell_h"]),
         Paragraph(ar(project_owner), st["cell"]),
         Paragraph(ar("الاستشاري / الجهة المشرفة"), st["cell_h"]),
         Paragraph(ar(consultant), st["cell"]),
         Paragraph(ar("المقاول / شركة التنفيذ"), st["cell_h"]),
         Paragraph(ar(contractor), st["cell"])],
    ]
    t = Table(header_data, colWidths=[32 * mm, 30 * mm, 32 * mm, 30 * mm, 32 * mm, 34 * mm])
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


def _info_table(report, st):
    rows = [
        (ar("اسم المشروع"), ar(report.project_name),
         ar("نوع التقرير"), ar(report.type_ar)),
        (ar("الموقع"), ar(report.location or "—"),
         ar("المقاول"), ar(report.contractor or "—")),
        (ar("التاريخ"), ar(str(report.report_date)),
         ar("رقم التقرير"), ar(f"RPT-{report.id:05d}" if report.id else "—")),
    ]
    body = []
    for h1, v1, h2, v2 in rows:
        body.append([Paragraph(v2, st["cell"]), Paragraph(h2, st["cell_h"]),
                     Paragraph(v1, st["cell"]), Paragraph(h1, st["cell_h"])])
    t = Table(body, colWidths=[60 * mm, 35 * mm, 60 * mm, 35 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, -1), LIGHT),
        ("BACKGROUND", (3, 0), (3, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _section_title(text_ar, st):
    t = Table([[Paragraph(ar(text_ar), st["h2"])]], colWidths=[190 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return t


def _kv_table(items, st):
    """items: list of (label_ar, value). Renders RTL label/value rows."""
    body = []
    for label, value in items:
        body.append([Paragraph(ar(value) if str(value).strip() else ar("—"),
                               st["cell"]),
                     Paragraph(ar(label), st["cell_h"])])
    t = Table(body, colWidths=[140 * mm, 50 * mm])
    style = [
        ("BACKGROUND", (1, 0), (1, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#b9c6d2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]
    t.setStyle(TableStyle(style))
    return t


SECTION_ORDER = {
    "daily": ("تفاصيل التقرير اليومي", [
        ("weather", "حالة الطقس"),
        ("temp_c", "درجة الحرارة (°م)"),
        ("work_hours", "ساعات العمل"),
        ("engineers_count", "عدد المهندسين"),
        ("technicians_count", "عدد الفنيين"),
        ("labor_count", "عدد العمال"),
        ("notes", "ملاحظات إضافية"),
    ]),
    "weekly": ("تفاصيل التقرير الأسبوعي", [
        ("week_no", "رقم الأسبوع"),
        ("progress_percent", "نسبة الإنجاز التراكمية (%)"),
        ("milestones", "الإنجازات والمعالم المحققة"),
        ("manpower_summary", "ملخص القوى العاملة والمعدات"),
        ("look_ahead", "البرنامج المستقبلي للأسبوع القادم"),
        ("challenges", "التحديات الرئيسية"),
        ("decisions_needed", "القرارات المطلوبة من الإدارة"),
        ("notes", "ملاحظات إضافية"),
    ]),
    "monthly": ("تفاصيل التقرير الشهري التنفيذي", [
        ("month", "الشهر / الفترة"),
        ("progress_percent", "نسبة الإنجاز التراكمية (%)"),
        ("financial_overview", "الموجز المالي"),
        ("achievements", "أبرز الإنجازات"),
        ("subcontractor_perf", "أداء المقاولين من الباطن"),
        ("risks", "المخاطر والقضايا العالقة"),
        ("next_month_plan", "خطة الشهر القادم"),
        ("management_signoff", "اعتماد الإدارة"),
        ("notes", "ملاحظات إضافية"),
    ]),
    "safety": ("تفاصيل تقرير السلامة (HSE)", [
        ("inspection_area", "منطقة التفتيش"),
        ("ppe_compliance", "الالتزام بمعدات الوقاية الشخصية"),
        ("toolbox_talks", "محاضرات التوعية المنفذة"),
        ("near_miss", "الحوادث الوشيكة / المسجلة"),
        ("hazards", "المخاطر المرصودة"),
        ("corrective_actions", "الإجراءات التصحيحية الفورية"),
        ("responsible", "المسؤول عن التنفيذ"),
        ("deadline", "الموعد المستهدف للإغلاق"),
        ("notes", "ملاحظات إضافية"),
    ]),
}


def _footer(canvas, doc, serial="", timestamp="", project_name="",
            report_type=""):
    """Full corporate footer: serial, timestamp, page, project context."""
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, A4[0], 34, fill=1, stroke=0)
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.5)
    canvas.line(0, 30, A4[0], 30)
    canvas.setFillColor(colors.white)
    canvas.setFont(FONT_BOLD, 8)
    canvas.drawString(10 * mm, 22, BRAND_AR)
    canvas.setFont(FONT_NORMAL, 7)
    canvas.drawString(10 * mm, 13,
                      "Generated securely via Azadexa Cloud Platform")
    canvas.setFont(FONT_NORMAL, 7.5)
    canvas.drawCentredString(A4[0] / 2, 22,
                             f"SIR-{serial}  •  {timestamp}")
    canvas.drawRightString(A4[0] - 10 * mm, 22,
                            f"Page {doc.page}")
    canvas.setFont(FONT_NORMAL, 6.5)
    canvas.drawCentredString(A4[0] / 2, 13,
                             f"{project_name or '—'}  •  {report_type or '—'}  •  "
                             "© 2026 AZAD Intelligent Systems — All rights reserved")
    canvas.restoreState()


def build_report_pdf(report, author_name: str = "", generated_at: str = "") -> bytes:
    """Render a full A4 PDF for any report type. Returns raw bytes."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10 * mm,
                            leftMargin=10 * mm, topMargin=12 * mm,
                            bottomMargin=36, title=f"Report-{report.id}")
    story = []
    story.append(_header_table(report, st))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.2, color=GOLD))
    story.append(Spacer(1, 4 * mm))
    story.append(_info_table(report, st))
    story.append(Spacer(1, 5 * mm))

    section_title, fields = SECTION_ORDER.get(
        report.report_type, ("تفاصيل التقرير", []))
    story.append(_section_title(section_title, st))
    story.append(Spacer(1, 3 * mm))
    payload = report.data or {}
    # pretty progress value
    items = []
    for key, label in fields:
        val = payload.get(key, "")
        if key == "progress_percent" and val not in ("", None):
            val = f"{val} %"
        items.append((label, val))
    story.append(_kv_table(items, st))
    story.append(Spacer(1, 6 * mm))

    # ---- signatory block
    story.append(_section_title("التوقيع والاعتماد", st))
    story.append(Spacer(1, 3 * mm))
    signatory = report.signatory_name or author_name or "—"
    stamp = generated_at or ""
    sig_rows = [
        [Paragraph(ar(stamp), st["cell"]),
         Paragraph(ar("تاريخ ووقت الإصدار"), st["cell_h"])],
        [Paragraph(ar(signatory), st["cell"]),
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

    serial = f"{report.id:06d}" if report.id else "000000"
    stamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    def _foot(c, d):
        _footer(c, d, serial=serial, timestamp=stamp,
                project_name=report.project_name, report_type=report.type_ar)
    doc.build(story, onFirstPage=_foot, onLaterPages=_foot)
    return buf.getvalue()
