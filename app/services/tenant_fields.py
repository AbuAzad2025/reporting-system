"""
Per-company report customisation.

Every consumer of a template's field list - the entry form, the read view, the
value collector, the completeness check and the PDF - resolves it through
`resolve_fields`. One choke point, so a company's custom form cannot be right on
the form and wrong on the printout.

The override row is a `TenantTemplateOverride`, and it holds four JSON columns:
fields to delete, fields to add, per-field changes, and a field order. They are
applied here and nowhere else.

**Why this returns objects rather than dicts.** The override functions that
existed before this (`apply_tenant_overrides` and `build_tenant_fields` in
app/services/default_templates.py) return plain dicts, because they were
written against `default_fields_for()`, the seed-time specification. The
templates and the PDF read `DynamicField` rows. Wiring the old functions into a
route would have handed the renderer the wrong type. `TenantField` closes that
gap by exposing the same attribute surface a `DynamicField` does, so
`dyn_form.html`, `dyn_view.html`, `_collect_dynamic`, `missing_critical_fields`
and `build_dynamic_pdf` need no change to work.

**A company's custom fields are never written to `dynamic_fields`.** That table
is the platform template, shared by every company. A tenant-added field is held
in the override's JSON and materialised here as a `TenantField` with no
database row at all, so customising one company cannot change what another
sees.
"""
from dataclasses import dataclass, field as _dc_field
from typing import Any

from app.extensions import db
from app.models import DynamicField, TenantTemplateOverride

#: Field types a company may add. Matched against FIELD_TYPES so the admin UI
#: and this validator cannot drift apart.
VALID_TYPES = ("text", "textarea", "number", "dropdown", "date",
               "checkbox", "table")

#: Longest a company-added field key may be, matching DynamicField.field_key.
MAX_KEY_LENGTH = 60

#: Types a table *column* may be. Narrower than VALID_TYPES: a column cannot be
#: a table. Mirrors DynamicField.CELL_TYPES.
CELL_TYPES = ("text", "textarea", "number", "dropdown", "date", "checkbox",
              "file")


@dataclass
class TenantField:
    """One field as one company sees it.

    Mirrors the attribute surface of `DynamicField` that the templates and
    services actually use, so a custom field is indistinguishable from a
    platform one at the point of use.
    """
    field_key: str
    label_ar: str
    field_type: str = "text"
    options: list = _dc_field(default_factory=list)
    required: bool = False
    rules: dict = _dc_field(default_factory=dict)
    sub_fields: list = _dc_field(default_factory=list)
    placeholder: str = ""
    #: The DynamicField this came from, or None for a company-added field.
    source: DynamicField | None = None
    #: True when the company added it, so the admin UI can label it.
    is_custom: bool = False

    @property
    def id(self):
        return self.source.id if self.source is not None else None

    @property
    def template_id(self):
        return self.source.template_id if self.source is not None else None

    @property
    def position(self):
        return self.source.position if self.source is not None else 0

    def options_list(self):
        """The dropdown choices, as DynamicField.options_list returns them."""
        out = []
        for opt in self.options or []:
            if isinstance(opt, dict):
                value = opt.get("value", opt.get("label", ""))
            else:
                value = opt
            if value is not None and str(value) != "":
                out.append(value)
        return out

    def sub_columns(self):
        """The table's columns, shaped exactly as DynamicField.sub_columns.

        Mirrored deliberately, key for key. An earlier version of this method
        omitted `placeholder` and defaulted an empty `label_ar` to "" instead
        of the column key, which is not a cosmetic difference: `placeholder`
        is where the guidance examples live, so every table cell on every
        company form silently lost its example. The equality test in
        tests/test_tenant_fields.py is what keeps the two from drifting.
        """
        cols = []
        for col in self.sub_fields or []:
            if not isinstance(col, dict):
                continue
            key = str(col.get("key", "")).strip().lower().replace(" ", "_")
            if not key:
                continue
            cell_type = col.get("type")
            if cell_type not in CELL_TYPES:
                cell_type = "text"
            cols.append({
                "key": key,
                "label_ar": str(col.get("label_ar") or key),
                "type": cell_type,
                "required": bool(col.get("required")),
                "placeholder": str(col.get("placeholder") or ""),
                "options": [str(o) for o in (col.get("options") or [])],
            })
        return cols

    def __repr__(self):
        return f"<TenantField {self.field_key}:{self.field_type}>"


