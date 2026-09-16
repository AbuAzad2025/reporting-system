"""Lightweight JSON-schema validation for dynamic fields.

Admins configure per-field rules from the dashboard (stored in
DynamicField.rules); this module enforces them server-side with zero
per-field code. Supported rule keys:

  required (bool) · min / max (numbers) · min_length / max_length (text) ·
  options (closed value list) · pattern (regex, text)
"""
import re


def validate_field_value(field_type: str, value, rules: dict | None,
                         label: str = "الحقل"):
    """Return an Arabic error string, or None when valid.

    Empty values pass here (presence is the caller's `required` concern),
    except checkboxes which always coerce.
    """
    rules = rules or {}
    if field_type == "checkbox":
        return None
    text = "" if value is None else str(value).strip()
    if not text:
        return None

    options = rules.get("options")
    if options and text not in [str(o) for o in options]:
        return f"قيمة غير مسموحة في {label}."

    if field_type == "number":
        try:
            num = float(text)
        except ValueError:
            return f"{label} يجب أن يكون رقماً."
        if rules.get("min") is not None and num < float(rules["min"]):
            return f"{label} يجب أن يكون ≥ {rules['min']}."
        if rules.get("max") is not None and num > float(rules["max"]):
            return f"{label} يجب أن يكون ≤ {rules['max']}."
        return None

    if field_type in ("text", "textarea"):
        if rules.get("min_length") is not None and \
                len(text) < int(rules["min_length"]):
            return f"{label} قصير جداً (الحد الأدنى {rules['min_length']})."
        if rules.get("max_length") is not None and \
                len(text) > int(rules["max_length"]):
            return f"{label} طويل جداً (الحد الأقصى {rules['max_length']})."
        pattern = rules.get("pattern")
        if pattern:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                return f"{label} — نمط التحقق غير صالح ({exc})."
            if not compiled.match(text):
                return f"{label} لا يطابق الصيغة المطلوبة."
        return None

    return None  # date/dropdown(predefined)/unknown: presence handled elsewhere


def rules_from_form(form) -> dict:
    """Build a rules dict from dashboard inputs (min/max/pattern/lengths)."""
    rules: dict = {}
    for key, cast in (("min", float), ("max", float),
                      ("min_length", int), ("max_length", int)):
        raw = (form.get(f"rule_{key}", "") or "").strip()
        if raw != "":
            try:
                rules[key] = cast(raw)
            except ValueError:
                pass
    pattern = (form.get("rule_pattern", "") or "").strip()
    if pattern:
        try:
            re.compile(pattern)
            rules["pattern"] = pattern
        except re.error:
            pass
    return rules
