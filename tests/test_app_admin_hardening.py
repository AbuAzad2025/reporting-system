"""Hardening regression tests — app factory, admin blueprint, main blueprint.

Covered production areas (exact assertions, no xfail, no smoke tests):

``app/__init__.py``
    * ``/healthz`` response contract (status / JSON body / mimetype).
    * security response headers and session-cookie hardening flags.
    * production ``SECRET_KEY`` guard (refuses the default dev secret) and
      the ``Secure``-cookie switch a real secret unlocks.
    * branded 403/404/500 pages rendered from an *isolated* app config and
      proven leak-free (no secret, no traceback, no exception class name).

``app/admin/routes.py``
    * ``parse_table_columns`` contract: key normalisation, type whitelist,
      required-flag vocabulary, Arabic-comma options, invalid/duplicate line
      skipping, hard 12-column cap.
    * table column add/delete round trips and field move round trips, each
      asserted against the database.
    * project create duplicate + blank-name validation (no row written).
    * user delete protection (self-delete refused, non-superadmin refused).
    * branding bootstrap idempotency and save (colour defaults + strip).

``app/main/routes.py``
    * archive date range, sort keys, order fallback, ``page``/``per_page``
      clamping, template/project filters and tenant scoping.
    * avatar save / reject / remove with the upload root redirected to tmp.
    * project backup export to a real ZIP file plus the import contract.

Deliberately NOT covered: the ``project_manager`` path through
``template_manager_required`` (that decorator admits ``project_manager``).
That behaviour is known and left untouched — every template/field call below
is made as ``t_admin`` (admin) or ``t_owner`` (superadmin).

Known limitation pinned by
``TestMainProjectBackup.test_import_of_export_fails_closed_without_partial_writes``:
a project-scope archive stores ISO date *strings* for ``created_at`` columns,
which the SQLite/PostgreSQL DATETIME bind processors reject, so re-importing
an exported project archive is refused with no partial writes. The import
success branch is pinned separately with a minimal valid archive.
"""
import io
import json
import re
import zipfile
from datetime import date

import pytest

from tests.conftest import login_as

#: Secret planted in the isolated app config AND in a raised exception; the
#: branded error pages must never echo it back to the client.
SECRET_CANARY = "isolated-secret-canary-4f2b91"


# ============================================================ app/__init__.py
@pytest.fixture()
def isolated_app(tmp_path, monkeypatch):
    """Second, fully isolated app: own config class, own DB file, no users."""
    from config import Config

    class IsolatedConfig(Config):
        TESTING = True
        PROPAGATE_EXCEPTIONS = False
        SECRET_KEY = SECRET_CANARY
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/isolated.db"

    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("AZADEXA_AUTO_CREATE", "0")
    from app import create_app

    application = create_app(IsolatedConfig)

    @application.route("/__hardening/gone")
    def _gone():
        from flask import abort
        abort(404, description="no such tenant: 4242")

    @application.route("/__hardening/forbidden")
    def _forbidden():
        from flask import abort
        abort(403)

    @application.route("/__hardening/boom")
    def _boom():
        raise RuntimeError("db password " + SECRET_CANARY + " exploded")

    yield application


class TestAppFactoryContract:
    def test_healthz_contract(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.mimetype == "application/json"
        assert r.get_json() == {"status": "ok"}
        assert sorted(r.get_json()) == ["status"]

    def test_healthz_sets_security_headers(self, client):
        r = client.get("/healthz")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert r.headers["Content-Type"] == "application/json"

    def test_cookie_and_csrf_flags_on_isolated_app(self, isolated_app):
        assert isolated_app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert isolated_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
        # CSRF is only relaxed while TESTING; production keeps it armed.
        assert isolated_app.config["WTF_CSRF_ENABLED"] is False

    def test_production_boot_refuses_default_secret(self, monkeypatch, tmp_path):
        from config import Config

        class DefaultSecretConfig(Config):
            TESTING = False
            SECRET_KEY = "dev-secret-change-in-production"
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/refuse.db"

        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("AZADEXA_AUTO_CREATE", "0")
        from app import create_app

        with pytest.raises(RuntimeError,
                           match="SECRET_KEY must be set in production."):
            create_app(DefaultSecretConfig)

    def test_production_boot_with_real_secret_marks_cookies_secure(
            self, monkeypatch, tmp_path):
        from config import Config

        class RealSecretConfig(Config):
            TESTING = False
            SECRET_KEY = "a-real-production-secret-value"
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/real.db"

        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("AZADEXA_AUTO_CREATE", "0")
        from app import create_app

        booted = create_app(RealSecretConfig)
        assert booted.config["SESSION_COOKIE_SECURE"] is True
        assert booted.config["SESSION_COOKIE_HTTPONLY"] is True
        assert booted.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_404_page_is_branded_and_leak_free(self, isolated_app):
        r = isolated_app.test_client().get("/__hardening/gone")
        assert r.status_code == 404
        html = r.get_data(as_text=True)
        assert '<div class="error-code">404</div>' in html
        assert "الصفحة غير موجودة" in html
        assert "/dashboard" in html            # branded recovery links survive
        assert SECRET_CANARY not in html
        assert "4242" not in html              # internal abort detail hidden
        assert "Traceback" not in html

    def test_unknown_url_returns_branded_404(self, isolated_app):
        r = isolated_app.test_client().get("/no-such-route-at-all")
        assert r.status_code == 404
        assert "الصفحة غير موجودة" in r.get_data(as_text=True)

    def test_403_page_is_branded(self, isolated_app):
        r = isolated_app.test_client().get("/__hardening/forbidden")
        assert r.status_code == 403
        html = r.get_data(as_text=True)
        assert '<div class="error-code">403</div>' in html
        assert SECRET_CANARY not in html

    def test_500_page_is_branded_and_leak_free(self, isolated_app):
        r = isolated_app.test_client().get("/__hardening/boom")
        assert r.status_code == 500
        html = r.get_data(as_text=True)
        assert '<div class="error-code">500</div>' in html
        assert "حدث خطأ غير متوقع" in html
        assert SECRET_CANARY not in html
        assert "RuntimeError" not in html
        assert "Traceback" not in html
        assert "exploded" not in html


# ================================================================== helpers
def _template_id(app, key):
    """id of a template, creating it on first use."""
    from app.extensions import db
    from app.models import ReportTemplate
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key=key).first()
        if tpl is None:
            tpl = ReportTemplate(key=key, name_ar="قالب " + key)
            db.session.add(tpl)
            db.session.commit()
        return tpl.id


