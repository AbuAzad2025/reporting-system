"""The template catalogue's own logic: option flattening, field config
overrides, and the migration that repairs a drifted column type.

These paths decide what an administrator actually sees when they build a form,
so they are worth pinning rather than leaving to whichever test happened to
touch the catalogue.
"""
import pytest


class TestFlatOptions:
    """EXTRA_SPECS carry options nested one level deep; validation does not."""

    def test_a_nested_list_is_unwrapped(self):
        from app.services.default_templates import _flat_opts

        assert _flat_opts([["أ", "ب"]]) == ["أ", "ب"]

    def test_a_nested_tuple_is_unwrapped(self):
        from app.services.default_templates import _flat_opts

        assert _flat_opts([("أ", "ب")]) == ["أ", "ب"]

    def test_a_flat_list_passes_through(self):
        from app.services.default_templates import _flat_opts

        assert _flat_opts(["أ", "ب", "ج"]) == ["أ", "ب", "ج"]

    def test_a_single_flat_value_is_not_unwrapped(self):
        """Only a lone nested sequence is unwrapped, never a lone scalar."""
        from app.services.default_templates import _flat_opts

        assert _flat_opts(["أ"]) == ["أ"]

    def test_two_nested_lists_are_left_alone(self):
        """Unwrapping would merge two columns' options into one dropdown."""
        from app.services.default_templates import _flat_opts

        assert _flat_opts([["أ"], ["ب"]]) == [["أ"], ["ب"]]


class TestFieldsConfigOverrides:
    """A per-tenant override reshapes the shipped catalogue."""

    def _fields(self, app, client, fields_config, key="site-inspections"):
        from app.extensions import db
        from app.models import (ReportTemplate, TenantTemplateOverride, User)
        from app.services.default_templates import apply_tenant_overrides

        with app.app_context():
            user = User.query.filter_by(username="t_owner").one()
            tpl = ReportTemplate.query.filter_by(key=key).first()
            if tpl is None:
                pytest.skip(f"{key} is not in this catalogue")
            db.session.add(TenantTemplateOverride(
                template_key=key, tenant_id=user.id, is_active=True,
                fields_config=fields_config))
            db.session.commit()
            return apply_tenant_overrides(tpl, user)

    def test_an_override_can_change_type_and_label(self, app, client):
        fields = self._fields(app, client, {
            "result_value": {"type": "textarea", "label_ar": "النتيجة المسرّدة"},
        })
        row = next(f for f in fields if f["key"] == "result_value")
        assert row["type"] == "textarea"
        assert row["label_ar"] == "النتيجة المسرّدة"

    def test_an_override_can_widen_a_dropdown(self, app, client):
        fields = self._fields(app, client, {
            "result_value": {"options": ["ممتاز", "جيد", "مقبول", "مرفوض"]},
        })
        row = next(f for f in fields if f["key"] == "result_value")
        assert "مرفوض" in row["options"]

    def test_an_override_can_set_placeholder_and_rules(self, app, client):
        fields = self._fields(app, client, {
            "result_value": {"placeholder": "اكتب النتيجة", "rules": {"max": 400}},
        })
        row = next(f for f in fields if f["key"] == "result_value")
        assert row["placeholder"] == "اكتب النتيجة"
        assert row["rules"] == {"max": 400}

    def test_required_can_be_turned_off_for_one_tenant(self, app, client):
        fields = self._fields(app, client, {"result_value": {"required": False}})
        row = next(f for f in fields if f["key"] == "result_value")
        assert row["required"] is False

    def test_an_override_may_delete_a_field_and_add_another(self, app, client):
        from app.extensions import db
        from app.models import (ReportTemplate, TenantTemplateOverride, User)
        from app.services.default_templates import apply_tenant_overrides

        with app.app_context():
            user = User.query.filter_by(username="t_owner").one()
            tpl = ReportTemplate.query.filter_by(key="site-inspections").first()
            if tpl is None:
                pytest.skip("site-inspections is not in this catalogue")
            base_keys = [f["key"] for f in
                         apply_tenant_overrides(tpl, user)]
            db.session.add(TenantTemplateOverride(
                template_key="site-inspections", tenant_id=user.id,
                is_active=True,
                deleted_fields=[base_keys[0]],
                added_fields=[{"key": "custom_note", "label_ar": "ملاحظة",
                               "type": "text"}],
                fields_config={"result_value": {"type": "number"}}))
            db.session.commit()

            fields = apply_tenant_overrides(tpl, user)
            keys = [f["key"] for f in fields]
            assert base_keys[0] not in keys
            assert "custom_note" in keys
            row = next(f for f in fields if f["key"] == "result_value")
            assert row["type"] == "number"
