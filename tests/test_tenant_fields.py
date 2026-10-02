"""Per-company report customisation.

The override table existed for a long time with no caller: `reordered_fields`
was read into an unused local and nothing else read the row at all. These tests
cover the behaviour that replaced that, and the two things that made the old
design unusable:

  1. It was scoped to a user, so a company of thirty engineers would have got
     thirty different forms. It is scoped to a project now.
  2. The functions that read it returned dicts while the renderer reads
     `DynamicField` rows, so wiring them in unchanged would have handed the
     template the wrong type. `TenantField` exists to close that.

The isolation tests are the ones that matter most. A customisation that leaked
between companies would be a data-disclosure bug: one company's form would show
another's fields.
"""
import pytest

from app.extensions import db
from app.models import (DynamicField, Project, ReportTemplate,
                        TenantTemplateOverride)
from app.services.tenant_fields import (TenantField, apply_order,
                                        get_override, normalise_key,
                                        resolve_fields, sanitise_added_fields,
                                        sanitise_config, save_override)


def _tpl(key="daily"):
    return ReportTemplate.query.filter_by(key=key).first()


def _project(name):
    p = Project(name=name)
    db.session.add(p)
    db.session.commit()
    return p


# ------------------------------------------------------------- pure helpers
class TestNormaliseKey:
    def test_a_space_becomes_an_underscore(self):
        # Order matters: filtering before the substitution collapses
        # "Foo Bar" to "foobar", a different key from the one the admin typed.
        assert normalise_key("Foo Bar") == "foo_bar"
        assert normalise_key("  Weather  Daily  ") == "weather__daily"

    def test_anything_outside_the_safe_set_is_dropped(self):
        assert normalise_key("a-b.c/d") == "abcd"
        assert normalise_key("f<script>") == "fscript"

    def test_non_strings_and_blanks_are_empty(self):
        for value in (None, 123, [], {}, ""):
            assert normalise_key(value) == ""

    def test_arabic_keys_survive(self):
        # The interface is Arabic; a key is not required to be latin.
        assert normalise_key("موقع المشروع") == "موقع_المشروع"

    def test_the_result_fits_the_platform_column(self):
        assert len(normalise_key("a" * 200)) == 60


class TestApplyOrder:
    def _fields(self, *keys):
        return [TenantField(field_key=k, label_ar=k) for k in keys]

    def test_no_order_leaves_the_platform_order(self):
        fs = self._fields("a", "b", "c")
        assert [f.field_key for f in apply_order(fs, None)] == ["a", "b", "c"]

    def test_a_partial_list_is_a_prefix_not_a_permutation(self):
        # This is the rule that makes a stored order survive the platform
        # owner adding a field afterwards.
        fs = self._fields("a", "b", "c", "d")
        assert [f.field_key for f in apply_order(fs, ["c", "a"])] == \
            ["c", "a", "b", "d"]

    def test_a_key_that_no_longer_exists_is_dropped_not_fatal(self):
        fs = self._fields("a", "b")
        assert [f.field_key for f in apply_order(fs, ["zz", "b"])] == ["b", "a"]

    def test_a_repeated_key_keeps_its_first_position(self):
        fs = self._fields("a", "b", "c")
        assert [f.field_key for f in apply_order(fs, ["a", "a", "c"])] == \
            ["a", "c", "b"]

    def test_junk_leaves_the_order_alone(self):
        for junk in ("nope", 7, {"a": 1}):
            fs = self._fields("a", "b")
            assert [f.field_key for f in apply_order(fs, junk)] == ["a", "b"]

    def test_the_input_list_is_not_reordered_in_place(self):
        fs = self._fields("a", "b", "c")
        apply_order(fs, ["c"])
        assert [f.field_key for f in fs] == ["a", "b", "c"]


class TestSanitise:
    def test_an_unknown_field_type_falls_back_to_text(self):
        out = sanitise_added_fields([{"key": "k", "type": "evil"}])
        assert out[0]["type"] == "text"

    def test_duplicate_keys_collapse(self):
        out = sanitise_added_fields([{"key": "a"}, {"key": "A "}, {"key": "b"}])
        assert [e["key"] for e in out] == ["a", "b"]

    def test_entries_that_are_not_objects_are_ignored(self):
        assert sanitise_added_fields(["x", 7, None, []]) == []
        assert sanitise_config({"a": "not a dict", "": {"label_ar": "x"}}) == {}

    def test_blank_dropdown_options_are_dropped(self):
        out = sanitise_added_fields(
            [{"key": "k", "type": "dropdown", "options": ["a", "", "  ", "b"]}])
        assert out[0]["options"] == ["a", "b"]

    def test_a_table_field_keeps_its_columns(self):
        out = sanitise_added_fields([{
            "key": "tbl", "type": "table",
            "columns": [{"key": "c1", "type": "dropdown", "options": ["x"]},
                        {"key": "", "label_ar": "no key"}]}])
        assert [c["key"] for c in out[0]["columns"]] == ["c1"]

    def test_a_bad_type_in_config_is_not_carried_through(self):
        cfg = sanitise_config({"a": {"field_type": "evil", "label_ar": "س"}})
        assert "field_type" not in cfg["a"]
        assert cfg["a"]["label_ar"] == "س"


