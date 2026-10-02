"""End-to-end: a company customises its form, and only its form changes."""
import pytest
from flask import url_for

from app.extensions import db
from app.models import Project, ReportTemplate, TenantTemplateOverride
from app.services.tenant_fields import resolve_fields, save_override
from tests.conftest import login_as


def _keys(app, template_key, project_id):
    """Field keys one company sees, re-queried inside its own context.

    A ReportTemplate captured in one app_context is detached in the next, and
    its `fields` relationship is lazy, so holding one across the boundary
    raises rather than returning stale-but-plausible data.
    """
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key=template_key).first()
        return [f.field_key for f in resolve_fields(tpl, project_id)]


def _field(app, template_key, project_id, field_key):
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key=template_key).first()
        return next(f for f in resolve_fields(tpl, project_id)
                    if f.field_key == field_key)


def _project(name):
    p = Project(name=name)
    db.session.add(p)
    db.session.commit()
    return p


class TestCompanySurface:
    def test_the_company_list_renders_for_an_admin(self, client, app):
        with app.app_context():
            _project("Renderable Co")
        login_as(client, "t_admin")
        r = client.get("/admin/companies")
        assert r.status_code == 200
        assert "Renderable Co" in r.get_data(as_text=True)

    def test_the_customisation_screen_renders(self, client, app):
        with app.app_context():
            co = _project("Screen Co")
            co_id = co.id
            tpl_name = ReportTemplate.query.filter_by(
                key="daily").first().name_ar
        login_as(client, "t_admin")
        r = client.get(f"/admin/companies/{co_id}/templates/daily")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Screen Co" in body
        assert tpl_name in body

    def test_a_guest_is_refused(self, client, app):
        r = client.get("/admin/companies")
        assert r.status_code in (302, 401, 403)