def _branding_template_id(app, key):
    """Template id for branding tests.

    ``admin.branding`` keys ``TenantBranding.project_id`` on the *template* id,
    so a project row with that same id is inserted to keep the foreign key
    valid on PostgreSQL as well as SQLite.
    """
    from app.extensions import db
    from app.models import Project
    tid = _template_id(app, key)
    with app.app_context():
        if Project.query.get(tid) is None:
            db.session.add(Project(id=tid, name="branding-holder-" + key))
            db.session.commit()
    return tid


def _field_id(app, template_id, key):
    from app.models import DynamicField
    with app.app_context():
        return DynamicField.query.filter_by(template_id=template_id,
                                            field_key=key).one().id


def _sub_fields(app, field_id):
    from app.extensions import db
    from app.models import DynamicField
    with app.app_context():
        return db.session.get(DynamicField, field_id).sub_fields


def _positions(app, template_id):
    """(field_key, position) pairs in the order the admin page renders them."""
    from app.models import DynamicField
    with app.app_context():
        rows = (DynamicField.query.filter_by(template_id=template_id)
                .order_by(DynamicField.position).all())
        return [(row.field_key, row.position) for row in rows]


def _add_field(client, template_id, key, label, ftype="text", **extra):
    data = {"field_key": key, "label_ar": label, "field_type": ftype}
    data.update(extra)
    return client.post(f"/admin/templates/{template_id}/fields", data=data,
                       follow_redirects=True)


def _project_id(app, name):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name=name).one().id


def _branding_id(app, key_id):
    from app.models import TenantBranding
    with app.app_context():
        return TenantBranding.query.filter_by(project_id=key_id).one().id


def _user_by_username(app, username):
    from app.models import User
    with app.app_context():
        return User.query.filter_by(username=username).one()


# ================================================== admin: column parsing unit
class TestParseTableColumns:
    def test_dropdown_row_with_arabic_comma_options(self):
        from app.admin.routes import parse_table_columns
        raw = "item_code | رمز البند | dropdown | required | 1، 2، 3"
        assert parse_table_columns(raw) == [
            {"key": "item_code", "label_ar": "رمز البند", "type": "dropdown",
             "required": True, "options": ["1", "2", "3"]}]

    def test_unknown_type_falls_back_to_text_and_drops_options(self):
        from app.admin.routes import parse_table_columns
        assert parse_table_columns("qty | الكمية | geo | 1 | a,b") == [
            {"key": "qty", "label_ar": "الكمية", "type": "text",
             "required": True, "options": []}]

    def test_missing_type_and_required_default_to_text_optional(self):
        from app.admin.routes import parse_table_columns
        assert parse_table_columns("unit | الوحدة") == [
            {"key": "unit", "label_ar": "الوحدة", "type": "text",
             "required": False, "options": []}]

    @pytest.mark.parametrize("flag,expected", [
        ("required", True), ("مطلوب", True), ("1", True), ("yes", True),
        ("0", False), ("true", False), ("", False), ("م", False),
    ])
    def test_required_flag_vocabulary(self, flag, expected):
        from app.admin.routes import parse_table_columns
        cols = parse_table_columns("k | تسمية | date | " + flag)
        assert cols == [{"key": "k", "label_ar": "تسمية", "type": "date",
                         "required": expected, "options": []}]

    def test_key_is_lowercased_and_spaces_become_underscores(self):
        from app.admin.routes import parse_table_columns
        assert parse_table_columns("Item Name | اسم الصنف")[0]["key"] == "item_name"

    def test_blank_short_and_duplicate_lines_are_skipped(self):
        from app.admin.routes import parse_table_columns
        raw = ("\n"
               "onlykey\n"
               " | بلا مفتاح\n"
               "Foo | أول\n"
               "foo | ثان\n"
               "  |  \n"
               "Bar | ثالث\n")
        cols = parse_table_columns(raw)
        assert [c["key"] for c in cols] == ["foo", "bar"]
        assert cols[0]["label_ar"] == "أول"      # first definition wins

    def test_empty_and_none_input(self):
        from app.admin.routes import parse_table_columns
        assert parse_table_columns("") == []
        assert parse_table_columns(None) == []

    def test_hard_cap_of_twelve_columns(self):
        from app.admin.routes import parse_table_columns
        raw = "\n".join(f"c{i} | عمود {i}" for i in range(1, 15))
        cols = parse_table_columns(raw)
        assert len(cols) == 12
        assert cols[-1]["key"] == "c12"

    def test_only_dropdown_columns_get_options(self):
        from app.admin.routes import parse_table_columns
        raw = "a | أ | number | 1 | x,y\nb | ب | dropdown | 1 | x,y"
        cols = parse_table_columns(raw)
        assert cols[0]["options"] == []
        assert cols[1]["options"] == ["x", "y"]


