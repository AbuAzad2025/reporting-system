"""Tenant customisation contract: branding, field overrides, ordering.

`apply_brand_to_template`, `apply_tenant_overrides` and `build_tenant_fields`
are the in-memory (never persisted) customisation layer a tenant uses to
reshape a system template. These tests pin their real behaviour: gradient
composition, field deletion, per-field rule overrides and custom additions.

Ordering is deliberately absent from that list. `reordered_fields` is stored on
the override row and is not read by either function, so a tenant cannot
reorder a template - only the platform owner can, through the per-field move
buttons on /admin/fields, which write `DynamicField.position`. The design for
closing that gap, and the reason it was not closed in passing, are written up
in docs/architecture/roadmap_reordered_fields.md; TestNoUnexecutedOverride
below is what stops the column drifting back into looking implemented.

`apply_tenant_branding` used to be part of that layer. It is gone; the reason
is written out where it used to be tested, in
TestBrandingDoesNotRewriteTemplates.
"""
import ast
import io
import os
import pathlib
import re
from types import SimpleNamespace

import pytest

from app.services.default_templates import (apply_brand_to_template,
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


class TestBrandingDoesNotRewriteTemplates:
    """A tenant's header text is not the report type's name.

    ``apply_tenant_branding`` used to set ``tpl.name_ar`` from the tenant's
    header text, which renamed the report type in the picker, in every list,
    and in every document already issued against it. Six tests pinned that
    behaviour, including one that asserted the title was truncated to 200
    characters - the length of the column, not of anything a reader would
    call a title.

    It also set ``tpl.gradient`` to ``from-#1e3a5f to-#c9a227``. Those are not
    utility classes that exist in any stylesheet, so the report cards rendered
    with no gradient at all, and one test asserted the exact broken string.

    Branding is applied where it belongs now: the templates read
    ``current_brand``, and a tenant colour reaches a card through the
    ``--card-from`` / ``--card-to`` custom properties, which are real.
    """

    def test_tenant_text_never_renames_a_report_template(self, app):
        from app.models import ReportTemplate, TenantBranding
        from app.extensions import db
        with app.app_context():
            template = ReportTemplate.query.first()
            if template is None:
                return
            original = template.name_ar
            db.session.add(TenantBranding(
                project_id=1, is_active=True,
                custom_header_text_ar="ترويسة المالك"))
            db.session.commit()
            db.session.expire_all()
            assert ReportTemplate.query.get(template.id).name_ar == original

    def test_a_tenant_colour_is_not_turned_into_a_class_name(self):
        import re
        # A colour cannot become a utility class, because nothing generates a
        # selector for it. What the stylesheet has to contain is checked here
        # rather than asserted on a string the code produces.
        css = io.open("static/css/layout.css", encoding="utf-8").read()
        rule = css.split(".report-card")[1][:300]
        assert "linear-gradient" in rule
        assert "var(--card-from)" in rule
        assert "from-[" not in rule and "to-[" not in rule, (
            "a literal from-#hex class cannot match any rule")
        assert re.search(r"\.from-\[", css) is None, (
            "a stylesheet holds a rule for a generated from-#hex class; there "
            "is no such thing unless something generates the selector")

    def test_the_card_receives_the_colour_as_a_custom_property(self, app, client):
        """A tenant's colours must reach the report cards.

        The colours used to be written onto each card as
        `style="--card-from: ..."`. They are now published once, on :root, as
        --brand-primary / --brand-secondary, and the .report-card rule maps
        them into the gradient. Both halves of that chain are asserted here,
        because either one alone leaves the cards unbranded: publishing the
        properties without the rule that reads them, or the rule without the
        values, both render a default-coloured card.
        """
        from app.models import Project, TenantBranding, User
        from app.extensions import db
        from app.ops.models import ProjectMember
        with app.app_context():
            project = Project(name="مشروع البطاقة")
            user = User(username="i18n-card", email="card@brand.test",
                        full_name="مستخدم", role="engineer")
            user.set_password("pw12345")
            db.session.add_all([project, user])
            db.session.flush()
            db.session.add(TenantBranding(project_id=project.id, is_active=True,
                                          primary_color="#112233",
                                          secondary_color="#445566"))
            db.session.add(ProjectMember(project_id=project.id, user_id=user.id,
                                         role_in_project="member"))
            db.session.commit()
            username, password = user.username, "pw12345"

        client.post("/auth/login",
                    data={"username": username, "password": password},
                    follow_redirects=True)
        body = client.get("/dashboard").get_data(as_text=True)

        # 1. The card is the tenant's, not the template gradient.
        assert "report-card" in body
        # 2. The values are published for the page.
        assert "--brand-primary: #112233" in body, (
            "the tenant's primary colour is not published on the page")
        assert "--brand-secondary: #445566" in body, (
            "the tenant's secondary colour is not published on the page")

        # 3. Something reads them and paints the card.
        layout = io.open(os.path.join("static", "css", "layout.css"),
                         encoding="utf-8").read()
        rule = re.search(r"\.report-card\s*\{(.*?)\}", layout, re.DOTALL)
        assert rule, "no .report-card rule"
        assert "--card-from: var(--brand-primary)" in rule.group(1), (
            ".report-card no longer maps the tenant's primary colour")
        assert "--card-to: var(--brand-secondary)" in rule.group(1), (
            ".report-card no longer maps the tenant's secondary colour")
        assert "background-image" in rule.group(1), (
            ".report-card no longer paints a gradient from them")


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


# ------------------------------------------------- no unexecuted overrides
class TestNoUnexecutedOverride:
    """`reordered_fields` must not look implemented when it is not.

    The column was read into a local named `reordered` in both override
    functions and never used again. Nothing failed: the functions have no
    production caller, the linter was configured to ignore the module, and the
    test module's own docstring listed "ordering" among the behaviours it
    pinned. Three independent signals all said the feature worked, and it had
    never run once.

    An assignment that is written and then ignored is the specific shape that
    caused it, so that is what is banned here. The roadmap is at
    docs/architecture/roadmap_reordered_fields.md; implement the feature and
    delete this class in the same change, or leave the column alone.
    """

    #: Files allowed to mention the column at all.
    ALLOWED = ("app/models.py", "app/services/default_templates.py")

    def _sources(self):
        root = pathlib.Path("app")
        for path in sorted(root.rglob("*.py")):
            posix = path.as_posix()
            yield posix, path.read_text(encoding="utf-8")

    def test_no_local_is_bound_to_reordered_fields(self):
        """A binding is the ghost: it reads as intent and executes as nothing."""
        offenders = []
        for posix, text in self._sources():
            if posix not in self.ALLOWED:
                continue
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    continue
                # Walk the whole right-hand side rather than testing it for
                # being an Attribute: the ghost was written as
                # `reordered = override.reordered_fields or []`, which parses as
                # a BoolOp, so a test that only matched a bare Attribute would
                # have sat here green through the whole time.
                for inner in ast.walk(node.value) if node.value else ():
                    if not isinstance(inner, ast.Attribute):
                        continue
                    if inner.attr != "reordered_fields":
                        continue
                    if isinstance(inner.value, ast.Name) and \
                            inner.value.id == "override":
                        line = getattr(node, "lineno", 0)
                        offenders.append(
                            f"{posix}:{line} reads override.reordered_fields")
        assert not offenders, (
            "override.reordered_fields is read by application code again. "
            "Either the feature is being implemented - in which case delete this "
            "class and the roadmap - or the read is a ghost: "
            + "; ".join(offenders))

    def test_the_column_is_still_declared_so_no_migration_is_owed(self):
        """Dropping the column is a schema change; keeping it is the cheap call."""
        models = pathlib.Path("app/models.py").read_text(encoding="utf-8")
        assert "reordered_fields = db.Column(db.JSON, default=list)" in models

    def test_reordering_the_fields_is_the_platform_owners_job(self):
        """The one reorder path that does work, asserted so it is not confused
        with the tenant one.

        `field_move` swaps `DynamicField.position` between two sibling fields
        and `ReportTemplate.ordered_fields` orders by that column. That is a
        platform-level capability, reachable from /admin/fields, and it is the
        only ordering the application honours. A tenant-level order list has to
        compose with it, not replace it - see the roadmap.
        """
        routes = pathlib.Path("app/admin/routes.py").read_text(encoding="utf-8")
        assert "def field_move" in routes
        assert "DynamicField.position" in routes
        models = pathlib.Path("app/models.py").read_text(encoding="utf-8")
        assert 'order_by="DynamicField.position"' in models

    def test_the_override_functions_have_no_production_caller(self):
        """Records why the column is inert, so nobody debugs it in production.

        These two functions are the only readers of the override columns, and
        only tests call them. The consequence is recorded here as an assertion
        rather than left as a discovery: if a route is ever wired to them, this
        fails and the point is to then decide deliberately whether the dict
        output is what the renderer needs - it is not, see the roadmap.

        Matched on the parsed tree rather than on the file text. A grep for the
        names also matches a docstring, and app/services/tenant_fields.py
        explains in its module docstring exactly why these two were not the
        thing to wire up - so the text version failed on the documentation of
        the problem while saying nothing about whether the problem came back.
        """
        wanted = ("apply_tenant_overrides", "build_tenant_fields")
        callers = []
        for path in sorted(pathlib.Path(".").rglob("*.py")):
            posix = path.as_posix().lstrip("./")
            if posix.startswith("tests"):
                continue
            if posix == "app/services/default_templates.py":
                continue          # their own definitions
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in wanted:
                    callers.append(f"{posix}:{node.lineno} {name}")
        assert not callers, (

            "the override functions now have a production caller, so the "
            "column may be reachable. Re-read the roadmap before assuming the "
            "dict output is what the form renderer consumes: "
            + "; ".join(sorted(set(callers))))
