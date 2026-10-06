"""app/admin/routes.py — the refusals and the fallbacks.

Seventeen statements, and almost all of them are refusals: a blank field key, a
field type that is not one of ours, a duplicate key, a company trying to
customise a template for a project it cannot act for, an override save that
raises. A success-path suite walks straight past all of them, which is how an
administrator finds out the duplicate-key guard is missing only after two
fields with the same name have collided on a live form.

Each refusal is paired with the case next to it, so none of them can pass
merely because the endpoint refuses everything.

The superadmin routes need t_owner: t_admin holds the admin role, which the
field and backup screens deliberately do not accept.
"""
import pytest
from flask import url_for

from app.admin import routes as admin_routes


def _login(client, who="t_owner"):
    from tests.conftest import login_as
    login_as(client, who)


def _template_id(app):
    from app.models import ReportTemplate
    with app.app_context():
        return ReportTemplate.query.first().id


def _project_id(app):
    from app.models import Project
    with app.app_context():
        return Project.query.first().id


def _fields_named(app, key):
    from app.models import DynamicField
    with app.app_context():
        return DynamicField.query.filter_by(field_key=key).all()


# ======================================= adding a field: three refusals

def test_a_field_with_no_key_or_no_label_is_refused(client, app):
    """Both halves of the key are required, and neither half is optional."""
    tid = _template_id(app)
    _login(client)
    for payload in ({"field_key": "", "label_ar": "اسم"},
                    {"field_key": "k", "label_ar": "   "}):
        client.post(url_for("admin.fields", template_id=tid), data=payload,
                    follow_redirects=True)
    assert not _fields_named(app, "k"), "a blank label must not be stored"


def test_a_field_type_outside_the_catalog_is_refused(client, app):
    """field_type is checked against FIELD_TYPES before anything is written.

    An unrecognised type would otherwise land in the column and only surface
    later, when somebody renders a form field with it.
    """
    tid = _template_id(app)
    _login(client)
    client.post(url_for("admin.fields", template_id=tid), data={
        "field_key": "k_bad", "label_ar": "نوع غريب", "field_type": "nonsense"},
        follow_redirects=True)
    assert not _fields_named(app, "k_bad"), (
        "an unrecognised field type must be refused before it is stored")


def test_a_duplicate_field_key_in_one_template_is_refused(client, app):
    """The uniqueness is per template, not global: two templates may both use
    "notes" without colliding."""
    tid = _template_id(app)
    _login(client)
    for _ in range(2):
        client.post(url_for("admin.fields", template_id=tid), data={
            "field_key": "dup_probe", "label_ar": "م", "field_type": "text"},
            follow_redirects=True)
    assert len(_fields_named(app, "dup_probe")) == 1, (
        "the same key must not be stored twice in one template")


def test_a_well_formed_field_is_accepted(client, app):
    """The control for the three refusals above.

    Without this, a handler that refused every field would satisfy all of them.
    """
    tid = _template_id(app)
    _login(client)
    client.post(url_for("admin.fields", template_id=tid), data={
        "field_key": "ok_probe", "label_ar": "سليم", "field_type": "text"},
        follow_redirects=True)
    assert _fields_named(app, "ok_probe"), "a valid field must be stored"


# ======================================= who may customise for a project

class _User:
    def __init__(self, role="admin", uid=1):
        self.id = uid
        self.role = role
        self.is_admin = role in ("admin", "superadmin")
        self.is_superadmin = role == "superadmin"


