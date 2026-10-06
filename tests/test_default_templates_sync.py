"""app/services/default_templates.py — the seeder that repairs drift.

Six statements here, all inside the branch that runs when a field already
exists. Fresh databases never reach it, and neither does a test suite that only
adds templates - which is exactly the problem. These statements are the ones
that decide whether editing this file changes an already-deployed database.

Three of them caused real bugs:

* `required` was not synced, so marking a field required in this file did
  nothing to a live deployment;
* `position` was not synced, so reordering a template here changed a fresh
  database and nothing else - and the printed report numbers from document
  position;
* the weekly photo column was stored as text, so the upload cell did not
  render as an upload cell.

Each test drifts the stored row away from the standard, re-runs the seeder, and
asserts it was pulled back.
"""
from app.services import default_templates as dt


def _sync(app):
    from app.models import ReportTemplate, DynamicField
    from app.extensions import db
    with app.app_context():
        dt.ensure_default_templates(db, ReportTemplate, DynamicField)


def _spec_index(template_key, field_key):
    for pos, f in enumerate(dt.default_fields_for(template_key)):
        if f["key"] == field_key:
            return pos
    raise AssertionError(f"{field_key} is not in the {template_key} standard")


def _spec(template_key, field_key):
    for f in dt.default_fields_for(template_key):
        if f["key"] == field_key:
            return f
    raise AssertionError(f"{field_key} is not in the {template_key} standard")


def _field(app, template_key, field_key):
    from app.models import ReportTemplate, DynamicField
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key=template_key).first()
        assert tpl is not None, f"the {template_key} template was not seeded"
        row = DynamicField.query.filter_by(
            template_id=tpl.id, field_key=field_key).first()
        assert row is not None, f"{field_key} is missing from {template_key}"
        return row.id, tpl.id


def _read(app, field_id, attr):
    from app.models import DynamicField
    with app.app_context():
        db_row = DynamicField.query.get(field_id)
        return getattr(db_row, attr)


def _write(app, field_id, **values):
    from app.models import DynamicField
    from app.extensions import db
    with app.app_context():
        row = DynamicField.query.get(field_id)
        for k, v in values.items():
            setattr(row, k, v)
        db.session.commit()


# ==================================== required is part of the standard

def test_a_required_flag_drifting_from_the_standard_is_repaired(app):
    """`required` is a property of the standard, not something an administrator
    types, so it is synced like the columns and the options."""
    key = "weather_esha"
    fid, _tid = _field(app, "daily", key)
    want = bool(_spec("daily", key)["required"])
    _write(app, fid, required=not want)
    _sync(app)
    assert _read(app, fid, "required") == want, (
        "marking a field required in this file has to reach a live database")


def test_an_already_correct_required_flag_is_left_alone(app):
    """The control: the seeder is idempotent, not just corrective."""
    key = "weather_esha"
    fid, _tid = _field(app, "daily", key)
    want = bool(_spec("daily", key)["required"])
    _write(app, fid, required=want)
    _sync(app)
    assert _read(app, fid, "required") == want


# ==================================== position decides the printed order

def test_a_field_position_drifting_from_the_order_is_repaired(app):
    """The report numbers its sections from document position.

    So reordering the standard has to move existing fields; otherwise the edit
    changes a fresh database and nothing else, and the printed report keeps the
    old order permanently.
    """
    key = "weather_esha"
    fid, _tid = _field(app, "daily", key)
    _write(app, fid, position=999)
    _sync(app)
    assert _read(app, fid, "position") == _spec_index("daily", key), (
        "the seeder must restore the field to its position in the standard")


def test_the_seeded_positions_match_the_standard_exactly(app):
    """The control: after a sync, the whole daily order agrees with the spec.

    This is what makes the test above meaningful - a field pulled to the right
    index proves nothing if every other field is also at the wrong one.
    """
    from app.models import ReportTemplate, DynamicField
    _sync(app)
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        stored = {f.field_key: f.position
                  for f in DynamicField.query.filter_by(template_id=tpl.id).all()}
    spec = {f["key"]: pos
            for pos, f in enumerate(dt.default_fields_for("daily"))}
    assert stored == spec, (
        "the seeded positions and the standard disagree: "
        f"{sorted(set(stored.items()) ^ set(spec.items()))[:6]}")


# ==================================== the weekly photo column is a file

def test_a_weekly_photo_column_stored_as_text_is_repaired(app):
    """A text cell cannot hold an upload, so the photo row rendered as a plain
    input and the images had nowhere to go."""
    key = "weekly_photos"
    fid, _tid = _field(app, "weekly", key)
    _write(app, fid, sub_fields=[{"key": "photo", "type": "text",
                                  "label_ar": "صورة"}])
    _sync(app)
    cols = _read(app, fid, "sub_fields")
    assert cols, "the photo column must still be there"
    assert cols[0]["type"] == "file", (
        f"the photo cell must be a file column, got {cols[0]}")


def test_a_weekly_photo_column_already_correct_is_left_alone(app):
    """The control: the repair must not rewrite a column that is right."""
    key = "weekly_photos"
    fid, _tid = _field(app, "weekly", key)
    _sync(app)
    before = _read(app, fid, "sub_fields")
    _sync(app)
    assert _read(app, fid, "sub_fields") == before, (
        "a correct sub_fields must survive two syncs unchanged")


def test_the_repair_reaches_the_session_not_just_the_object(app):
    """The fix uses flag_modified, because sub_fields is a JSON column.

    Mutating the list in place without marking it dirty is the version of this
    bug where the object is right in memory and the database never hears about
    it - so this asserts the value survives a fresh read.
    """
    from app.models import ReportTemplate, DynamicField
    from app.extensions import db
    key = "weekly_photos"
    fid, tid = _field(app, "weekly", key)
    _write(app, fid, sub_fields=[{"key": "photo", "type": "text",
                                  "label_ar": "صورة"}])
    _sync(app)
    with app.app_context():
        db.session.expunge_all()
        row = DynamicField.query.filter_by(
            template_id=tid, field_key=key).first()
        assert row.sub_fields[0]["type"] == "file", (
            "the repair must be flushed to the database, not just held in "
            "memory on a JSON column")