# ============================================== admin: column add / delete I/O
class TestAdminTableColumnRoundTrips:
    def test_table_field_stores_parsed_columns(self, app, client):
        tid = _template_id(app, "hardening_cols")
        login_as(client, "t_admin")
        raw = "code | الرمز | text | 1\nqty | الكمية | number | required\n"
        r = _add_field(client, tid, "items", "بنود", "table", columns=raw)
        assert r.status_code == 200
        from app.models import DynamicField
        with app.app_context():
            field = DynamicField.query.filter_by(template_id=tid,
                                                 field_key="items").one()
            assert field.field_type == "table"
            assert field.position == 1
            assert field.sub_fields == [
                {"key": "code", "label_ar": "الرمز", "type": "text",
                 "required": True, "options": []},
                {"key": "qty", "label_ar": "الكمية", "type": "number",
                 "required": True, "options": []},
            ]
            assert field.sub_columns()[0] == {
                "key": "code", "label_ar": "الرمز", "type": "text",
                "required": True, "placeholder": "", "options": []}

    def test_column_add_normalises_and_persists(self, app, client):
        tid = _template_id(app, "hardening_add")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table")
        fid = _field_id(app, tid, "items")
        r = client.post(f"/admin/fields/{fid}/columns", data={
            "col_key": "Unit Name", "col_label": "الوحدة",
            "col_type": "dropdown", "col_options": "م³، طن , ",
            "col_required": "on"}, follow_redirects=True)
        assert r.status_code == 200
        assert "تمت إضافة العمود «الوحدة»." in r.get_data(as_text=True)
        assert _sub_fields(app, fid) == [
            {"key": "unit_name", "label_ar": "الوحدة", "type": "dropdown",
             "required": True, "options": ["م³", "طن"]}]

    def test_column_add_coerces_unknown_type(self, app, client):
        tid = _template_id(app, "hardening_type")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table")
        fid = _field_id(app, tid, "items")
        client.post(f"/admin/fields/{fid}/columns", data={
            "col_key": "weird", "col_label": "غريب", "col_type": "geo",
            "col_options": "x,y"}, follow_redirects=True)
        assert _sub_fields(app, fid) == [
            {"key": "weird", "label_ar": "غريب", "type": "text",
             "required": False, "options": []}]

    def test_column_add_rejects_duplicate_key(self, app, client):
        tid = _template_id(app, "hardening_dup")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table")
        fid = _field_id(app, tid, "items")
        client.post(f"/admin/fields/{fid}/columns", data={
            "col_key": "code", "col_label": "الرمز", "col_type": "text"},
            follow_redirects=True)
        before = _sub_fields(app, fid)
        r = client.post(f"/admin/fields/{fid}/columns", data={
            "col_key": "code", "col_label": "مكرر", "col_type": "number"},
            follow_redirects=True)
        assert "يوجد عمود بنفس المفتاح." in r.get_data(as_text=True)
        assert _sub_fields(app, fid) == before

    def test_column_add_requires_key_and_label(self, app, client):
        tid = _template_id(app, "hardening_missing")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table")
        fid = _field_id(app, tid, "items")
        r = client.post(f"/admin/fields/{fid}/columns", data={"col_label": "بلا مفتاح"},
                        follow_redirects=True)
        assert "مفتاح العمود وتسميته مطلوبان." in r.get_data(as_text=True)
        assert _sub_fields(app, fid) == []

    def test_column_add_refused_for_non_table_field(self, app, client):
        tid = _template_id(app, "hardening_nontable")
        login_as(client, "t_admin")
        _add_field(client, tid, "note", "ملاحظة", "text")
        fid = _field_id(app, tid, "note")
        r = client.post(f"/admin/fields/{fid}/columns", data={
            "col_key": "code", "col_label": "الرمز", "col_type": "text"},
            follow_redirects=True)
        assert "الأعمدة لجداول البنود فقط." in r.get_data(as_text=True)
        assert _sub_fields(app, fid) == []

    def test_column_add_capped_at_twelve(self, app, client):
        from app.extensions import db
        from app.models import DynamicField
        tid = _template_id(app, "hardening_cap")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table")
        fid = _field_id(app, tid, "items")
        with app.app_context():
            field = db.session.get(DynamicField, fid)
            field.sub_fields = [{"key": f"c{i}", "label_ar": f"عمود {i}",
                                 "type": "text", "required": False,
                                 "options": []} for i in range(12)]
            db.session.commit()
        r = client.post(f"/admin/fields/{fid}/columns", data={
            "col_key": "c12", "col_label": "ثالث عشر", "col_type": "text"},
            follow_redirects=True)
        assert "الحد الأقصى 12 عموداً." in r.get_data(as_text=True)
        assert len(_sub_fields(app, fid)) == 12

    def test_column_delete_then_readd_round_trip(self, app, client):
        tid = _template_id(app, "hardening_del")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table",
                   columns="code | الرمز | text | 1\nqty | الكمية | number")
        fid = _field_id(app, tid, "items")
        assert [c["key"] for c in _sub_fields(app, fid)] == ["code", "qty"]
        r = client.post(f"/admin/fields/{fid}/columns/qty/delete",
                        follow_redirects=True)
        assert "تم حذف العمود." in r.get_data(as_text=True)
        assert [c["key"] for c in _sub_fields(app, fid)] == ["code"]
        client.post(f"/admin/fields/{fid}/columns", data={
            "col_key": "qty", "col_label": "الكمية", "col_type": "number"},
            follow_redirects=True)
        assert [c["key"] for c in _sub_fields(app, fid)] == ["code", "qty"]

    def test_column_delete_unknown_key_is_a_no_op(self, app, client):
        tid = _template_id(app, "hardening_delmiss")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table",
                   columns="code | الرمز | text | 1")
        fid = _field_id(app, tid, "items")
        r = client.post(f"/admin/fields/{fid}/columns/ghost/delete",
                        follow_redirects=True)
        assert r.status_code == 200
        assert "تم حذف العمود." not in r.get_data(as_text=True)
        assert [c["key"] for c in _sub_fields(app, fid)] == ["code"]

    def test_field_delete_removes_the_whole_table(self, app, client):
        from app.extensions import db
        from app.models import DynamicField
        tid = _template_id(app, "hardening_fdel")
        login_as(client, "t_admin")
        _add_field(client, tid, "items", "بنود", "table",
                   columns="code | الرمز | text | 1")
        fid = _field_id(app, tid, "items")
        r = client.post(f"/admin/fields/{fid}/delete", follow_redirects=True)
        assert "تم حذف الحقل." in r.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(DynamicField, fid) is None
        assert _positions(app, tid) == []


# ========================================================= admin: field moves
class TestAdminFieldMoves:
    def test_move_up_and_down_swap_positions(self, app, client):
        tid = _template_id(app, "hardening_move")
        login_as(client, "t_admin")
        for key in ("a", "b", "c"):
            _add_field(client, tid, key, "حقل " + key)
        assert _positions(app, tid) == [("a", 1), ("b", 2), ("c", 3)]
        c_id = _field_id(app, tid, "c")
        r = client.post(f"/admin/fields/{c_id}/move/up", follow_redirects=True)
        assert r.status_code == 200
        assert _positions(app, tid) == [("a", 1), ("c", 2), ("b", 3)]
        client.post(f"/admin/fields/{c_id}/move/down", follow_redirects=True)
        assert _positions(app, tid) == [("a", 1), ("b", 2), ("c", 3)]

    def test_move_at_the_edges_changes_nothing(self, app, client):
        tid = _template_id(app, "hardening_edges")
        login_as(client, "t_admin")
        for key in ("a", "b"):
            _add_field(client, tid, key, "حقل " + key)
        a_id = _field_id(app, tid, "a")
        b_id = _field_id(app, tid, "b")
        client.post(f"/admin/fields/{a_id}/move/up", follow_redirects=True)
        assert _positions(app, tid) == [("a", 1), ("b", 2)]
        client.post(f"/admin/fields/{b_id}/move/down", follow_redirects=True)
        assert _positions(app, tid) == [("a", 1), ("b", 2)]