# ------------------------------------------------------------- the resolver
class TestTenantFieldMirrorsDynamicField:
    """`TenantField` exists to be indistinguishable from a `DynamicField`.

    The templates and the PDF read `field_key`, `label_ar`, `field_type`,
    `required`, `placeholder`, `options_list()` and `sub_columns()`. The last
    one returns a list of dicts, and a dict is easy to get subtly wrong: an
    earlier version of `TenantField.sub_columns` omitted `placeholder`, which is
    where the guidance examples live, so every table cell on every customised
    form lost its example and nothing failed. The page was 210 characters
    shorter than before and no test noticed until one asserted on the text.

    So the two are compared directly, key for key, rather than left to review.
    """

    def _platform_table(self, app):
        tpl = _tpl()
        return next(f for f in tpl.ordered_fields if f.field_type == "table")

    def test_sub_columns_is_identical_for_a_platform_table(self, app):
        with app.app_context():
            source = self._platform_table(app)
            mirror = TenantField(
                field_key=source.field_key, label_ar=source.label_ar,
                field_type=source.field_type, sub_fields=source.sub_fields)
            assert mirror.sub_columns() == source.sub_columns()

    def test_sub_columns_is_identical_for_awkward_input(self, app):
        source = DynamicField(field_key="t", label_ar="t", field_type="table",
                              sub_fields=[
                                  {"key": "  Mixed Case  ", "label_ar": ""},
                                  {"key": "b", "type": "not-a-type"},
                                  {"key": "", "label_ar": "dropped"},
                                  "not a dict",
                                  {"key": "c", "options": None,
                                   "required": "yes"},
                              ])
        mirror = TenantField(field_key="t", label_ar="t", field_type="table",
                             sub_fields=source.sub_fields)
        assert mirror.sub_columns() == source.sub_columns()

    def test_every_attribute_the_templates_read_exists(self, app):
        with app.app_context():
            tpl = _tpl()
            for field in resolve_fields(tpl, None):
                for attribute in ("field_key", "label_ar", "field_type",
                                  "required", "placeholder", "rules", "id",
                                  "template_id", "position"):
                    assert hasattr(field, attribute), attribute
                assert isinstance(field.options_list(), list)
                assert isinstance(field.sub_columns(), list)

    def test_resolution_without_an_override_is_byte_identical(self, app):
        # Same keys, same order, same labels, same placeholders, same columns.
        with app.app_context():
            tpl = _tpl()
            platform = list(tpl.ordered_fields)
            resolved = resolve_fields(tpl, None)
            assert [f.field_key for f in resolved] == \
                [f.field_key for f in platform]
            for plat, res in zip(platform, resolved):
                assert (plat.label_ar, plat.field_type, plat.required,
                        plat.placeholder) == \
                       (res.label_ar, res.field_type, res.required,
                        res.placeholder)
                assert res.options_list() == plat.options_list()
                if plat.field_type == "table":
                    assert res.sub_columns() == plat.sub_columns()


