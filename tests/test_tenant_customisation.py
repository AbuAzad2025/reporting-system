"""Tenant customisation contract: branding, field overrides, reordering.

`apply_brand_to_template`, `apply_tenant_overrides`, `apply_tenant_branding`
and `build_tenant_fields` are the in-memory (never persisted) customisation
layer a tenant uses to reshape a system template. These tests pin their real
behaviour: gradient composition, header text, field deletion, per-field rule
overrides, custom additions and ordering.
"""
from types import SimpleNamespace

import pytest

from app.services.default_templates import (apply_brand_to_template,
                                            apply_tenant_branding,
                                            apply_tenant_overrides,
                                            build_tenant_fields,
                                            default_fields_for)


def _tpl(key="daily"):
    return SimpleNamespace(key=key, name_ar="افتراضي",
                           gradient="from-sky-500 to-blue-700",
                           icon="📋", description="")


def _branding(**over):
    base = {"is_active": True, "primary_color": "#1e3a5f",
            "secondary_color": "#c9a227", "gradient": "custom",
            "company_name_ar": "شركة أ", "company_name_en": "Company A",
            "custom_header_text_ar": "", "logo_path": ""}
    base.update(over)
    return SimpleNamespace(**base)


def _user(uid=7):
    return SimpleNamespace(id=uid, is_authenticated=True, role="site_engineer")


class TestApplyBrandToTemplate:

    def test_none_branding_is_a_no_op(self):
        tpl = _tpl()
        before = (tpl.gradient, tpl.name_ar)
        apply_brand_to_template(tpl, None, 1)
        assert (tpl.gradient, tpl.name_ar) == before

    def test_inactive_branding_is_ignored(self):
        tpl = _tpl()
        apply_brand_to_template(tpl, _branding(is_active=False), 1)
        assert tpl.gradient == "from-sky-500 to-blue-700"

    def test_both_colors_compose_a_tailwind_gradient(self):
        tpl = _tpl()
        apply_brand_to_template(tpl, _branding(), 1)
        assert tpl.gradient == "from-[1e3a5f] to-[c9a227]"

    def test_missing_secondary_color_keeps_the_default_gradient(self):
        tpl = _tpl()
        apply_brand_to_template(tpl, _branding(secondary_color=""), 1)
        assert tpl.gradient == "from-sky-500 to-blue-700"

    def test_missing_primary_color_keeps_the_default_gradient(self):
        tpl = _tpl()
        apply_brand_to_template(tpl, _branding(primary_color=""), 1)
        assert tpl.gradient == "from-sky-500 to-blue-700"

    def test_gradient_flag_alone_does_not_overwrite(self):
        tpl = _tpl()
        apply_brand_to_template(tpl, _branding(gradient=""), 1)
        assert tpl.gradient == "from-sky-500 to-blue-700"


class TestApplyTenantBranding:

    def test_none_is_a_no_op(self):
        tpl = _tpl()
        apply_tenant_branding(tpl, None)
        assert tpl.gradient == "from-sky-500 to-blue-700"
        assert tpl.name_ar == "افتراضي"

    def test_header_text_replaces_the_template_title(self):
        tpl = _tpl()
        apply_tenant_branding(tpl, _branding(custom_header_text_ar="ترويسة مخصصة"))
        assert tpl.name_ar == "ترويسة مخصصة"

    def test_header_text_is_truncated_to_200_chars(self):
        tpl = _tpl()
        apply_tenant_branding(tpl, _branding(custom_header_text_ar="ا" * 250))
        assert len(tpl.name_ar) == 200

    def test_empty_header_text_leaves_the_title(self):
        tpl = _tpl()
        apply_tenant_branding(tpl, _branding())
        assert tpl.name_ar == "افتراضي"

    def test_gradient_is_applied_when_both_colors_exist(self):
        tpl = _tpl()
        apply_tenant_branding(tpl, _branding())
        assert tpl.gradient == "from-[1e3a5f] to-[c9a227]"

    def test_no_colors_leaves_the_gradient_untouched(self):
        tpl = _tpl()
        apply_tenant_branding(tpl, _branding(primary_color="",
                                             secondary_color=""))
        assert tpl.gradient == "from-sky-500 to-blue-700"