# ====================================================== admin: project create
class TestAdminProjectCreate:
    def test_duplicate_name_is_refused_and_writes_nothing(self, app, client):
        from app.models import Project
        with app.app_context():
            before = Project.query.count()
        login_as(client, "t_admin")
        r = client.post("/admin/projects",
                        data={"name": "Alpha Tower", "location": "x"})
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/admin/projects")
        page = client.get("/admin/projects").get_data(as_text=True)
        assert "يوجد مشروع بنفس الاسم." in page
        with app.app_context():
            assert Project.query.count() == before
            # the pre-existing row is untouched by the rejected create
            assert Project.query.filter_by(name="Alpha Tower").one().location \
                == "Riyadh"

    def test_blank_name_is_refused(self, app, client):
        from app.models import Project
        with app.app_context():
            before = Project.query.count()
        login_as(client, "t_admin")
        client.post("/admin/projects", data={"name": "   "})
        page = client.get("/admin/projects").get_data(as_text=True)
        assert "اسم المشروع مطلوب." in page
        with app.app_context():
            assert Project.query.count() == before

    def test_valid_create_persists_full_row(self, app, client):
        from app.models import Project
        login_as(client, "t_admin")
        r = client.post("/admin/projects", data={
            "name": "مشروع جديد للاختبار", "location": "الرياض",
            "contractor": "مقاول رئيسي", "client": "عميل"},
            follow_redirects=True)
        assert r.status_code == 200
        assert "تمت إضافة المشروع «مشروع جديد للاختبار»." \
            in r.get_data(as_text=True)
        with app.app_context():
            proj = Project.query.filter_by(name="مشروع جديد للاختبار").one()
            assert (proj.location, proj.contractor, proj.client) == (
                "الرياض", "مقاول رئيسي", "عميل")
            assert proj.is_active is True
            assert proj.logo_path == "" and proj.logo2_path == ""

    def test_non_manager_cannot_create(self, app, client):
        from app.models import Project
        with app.app_context():
            before = Project.query.count()
        login_as(client, "t_eng")
        r = client.post("/admin/projects", data={"name": "مشروع مهندس"})
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/dashboard")
        page = client.get("/dashboard").get_data(as_text=True)
        assert "لا تملك صلاحية الوصول إلى هذه الصفحة." in page
        with app.app_context():
            assert Project.query.count() == before


# ================================================= admin: user delete safety
class TestAdminUserDeleteProtection:
    @staticmethod
    def _victim_id(app):
        from app.extensions import db
        from app.models import User
        with app.app_context():
            user = User(username="hardening_victim", email="victim@t.com",
                        full_name="مستخدم ضحية للاختبار",
                        role="site_engineer")
            user.set_password("pw12345")
            db.session.add(user)
            db.session.commit()
            return user.id

    def test_superadmin_cannot_delete_self(self, app, client):
        from app.extensions import db
        from app.models import User
        login_as(client, "t_owner")
        with app.app_context():
            owner_id = User.query.filter_by(username="t_owner").one().id
        r = client.post(f"/admin/users/{owner_id}/delete")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/admin/users")
        page = client.get("/admin/users").get_data(as_text=True)
        assert "لا يمكنك حذف حسابك الخاص." in page
        with app.app_context():
            assert db.session.get(User, owner_id) is not None

    def test_superadmin_deletes_another_user(self, app, client):
        from app.extensions import db
        from app.models import User
        uid = self._victim_id(app)
        login_as(client, "t_owner")
        r = client.post(f"/admin/users/{uid}/delete", follow_redirects=True)
        assert r.status_code == 200
        assert "تم حذف حساب مستخدم ضحية للاختبار." in r.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(User, uid) is None

    def test_plain_admin_is_refused(self, app, client):
        from app.extensions import db
        from app.models import User
        uid = self._victim_id(app)
        login_as(client, "t_admin")
        r = client.post(f"/admin/users/{uid}/delete")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/dashboard")
        page = client.get("/dashboard").get_data(as_text=True)
        assert "لا تملك صلاحية الوصول إلى هذه الصفحة." in page
        with app.app_context():
            assert db.session.get(User, uid) is not None

    def test_anonymous_delete_redirects_to_login(self, client):
        r = client.post("/admin/users/1/delete")
        assert r.status_code == 302
        assert "/auth/login" in r.headers["Location"]


# ========================================================= admin: tenant brand
class TestAdminBranding:
    def test_get_bootstraps_one_active_row_and_is_idempotent(self, app, client):
        from app.extensions import db
        from app.models import TenantBranding
        tid = _branding_template_id(app, "hardening_brand")
        login_as(client, "t_admin")
        assert client.get(f"/admin/branding/{tid}").status_code == 200
        with app.app_context():
            rows = TenantBranding.query.filter_by(project_id=tid).all()
            assert len(rows) == 1
            assert rows[0].is_active is True
        first_id = _branding_id(app, tid)
        assert client.get(f"/admin/branding/{tid}").status_code == 200
        assert _branding_id(app, tid) == first_id
        with app.app_context():
            assert TenantBranding.query.filter_by(project_id=tid).count() == 1

    def test_save_persists_values_and_colour_defaults(self, app, client):
        from app.models import TenantBranding
        tid = _branding_template_id(app, "hardening_brand_save")
        login_as(client, "t_admin")
        client.get(f"/admin/branding/{tid}")
        r = client.post(f"/admin/branding/{tid}", data={
            "company_name_ar": "  شركة أزاد للأنظمة الذكية  ",
            "company_name_en": "  AZAD Intelligent Systems ",
            "logo_path": "  logos/brand.png ",
            "primary_color": "   ",          # blank -> default
            "secondary_color": "  #abcdef  ",
            "custom_header_text_ar": " ترويسة ",
            "custom_footer_notes": " حاشية ",
            "disclaimer_text": " إخلاء مسؤولية "}, follow_redirects=True)
        assert r.status_code == 200
        assert "تم حفظ تخصيص المظهر للمشروع." in r.get_data(as_text=True)
        with app.app_context():
            brand = TenantBranding.query.filter_by(project_id=tid).one()
            assert brand.company_name_ar == "شركة أزاد للأنظمة الذكية"
            assert brand.company_name_en == "AZAD Intelligent Systems"
            assert brand.logo_path == "logos/brand.png"
            assert brand.primary_color == "#1e3a5f"      # blank -> default
            assert brand.secondary_color == "#abcdef"
            assert brand.custom_header_text_ar == "ترويسة"
            assert brand.custom_footer_notes == "حاشية"
            assert brand.disclaimer_text == "إخلاء مسؤولية"
            assert brand.is_active is True

    def test_unknown_template_is_branded_404(self, client):
        login_as(client, "t_admin")
        r = client.get("/admin/branding/987654")
        assert r.status_code == 404
        assert "الصفحة غير موجودة" in r.get_data(as_text=True)

    def test_non_manager_cannot_touch_branding(self, app, client):
        from app.models import TenantBranding
        tid = _branding_template_id(app, "hardening_brand_denied")
        login_as(client, "t_eng")
        r = client.get(f"/admin/branding/{tid}")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/dashboard")
        with app.app_context():
            assert TenantBranding.query.count() == 0


