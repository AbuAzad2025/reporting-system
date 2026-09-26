"""Reference-data contract: labels, active keys, and option seeding.

`reference_data` is the single source of truth for every dropdown in the ops
engine. These tests pin the lookup helpers and the `seed_reference_data` pass
that writes those keys into `DynamicField.options`.
"""
import pytest

from app.services import reference_data as ref


class TestRefTableLookups:

    def test_known_table_is_returned(self):
        table = ref.get_reference_table("test_categories")
        assert table is not None
        assert table.name == "test_categories"

    def test_unknown_table_returns_none(self):
        assert ref.get_reference_table("nope") is None
        assert ref.get_choices("nope") == []

    def test_choices_are_key_label_pairs(self):
        choices = ref.get_choices("test_categories")
        assert choices
        for value, label in choices:
            assert isinstance(value, str) and value
            assert isinstance(label, str) and label

    def test_choices_can_switch_language(self):
        ar = dict(ref.get_choices("ball_in_court", "ar"))
        en = dict(ref.get_choices("ball_in_court", "en"))
        assert set(ar) == set(en)
        assert any(ar[k] != en[k] for k in ar)

    def test_get_label_returns_the_translated_label(self):
        table = ref.get_reference_table("test_categories")
        key = table.keys()[0]
        assert table.get_label(key, "ar")
        assert table.get_label(key, "en")

    def test_get_label_falls_back_to_the_key(self):
        table = ref.get_reference_table("test_categories")
        assert table.get_label("missing-key") == "missing-key"

    def test_inactive_items_are_excluded_from_keys(self):
        table = ref.get_reference_table("test_categories")
        all_keys = [item.key for item in table.items]
        assert set(table.keys()) <= set(all_keys)
        assert len(table.keys()) == len([k for i in table.items
                                         if i.is_active for k in [i.key]])

    def test_choices_respect_the_active_flag(self):
        for name in ("test_categories", "ball_in_court", "risk_levels",
                     "vo_categories", "vo_recommendations",
                     "consultant_actions", "sub_recommendations",
                     "equipment_status", "weather"):
            table = ref.get_reference_table(name)
            assert table is not None, name
            assert table.keys(), name
            assert table.choices("ar"), name


class TestExportedLists:

    @pytest.mark.parametrize("name", [
        "TEST_CATEGORIES_LIST", "BALL_IN_COURT_LIST", "WEATHER_LIST",
        "VO_CATEGORIES_LIST", "VO_RECOMMENDATIONS_LIST", "RISK_LEVELS_LIST",
        "SAFETY_INSPECTION_TYPES_LIST", "SAFETY_RESPONSIBLE_LIST",
        "CONSULTANT_ACTIONS_LIST", "SUB_RECOMMENDATIONS_LIST",
        "EQUIPMENT_STATUS_LIST", "COMMENT_PARTIES_LIST"])
    def test_exported_lists_are_unique_non_empty_strings(self, name):
        values = getattr(ref, name)
        assert values, name
        assert all(isinstance(v, str) and v.strip() for v in values), name
        assert len(values) == len(set(values)), name

    @pytest.mark.parametrize("name", [
        "TEST_CATEGORIES_DICT", "BALL_IN_COURT_DICT", "WEATHER_DICT",
        "VO_CATEGORIES_DICT", "VO_RECOMMENDATIONS_DICT", "RISK_LEVELS_DICT",
        "SAFETY_INSPECTION_TYPES_DICT", "SAFETY_RESPONSIBLE_DICT",
        "CONSULTANT_ACTIONS_DICT", "SUB_RECOMMENDATIONS_DICT",
        "EQUIPMENT_STATUS_DICT", "COMMENT_PARTIES_DICT"])
    def test_exported_dicts_carry_both_labels(self, name):
        data = getattr(ref, name)
        assert data, name
        for key, labels in data.items():
            assert isinstance(key, str)
            assert set(labels) == {"label_ar", "label_en"}
            assert labels["label_ar"] and labels["label_en"]

    def test_list_and_dict_exports_agree(self):
        for stem in ("TEST_CATEGORIES", "BALL_IN_COURT", "WEATHER",
                     "RISK_LEVELS", "EQUIPMENT_STATUS"):
            keys = getattr(ref, f"{stem}_LIST")
            mapping = getattr(ref, f"{stem}_DICT")
            assert set(keys) <= set(mapping), stem


class TestSeedReferenceData:

    def test_seeding_writes_keys_into_matching_fields(self, app):
        from app.extensions import db
        from app.models import DynamicField
        from app.services.reference_data import seed_reference_data
        with app.app_context():
            DynamicField.query.filter(
                DynamicField.options.isnot(None)).delete(
                    synchronize_session=False)
            db.session.commit()
            results = seed_reference_data(db)
            assert results["errors"] == []
            updated = DynamicField.query.filter(
                DynamicField.options.isnot(None)).all()
            assert len(updated) == results["updated"]
            assert results["skipped"] > 0
            for field in updated:
                table = None
                for name in ref.REFERENCE_TABLES:
                    if ref.REFERENCE_TABLES[name].keys() == field.options:
                        table = ref.REFERENCE_TABLES[name]
                        break
                assert table is not None, field.field_key
                assert field.options
                assert all(isinstance(v, str) and v for v in field.options)

    def test_seeding_is_idempotent(self, app):
        from app.extensions import db
        from app.models import DynamicField
        from app.services.reference_data import seed_reference_data
        with app.app_context():
            first = seed_reference_data(db)
            before = {f.field_key: list(f.options or [])
                      for f in DynamicField.query.all()}
            second = seed_reference_data(db)
            after = {f.field_key: list(f.options or [])
                     for f in DynamicField.query.all()}
        assert first == second
        assert before == after

    def test_absent_fields_are_counted_as_skipped(self, app):
        from app.extensions import db
        from app.models import DynamicField
        from app.services.reference_data import seed_reference_data
        with app.app_context():
            db.session.query(DynamicField).delete()
            db.session.commit()
            results = seed_reference_data(db)
        assert results["updated"] == 0
        assert results["skipped"] > 0
        assert results["errors"] == []

    def test_unknown_reference_table_is_reported(self, app):
        from unittest.mock import patch
        from app.extensions import db
        from app.services import reference_data as module
        from app.services.reference_data import seed_reference_data
        with patch.dict(module.REFERENCE_TABLES, {"test_categories": None}):
            with app.app_context():
                results = seed_reference_data(db)
        assert any("not found: test_categories" in e for e in results["errors"])

    def test_a_failing_field_is_captured_not_raised(self, app):
        from unittest.mock import patch
        from app.extensions import db
        from app.models import DynamicField
        from app.services.reference_data import seed_reference_data

        class _Boom:
            @staticmethod
            def filter_by(**_kwargs):
                raise RuntimeError("database exploded")

        with app.app_context():
            with patch.object(DynamicField, "query", _Boom):
                results = seed_reference_data(db)
        assert results["errors"]
        assert any("database exploded" in e for e in results["errors"])
        assert results["updated"] == 0


class TestRefItem:

    def test_item_exposes_its_labels(self):
        item = ref.RefItem("k", "بالعربية", "In English", 3)
        assert item.key == "k"
        assert item.label_ar == "بالعربية"
        assert item.label_en == "In English"
        assert item.is_active is True

    def test_inactive_item_is_excluded(self):
        table = ref.RefTable(name="t", items=(
            ref.RefItem("a", "أ", "A", 1),
            ref.RefItem("b", "ب", "B", 2, is_active=False)))
        assert table.keys() == ["a"]
        assert dict(table.choices("ar")) == {"a": "أ"}