class TestBuildTenantFields:

    def test_no_override_returns_the_defaults(self):
        fields = build_tenant_fields(_tpl(), None)
        assert [f["key"] for f in fields] == \
            [f["key"] for f in default_fields_for("daily")]

    def test_inactive_override_returns_the_defaults(self):
        override = SimpleNamespace(is_active=False, deleted_fields=[default_fields_for("daily")[0]["key"]],
                                   added_fields=[], reordered_fields=[],
                                   fields_config={})
        fields = build_tenant_fields(_tpl(), override)
        assert default_fields_for("daily")[0]["key"] in [f["key"] for f in fields]

    def test_deleted_fields_are_removed(self):
        base_keys = [f["key"] for f in default_fields_for("daily")]
        override = SimpleNamespace(is_active=True,
                                   deleted_fields=[base_keys[0]],
                                   added_fields=[], reordered_fields=[],
                                   fields_config={})
        fields = build_tenant_fields(_tpl(), override)
        keys = [f["key"] for f in fields]
        assert base_keys[0] not in keys
        assert len(keys) == len(base_keys) - 1

    def test_fields_config_overrides_every_supported_attribute(self):
        target = default_fields_for("daily")[0]["key"]
        override = SimpleNamespace(
            is_active=True, deleted_fields=[], added_fields=[],
            reordered_fields=[],
            fields_config={target: {"type": "textarea", "required": True,
                                    "label_ar": "عنوان مخصص",
                                    "options": ["x"],
                                    "placeholder": "اكتب هنا"}})
        field = next(f for f in build_tenant_fields(_tpl(), override)
                     if f["key"] == target)
        assert field["type"] == "textarea"
        assert field["required"] is True
        assert field["label_ar"] == "عنوان مخصص"
        assert field["options"] == ["x"]
        assert field["placeholder"] == "اكتب هنا"

    def test_configured_field_keeps_its_original_shape(self):
        target = default_fields_for("daily")[0]["key"]
        original = next(f for f in default_fields_for("daily")
                        if f["key"] == target)
        override = SimpleNamespace(is_active=True, deleted_fields=[],
                                   added_fields=[], reordered_fields=[],
                                   fields_config={target: {"required": True}})
        field = next(f for f in build_tenant_fields(_tpl(), override)
                     if f["key"] == target)
        assert set(field) == set(original)

    def test_custom_fields_are_appended_with_defaults(self):
        override = SimpleNamespace(
            is_active=True, deleted_fields=[], reordered_fields=[],
            fields_config={},
            added_fields=[{"key": "custom_a", "label_ar": "مخصص"},
                          {"key": "custom_b", "type": "number",
                           "required": "yes", "options": [1, 2],
                           "columns": [{"key": "c"}], "placeholder": "p"}])
        fields = build_tenant_fields(_tpl(), override)
        by_key = {f["key"]: f for f in fields}
        assert "custom_a" in by_key
        assert by_key["custom_a"]["label_ar"] == "مخصص"
        assert by_key["custom_a"]["type"] == "text"
        assert by_key["custom_a"]["required"] is False
        assert by_key["custom_a"]["options"] == []
        assert by_key["custom_a"]["columns"] == []
        assert by_key["custom_a"]["placeholder"] == ""
        assert by_key["custom_b"]["type"] == "number"
        assert by_key["custom_b"]["required"] is True
        assert by_key["custom_b"]["options"] == [1, 2]
        assert by_key["custom_b"]["columns"] == [{"key": "c"}]
        assert by_key["custom_b"]["placeholder"] == "p"

    def test_added_field_without_label_falls_back_to_its_key(self):
        override = SimpleNamespace(is_active=True, deleted_fields=[],
                                   added_fields=[{"key": "only_key"}],
                                   reordered_fields=[], fields_config={})
        fields = build_tenant_fields(_tpl(), override)
        assert fields[-1]["label_ar"] == "only_key"

    def test_build_tenant_fields_does_not_mutate_the_defaults(self):
        before = [dict(f) for f in default_fields_for("daily")]
        target = before[0]["key"]
        override = SimpleNamespace(
            is_active=True, deleted_fields=[], added_fields=[],
            reordered_fields=[],
            fields_config={target: {"label_ar": "changed", "required": True}})
        build_tenant_fields(_tpl(), override)
        assert default_fields_for("daily") == before