# ========================================================== main: archive list
def _seed_archive_rows(app):
    """Dynamic + legacy rows; submission project names match real projects."""
    from app.extensions import db
    from app.models import (Project, Report, ReportSubmission,
                            ReportTemplate, User)
    with app.app_context():
        tpl = ReportTemplate.query.filter_by(key="daily").one()
        eng = User.query.filter_by(username="t_eng").one()
        safety = User.query.filter_by(username="t_safety").one()
        proj = Project.query.filter_by(name="Alpha Tower").one()
        sub_ids = []
        for name, when in (("Alpha Tower", date(2026, 1, 10)),
                           ("Zeta Site", date(2026, 1, 20)),
                           ("Mid Site", date(2026, 1, 15))):
            sub = ReportSubmission(template_id=tpl.id, project_id=proj.id,
                                   project_name=name, location="Riyadh",
                                   contractor="Alpha Main", report_date=when,
                                   data={}, signatory_name=eng.full_name,
                                   user_id=eng.id)
            db.session.add(sub)
            db.session.flush()
            sub_ids.append(sub.id)
        other = ReportSubmission(template_id=tpl.id, project_id=proj.id,
                                 project_name="Safety Site",
                                 location="Jeddah", contractor="Beta Main",
                                 report_date=date(2026, 1, 18), data={},
                                 signatory_name=safety.full_name,
                                 user_id=safety.id)
        db.session.add(other)
        db.session.flush()
        legacy_ids = []
        for rtype, when in (("daily", date(2026, 2, 2)),
                            ("safety", date(2026, 2, 1))):
            rep = Report(report_type=rtype, project_name="Alpha Tower",
                         location="Riyadh", contractor="Alpha Main",
                         report_date=when, data={},
                         signatory_name=eng.full_name, user_id=eng.id)
            db.session.add(rep)
            db.session.flush()
            legacy_ids.append(rep.id)
        db.session.commit()
        other_id = other.id
    return {"sub": sub_ids, "other": other_id, "legacy": legacy_ids}


def _serials(html, prefix):
    """Ordered unique serial numbers (DS-##### / RPT-#####) as rendered."""
    out = []
    for token in re.findall(prefix + r"-(\d{5})", html):
        if int(token) not in out:
            out.append(int(token))
    return out


def _archive_total(html):
    match = re.search(
        r"الإجمالي: <span class=\"text-navy text-sm\">(\d+)</span>", html)
    assert match, "archive summary bar missing"
    return int(match.group(1))


class TestMainArchiveListing:
    def test_default_sort_is_date_descending(self, app, client):
        ids = _seed_archive_rows(app)
        login_as(client, "t_admin")
        html = client.get("/archive").get_data(as_text=True)
        s1, s2, s3 = ids["sub"]
        assert _serials(html, "DS") == [s2, ids["other"], s3, s1]
        assert _archive_total(html) == 4

    def test_date_order_ascending(self, app, client):
        ids = _seed_archive_rows(app)
        s1, s2, s3 = ids["sub"]
        login_as(client, "t_admin")
        html = client.get("/archive?sort=date&order=asc").get_data(as_text=True)
        assert _serials(html, "DS") == [s1, s3, ids["other"], s2]

    def test_invalid_sort_and_order_fall_back_to_defaults(self, app, client):
        ids = _seed_archive_rows(app)
        s1, s2, s3 = ids["sub"]
        login_as(client, "t_admin")
        html = client.get("/archive?sort=bogus&order=sideways").get_data(
            as_text=True)
        assert _serials(html, "DS") == [s2, ids["other"], s3, s1]
        assert "•" in html and "صفحة 1 من 1" not in html

    def test_sort_by_project_ascending_and_descending(self, app, client):
        ids = _seed_archive_rows(app)
        s1, s2, s3 = ids["sub"]
        login_as(client, "t_admin")
        html = client.get("/archive?sort=project&order=asc").get_data(
            as_text=True)
        assert _serials(html, "DS") == [s1, s3, ids["other"], s2]
        html = client.get("/archive?sort=project&order=desc").get_data(
            as_text=True)
        assert _serials(html, "DS") == [s2, ids["other"], s3, s1]

    def test_dynamic_type_sort_stays_date_ordered(self, app, client):
        ids = _seed_archive_rows(app)
        s1, s2, s3 = ids["sub"]
        login_as(client, "t_admin")
        html = client.get("/archive?sort=type&order=asc").get_data(as_text=True)
        assert _serials(html, "DS") == [s2, ids["other"], s3, s1]

    def test_date_range_filters_inclusively(self, app, client):
        ids = _seed_archive_rows(app)
        s1, s2, s3 = ids["sub"]
        login_as(client, "t_admin")
        html = client.get("/archive?from=2026-01-15&to=2026-01-18").get_data(
            as_text=True)
        assert _serials(html, "DS") == [ids["other"], s3]
        assert _archive_total(html) == 2
        html = client.get("/archive?from=2026-01-11&to=2026-01-15").get_data(
            as_text=True)
        assert _serials(html, "DS") == [s3]
        html = client.get("/archive?from=2026-02-01").get_data(as_text=True)
        assert _archive_total(html) == 0
        assert s2 not in _serials(html, "DS")
        assert s1 not in _serials(html, "DS")

    def test_search_matches_project_and_signatory(self, app, client):
        ids = _seed_archive_rows(app)
        login_as(client, "t_admin")
        html = client.get("/archive?q=Zeta").get_data(as_text=True)
        assert _serials(html, "DS") == [ids["sub"][1]]
        assert _archive_total(html) == 1
        html = client.get("/archive?q=مسؤول سلامة").get_data(as_text=True)
        assert _serials(html, "DS") == [ids["other"]]

    def test_project_filter_resolves_id_to_name(self, app, client):
        ids = _seed_archive_rows(app)
        alpha_id = _project_id(app, "Alpha Tower")
        beta_id = _project_id(app, "Beta Hospital")
        login_as(client, "t_admin")
        html = client.get(f"/archive?project={alpha_id}").get_data(as_text=True)
        assert _serials(html, "DS") == [ids["sub"][0]]
        assert _archive_total(html) == 1
        html = client.get(f"/archive?project={beta_id}").get_data(as_text=True)
        assert _archive_total(html) == 0
        assert "DS-" not in html
        html = client.get("/archive?project=999999").get_data(as_text=True)
        assert _archive_total(html) == 4      # unknown id is not a filter

    def test_template_filter(self, app, client):
        _seed_archive_rows(app)
        login_as(client, "t_admin")
        html = client.get("/archive?src=dyn&tpl=weekly").get_data(as_text=True)
        assert _archive_total(html) == 0
        html = client.get("/archive?src=dyn&tpl=daily").get_data(as_text=True)
        assert _archive_total(html) == 4

    def test_per_page_is_clamped_to_one(self, app, client):
        _seed_archive_rows(app)
        login_as(client, "t_admin")
        for query in ("per_page=0", "per_page=-7"):
            html = client.get(f"/archive?{query}").get_data(as_text=True)
            assert _archive_total(html) == 4
            assert len(_serials(html, "DS")) == 1
            assert "صفحة 1 من 4" in html

    def test_pagination_slices_and_clamps_the_page(self, app, client):
        ids = _seed_archive_rows(app)
        s1, s2, s3 = ids["sub"]
        order_desc = [s2, ids["other"], s3, s1]
        login_as(client, "t_admin")
        html = client.get("/archive?per_page=2&page=1").get_data(as_text=True)
        assert _serials(html, "DS") == order_desc[:2]
        assert "صفحة 1 من 2" in html
        # a page past the end is clamped to the last page
        html = client.get("/archive?per_page=2&page=99").get_data(as_text=True)
        assert _serials(html, "DS") == order_desc[2:]
        assert "صفحة 2 من 2" in html
        # non-numeric / negative values fall back to the defaults
        for query in ("per_page=abc&page=xyz", "page=-4", "per_page=99999"):
            html = client.get(f"/archive?{query}").get_data(as_text=True)
            assert _serials(html, "DS") == order_desc
            assert _archive_total(html) == 4
            assert "صفحة 1 من 1" not in html     # single page -> no pager

    def test_engineer_sees_only_own_submissions(self, app, client):
        ids = _seed_archive_rows(app)
        login_as(client, "t_eng")
        html = client.get("/archive").get_data(as_text=True)
        assert sorted(_serials(html, "DS")) == sorted(ids["sub"])
        assert _archive_total(html) == 3
        # membership-scoped project dropdown: Alpha Tower only
        assert "Beta Hospital" not in html
        assert "Alpha Tower" in html

    def test_legacy_source_sorts_by_type(self, app, client):
        ids = _seed_archive_rows(app)
        daily_id, safety_id = ids["legacy"]
        login_as(client, "t_admin")
        html = client.get("/archive?src=legacy&sort=type&order=asc").get_data(
            as_text=True)
        assert _serials(html, "RPT") == [daily_id, safety_id]
        html = client.get("/archive?src=legacy&type=safety").get_data(
            as_text=True)
        assert _serials(html, "RPT") == [safety_id]
        assert _archive_total(html) == 1
        html = client.get("/archive?src=legacy&from=2026-02-02").get_data(
            as_text=True)
        assert _serials(html, "RPT") == [daily_id]


