"""ensure_default_templates must repair drifted field rows, not just add.

The seeder runs on boot and on demand from the admin "restore defaults" action.
Beyond creating missing templates it re-syncs stored field metadata (options,
sub-columns, placeholder, validation rules) — the branch that keeps a database
hand-edited or half-migrated from serving broken forms forever.
"""
from app.extensions import db
from app.models import DynamicField, ReportTemplate
from app.services.default_templates import (DEFAULT_TEMPLATES, OBSOLETE_DAILY_KEYS,
                                            default_fields_for,
                                            ensure_default_templates)


def _reseed(app):
    with app.app_context():
        ensure_default_templates(db, ReportTemplate, DynamicField)


def _field(app, template_key, field_key):
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key=template_key).one()
        return db.session.get(DynamicField, DynamicField.query.filter_by(
            template_id=tpl.id, field_key=field_key).one().id)


def _mutate(app, template_key, field_key, **values):
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key=template_key).one()
        row = DynamicField.query.filter_by(
            template_id=tpl.id, field_key=field_key).one()
        for key, value in values.items():
            setattr(row, key, value)
        db.session.commit()


class TestIdempotency:

    def test_second_run_changes_nothing(self, app):
        def _snapshot():
            with app.app_context():
                return {
                    t.key: sorted(
                        (f.field_key, f.field_type, f.required,
                         tuple(f.options or []), f.placeholder,
                         tuple(sorted((f.rules or {}).items())))
                        for f in t.fields.all())
                    for t in ReportTemplate.query.filter_by(
                        is_system=True).all()}

        before = _snapshot()
        _reseed(app)
        _reseed(app)
        assert _snapshot() == before

    def test_every_default_template_exists_with_fields(self, app):
        _reseed(app)
        with app.app_context():
            for spec in DEFAULT_TEMPLATES:
                tpl = ReportTemplate.query.filter_by(key=spec["key"]).one()
                expected = {f["key"] for f in default_fields_for(spec["key"])}
                stored = {f.field_key for f in tpl.fields.all()}
                assert expected <= stored, spec["key"]


class TestRepairOfDriftedRows:

    def test_missing_template_is_recreated_with_its_fields(self, app):
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            db.session.delete(tpl)
            db.session.commit()
            assert ReportTemplate.query.filter_by(key="daily").count() == 0
        _reseed(app)
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            assert tpl.fields.count() > 0

    def test_missing_field_is_recreated(self, app):
        target = default_fields_for("daily")[0]["key"]
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            row = DynamicField.query.filter_by(
                template_id=tpl.id, field_key=target).one()
            db.session.delete(row)
            db.session.commit()
        _reseed(app)
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            assert DynamicField.query.filter_by(
                template_id=tpl.id, field_key=target).count() == 1

    def test_duplicated_dropdown_options_are_collapsed(self, app):
        with app.app_context():
            dropdown = DynamicField.query.filter(
                DynamicField.field_type == "dropdown",
                DynamicField.options.isnot(None)).first()
            template_key = ReportTemplate.query.get(
                dropdown.template_id).key
            key = dropdown.field_key
            wanted = list(dropdown.options)
        assert wanted
        _mutate(app, template_key, key, options=list(wanted) + list(wanted))
        _reseed(app)
        assert _field(app, template_key, key).options == wanted

    def test_stale_placeholder_is_restored(self, app):
        key = default_fields_for("daily")[0]["key"]
        _mutate(app, "daily", key, placeholder="old text")
        _reseed(app)
        row = _field(app, "daily", key)
        assert row.placeholder != "old text"

    def test_lost_validation_rules_are_restored(self, app):
        rules = default_fields_for("subcontractor-performances")
        scored = [f for f in rules if f["key"] == "quality_score"][0]
        _mutate(app, "subcontractor-performances", "quality_score", rules={})
        _reseed(app)
        row = _field(app, "subcontractor-performances", "quality_score")
        assert row.rules.get("min") == 0
        assert row.rules.get("max") == 100

    def test_weekly_photo_cell_is_migrated_to_file_type(self, app):
        _mutate(app, "weekly", "weekly_photos", sub_fields=[
            {"key": "photo", "label_ar": "صورة", "type": "text",
             "required": True, "options": []},
            {"key": "note", "label_ar": "ملاحظة", "type": "text",
             "required": False, "options": []}])
        _reseed(app)
        cols = _field(app, "weekly", "weekly_photos").sub_fields
        photo = [c for c in cols if c.get("key") == "photo"]
        assert photo and photo[0]["type"] == "file"

    def test_obsolete_daily_fields_are_dropped(self, app):
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            for index, key in enumerate(OBSOLETE_DAILY_KEYS):
                db.session.add(DynamicField(
                    template_id=tpl.id, field_key=key, label_ar="قديم",
                    field_type="text", position=500 + index))
            db.session.commit()
        _reseed(app)
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            stored = {f.field_key for f in tpl.fields.all()}
            assert not (set(OBSOLETE_DAILY_KEYS) & stored)


class TestFieldContract:

    def test_table_fields_expose_normalized_sub_columns(self, app):
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            tables = tpl.fields.filter(
                DynamicField.field_type == "table").all()
            assert tables
            for field in tables:
                cols = field.sub_columns()
                assert cols
                for col in cols:
                    assert set(col) == {"key", "label_ar", "type", "required",
                                        "placeholder", "options"}
                    assert col["key"] == col["key"].lower().replace(" ", "_")

    def test_rules_are_json_serialisable(self, app):
        import json
        with app.app_context():
            for field in DynamicField.query.all():
                json.dumps(field.rules or {})
                json.dumps(field.sub_fields or [])
                json.dumps(field.options or [])