class TestBranchesTheFormDoesNotReach:
    """The paths a dropdown on the admin form cannot produce.

    The admin POST splits a comma-separated string, so `options` arrives as a
    list of plain strings and `placeholder`/`rules` arrive as text. The lines
    below are only reachable from a row written by hand or by a version that
    validated less - which is exactly when they matter, because that is the
    input that is not shaped like the form.
    """

    def test_a_dict_shaped_option_is_unwrapped_to_its_value(self, app):
        field = TenantField(field_key="k", label_ar="k", field_type="dropdown",
                            options=[{"value": "أ", "label": "أول"},
                                     {"label": "ثانٍ"}])
        assert field.options_list() == ["أ", "ثانٍ"]

    def test_options_that_are_not_a_list_are_dropped(self, app):
        with app.app_context():
            out = sanitise_added_fields(
                [{"key": "k", "type": "dropdown", "options": "not a list"}])
            assert out[0]["options"] == []

    def test_placeholder_and_rules_survive_a_stored_config(self, app):
        cfg = sanitise_config({"k": {"placeholder": "اكتب هنا",
                                      "rules": {"min": 1, "max": 9}}})
        assert cfg["k"]["placeholder"] == "اكتب هنا"
        assert cfg["k"]["rules"] == {"min": 1, "max": 9}

    def test_a_blank_option_value_is_not_offered(self, app):
        field = TenantField(field_key="k", label_ar="k",
                            options=["", None, "ب"])
        assert field.options_list() == ["ب"]

    def test_the_repr_names_the_field(self, app):
        assert repr(TenantField(field_key="k", label_ar="k",
                                field_type="number")) == \
            "<TenantField k:number>"

    def test_a_company_added_field_has_no_database_identity(self, app):
        custom = TenantField(field_key="k", label_ar="k", is_custom=True)
        assert custom.id is None and custom.template_id is None
        assert custom.position == 0


class TestResolveFields:
    def test_without_a_project_the_platform_template_is_untouched(self, app):
        with app.app_context():
            tpl = _tpl()
            before = [f.field_key for f in tpl.ordered_fields]
            after = [f.field_key for f in resolve_fields(tpl, None)]
            assert after == before

    def test_a_company_with_no_override_gets_the_platform_template(self, app):
        with app.app_context():
            tpl = _tpl()
            other = _project("No Override Co")
            assert get_override(tpl.key, other.id) is None
            assert [f.field_key for f in resolve_fields(tpl, other.id)] == \
                [f.field_key for f in tpl.ordered_fields]

    def test_a_deleted_field_is_gone_for_that_company_only(self, app):
        with app.app_context():
            tpl = _tpl()
            mine, theirs = _project("Mine"), _project("Theirs")
            victim = tpl.ordered_fields[1].field_key
            save_override(tpl.key, mine.id, deleted_fields=[victim])

            assert victim not in [f.field_key for f in resolve_fields(tpl, mine.id)]
            assert victim in [f.field_key for f in resolve_fields(tpl, theirs.id)]
            assert victim in [f.field_key for f in resolve_fields(tpl, None)]

    def test_a_company_can_relabel_and_retype_a_platform_field(self, app):
        with app.app_context():
            tpl = _tpl()
            mine = _project("Relabel Co")
            target = tpl.ordered_fields[0]
            save_override(tpl.key, mine.id, fields_config={
                target.field_key: {"label_ar": "اسم مخصص",
                                   "field_type": "dropdown",
                                   "options": ["أ", "ب"], "required": True}})

            got = resolve_fields(tpl, mine.id)[0]
            assert got.field_key == target.field_key
            assert got.label_ar == "اسم مخصص"
            assert got.field_type == "dropdown"
            assert got.options_list() == ["أ", "ب"]
            assert got.required is True

    def test_a_company_can_add_a_field_nobody_else_sees(self, app):
        with app.app_context():
            tpl = _tpl()
            mine, theirs = _project("Adder Co"), _project("Other Co")
            save_override(tpl.key, mine.id, added_fields=[
                {"key": "safety_note", "label_ar": "ملاحظة سلامة",
                 "type": "textarea"}])

            mine_keys = [f.field_key for f in resolve_fields(tpl, mine.id)]
            assert "safety_note" in mine_keys
            assert "safety_note" not in [f.field_key
                                         for f in resolve_fields(tpl, theirs.id)]
            # and nothing was written to the shared platform table
            assert db.session.query(DynamicField).filter_by(
                field_key="safety_note").count() == 0

    def test_a_company_can_reorder(self, app):
        with app.app_context():
            tpl = _tpl()
            mine = _project("Order Co")
            keys = [f.field_key for f in tpl.ordered_fields]
            save_override(tpl.key, mine.id, reordered_fields=[keys[-1], keys[0]])
            got = [f.field_key for f in resolve_fields(tpl, mine.id)]
            assert got[:2] == [keys[-1], keys[0]]
            assert sorted(got) == sorted(keys)

    def test_a_custom_field_cannot_shadow_a_platform_one(self, app):
        with app.app_context():
            tpl = _tpl()
            mine = _project("Shadow Co")
            key = tpl.ordered_fields[0].field_key
            save_override(tpl.key, mine.id, added_fields=[
                {"key": key, "label_ar": "不应该 تظهر"}])
            got = [f for f in resolve_fields(tpl, mine.id)
                   if f.field_key == key]
            assert len(got) == 1
            assert got[0].is_custom is False

    def test_an_inactive_override_is_ignored(self, app):
        with app.app_context():
            tpl = _tpl()
            mine = _project("Dormant Co")
            row = save_override(tpl.key, mine.id, deleted_fields=[])
            row.is_active = False
            db.session.commit()
            assert get_override(tpl.key, mine.id) is None

    def test_a_malformed_stored_row_does_not_break_the_form(self, app):
        # A row written by hand, or by a version that validated less, must not
        # take the report page down.
        with app.app_context():
            tpl = _tpl()
            mine = _project("Broken Co")
            db.session.add(TenantTemplateOverride(
                template_key=tpl.key, project_id=mine.id,
                fields_config="not a dict", deleted_fields=None,
                added_fields={"nope": 1}, reordered_fields="junk",
                is_active=True))
            db.session.commit()
            got = resolve_fields(tpl, mine.id)
            assert [f.field_key for f in got] == \
                [f.field_key for f in tpl.ordered_fields]

    def test_the_result_exposes_the_surface_the_templates_use(self, app):
        # dyn_form.html reads exactly these; if TenantField stops providing one
        # the page breaks at render time, not at import.
        with app.app_context():
            tpl = _tpl()
            table = next(f for f in tpl.ordered_fields
                         if f.field_type == "table")
            mine = _project("Surface Co")
            save_override(tpl.key, mine.id, added_fields=[
                {"key": "custom_tbl", "label_ar": "جدول مخصص", "type": "table",
                 "columns": [{"key": "c1", "label_ar": "عمود", "type": "text",
                              "required": True}]}])
            fields = resolve_fields(tpl, mine.id)
            custom = next(f for f in fields if f.field_key == "custom_tbl")
            for attribute in ("field_key", "label_ar", "field_type", "required",
                              "placeholder", "rules"):
                assert hasattr(custom, attribute), attribute
            assert callable(custom.options_list)
            cols = custom.sub_columns()
            assert cols[0]["key"] == "c1" and cols[0]["required"] is True
            # and the platform table field still yields its own columns
            assert table.sub_columns()