# ============================================================= main: avatar I/O
@pytest.fixture()
def avatar_client(app, client, tmp_path, monkeypatch):
    """Redirect the avatar upload root to tmp (the module __file__ anchors it)."""
    import app.main.routes as main_routes
    fake_module = tmp_path / "app" / "main" / "routes.py"
    fake_module.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_routes, "__file__", str(fake_module))
    return client


def _avatar_root(tmp_path):
    return tmp_path / "app" / "static" / "uploads"


class TestMainAvatar:
    def test_valid_png_is_saved_to_uploads(self, app, avatar_client, tmp_path):
        from app.models import User
        png = b"\x89PNG\r\n\x1a\n" + b"hardening-pixel" * 4
        login_as(avatar_client, "t_eng")
        r = avatar_client.post("/profile", data={
            "full_name": "خالد سعيد محمود عبدالله",
            "phone": "+966500000000", "job_title": "مهندس موقع",
            "notify_email": "on",
            "avatar": (io.BytesIO(png), "face.png")}, follow_redirects=True)
        assert r.status_code == 200
        assert "تم تحديث الملف الشخصي بنجاح." in r.get_data(as_text=True)
        with app.app_context():
            user = User.query.filter_by(username="t_eng").one()
            assert user.avatar.startswith("avatars/%d_" % user.id)
            assert user.avatar.endswith(".png")
            assert user.phone == "+966500000000"
            assert user.job_title == "مهندس موقع"
            assert user.notification_prefs == {"email": True, "sms": False,
                                               "push": False, "in_app": False}
            saved = _avatar_root(tmp_path) / user.avatar
            assert saved.is_file()
            assert saved.read_bytes() == png

    def test_non_image_mime_is_rejected_and_nothing_is_written(
            self, app, avatar_client, tmp_path):
        from app.models import User
        login_as(avatar_client, "t_eng")
        r = avatar_client.post("/profile", data={
            "full_name": "خالد سعيد محمود عبدالله",
            "avatar": (io.BytesIO(b"%PDF-1.4 fake"), "resume.pdf")},
            follow_redirects=True)
        assert r.status_code == 200
        assert "نوع الملف غير مدعوم (JPG, PNG, GIF, WebP فقط)." \
            in r.get_data(as_text=True)
        with app.app_context():
            user = User.query.filter_by(username="t_eng").one()
            assert user.avatar == ""
            assert user.full_name == "مهندس اختبار تجريبي عام"  # rolled back
        assert not (_avatar_root(tmp_path) / "avatars").exists()

    def test_oversized_avatar_is_rejected(self, app, avatar_client, tmp_path):
        from app.models import User
        big = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024)
        login_as(avatar_client, "t_eng")
        r = avatar_client.post("/profile", data={
            "full_name": "خالد سعيد محمود عبدالله",
            "avatar": (io.BytesIO(big), "huge.png")}, follow_redirects=True)
        assert r.status_code == 200
        assert "حجم الصورة يتجاوز 2 ميغابايت." in r.get_data(as_text=True)
        with app.app_context():
            assert User.query.filter_by(username="t_eng").one().avatar == ""
        assert not (_avatar_root(tmp_path) / "avatars").exists()

    def test_remove_deletes_the_file_and_clears_the_key(
            self, app, avatar_client, tmp_path):
        from app.extensions import db
        from app.models import User
        with app.app_context():
            user = User.query.filter_by(username="t_eng").one()
            key = "avatars/%d_1700000000.png" % user.id
            user.avatar = key
            db.session.commit()
        target = _avatar_root(tmp_path) / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x89PNG\r\n\x1a\nstale")
        login_as(avatar_client, "t_eng")
        r = avatar_client.post("/profile/avatar/remove")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/profile")
        page = avatar_client.get("/profile").get_data(as_text=True)
        assert "تم حذف الصورة الشخصية." in page
        with app.app_context():
            assert User.query.filter_by(username="t_eng").one().avatar == ""
        assert not target.exists()

    def test_remove_without_avatar_warns(self, app, avatar_client):
        from app.models import User
        login_as(avatar_client, "t_eng")
        avatar_client.post("/profile/avatar/remove")
        page = avatar_client.get("/profile").get_data(as_text=True)
        assert "لا توجد صورة لحذفها." in page
        with app.app_context():
            assert User.query.filter_by(username="t_eng").one().avatar == ""

    def test_profile_guards_short_name_and_password(self, app, avatar_client):
        from app.models import User
        login_as(avatar_client, "t_eng")
        r = avatar_client.post("/profile", data={"full_name": "خالد سعيد محمود"},
                               follow_redirects=True)
        assert "الاسم الرباعي يجب أن يتكون من أربعة مقاطع على الأقل." \
            in r.get_data(as_text=True)
        r = avatar_client.post("/profile", data={
            "full_name": "خالد سعيد محمود عبدالله",
            "new_password": "short7"}, follow_redirects=True)
        assert "كلمة المرور الجديدة قصيرة (8 أحرف على الأقل)." \
            in r.get_data(as_text=True)
        with app.app_context():
            user = User.query.filter_by(username="t_eng").one()
            assert user.full_name == "مهندس اختبار تجريبي عام"
            assert user.check_password("pw12345") is True
        r = avatar_client.post("/profile", data={
            "full_name": "خالد سعيد محمود عبدالله",
            "new_password": "longenough9"}, follow_redirects=True)
        assert "تم تحديث الملف الشخصي بنجاح." in r.get_data(as_text=True)
        with app.app_context():
            user = User.query.filter_by(username="t_eng").one()
            assert user.full_name == "خالد سعيد محمود عبدالله"
            assert user.check_password("longenough9") is True
            assert user.check_password("pw12345") is False