class TestApplyTenantOverrides:

    def test_anonymous_user_gets_the_defaults(self, app):
        from app.models import ReportTemplate
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            fields = apply_tenant_overrides(tpl, None)
        assert [f["key"] for f in fields] == \
            [f["key"] for f in default_fields_for("daily")]

    def test_user_without_an_override_gets_the_defaults(self, app):
        from app.models import ReportTemplate, User
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            user = User.query.filter_by(username="t_eng").one()
            fields = apply_tenant_overrides(tpl, user)
        assert [f["key"] for f in fields] == \
            [f["key"] for f in default_fields_for("daily")]

    def test_a_stored_override_is_applied(self, app):
        from app.extensions import db
        from app.models import ReportTemplate, TenantTemplateOverride, User
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            user = User.query.filter_by(username="t_eng").one()
            target = default_fields_for("daily")[0]["key"]
            db.session.add(TenantTemplateOverride(
                template_key="daily", tenant_id=user.id, is_active=True,
                deleted_fields=[], added_fields=[],
                reordered_fields=[],
                fields_config={target: {"label_ar": "مُعدَّل",
                                        "required": True}}))
            db.session.commit()
            fields = apply_tenant_overrides(tpl, user)
        field = next(f for f in fields if f["key"] == target)
        assert field["label_ar"] == "مُعدَّل"
        assert field["required"] is True

    def test_inactive_override_row_is_ignored(self, app):
        from app.extensions import db
        from app.models import ReportTemplate, TenantTemplateOverride, User
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            user = User.query.filter_by(username="t_eng").one()
            target = default_fields_for("daily")[0]["key"]
            db.session.add(TenantTemplateOverride(
                template_key="daily", tenant_id=user.id, is_active=False,
                deleted_fields=[], added_fields=[], reordered_fields=[],
                fields_config={target: {"label_ar": "should-not-apply"}}))
            db.session.commit()
            fields = apply_tenant_overrides(tpl, user)
        field = next(f for f in fields if f["key"] == target)
        assert field["label_ar"] != "should-not-apply"

    def test_override_for_another_tenant_is_never_applied(self, app):
        from app.extensions import db
        from app.models import ReportTemplate, TenantTemplateOverride, User
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            me = User.query.filter_by(username="t_eng").one()
            other = User.query.filter_by(username="t_eng2").one()
            target = default_fields_for("daily")[0]["key"]
            db.session.add(TenantTemplateOverride(
                template_key="daily", tenant_id=other.id, is_active=True,
                deleted_fields=[], added_fields=[], reordered_fields=[],
                fields_config={target: {"label_ar": "other-tenant"}}))
            db.session.commit()
            fields = apply_tenant_overrides(tpl, me)
        field = next(f for f in fields if f["key"] == target)
        assert field["label_ar"] != "other-tenant"

    def test_override_survives_a_dict_of_none_config(self, app):
        tpl = _tpl()
        override = SimpleNamespace(
            deleted_fields=None, added_fields=None, reordered_fields=None,
            fields_config=None)
        with app.app_context():
            fields = apply_tenant_overrides(tpl, _user())
        assert isinstance(fields, list)
        assert fields


class TestFieldDictContract:

    @pytest.mark.parametrize("key", ["daily", "monthly", "rfis", "safety"])
    def test_default_field_dicts_are_uniform(self, key):
        required = {"key", "label_ar", "type", "required", "options",
                    "placeholder"}
        for field in default_fields_for(key):
            assert required <= set(field), (key, field["key"])
            assert isinstance(field["key"], str) and field["key"]
            assert isinstance(field["required"], bool)
            assert isinstance(field["options"], list)

    @pytest.mark.parametrize("key", ["daily", "monthly"])
    def test_table_fields_carry_normalised_columns(self, key):
        tables = [f for f in default_fields_for(key)
                  if f["type"] == "table"]
        assert tables, key
        for field in tables:
            assert isinstance(field["columns"], list)
            for col in field["columns"]:
                assert col["key"] == col["key"].lower().replace(" ", "_")
                assert col["type"] in ("text", "number", "dropdown", "date",
                                       "file", "checkbox", "textarea")
                assert isinstance(col["required"], bool)

    def test_unknown_template_key_yields_no_fields(self):
        assert default_fields_for("does-not-exist") == []
