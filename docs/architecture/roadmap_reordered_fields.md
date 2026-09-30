# Roadmap: tenant-level field reordering (`reordered_fields`)

| | |
|---|---|
| **Status** | Deferred — schema live, behaviour absent |
| **Owner** | Forms / reporting subsystem |
| **Ticket type** | Tech debt (feature never completed, not a regression) |
| **Guarded by** | `tests/test_tenant_customisation.py::TestNoUnexecutedOverride` |
| **First raised** | During the core architectural overhaul (inline-JS extraction, CSS token work, template contract guards) |

## Summary

`TenantTemplateOverride.reordered_fields` is a JSON column that a tenant-level
form builder was meant to read so one tenant could present a template's fields
in a different order from the platform default. The column exists and is
declared with `default=list`. Nothing writes it, nothing reads it, and no
administrative surface exists to set it.

The application *does* support reordering fields — but that is a different
mechanism at a different level, and conflating the two is the main trap here.
See [Two ordering systems](#two-ordering-systems) below.

This document records what was intended, why it was not finished, and what a
correct implementation would have to do. It is deliberately not an instruction
to implement it now.

## What exists today

The column, verbatim (`app/models.py:416`):

```python
class TenantTemplateOverride(db.Model):
    __tablename__ = "tenant_template_overrides"
    template_key = db.Column(db.String(60), nullable=False, index=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    is_active = db.Column(db.Boolean, default=True)
    fields_config = db.Column(db.JSON, default=dict)
    deleted_fields = db.Column(db.JSON, default=list)
    added_fields = db.Column(db.JSON, default=list)
    reordered_fields = db.Column(db.JSON, default=list)
```

It is one of four sibling JSON columns on the same row. Three of the four
(`fields_config`, `deleted_fields`, `added_fields`) *are* read, by two
functions in `app/services/default_templates.py`:

- `apply_tenant_overrides(tpl, current_user)`
- `build_tenant_fields(tpl, override)`

`reordered_fields` is the only one of the four that is not.

## The ghost binding this replaced

Both functions previously opened with a line like this, and then never used the
name again:

```python
reordered = override.reordered_fields or []
```

That single statement is why this took as long as it did to see. It is
syntactically valid, it sits alongside three sibling lines that genuinely do
something, and the linter is silent — the module is excluded because it
legitimately carries 189 over-long data-literal lines. Meanwhile three
independent signals all indicated the feature worked:

1. The column was declared, populated-by-default, and named exactly as a working
   one would be.
2. The read sat next to reads of `deleted_fields` and `added_fields`, which
   *are* consumed.
3. The test module's own docstring listed "ordering" among the behaviours it
   pinned.

None of it had ever executed. The unbound local was the whole of the
implementation.

A fourth signal, in the same family, was corrected at the same time:
`build_tenant_fields`'s own docstring read *"Build ordered DynamicField dicts
honoring override rules"*. It builds unordered dicts, not ORM objects, and it
drops `rules` on custom fields. A docstring asserting a capability is exactly
how the other three signals survived review, so it now says what the function
does and does not do, and points here.

The dead bindings have been removed, the false claims in the test module and
function docstrings have been corrected, and `TestNoUnexecutedOverride` now
fails if application code reads `override.reordered_fields` again. That class
and this document should both be deleted in the same change that implements
the feature.

## Two ordering systems

The single most important thing to understand before implementing this: field
order is expressed **twice**, at two different levels, in two different data
shapes. A tenant-level order list has to compose with the platform one, not
replace it.

### 1. Platform order — works today

| | |
|---|---|
| Storage | `DynamicField.position` (`Integer`, `app/models.py:281`) |
| Ordering | `ReportTemplate.fields` is `order_by="DynamicField.position"` (`app/models.py:240-248`) |
| Mutation | `admin.field_move` (`app/admin/routes.py:232`) swaps `position` with a sibling |
| Surface | The ↑ / ↓ buttons on `/admin/fields` |
| Scope | One order for every user of the template |

`field_move` is a swap, not a renumber, so it cannot produce gaps or
duplicates:

```python
sibs = DynamicField.query.filter_by(template_id=f.template_id).order_by(
    DynamicField.position).all()
j = idx - 1 if direction == "up" else idx + 1
if 0 <= j < len(sibs):
    sibs[idx].position, sibs[j].position = sibs[j].position, sibs[idx].position
```

This is the ordering the README describes under "add/edit/remove/reorder
fields", and it is real. It is **not** what `reordered_fields` was for.

### 2. Tenant order — does not exist

`reordered_fields` was intended to let one tenant see the same template's
fields in its own preferred sequence, without the platform owner having to
change the order for everyone. It would be a per-tenant permutation layered on
top of the platform order.

### The shape mismatch that blocks any naive wiring

This is the finding that makes "just call the function from the route" wrong,
and it is why the two override functions are not simply unhooked:

```
default_fields_for()      -> [dict]  keys: key, label_ar, options, required, columns
build_tenant_fields()     -> [dict]  <- the override layer's output shape
ReportTemplate.ordered_fields -> [DynamicField]  field_key, label_ar, field_type
```

The override functions produce **dicts**. The live form renderer — `dyn_new`,
`dyn_edit`, `dyn_view` and `_collect_dynamic` in `app/reports/routes.py` —
consumes **`DynamicField` ORM objects**. Wiring `build_tenant_fields` into
`dyn_new` unchanged would not merely fail to reorder anything; it would feed the
template the wrong object type entirely.

There is a second, independent shape problem: `apply_tenant_overrides` and
`build_tenant_fields` are seeded from `default_fields_for()`, which is the
**seed-time** spec. Runtime rendering reads the ORM. The two have already
drifted apart.

## Why it was deferred

Not to protect working behaviour — there is none to protect. The reasons are
about blast radius and about a false economy:

1. **No production caller exists.** Both functions are referenced only from
   `tests/`. The tenant-override subsystem as a whole is unwired, so
   `reordered_fields` is the visible symptom of a larger deferral, not an
   isolated gap. Fixing just the ordering would leave the rest unwired and
   would not make tenant reordering work.

2. **Wiring it in is a renderer change, not a column change.** Per the shape
   mismatch above, this touches the field list that `dyn_new`, `dyn_edit`,
   `dyn_view` and `_collect_dynamic` all consume, plus PDF generation
   (`build_dynamic_pdf`, `pdf_dynamic.py`) which re-derives section order.
   That is the report's primary output. Regressing it degrades printed
   deliverables, not just a screen.

3. **It is not observable today.** Because nothing writes the column, no
   production row can be affected by getting the read wrong. Building it
   eagerly would mean inventing a data shape, a write path, and a migration for
   data that does not exist.

4. **The adjacent divergence is the real hazard.** The two functions already
   disagree with each other, and the disagreement is invisible while both are
   unwired:

   | behaviour | `apply_tenant_overrides` | `build_tenant_fields` |
   |---|---|---|
   | blank a label with `label_ar: ""` | ignored (`if cfg.get(...)`) | honoured (`if "label_ar" in cfg`) |
   | `type` set to `""` | ignored | honoured |
   | `options` set to `null` | ignored (`is not None` test differs) | honoured |
   | `rules` on a base field | applied | **not handled** |
   | `rules` on an added field | applied | **key dropped silently** |
   | inactive override | gated in the query (`is_active=True`, line 709) | gated on the object (`if not override.is_active`, line 779) |

   The last row is the same rule expressed twice, in two places — benign today,
   but it is the pattern that produced the two `rules` rows above.

   Implementing reordering on top of two functions that already disagree about
   label blanking would double down on the ambiguity. One of the two has to be
   chosen first, deliberately.

5. **Scope discipline.** The architectural pass that surfaced this was about
   extracting inline JavaScript, consolidating CSS tokens and adding template
   contract guards. Implementing a tenant-facing feature inside it would have
   put unreviewed new behaviour in a refactoring change, which is how a
   report-ordering regression gets shipped unnoticed.

## Design blueprint for a future implementation

Not a prescription. These are the constraints any correct implementation has to
satisfy, in the order they bite.

### Phase 0 — settle the substrate

Before ordering can be layered on, the tenant-override layer itself has to be
wired and made singular.

- **Pick one function.** `build_tenant_fields` is the stricter and more
  expressive of the two (`in cfg` rather than truthiness, and it gates on
  `is_active`). Fold `apply_tenant_overrides` into it as the wrapper that
  resolves the override row, then delete the loser and its tests.
- **Choose the truthiness rule once** and apply it to `type`, `label_ar`,
  `options`, `placeholder` and `rules`. Whether `label_ar: ""` means "blank
  this label" or "leave the default" is a product decision; it cannot be left
  as whichever the surviving function happened to do.
- **Fix the `rules` asymmetry.** A custom field's `rules` must survive
  `build_tenant_fields`, and base fields must accept them too.
- **Move to the runtime shape.** The override layer must operate on
  `DynamicField`, not on seed dicts — or the renderer must be taught to accept
  dicts. Pick one; do not convert at the call site.
- **Only then** pick up a caller in `dyn_new` / `dyn_edit`.

Exit criterion: a tenant's `deleted_fields` and `fields_config` visibly change
the rendered form and the PDF, in a test, with no ordering involved.

### Phase 1 — specify the stored shape

`reordered_fields` is `JSON` with `default=list`, and is empty on every
existing row, so the format is unconstrained. It has to be **specified before
code**, because the tenant's stored list must survive the platform owner
adding, renaming or deleting fields afterwards.

Minimum viable shape — a permutation of **keys**, not of ids or indexes:

```json
["project_name", "report_date", "contractor", "weather", "manpower"]
```

Rules the format must satisfy:

| Rule | Reason |
|---|---|
| Identify by `field_key`, never by `id` or array index | `id` is per-tenant-row and unstable across restore/backup; an index is meaningless once the base list changes |
| A **partial** list is a prefix, not a permutation | Otherwise adding one platform field silently invalidates every tenant's order |
| **Unknown keys are ignored**, never fatal | A tenant's stored list outlives any platform field rename; this is the case that makes a hard failure unacceptable |
| Never reorder *within* a `table` field's columns | Column order is `sub_columns()` on the field itself, edited by `field_column_add` / `field_column_delete`; it is a different axis |
| Empty / `None` / malformed ⇒ no override | Fall back to platform order. A bad JSON blob must never take a form down |

Use `field_key`, which already carries a per-template unique constraint
(`uq_template_field_key`, `app/models.py:258-261`), so the ordering vocabulary
is already enforced to be unique. It is also a `String(60)`, which bounds the
validation in Phase 3.

### Phase 2 — implement the sort as one pure function

One function, no I/O, no globals, trivially testable — the same shape as
`theme.js`'s `resolveTheme` and `profile.js`'s `isDisplayableImage`, which are
already the pattern in this codebase:

```python
def apply_tenant_order(fields, reordered):
    """Reorder `fields` (DynamicField objects) for a tenant.

    A partial list is a prefix. Unknown keys are skipped. A missing or
    malformed list returns the platform order unchanged.
    """
```

Contract to pin down in tests first:

1. `reordered` empty / `None` / not a list ⇒ platform order, same list object.
2. Keys not present on the template are dropped, and the rest still apply.
3. A key listed twice keeps its **first** occurrence.
4. Keys absent from `reordered` keep their relative platform order, and land
   after the explicitly-listed prefix.
5. The input list is not mutated — `build_tenant_fields` already has a
   `test_build_tenant_fields_does_not_mutate_the_defaults` contract, and this
   must not reintroduce aliasing.
6. `table` fields are not descended into.

### Phase 3 — validation, at the trust boundary

The list is user-supplied JSON, so validate it where it arrives, not where it
is used. In the style of `branding.normalise_hex`, which sanitises a tenant
colour before it can reach the inline `<style>` block in `base.html`:

- Accept only a list of strings.
- Coerce to `str`, strip, reject anything over `DynamicField.field_key`'s
  60-character length.
- Deduplicate while preserving first occurrence.
- Reject non-string entries outright rather than coercing them, so a caller
  gets a clear error instead of a silently reordered form.

**Do not trust the stored list at render time.** It may predate a field
rename. Rendering must re-derive against the current template and tolerate
drift — that is rule 3 of the Phase 1 table, and it is the one that keeps a
stale tenant from breaking a form.

### Phase 4 — tenant scoping

`tenant_id` is `ForeignKey("users.id")` — a **user**, not a project, while
tenant branding elsewhere is scoped per **project** (`TenantBranding.project_id`).
The override lookup is user-level only, and that asymmetry is deliberate and
already documented at the call site:

```python
# The override is looked up by user id only. There is no project-level
# fallback, which is the isolation rule: a user sees their own customisation
# or the platform default, never another tenant's.
```

That rule must survive. Any implementation must:

- Resolve the override by `current_user.id` only. No project fallback, no
  cross-tenant lookup, no "nearest ancestor" resolution.
- Keep the isolation test in `test_tenant_customisation.py` (a second tenant's
  override must not alter this tenant's form) and extend it to cover order.
- Consider whether user-level scoping is still the right call now that
  branding is project-level. If it changes, it is a **schema change** — it
  needs a migration, and it is a product decision, not a refactor.

### Phase 5 — apply at every render site, or none

Order is consumed in more places than the form. A change that only fixes
`dyn_new` will produce a form and a PDF that disagree:

| Consumer | File |
|---|---|
| Form render | `reports/routes.py` — `dyn_new`, `dyn_edit` |
| View render | `reports/routes.py` — `dyn_view` |
| Value collection | `reports/routes.py` — `_collect_dynamic` |
| PDF output | `services/pdf_dynamic.py` — `build_dynamic_pdf` |
| Archive | `templates/reports/dyn_view.html` (section order) |
| Completion warning | `services/report_completeness.py` — `missing_critical_fields` |

Decide explicitly: does tenant order affect the **printed report**? A form
whose field order differs from its PDF order is a defect report, not a feature.
The default should be that it does not, in which case the PDF must be pinned to
platform order deliberately and by comment.

### Phase 6 — the write path

There is no administrative surface for any of this today — no route in
`app/admin/routes.py` references `TenantTemplateOverride` at all. Shipping the
read before the write keeps the column inert and keeps the deferral honest;
shipping the write means a new form, and drag-and-drop ordering needs keyboard
accessibility and a non-DOM fallback, or it fails the accessibility posture the
rest of the app holds.

Note that `field_move` already establishes the swap idiom for the platform
level. A tenant order list should reuse the same "move up / move down" shape
rather than introduce a second interaction pattern.

### Phase 7 — retire the guard

In the same change that implements the feature:

- Delete `TestNoUnexecutedOverride` — or reduce it to asserting that the column
  is read *and* written, so it keeps guarding rather than just getting deleted.
- Delete this document, or move it to a changelog.
- Update the test module docstring, which currently states that ordering is
  deliberately absent.

## What was verified for this ticket

Run on the working tree at the time of writing.

| Check | Result |
|---|---|
| `reordered_fields` read anywhere in `app/` | no — only the column declaration, plus two explanatory comments |
| `reordered_fields` assigned by any route, CLI or service | no |
| Administrative surface for tenant overrides (`app/admin/routes.py`) | none exists |
| Production callers of `apply_tenant_overrides` / `build_tenant_fields` | none — `tests/` only |
| Lint (`ruff F401,F841,F821` on `app/services/default_templates.py`, `app/models.py`) | clean |
| `TestNoUnexecutedOverride` fails on a re-injected ghost binding | yes, confirmed by injection |
| `tests/test_tenant_customisation.py` | 34 passed |

## Decision required

This ticket records a deferral, not a commitment. Someone with product context
has to decide:

1. Is tenant-level ordering wanted at all, given the platform owner can already
   reorder and there is no tenant admin UI?
2. If yes — is user-level (`tenant_id` → `users.id`) still the right scope, now
   that branding is per project?
3. If yes — should the printed report follow the tenant's order, or stay on the
   platform order?

Until those are answered, the column stays declared and unread, and the guard
keeps it that way. Dropping the column outright is the other legitimate
option, and it is a schema change with a migration.