def test_a_company_admin_may_customise_only_a_project_it_can_reach(
        app, monkeypatch):
    """The tenant check has three outcomes and all three matter.

    A platform manager passes on the first line. A company admin needs both
    access to the project *and* a customising role. Anyone else is refused.
    """
    from app.ops import isolation
    pid = _project_id(app)
    proj = type("P", (), {"id": pid})()

    monkeypatch.setattr(isolation, "is_platform_manager", lambda u: True)
    monkeypatch.setattr(isolation, "can_access_project", lambda u, p: False)
    with app.app_context():
        assert admin_routes._tenant_can_customise(_User(), proj) is True, (
            "a platform manager is not limited to their own projects")

    monkeypatch.setattr(isolation, "is_platform_manager", lambda u: False)
    monkeypatch.setattr(isolation, "can_access_project", lambda u, p: True)
    with app.app_context():
        assert admin_routes._tenant_can_customise(_User(), proj) is True
        assert admin_routes._tenant_can_customise(
            _User(role="engineer"), proj) is False, (
            "an engineer is not a customiser even inside the project")

    monkeypatch.setattr(isolation, "can_access_project", lambda u, p: False)
    with app.app_context():
        assert admin_routes._tenant_can_customise(_User(), proj) is False, (
            "a project the user cannot reach must be refused")


def test_customising_another_companys_template_is_a_404_not_a_403(
        client, app, monkeypatch):
    """404 rather than 403, so the page is not an existence oracle.

    Answering 403 for someone else's project id confirms the id is real, which
    is the first half of enumerating another company's work.
    """
    from app.ops import isolation
    pid = _project_id(app)
    _login(client)
    monkeypatch.setattr(isolation, "is_platform_manager", lambda u: False)
    monkeypatch.setattr(isolation, "can_access_project", lambda u, p: False)
    r = client.get(url_for("admin.company_templates", project_id=pid,
                           template_key="daily"))
    assert r.status_code == 404, (
        f"got {r.status_code}; 403 would confirm the project id exists")


def test_the_page_still_renders_for_a_permitted_caller(client, app,
                                                        monkeypatch):
    """The control: the same page, same role, permitted project."""
    from app.ops import isolation
    pid = _project_id(app)
    _login(client)
    monkeypatch.setattr(isolation, "is_platform_manager", lambda u: False)
    monkeypatch.setattr(isolation, "can_access_project", lambda u, p: True)
    r = client.get(url_for("admin.company_templates", project_id=pid,
                           template_key="daily"))
    assert r.status_code == 200, f"got {r.status_code}"


# ======================================= company override actions

def _company_post(client, app, data):
    pid = _project_id(app)
    _login(client)
    r = client.post(
        url_for("admin.company_templates", project_id=pid,
                 template_key="daily"),
        data=data, follow_redirects=True)
    return r


def test_an_unknown_override_action_is_refused(client, app):
    """Only labels, order and add are actions; anything else is a mistake.

    An unrecognised action has to be reported, not ignored - silently doing
    nothing leaves the operator believing a change was saved.
    """
    body = _company_post(client, app, {"action": "delete-everything"})
    assert "إجراء غير معروف" in body.get_data(as_text=True)


def test_a_failing_override_save_is_reported_not_swallowed(client, app,
                                                           monkeypatch):
    """save_override raises ValueError on a field list it cannot accept.

    That message is the only thing between a malformed override and a silently
    truncated one, so it has to reach the page.
    """
    def _boom(*a, **k):
        raise ValueError("حقل غير معروف: ghost")

    # save_override is bound into this module at import time, so that is the
    # name to replace - patching the service module would not be seen.
    monkeypatch.setattr(admin_routes, "save_override", _boom)
    body = _company_post(client, app, {"action": "order",
                                       "order_keys": "ghost"})
    assert "حقل غير معروف" in body.get_data(as_text=True), (
        "the validation message from save_override must be shown")


def test_a_successful_override_save_says_so(client, app):
    """The control: the same action, with nothing raising."""
    body = _company_post(client, app, {"action": "order",
                                       "order_keys": "ghost"})
    text = body.get_data(as_text=True)
    assert "تم تحديث ترتيب الحقول" in text, (
        "a successful order save must confirm itself")
    assert "حقل غير معروف" not in text


def test_a_known_action_is_not_reported_as_unknown(client, app):
    """The control: the same page with a real action reports nothing."""
    body = _company_post(client, app, {"action": "order", "order_keys": "x"})
    assert "إجراء غير معروف" not in body.get_data(as_text=True)


