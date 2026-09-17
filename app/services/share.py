"""Multi-platform report sharing service for Azadexa.

Provides secure share URL generation for:
- Native Web Share API
- WhatsApp (wa.me deep links)
- Direct link copying
- Email (mailto fallback)
"""
from urllib.parse import quote, urlencode
from flask import url_for


def build_report_share_url(report_id: int, report_type: str = "dynamic") -> str:
    """Generate absolute URL for report detail page."""
    if report_type == "legacy":
        return url_for("reports.view", report_id=report_id, _external=True)
    return url_for("reports.dyn_view", sub_id=report_id, _external=True)


def build_share_payload(report, report_type: str = "dynamic") -> dict:
    """Build standardized share payload for a report."""
    serial = getattr(report, "serial", getattr(report, "id", "N/A"))
    if report_type == "legacy":
        serial = f"RPT-{report.id:05d}"

    project = getattr(report, "project_name", "مشروع غير محدد")
    report_date = getattr(report, "report_date", None)
    date_str = report_date.strftime("%Y-%m-%d") if report_date else "—"
    signatory = getattr(report, "signatory_name", "—")
    status = getattr(report, "status_ar", getattr(report, "status", "—"))

    title_map = {
        "site-inspections": "تقرير فحص الموقع",
        "material-submittals": "سجل اعتماد المواد",
        "rfis": "سجل الاستفسارات (RFI)",
        "cost-variances": "تقرير فروقات التكلفة",
        "progress-billings": "تقرير المستخلصات",
        "subcontractor-performances": "تقرير أداء المقاولين",
        "daily-reports": "التقرير اليومي للموقع",
        "variation-orders": "أمر تغييري",
        "safety-reports": "تقرير السلامة (HSE)",
        "legacy": getattr(report, "type_ar", "تقرير"),
    }

    kind = getattr(report, "template", None)
    kind_key = getattr(kind, "key", "legacy") if kind else "legacy"
    report_title = title_map.get(kind_key, "تقرير")

    url = build_report_share_url(report.id, "legacy" if report_type == "legacy" else "dynamic")

    return {
        "serial": serial,
        "title": report_title,
        "project": project,
        "date": date_str,
        "signatory": signatory,
        "status": status,
        "url": url,
    }


def whatsapp_share_url(payload: dict) -> str:
    """Generate WhatsApp share URL (wa.me) with pre-formatted Arabic message."""
    text_lines = [
        "📋 *مشاركة تقرير أزادكسا*",
        "━━━━━━━━━━━━━━━",
        f"📌 *النوع:* {payload['title']}",
        f"🔢 *الرقم التسلسلي:* {payload['serial']}",
        f"🏗 *المشروع:* {payload['project']}",
        f"📅 *التاريخ:* {payload['date']}",
        f"✍️ *المعد:* {payload['signatory']}",
        f"📊 *الحالة:* {payload['status']}",
        "━━━━━━━━━━━━━━━",
        f"🔗 *الرابط:* {payload['url']}",
        "",
        "منصة أزادكسا لتقارير المشاريع الإنشائية",
        "AZAD Intelligent Systems",
    ]
    text = "\n".join(text_lines)
    encoded = quote(text)
    return f"https://wa.me/?text={encoded}"


def email_share_url(payload: dict) -> str:
    """Generate mailto URL with pre-filled subject and body."""
    subject = f"مشاركة تقرير: {payload['title']} - {payload['serial']}"
    body = "\n".join([
        "مرحباً،",
        "",
        "أشارك معك التقرير التالي من منصة أزادكسا:",
        "",
        f"📌 النوع: {payload['title']}",
        f"🔢 الرقم التسلسلي: {payload['serial']}",
        f"🏗 المشروع: {payload['project']}",
        f"📅 التاريخ: {payload['date']}",
        f"✍️ المعد: {payload['signatory']}",
        f"📊 الحالة: {payload['status']}",
        "",
        f"رابط التقرير: {payload['url']}",
        "",
        "—",
        "منصة أزادكسا لتقارير المشاريع الإنشائية",
        "AZAD Intelligent Systems",
    ])
    params = urlencode({"subject": subject, "body": body})
    return f"mailto:?{params}"


def get_share_data(report, report_type: str = "dynamic") -> dict:
    """Get all share data for a report."""
    payload = build_share_payload(report, report_type)
    return {
        "payload": payload,
        "url": payload["url"],
        "whatsapp_url": whatsapp_share_url(payload),
        "email_url": email_share_url(payload),
    }