# ==================================================== main: project backup I/O
@pytest.fixture()
def backup_client(app, client, tmp_path, monkeypatch):
    """Point the local storage backend at tmp so ZIPs land outside the repo."""
    import app.services.storage as storage
    monkeypatch.setattr(storage, "BACKUP_LOCAL_DIR", str(tmp_path / "backups"))
    return client


def _backup_files(tmp_path):
    root = tmp_path / "backups"
    return sorted(root.iterdir()) if root.exists() else []


def _minimal_project_archive(path, project_id):
    """A valid project-scope archive carrying no rows (import must succeed)."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps({
            "version": "1.0", "scope": "project", "project_id": project_id,
            "created_at": "2026-01-01T00:00:00",
            "generator": "hardening-test"}).encode("utf-8"))


class TestMainProjectBackup:
    def test_export_writes_a_real_project_scoped_zip(self, app, backup_client,
                                                     tmp_path):
        pid = _project_id(app, "Alpha Tower")
        login_as(backup_client, "t_owner")
        r = backup_client.post(f"/projects/{pid}/backup")
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/projects/{pid}")
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "تم إنشاء نسخة احتياطية للمشروع «Alpha Tower»." in page
        files = _backup_files(tmp_path)
        assert len(files) == 1
        assert re.fullmatch(r"azadexa-project-%d-\d{8}-\d{6}\.zip" % pid,
                            files[0].name)
        with zipfile.ZipFile(files[0]) as z:
            names = set(z.namelist())
            assert "metadata.json" in names
            assert "users.json" not in names        # project scope only
            meta = json.loads(z.read("metadata.json"))
            assert meta["scope"] == "project"
            assert meta["project_id"] == pid
            assert meta["version"] == "1.0"
            members = json.loads(z.read("project_members.json"))
            assert len(members) == 3               # Alpha Tower roster
            assert sorted(m["project_id"] for m in members) == [pid] * 3
            assert sorted(m["role_in_project"] for m in members) == [
                "member", "member", "owner"]
            inspections = json.loads(
                z.read("ops_records/site_inspections.json"))
            assert [row["serial"] for row in inspections] == ["SIR-000001"]
            # project scoping: Beta Hospital's rows stay out
            variances = json.loads(z.read("ops_records/cost_variances.json"))
            assert [row["serial"] for row in variances] == ["CVR-000001"]
            assert json.loads(z.read("report_submissions.json")) == []
            assert json.loads(z.read("attachments.json")) == []

    def test_exported_zip_is_a_valid_archive(self, app, backup_client, tmp_path):
        from app.services.backup import validate_backup
        pid = _project_id(app, "Alpha Tower")
        login_as(backup_client, "t_owner")
        backup_client.post(f"/projects/{pid}/backup")
        payload = _backup_files(tmp_path)[0].read_bytes()
        report = validate_backup(payload)
        assert report["ok"] is True
        assert report["size"] == len(payload)
        assert report["metadata"]["project_id"] == pid

    def test_export_refused_for_plain_project_member(self, app, backup_client,
                                                     tmp_path):
        pid = _project_id(app, "Alpha Tower")
        login_as(backup_client, "t_eng")
        r = backup_client.post(f"/projects/{pid}/backup")
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/projects/{pid}")
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "إدارة النسخ الاحتياطي مقصورة على مالك المشروع." in page
        assert _backup_files(tmp_path) == []

    def test_export_refused_for_unlinked_project(self, app, backup_client,
                                                 tmp_path):
        pid = _project_id(app, "Beta Hospital")
        login_as(backup_client, "t_eng")
        r = backup_client.post(f"/projects/{pid}/backup")
        assert r.status_code == 404
        assert "الصفحة غير موجودة" in r.get_data(as_text=True)
        assert _backup_files(tmp_path) == []

    def test_import_requires_a_file(self, app, backup_client):
        from app.ops.models import ProjectMember
        pid = _project_id(app, "Alpha Tower")
        with app.app_context():
            before = ProjectMember.query.count()
        login_as(backup_client, "t_owner")
        r = backup_client.post(f"/projects/{pid}/backup/import")
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/projects/{pid}")
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "لم يتم اختيار ملف نسخة احتياطية." in page
        with app.app_context():
            assert ProjectMember.query.count() == before

    def test_import_rejects_empty_filename(self, app, backup_client):
        pid = _project_id(app, "Alpha Tower")
        login_as(backup_client, "t_owner")
        backup_client.post(f"/projects/{pid}/backup/import", data={
            "backup_file": (io.BytesIO(b""), "")})
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "لم يتم اختيار ملف نسخة احتياطية." in page

    def test_import_rejects_corrupt_archive(self, app, backup_client):
        from app.ops.models import ProjectMember
        pid = _project_id(app, "Alpha Tower")
        with app.app_context():
            before = ProjectMember.query.count()
        login_as(backup_client, "t_owner")
        backup_client.post(f"/projects/{pid}/backup/import", data={
            "backup_file": (io.BytesIO(b"definitely-not-a-zip"), "x.zip")})
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "الملف غير صالح:" in page
        with app.app_context():
            assert ProjectMember.query.count() == before

    def test_import_of_export_round_trips_without_data_loss(
            self, app, backup_client, tmp_path):
        from app.models import Project
        from app.ops.models import (CostVariance, ProjectMember, RFI,
                                    SiteInspection)
        pid = _project_id(app, "Alpha Tower")
        login_as(backup_client, "t_owner")
        backup_client.post(f"/projects/{pid}/backup")
        archive = _backup_files(tmp_path)[0]
        with app.app_context():
            before = {
                "members": ProjectMember.query.filter_by(
                    project_id=pid).count(),
                "inspections": SiteInspection.query.filter_by(
                    project_id=pid).count(),
                "rfis": RFI.query.filter_by(project_id=pid).count(),
                "variances": CostVariance.query.filter_by(
                    project_id=pid).count(),
            }
        assert before["members"] == 3
        assert before["inspections"] == 1

        r = backup_client.post(f"/projects/{pid}/backup/import", data={
            "backup_file": (io.BytesIO(archive.read_bytes()), archive.name)})
        assert r.status_code == 302
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "تم استعادة المشروع «Alpha Tower»" in page
        assert "فشل الاستعادة" not in page

        with app.app_context():
            assert ProjectMember.query.filter_by(project_id=pid).count() == 3
            inspection = SiteInspection.query.filter_by(
                project_id=pid, serial="SIR-000001").one()
            assert isinstance(inspection.created_at, date)
            assert inspection.test_type == "cube 7d"
            assert RFI.query.filter_by(project_id=pid).count() == 1
            assert CostVariance.query.filter_by(
                project_id=pid, serial="CVR-000001").count() == 1
            assert Project.query.count() == 2
            assert Project.query.filter_by(
                name="Alpha Tower").one().location == "Riyadh"

    def test_import_is_idempotent_and_replace_purges_stale_rows(
            self, app, backup_client, tmp_path):
        from app.extensions import db
        from app.ops.models import ProjectMember, RFI
        pid = _project_id(app, "Alpha Tower")
        login_as(backup_client, "t_owner")
        backup_client.post(f"/projects/{pid}/backup")
        archive = _backup_files(tmp_path)[0]
        with app.app_context():
            stale = RFI(project_id=pid, user_id=1, serial="RFI-STALE-0001",
                        subject="row that must not survive a replace",
                        question="stale?")
            db.session.add(stale)
            db.session.commit()
        payload = archive.read_bytes()
        for _ in range(2):
            r = backup_client.post(f"/projects/{pid}/backup/import", data={
                "backup_file": (io.BytesIO(payload), archive.name)})
            assert r.status_code == 302
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "تم استعادة المشروع «Alpha Tower»" in page
        with app.app_context():
            assert ProjectMember.query.filter_by(project_id=pid).count() == 3
            assert RFI.query.filter_by(project_id=pid).count() == 1
            assert RFI.query.filter_by(serial="RFI-STALE-0001").count() == 0

    def test_import_of_minimal_valid_archive_succeeds(self, app, backup_client,
                                                      tmp_path):
        from app.extensions import db
        from app.models import Project
        from app.ops.models import ProjectMember, SiteInspection
        pid = _project_id(app, "Alpha Tower")
        with app.app_context():
            for member in ProjectMember.query.filter_by(project_id=pid).all():
                db.session.delete(member)
            for row in SiteInspection.query.filter_by(project_id=pid).all():
                db.session.delete(row)
            db.session.get(Project, pid).location = "DRIFTED"
            db.session.commit()
        archive = tmp_path / "minimal.zip"
        _minimal_project_archive(archive, pid)
        login_as(backup_client, "t_owner")
        r = backup_client.post(f"/projects/{pid}/backup/import", data={
            "backup_file": (io.BytesIO(archive.read_bytes()), archive.name)})
        assert r.status_code == 302
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "تم استعادة المشروع «Alpha Tower» — projects: 0, " \
               "project_members: 0, report_templates: 0, dynamic_fields: 0, " \
               "report_submissions: 0, legacy_reports: 0, site_inspections: 0, " \
               "material_submittals: 0, rfis: 0, cost_variances: 0, " \
               "progress_billings: 0, subcontractor_performances: 0, " \
               "daily_site_reports: 0, variation_orders: 0, " \
               "safety_reports: 0, attachments: 0" in page
        with app.app_context():
            # an archive with no rows restores nothing
            assert Project.query.filter_by(name="Alpha Tower").one().location \
                == "DRIFTED"
            assert ProjectMember.query.filter_by(project_id=pid).count() == 0
            assert SiteInspection.query.count() == 0

    def test_import_refused_for_plain_project_member(self, app, backup_client,
                                                     tmp_path):
        pid = _project_id(app, "Alpha Tower")
        archive = tmp_path / "minimal.zip"
        _minimal_project_archive(archive, pid)
        login_as(backup_client, "t_eng")
        backup_client.post(f"/projects/{pid}/backup/import", data={
            "backup_file": (io.BytesIO(archive.read_bytes()), archive.name)})
        page = backup_client.get(f"/projects/{pid}").get_data(as_text=True)
        assert "إدارة النسخ الاحتياطي مقصورة على مالك المشروع." in page
        assert _backup_files(tmp_path) == []

    def test_import_of_unlinked_project_is_404(self, app, backup_client,
                                               tmp_path):
        pid = _project_id(app, "Beta Hospital")
        archive = tmp_path / "minimal.zip"
        _minimal_project_archive(archive, pid)
        login_as(backup_client, "t_eng")
        r = backup_client.post(f"/projects/{pid}/backup/import", data={
            "backup_file": (io.BytesIO(archive.read_bytes()), archive.name)})
        assert r.status_code == 404
        assert "الصفحة غير موجودة" in r.get_data(as_text=True)