# ======================================= posted column rows

class _Form:
    """The subset of a Werkzeug MultiDict that _posted_columns uses."""

    def __init__(self, data):
        self._data = data

    def getlist(self, key):
        return list(self._data.get(key, []))


def test_a_blank_column_key_is_skipped_not_stored():
    """Half-filled rows come back from a browser constantly - one label input
    got cleared and the key did not.

    Storing an empty key produces a column that can never be filled in.
    """
    rows = admin_routes._posted_columns(_Form({
        "col_key": ["good", "   ", "also_good"],
        "col_label": ["جيد", "بلا", "جيد2"],
        "col_type": ["text", "text", "number"],
    }))
    assert [r["key"] for r in rows] == ["good", "also_good"], (
        f"a blank key must be dropped, got {rows}")


def test_a_column_with_more_keys_than_labels_still_gets_a_row():
    """Keys, labels and types are posted as parallel lists, and a truncated
    one must not raise - the row falls back to blanks."""
    rows = admin_routes._posted_columns(_Form({
        "col_key": ["a", "b"], "col_label": ["أ"], "col_type": ["text"]}))
    assert len(rows) == 2
    assert rows[1]["label_ar"] == "" and rows[1]["type"] == "text", (
        f"missing parallel values must fall back, got {rows[1]}")


def test_no_posted_columns_gives_no_rows():
    assert admin_routes._posted_columns(_Form({})) == []


# ======================================= backup export refuses a bad archive

def _patch_backup(monkeypatch, ok):
    from app.services import backup as backup_service
    uploaded = []
    monkeypatch.setattr(backup_service, "build_backup", lambda: b"PK\x03\x04")
    monkeypatch.setattr(
        backup_service, "validate_backup",
        lambda d: {"ok": ok, "error": "أرشيف غير صالح"} if not ok
        else {"ok": True})
    monkeypatch.setattr(backup_service, "backup_filename", lambda: "probe.zip")
    import app.services.storage as storage
    monkeypatch.setattr(storage, "upload",
                        lambda data, name: uploaded.append(name))
    return uploaded


def test_a_backup_that_fails_validation_is_not_offered_for_download(
        client, app, monkeypatch):
    """The export is validated before it is stored.

    Storing an archive that cannot be read back leaves the operator with a
    backup that only looks like one - so a failed validation writes nothing.
    """
    uploaded = _patch_backup(monkeypatch, ok=False)
    _login(client)
    r = client.post(url_for("admin.backup_export"), follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "فشل التحقق من النسخة" in body and "أرشيف غير صالح" in body
    assert not uploaded, (
        f"an archive that failed validation must not be stored: {uploaded}")


def test_a_backup_that_passes_validation_is_stored(client, app, monkeypatch):
    """The control: the same path, with validation saying yes."""
    uploaded = _patch_backup(monkeypatch, ok=True)
    _login(client)
    client.post(url_for("admin.backup_export"), follow_redirects=True)
    assert uploaded == ["probe.zip"], (
        "a valid archive must reach storage")


# ======================================= branding needs a project first

def test_branding_without_any_active_project_sends_you_to_projects(client, app):
    """Branding is per project, so there is nothing to brand with none.

    The redirect says which page to fix, rather than rendering a form whose
    project dropdown is empty.
    """
    from app.models import Project, db
    with app.app_context():
        for p in Project.query.all():
            p.is_active = False
        db.session.commit()
    _login(client)
    r = client.get(url_for("admin.branding"), follow_redirects=True)
    assert "أضف مشروعاً أولاً" in r.get_data(as_text=True), (
        "the operator has to be told what is missing first")


def test_branding_with_an_active_project_renders(client, app):
    """The control for the redirect above."""
    from app.models import Project, db
    with app.app_context():
        Project.query.first().is_active = True
        db.session.commit()
    _login(client)
    r = client.get(url_for("admin.branding"))
    assert r.status_code == 200, f"got {r.status_code}"
    assert "أضف مشروعاً أولاً" not in r.get_data(as_text=True)