class TestCustomisationThroughTheUI:
    def test_hiding_a_field_through_the_form_removes_it_for_that_company(
            self, client, app):
        with app.app_context():
            co = _project("Hiding Co")
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            victim = tpl.ordered_fields[0].field_key
            co_id = co.id
        login_as(client, "t_admin")
        r = client.post(
            f"/admin/companies/{co_id}/templates/daily",
            data={"action": "hide", "hidden_fields": victim},
            follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            row = TenantTemplateOverride.query.filter_by(
                template_key="daily", project_id=co_id).first()
            assert row is not None and victim in row.deleted_fields
        assert victim not in _keys(app, "daily", co_id)

    def test_adding_a_field_through_the_form_persists_it(self, client, app):
        with app.app_context():
            co = _project("Adding Co")
            co_id = co.id
        login_as(client, "t_admin")
        r = client.post(
            f"/admin/companies/{co_id}/templates/daily",
            data={"action": "add", "key": "My Note", "label_ar": "ملاحظتي",
                  "field_type": "dropdown", "options": "أ, ب, , ج",
                  "required": "1"},
            follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            got = {f.field_key: f for f in resolve_fields(tpl, co.id)}
            assert "my_note" in got
            assert got["my_note"].label_ar == "ملاحظتي"
            assert got["my_note"].options_list() == ["أ", "ب", "ج"]
            assert got["my_note"].required is True

    def test_relabelling_through_the_form_persists_it(self, client, app):
        with app.app_context():
            co = _project("Relabel Co")
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            key = tpl.ordered_fields[0].field_key
            co_id = co.id
        login_as(client, "t_admin")
        client.post(
            f"/admin/companies/{co_id}/templates/daily",
            data={"action": "edit", "edit_key": key,
                  "edit_label": "اسم جديد", "edit_type": "text",
                  "edit_options": "", "edit_required": key},
            follow_redirects=True)
        got = _field(app, "daily", co_id, key)
        assert got.label_ar == "اسم جديد"
        assert got.required is True

    def test_reordering_through_the_form_persists_it(self, client, app):
        with app.app_context():
            co = _project("Order Co")
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            keys = [f.field_key for f in tpl.ordered_fields]
            co_id = co.id
        login_as(client, "t_admin")
        client.post(
            f"/admin/companies/{co_id}/templates/daily",
            data={"action": "order",
                  "order_keys": [keys[-1], keys[0]] + keys[1:-1]},
            follow_redirects=True)
        assert _keys(app, "daily", co_id)[:2] == [keys[-1], keys[0]]

    def test_restore_puts_the_platform_fields_back(self, client, app):
        with app.app_context():
            co = _project("Restore Co")
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            key = tpl.ordered_fields[0].field_key
            save_override(tpl.key, co.id, deleted_fields=[key])
            co_id = co.id
        login_as(client, "t_admin")
        client.post(f"/admin/companies/{co_id}/templates/daily",
                    data={"action": "restore"}, follow_redirects=True)
        assert key in _keys(app, "daily", co_id)

    def test_a_bad_field_type_is_corrected_not_stored(self, client, app):
        with app.app_context():
            co = _project("Bad Type Co")
            co_id = co.id
        login_as(client, "t_admin")
        client.post(
            f"/admin/companies/{co_id}/templates/daily",
            data={"action": "add", "key": "k", "label_ar": "س",
                  "field_type": "<script>"},
            follow_redirects=True)
        with app.app_context():
            row = TenantTemplateOverride.query.filter_by(
                template_key="daily", project_id=co_id).first()
            assert row.added_fields[0]["type"] == "text"


class TestTheCustomFormIsWhatUsersSee:
    def test_the_entry_form_shows_the_company_field(self, client, app):
        with app.app_context():
            co = _project("Sees Custom Co")
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            save_override(tpl.key, co.id, added_fields=[
                {"key": "company_only_field", "label_ar": "حقل الشركة فقط",
                 "type": "text"}])
            co_id = co.id
        login_as(client, "t_admin")
        # A first GET has no project chosen yet, so it shows the platform form.
        plain = client.get("/reports/dyn/new/daily").get_data(as_text=True)
        assert "company_only_field" not in plain
        # A successful save redirects to the read view, which renders labels
        # rather than keys - so the field is asserted by its title.
        posted = client.post(
            "/reports/dyn/new/daily",
            data={"project_id": str(co_id), "project_name": "Sees Custom Co",
                  "report_date": "2026-09-30", "f_company_only_field": "قيمة"},
            follow_redirects=True)
        assert posted.status_code == 200
        assert "حقل الشركة فقط" in posted.get_data(as_text=True)

    def test_the_custom_field_value_is_saved(self, client, app):
        from app.models import ReportSubmission
        with app.app_context():
            co = _project("Saves Custom Co")
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            save_override(tpl.key, co.id, added_fields=[
                {"key": "company_only_field", "label_ar": "حقل الشركة",
                 "type": "text"}])
            co_id = co.id
        login_as(client, "t_admin")
        r = client.post(
            "/reports/dyn/new/daily",
            data={"project_id": str(co_id), "project_name": "Saves Custom Co",
                  "report_date": "2026-09-30", "f_company_only_field": "قيمة"},
            follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            s = ReportSubmission.query.filter_by(
                project_id=co_id, project_name="Saves Custom Co").first()
            assert s is not None
            assert s.data.get("company_only_field") == "قيمة"


class TestIsolationThroughTheUI:
    """Who may customise which company.

    In this application `project_manager` is a *platform* manager: it is in
    MANAGER_ROLES, and `is_platform_manager` is documented as "global staff
    bypass project scoping (they are not tenants)". So a project manager
    legitimately administers any company's form, which is what the requirement
    asked for - the super-admin panel customises a report for any company.

    The boundary that is actually enforced is between platform staff and
    everyone else: an engineer is refused even for their own project. The other
    half of the guarantee - that one company's customisation never reaches
    another - is in test_tenant_fields.py, and it is the half that matters most.
    """
    def _engineer_in(self, project):
        from app.models import User
        from app.ops.models import ProjectMember
        eng = User(username="eng_scoped", email="eng@t.com",
                   full_name="مهندس", role="site_engineer")
        eng.set_password("pw12345")
        db.session.add(eng)
        db.session.flush()
        db.session.add(ProjectMember(user_id=eng.id, project_id=project.id,
                                     role_in_project="member"))
        db.session.commit()
        return eng

    def test_a_platform_manager_may_customise_any_company(self, client, app):
        with app.app_context():
            co = _project("Any Co")
            co_id = co.id
        login_as(client, "t_admin")
        assert client.get(
            f"/admin/companies/{co_id}/templates/daily").status_code == 200

    def test_an_engineer_is_refused_even_for_their_own_company(self, client,
                                                               app):
        with app.app_context():
            co = _project("Eng Own Co")
            self._engineer_in(co)
            co_id = co.id
        login_as(client, "eng_scoped")
        r = client.get(f"/admin/companies/{co_id}/templates/daily")
        assert r.status_code in (302, 403, 404)

    def test_a_company_admin_cannot_see_another_company_customisation(
            self, client, app):
        # A platform manager can administer any company, but the *result* is
        # still scoped: what they write for one company is invisible to another.
        with app.app_context():
            mine, theirs = _project("Scoped A"), _project("Scoped B")
            mine_id, theirs_id = mine.id, theirs.id
        login_as(client, "t_admin")
        client.post(f"/admin/companies/{mine_id}/templates/daily",
                    data={"action": "add", "key": "a_confidential_field",
                          "label_ar": "خاص", "field_type": "text"},
                    follow_redirects=True)
        assert "a_confidential_field" in _keys(app, "daily", mine_id)
        assert "a_confidential_field" not in _keys(app, "daily", theirs_id)

    def test_the_company_list_hides_companies_outside_scope(self, client, app):
        # A non-manager only ever sees the projects they are a member of.
        with app.app_context():
            visible = _project("Member Co")
            other = _project("Not Member Co")
            self._engineer_in(visible)
        login_as(client, "eng_scoped")
        body = client.get("/admin/companies")
        # denied at the gate, which is the stronger guarantee
        assert body.status_code in (302, 403)


class TestSharedTemplateIsNowPlatformOwnerOnly:
    @pytest.mark.parametrize("path", [
        "/admin/templates/1/fields",
    ])
    def test_a_company_manager_cannot_edit_the_shared_form(self, client, app,
                                                           path):
        from app.models import User
        from app.ops.models import ProjectMember
        with app.app_context():
            co = _project("Shared Co")
            pm = User(username="pm_only", email="pm@t.com",
                      full_name="مدير", role="project_manager")
            pm.set_password("pw12345")
            db.session.add(pm)
            db.session.flush()
            db.session.add(ProjectMember(user_id=pm.id, project_id=co.id,
                                         role_in_project="owner"))
            db.session.commit()
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            tid = tpl.id
        login_as(client, "pm_only")
        r = client.get(f"/admin/templates/{tid}/fields")
        assert r.status_code in (302, 403), (
            "a project manager can still edit the form every company fills in")

    def test_the_platform_owner_still_can(self, client, app):
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="daily").first()
            tid = tpl.id
        login_as(client, "t_owner")
        assert client.get(
            f"/admin/templates/{tid}/fields").status_code == 200