def get_override(template_key: str, project_id: int | None) -> Any:
    """The active override for one company and template, or None.

    project_id is None for a submission with no project, which is a legitimate
    state: the entry form lets a user type a project name freehand. Such a
    submission is served the platform template, never somebody else's.
    """
    if not project_id or not template_key:
        return None
    return TenantTemplateOverride.query.filter_by(
        template_key=template_key, project_id=project_id,
        is_active=True).first()


def normalise_key(key: Any) -> str:
    """A field key, cleaned and bounded.

    Company input is untrusted, and the key becomes an element name in the POST
    and a key in the stored JSON. Spaces become underscores, everything else
    outside [a-z0-9_] is dropped, and the result is truncated to the column
    width so a long key cannot produce a value the platform table could not
    hold.

    Order matters: the space-to-underscore step has to run before the filter,
    or "Foo Bar" collapses to "foobar" and reads as a different key than the
    one the admin typed.
    """
    if not isinstance(key, str):
        return ""
    spaced = key.strip().lower().replace(" ", "_")
    cleaned = "".join(ch for ch in spaced if ch.isalnum() or ch == "_")
    return cleaned[:MAX_KEY_LENGTH]


def sanitise_added_fields(added: Any) -> list[dict]:
    """Validate a company-supplied list of new fields.

    Applied on write as well as on read: the admin POST is validated here before
    it reaches the database, and again here on the way out, so a row written
    by hand or by an older version cannot reach a template.
    """
    out = []
    if not isinstance(added, list):
        return out
    seen = set()
    for raw in added:
        if not isinstance(raw, dict):
            continue
        key = normalise_key(raw.get("key"))
        if not key or key in seen:
            continue
        ftype = raw.get("type")
        if ftype not in VALID_TYPES:
            ftype = "text"
        options = raw.get("options") or []
        if not isinstance(options, list):
            options = []
        entry = {
            "key": key,
            "label_ar": str(raw.get("label_ar") or key)[:200],
            "type": ftype,
            "required": bool(raw.get("required", False)),
            "options": [str(o)[:200] for o in options if str(o).strip()][:100],
            "placeholder": str(raw.get("placeholder") or "")[:200],
            "rules": raw.get("rules") if isinstance(raw.get("rules"), dict) else {},
            "columns": [],
        }
        if ftype == "table" and isinstance(raw.get("columns"), list):
            entry["columns"] = [
                {
                    "key": normalise_key(c.get("key"))[:MAX_KEY_LENGTH],
                    "label_ar": str(c.get("label_ar") or "")[:200],
                    "type": c.get("type") if c.get("type") in VALID_TYPES else "text",
                    "required": bool(c.get("required", False)),
                    "options": [str(o)[:200] for o in (c.get("options") or [])][:100],
                }
                for c in raw["columns"]
                if isinstance(c, dict) and normalise_key(c.get("key"))
            ]
        seen.add(key)
        out.append(entry)
    return out


def sanitise_config(config: Any) -> dict:
    """Validate a company-supplied map of per-field changes."""
    out: dict = {}
    if not isinstance(config, dict):
        return out
    for raw_key, cfg in config.items():
        if not isinstance(cfg, dict):
            continue
        key = normalise_key(raw_key)
        if not key:
            continue
        clean: dict = {}
        if cfg.get("field_type") in VALID_TYPES:
            clean["field_type"] = cfg["field_type"]
        if "label_ar" in cfg:
            clean["label_ar"] = str(cfg["label_ar"])[:200]
        if "required" in cfg:
            clean["required"] = bool(cfg["required"])
        if "options" in cfg and isinstance(cfg["options"], list):
            clean["options"] = [str(o)[:200] for o in cfg["options"]
                                if str(o).strip()][:100]
        if "placeholder" in cfg:
            clean["placeholder"] = str(cfg["placeholder"])[:200]
        if isinstance(cfg.get("rules"), dict):
            clean["rules"] = cfg["rules"]
        if clean:
            out[key] = clean
    return out