class TestIsolation:
    def test_one_company_cannot_see_another_customisation(self, app):
        with app.app_context():
            tpl = _tpl()
            mine, theirs = _project("Alpha Co"), _project("Beta Co")
            save_override(tpl.key, mine.id,
                          added_fields=[{"key": "secret_field",
                                         "label_ar": "خاص"}])
            body = [f.field_key for f in resolve_fields(tpl, theirs.id)]
            assert "secret_field" not in body

    def test_a_user_of_another_company_gets_the_platform_form(self, app):
        with app.app_context():
            tpl = _tpl()
            a, b = _project("Co A"), _project("Co B")
            save_override(tpl.key, a.id, deleted_fields=[tpl.ordered_fields[0].field_key])
            rendered = [f.field_key for f in resolve_fields(tpl, b.id)]
            assert rendered == [f.field_key for f in tpl.ordered_fields]

    def test_a_user_with_no_project_is_never_served_a_tenant_form(self, app):
        # The entry form allows a freehand project name, so project_id can be
        # null. That must resolve to the platform template, not to a fallback.
        with app.app_context():
            tpl = _tpl()
            other = _project("Someone Else")
            save_override(tpl.key, other.id, added_fields=[
                {"key": "hidden_field", "label_ar": "مخفي"}])
            resolved = [f.field_key for f in resolve_fields(tpl, None)]
            assert "hidden_field" not in resolved


class TestSaveOverride:
    def test_it_creates_then_updates_rather_than_duplicating(self, app):
        with app.app_context():
            tpl = _tpl()
            co = _project("Twice Co")
            first = save_override(tpl.key, co.id, deleted_fields=["a"])
            second = save_override(tpl.key, co.id, deleted_fields=["b"])
            assert first.id == second.id
            assert TenantTemplateOverride.query.filter_by(
                template_key=tpl.key, project_id=co.id).count() == 1

    def test_it_validates_before_writing(self, app):
        with app.app_context():
            tpl = _tpl()
            co = _project("Validate Co")
            save_override(tpl.key, co.id,
                          added_fields=[{"key": "k", "type": "evil"}],
                          reordered_fields=["a", "a", " b "])
            row = get_override(tpl.key, co.id)
            assert row.added_fields[0]["type"] == "text"
            assert row.reordered_fields == ["a", "b"]

    def test_it_refuses_without_a_company(self, app):
        with app.app_context():
            tpl = _tpl()
            with pytest.raises(ValueError):
                save_override(tpl.key, None, deleted_fields=[])
            with pytest.raises(ValueError):
                save_override("", 1, deleted_fields=[])
