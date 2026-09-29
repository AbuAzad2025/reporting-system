"""Which parts of a report a reader would call it missing.

Every field in the daily model is optional on the form, on purpose: a
compliance officer who must tick eighty boxes to press Save will stop
submitting, and a partly filled report is worth more than none. So the form
warns instead of refusing, and the printed report hides whatever was left out.

This is the list behind that warning. It is deliberately short — the header
facts, the description of the day's work, and the sign-off. Not the sixty-five
ESHS compliance actions: those belong to a compliance officer's judgement
about whether a mitigation applied, and prompting for them on a general
engineer's form would be noise. A section nobody filled does not print, which
is the visible consequence.
"""
from __future__ import annotations

#: field_key -> why it matters, shown under the warning so the user is told
#: what is missing rather than only that something is.
CRITICAL_FIELDS = {
    "eshs_desc_81": "وصف أنشطة البناء المنفذة اليوم",
    "eshs_location_82": "موقع تنفيذ الأنشطة",
    "weather_esha": "حالة الطقس وجودة الهواء",
    "staff_esha": "الكادر الفني والعاملون",
    "work_progress_esha": "تقدم الأشغال",
    "safety_team_esha": "فريق البيئة والسلامة في الموقع",
    "signatures_esha": "التوقيع والاعتماد",
}

#: A section is "present" when it carries at least one cell with content, or
#: when it was explicitly declared not to apply. Declaring N/A is a decision
#: and counts; an empty table is an omission and does not.
NOT_APPLICABLE = {"n/a", "na", "لا ينطبق", "غير منطبق", "لا ينطبق اليوم"}


def _is_filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple, dict)):
        if not value:
            return False
        if isinstance(value, dict):
            return any(_is_filled(v) for v in value.values())
        return any(_is_filled(v) for v in value)
    return str(value).strip() not in ("", "no", "false", "0")


def _is_declared_na(value) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_is_declared_na(v) for v in value)
    if isinstance(value, dict):
        return any(_is_declared_na(v) for v in value.values())
    return str(value or "").strip().lower() in NOT_APPLICABLE


def missing_critical_fields(template, payload: dict | None) -> list[tuple[str, str]]:
    """The critical fields this submission left empty.

    Returns ``(field_key, label)`` for each, in the order the standard lists
    them. An empty list means the report can be signed off as it stands.
    """
    payload = payload or {}
    by_key = {f.field_key: f for f in template.ordered_fields}
    missing = []
    for key, why in CRITICAL_FIELDS.items():
        field = by_key.get(key)
        if field is None:
            continue  # not part of this template
        value = payload.get(key)
        if _is_filled(value) or _is_declared_na(value):
            continue
        missing.append((key, why))
    return missing