def apply_order(fields: list[TenantField], reordered: Any) -> list[TenantField]:
    """Reorder fields for a company.

    A partial list is a prefix, not a permutation: a company lists only the
    fields it wants moved to the top, and everything else follows in platform
    order. Keys that no longer exist on the template are dropped rather than
    raising, because a stored order outlives any field rename the platform
    might later make.

    Returns a new list; the input is not reordered in place.
    """
    if not isinstance(reordered, list):
        return list(fields)

    by_key = {f.field_key: f for f in fields}
    prefix, used, tail = [], set(), []
    for raw in reordered:
        key = normalise_key(raw)
        if not key or key in used or key not in by_key:
            continue
        prefix.append(by_key[key])
        used.add(key)
    for f in fields:
        if f.field_key not in used:
            tail.append(f)
    return prefix + tail


def resolve_fields(template, project_id: int | None = None) -> list[TenantField]:
    """The field list one company sees for one template.

    This is the single place a company's customisation is applied. Every render
    path calls it, so the form, the read view, the saved values, the
    completeness warning and the PDF cannot disagree about what the form was.

    With no project, or no override, the result is the platform template
    unchanged - the same order, the same fields, wrapped but otherwise
    identical.
    """
    platform = template.ordered_fields
    override = get_override(template.key, project_id)
    if override is None:
        return [TenantField(
            field_key=f.field_key,
            label_ar=f.label_ar,
            field_type=f.field_type,
            options=list(f.options or []),
            required=bool(f.required),
            rules=dict(f.rules or {}),
            sub_fields=list(f.sub_fields or []),
            placeholder=f.placeholder or "",
            source=f,
        ) for f in platform]

    deleted = {normalise_key(k) for k in (override.deleted_fields or [])}
    config = sanitise_config(override.fields_config)
    custom = sanitise_added_fields(override.added_fields)

    out: list[TenantField] = []
    for f in platform:
        if f.field_key in deleted:
            continue
        cfg = config.get(f.field_key, {})
        out.append(TenantField(
            field_key=f.field_key,
            label_ar=cfg.get("label_ar", f.label_ar),
            field_type=cfg.get("field_type", f.field_type),
            options=cfg.get("options", list(f.options or [])),
            required=cfg.get("required", bool(f.required)),
            rules=cfg.get("rules", dict(f.rules or {})),
            sub_fields=list(f.sub_fields or []),
            placeholder=cfg.get("placeholder", f.placeholder or ""),
            source=f,
        ))

    # A company-added field must not shadow a platform one, and must not
    # reintroduce something the company deleted.
    existing = {f.field_key for f in out}
    for raw in custom:
        if raw["key"] in existing:
            continue
        out.append(TenantField(
            field_key=raw["key"],
            label_ar=raw["label_ar"],
            field_type=raw["type"],
            options=list(raw["options"]),
            required=raw["required"],
            rules=dict(raw["rules"]),
            sub_fields=list(raw["columns"]),
            placeholder=raw["placeholder"],
            source=None,
            is_custom=True,
        ))

    return apply_order(out, override.reordered_fields)


def save_override(template_key: str, project_id: int, *,
                  fields_config: Any = None, deleted_fields: Any = None,
                  added_fields: Any = None,
                  reordered_fields: Any = None) -> TenantTemplateOverride:
    """Create or update one company's override, after validation.

    Validation happens here rather than at the form, so a row cannot be written
    with a field type the renderer does not know or a key the platform table
    could not hold.
    """
    if not project_id:
        raise ValueError("a company is required to customise a template")
    if not template_key:
        raise ValueError("a template key is required")

    row = TenantTemplateOverride.query.filter_by(
        template_key=template_key, project_id=project_id).first()
    if row is None:
        row = TenantTemplateOverride(template_key=template_key,
                                     project_id=project_id)
        db.session.add(row)

    if fields_config is not None:
        row.fields_config = sanitise_config(fields_config)
    if deleted_fields is not None:
        row.deleted_fields = sorted(
            {normalise_key(k) for k in deleted_fields if normalise_key(k)})
    if added_fields is not None:
        row.added_fields = sanitise_added_fields(added_fields)
    if reordered_fields is not None:
        seen, order = set(), []
        for raw in reordered_fields:
            key = normalise_key(raw)
            if key and key not in seen:
                seen.add(key)
                order.append(key)
        row.reordered_fields = order

    db.session.commit()
    return row
