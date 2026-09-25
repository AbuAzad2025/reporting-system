"""Hardening contract for app/auth/routes.py + app/utils/decorators.py.

Complements (does not repeat) tests/test_auth_routes.py (auth happy paths) and
tests/test_rbac.py (role/permission matrix).  The focus here is the *negative*
contract, asserted on payloads rather than bare status codes:

  * _is_safe_next allow/deny matrix: relative targets, empty target,
    scheme-relative ``//evil``, backslash variants, absolute http(s) URLs
  * login / register / logout while a session already exists
  * remember-me: only the literal ``on`` arms it, cookie teardown on logout
  * ``next=`` is honoured for safe relative targets and dropped otherwise
  * roles_required / any_permission_required / permission_required:
    401 (unauthenticated) vs 403 (authenticated but not authorised)
  * JSON vs HTML denial shape: exact bodies, exact redirect target,
    exact flash text + category
"""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from flask import g, get_flashed_messages, session
from flask_login.utils import decode_cookie

from app.auth.routes import SELF_REGISTER_ROLES, _is_safe_next
from app.utils.decorators import (any_permission_required, has_role, norm_role,
                                  permission_required, roles_required,
                                  superadmin_required)
from tests.conftest import login_as

# ---- shared expectations (the machine/UI contract) ----------------------
DASHBOARD = "/dashboard"
LOGIN = "/auth/login"
REMEMBER_COOKIE = "remember_token"

JSON_401 = {"error": "authentication required"}
JSON_403 = {"error": "insufficient permissions"}

FLASH_LOGIN_REQUIRED = "يرجى تسجيل الدخول أولاً للوصول إلى هذه الصفحة."
FLASH_NO_PERMISSION = "لا تملك صلاحية الوصول إلى هذه الصفحة."

#: markers rendered by templates/base.html once per queued flash message
FLASH_MARKER = b'class="flash-msg'

ALLOWED = "ALLOWED-BY-DECORATOR"

#: a valid registration body (role is deliberately left to each test)
VALID_REGISTRATION = {
    "username": "hardening_new_user",
    "email": "hardening.new@example.com",
    "full_name": "خالد سعيد محمود عبدالله",
    "password": "password123",
    "confirm": "password123",
    "role": "site_engineer",
}


# ---- small helpers -------------------------------------------------------
def _user_snapshot(app, **match):
    """Read a user row inside an app context; return plain values."""
    from app.models import User
    with app.app_context():
        u = User.query.filter_by(**match).first()
        if u is None:
            return None
        return {"id": u.id, "username": u.username, "email": u.email,
                "role": u.role, "is_superadmin": u.is_superadmin,
                "hash": u.password_hash}


def _user_count(app):
    from app.models import User
    with app.app_context():
        return User.query.count()


def _user_id(app, username):
    snap = _user_snapshot(app, username=username)
    assert snap is not None, f"fixture user {username!r} missing"
    return snap["id"]


def _gated(factory, *args):
    """Wrap a sentinel view with a decorator factory (roles_required(...))."""
    @factory(*args)
    def view():
        return ALLOWED
    return view


def _gated_by(decorator):
    """Wrap a sentinel view with an already-built decorator (superadmin_required)."""
    @decorator
    def view():
        return ALLOWED
    return view


@contextmanager
def _request_as(app, path, username=None, **ctx_kwargs):
    """Test request context optionally carrying a logged-in session user."""
    uid = _user_id(app, username) if username else None
    # pytest-flask keeps one app context alive per test, so push a fresh one
    # here: flask-login caches ``current_user`` on ``g`` and a stale entry
    # would silently authenticate the next simulated request.
    with app.app_context():
        with app.test_request_context(path, **ctx_kwargs):
            g.pop("_login_user", None)
            if uid is not None:
                session["_user_id"] = str(uid)
                session["_fresh"] = True
            yield


def _remember_headers(response):
    return [c for c in response.headers.getlist("Set-Cookie")
            if c.startswith(REMEMBER_COOKIE + "=")]


def _is_future(moment):
    """True for a cookie expiry that lies in the future (tz-agnostic)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment > datetime.now(timezone.utc)


# ======================================================================
# 1. _is_safe_next — open-redirect guard
# ======================================================================
class TestIsSafeNext:
    """app/auth/routes.py::_is_safe_next"""

    @pytest.mark.parametrize("target", [
        "/",
        "/dashboard",
        "/ops/cost-variances",
        "/ops/cost-variances?page=2",
        "/reports/dyn/12",
        "/admin/users?next=%2Fops",
    ])
    def test_relative_targets_are_allowed(self, target):
        assert _is_safe_next(target) is True

    @pytest.mark.parametrize("target", ["", None])
    def test_empty_target_is_rejected(self, target):
        assert _is_safe_next(target) is False

    @pytest.mark.parametrize("target", [
        "//evil.example",              # scheme-relative, cross-host
        "//evil.example/deep/link",
        "//user@evil.example",
        "//evil.example:8080/x",
    ])
    def test_scheme_relative_target_is_rejected(self, target):
        assert _is_safe_next(target) is False

    @pytest.mark.parametrize("target", [
        "/\\evil.example",             # leading slash + backslash
        "\\\\evil.example",            # UNC-ish, leading backslashes
        "/ops\\..\\evil.example",      # backslash inside an otherwise-safe path
        "\\\\evil.example\\share",
    ])
    def test_backslash_variants_are_rejected(self, target):
        assert _is_safe_next(target) is False

    @pytest.mark.parametrize("target", [
        "http://evil.example/x",
        "https://evil.example",
        "http://evil.example/x?a=1",
        "http:/evil.example",          # scheme without authority
        "https://evil.example",
    ])
    def test_absolute_http_targets_are_rejected(self, target):
        assert _is_safe_next(target) is False

    @pytest.mark.parametrize("target", [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "mailto:a@b.example",
    ])
    def test_other_url_schemes_are_rejected(self, target):
        assert _is_safe_next(target) is False

    @pytest.mark.parametrize("target", [
        "dashboard",                   # no leading slash
        "reports/dyn/1",
        "?next=/ops",
        "#anchor",
        "%2F%2Fevil.example",         # encoded scheme-relative prefix
    ])
    def test_targets_without_leading_slash_are_rejected(self, target):
        assert _is_safe_next(target) is False

    @pytest.mark.parametrize("target", [
        "https://EVIL.example",       # host case must not matter
        "HTTPS://evil.example",
        "http:%2F%2Fevil.example",     # scheme without //, still absolute
        "/\t/evil.example",           # tab is stripped by urlsplit
    ])
    def test_case_and_encoding_variants_are_rejected(self, target):
        assert _is_safe_next(target) is False


# ======================================================================
# 2. next= wiring: safe target honoured, unsafe target dropped
# ======================================================================
class TestLoginNextRedirect:
    """app/auth/routes.py::login (the `nxt` branch)"""

    @pytest.mark.parametrize("nxt", [
        "/ops/cost-variances",
        "/ops/cost-variances?page=2",
        "/admin/users",
    ])
    def test_safe_relative_next_is_honoured(self, client, nxt):
        r = client.post("/auth/login", query_string={"next": nxt},
                        data={"username": "t_eng", "password": "pw12345"})
        assert r.status_code == 302
        assert r.headers["Location"] == nxt

    @pytest.mark.parametrize("nxt", [
        "//evil.example",              # scheme-relative
        "/\\evil.example",             # backslash variant
        "\\\\evil.example",
        "http://evil.example/x",       # absolute http
        "https://evil.example/login",
        "javascript:alert(1)",
        "dashboard",                   # not root-relative
        "",                            # empty -> falsy
    ])
    def test_unsafe_next_falls_back_to_dashboard(self, client, nxt):
        r = client.post("/auth/login", query_string={"next": nxt},
                        data={"username": "t_eng", "password": "pw12345"})
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD
        assert "evil.example" not in r.headers["Location"]

    def test_missing_next_falls_back_to_dashboard(self, client):
        r = client.post("/auth/login",
                        data={"username": "t_eng", "password": "pw12345"})
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD

    def test_unsafe_next_is_ignored_when_credentials_are_wrong(self, client):
        r = client.post("/auth/login", query_string={"next": "//evil.example"},
                        data={"username": "t_eng", "password": "wrong-password"})
        assert r.status_code == 200
        assert "بيانات الدخول غير صحيحة".encode("utf-8") in r.data
        # no redirect header at all on a failed login
        assert "Location" not in r.headers

    def test_unsafe_next_never_reaches_the_dashboard_request(self, client):
        r = client.post("/auth/login", query_string={"next": "//evil.example"},
                        data={"username": "t_eng", "password": "pw12345"})
        assert r.headers["Location"] == DASHBOARD
        # following the redirect stays on the app origin
        page = client.get(r.headers["Location"])
        assert page.status_code == 200
        assert "evil.example" not in page.get_data(as_text=True)


# ======================================================================
# 3. authenticated-session behaviour of the auth blueprint
# ======================================================================
class TestLoginWhileAuthenticated:
    """app/auth/routes.py::login — authenticated short-circuit"""

    def test_get_login_page_while_authenticated_redirects(self, client):
        login_as(client, "t_eng")
        r = client.get(LOGIN)
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD
        assert b'name="password"' not in r.data   # the form is never served

    def test_get_login_page_with_next_while_authenticated_ignores_next(self, client):
        login_as(client, "t_eng")
        r = client.get(LOGIN + "?next=/admin/users")
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD

    def test_post_login_while_authenticated_keeps_the_existing_user(self, client):
        login_as(client, "t_eng")
        r = client.post(LOGIN, data={"username": "t_admin", "password": "pw12345"})
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD
        # t_eng is still the session owner: the admin-only page stays denied
        denied = client.get("/admin/users")
        assert denied.status_code == 302
        assert denied.headers["Location"] == DASHBOARD
        page = client.get(DASHBOARD)
        assert FLASH_NO_PERMISSION.encode("utf-8") in page.data
        # handing the client over to t_admin does unlock it
        login_as(client, "t_admin")
        assert client.get("/admin/users").status_code == 200


class TestRegisterWhileAuthenticated:
    """app/auth/routes.py::register — authenticated short-circuit"""

    def test_get_register_while_authenticated_redirects(self, client):
        login_as(client, "t_eng")
        r = client.get("/auth/register")
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD

    def test_post_register_while_authenticated_creates_nothing(self, client, app):
        before = _user_count(app)
        login_as(client, "t_eng")
        r = client.post("/auth/register", data=dict(VALID_REGISTRATION))
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD
        assert _user_count(app) == before
        assert _user_snapshot(app, username=VALID_REGISTRATION["username"]) is None


# ======================================================================
# 4. remember-me
# ======================================================================
class TestRememberMeLogin:
    """app/auth/routes.py::login (the `remember` branch)"""

    def test_remember_on_issues_remember_cookie(self, client):
        r = client.post(LOGIN, data={"username": "t_eng", "password": "pw12345",
                                     "remember": "on"})
        assert r.status_code == 302
        assert r.headers["Location"] == DASHBOARD
        headers = _remember_headers(r)
        assert len(headers) == 1, headers
        token = headers[0].split("=", 1)[1].split(";")[0]
        assert len(token) > 10, headers[0]      # signed, never empty
        assert client.get_cookie(REMEMBER_COOKIE) is not None

    def test_omitted_remember_issues_no_cookie(self, client):
        r = client.post(LOGIN, data={"username": "t_eng", "password": "pw12345"})
        assert r.status_code == 302
        assert _remember_headers(r) == []
        assert client.get_cookie(REMEMBER_COOKIE) is None

    @pytest.mark.parametrize("remember", ["off", "true", "1", "yes", "ON", ""])
    def test_only_the_literal_checkbox_value_arms_remember(self, client, remember):
        r = client.post(LOGIN, data={"username": "t_eng", "password": "pw12345",
                                     "remember": remember})
        assert r.status_code == 302
        assert _remember_headers(r) == [], remember
        assert client.get_cookie(REMEMBER_COOKIE) is None

    def test_failed_login_issues_no_remember_cookie(self, client):
        r = client.post(LOGIN, data={"username": "t_eng", "password": "nope",
                                     "remember": "on"})
        assert r.status_code == 200
        assert "بيانات الدخول غير صحيحة".encode("utf-8") in r.data
        assert _remember_headers(r) == []
        assert client.get_cookie(REMEMBER_COOKIE) is None

    def test_remember_cookie_is_bound_to_the_logged_in_user(self, client, app):
        r = client.post(LOGIN, data={"username": "t_eng", "password": "pw12345",
                                     "remember": "on"})
        token = _remember_headers(r)[0].split("=", 1)[1].split(";")[0]
        stored = client.get_cookie(REMEMBER_COOKIE)
        assert stored is not None
        assert stored.value == token
        # a signed token that decodes back to the authenticated user id
        assert decode_cookie(token) == str(_user_id(app, "t_eng"))

    def test_remember_cookies_differ_per_user(self, client):
        first = client.post(LOGIN, data={"username": "t_eng", "password": "pw12345",
                                         "remember": "on"})
        first_token = _remember_headers(first)[0].split("=", 1)[1].split(";")[0]
        client.get("/auth/logout")
        second = client.post(LOGIN, data={"username": "t_admin", "password": "pw12345",
                                          "remember": "on"})
        second_token = _remember_headers(second)[0].split("=", 1)[1].split(";")[0]
        assert decode_cookie(first_token) != decode_cookie(second_token)
        assert client.get_cookie(REMEMBER_COOKIE).value == second_token

    def test_remember_cookie_carries_an_expiry(self, client):
        r = client.post(LOGIN, data={"username": "t_eng", "password": "pw12345",
                                     "remember": "on"})
        header = _remember_headers(r)[0]
        assert "Expires=" in header
        assert "Max-Age=0" not in header
        assert client.get_cookie(REMEMBER_COOKIE).expires > datetime.now(timezone.utc)


# ======================================================================
# 5. logout
# ======================================================================
class TestLogout:
    """app/auth/routes.py::logout"""

    def test_authenticated_logout_clears_session_and_flashes(self, client):
        login_as(client, "t_eng")
        r = client.get("/auth/logout")
        assert r.status_code == 302
        assert r.headers["Location"] == LOGIN
        # the session is gone: the dashboard bounces back to the login page
        after = client.get(DASHBOARD)
        assert after.status_code == 302
        assert after.headers["Location"] == LOGIN
        # the login form is served again with every queued flash, in order:
        # welcome (login) -> logout confirmation -> login-required warning
        page = client.get(LOGIN)
        assert b'name="password"' in page.data
        welcome = "مرحباً".encode("utf-8")
        logout_flash = "تم تسجيل الخروج بنجاح.".encode("utf-8")
        body = page.data
        assert welcome in body and logout_flash in body
        assert FLASH_LOGIN_REQUIRED.encode("utf-8") in body
        assert body.index(welcome) < body.index(logout_flash)
        assert body.index(logout_flash) < body.index(FLASH_LOGIN_REQUIRED.encode("utf-8"))
        assert body.count(FLASH_MARKER) == 3
        # and the flashes are consumed, not replayed on every page
        assert client.get(LOGIN).data.count(FLASH_MARKER) == 0

    def test_authenticated_logout_clears_the_remember_cookie(self, client):
        client.post(LOGIN, data={"username": "t_eng", "password": "pw12345",
                                 "remember": "on"})
        assert client.get_cookie(REMEMBER_COOKIE) is not None
        r = client.get("/auth/logout")
        headers = _remember_headers(r)
        assert len(headers) == 1, headers
        assert headers[0].startswith(REMEMBER_COOKIE + "=;")
        assert "Max-Age=0" in headers[0]
        assert client.get_cookie(REMEMBER_COOKIE) is None
        # a remembered session must not resurrect the user
        assert client.get(DASHBOARD).status_code == 302

    def test_anonymous_logout_redirects_without_confirmation_flash(self, client):
        r = client.get("/auth/logout")
        assert r.status_code == 302
        assert r.headers["Location"] == LOGIN
        page = client.get(LOGIN)
        assert "تم تسجيل الخروج بنجاح.".encode("utf-8") not in page.data
        assert page.data.count(FLASH_MARKER) == 0

    def test_double_logout_flashes_the_confirmation_only_once(self, client):
        login_as(client, "t_eng")
        first = client.get("/auth/logout")
        assert first.headers["Location"] == LOGIN
        second = client.get("/auth/logout")
        assert second.status_code == 302
        assert second.headers["Location"] == LOGIN
        page = client.get(LOGIN)
        assert page.data.count("تم تسجيل الخروج بنجاح.".encode("utf-8")) == 1


# ======================================================================
# 6. register hardening
# ======================================================================
class TestRegisterHardening:
    """app/auth/routes.py::register"""

    def test_successful_registration_redirects_to_login(self, client, app):
        r = client.post("/auth/register", data=dict(VALID_REGISTRATION))
        assert r.status_code == 302
        assert r.headers["Location"] == LOGIN
        created = _user_snapshot(app, username=VALID_REGISTRATION["username"])
        assert created is not None
        assert created["role"] == "site_engineer"
        assert created["email"] == VALID_REGISTRATION["email"]
        page = client.get(LOGIN)
        assert "تم إنشاء الحساب بنجاح.".encode("utf-8") in page.data

    @pytest.mark.parametrize("requested", [
        "superadmin", "admin", "project_director", "bogus_role", "",
    ])
    def test_role_field_cannot_escalate_privileges(self, client, app, requested):
        r = client.post("/auth/register",
                        data=dict(VALID_REGISTRATION, role=requested))
        assert r.status_code == 302
        assert r.headers["Location"] == LOGIN
        created = _user_snapshot(app, username=VALID_REGISTRATION["username"])
        assert created["role"] == "site_engineer"
        assert created["is_superadmin"] is False

    def test_seeded_platform_means_no_superadmin_promotion(self, client, app):
        # conftest already owns the first slot, so the platform-owner
        # branch must not fire for a self-registered account
        r = client.post("/auth/register", data=dict(VALID_REGISTRATION))
        assert r.status_code == 302
        created = _user_snapshot(app, username=VALID_REGISTRATION["username"])
        assert created["role"] == "site_engineer"

    def test_duplicate_username_and_email_report_both_and_create_nothing(self, client, app):
        before = _user_count(app)
        r = client.post("/auth/register", data=dict(
            VALID_REGISTRATION,
            username="t_eng",                       # seeded username
            email="t_admin@t.com",                  # seeded email
        ))
        assert r.status_code == 200                 # re-rendered, not redirected
        assert b'name="confirm"' in r.data          # the register form is served
        body = r.data
        assert body.count("مسجل مسبقاً".encode("utf-8")) == 2
        assert body.index("اسم المستخدم مسجل مسبقاً".encode("utf-8")) < \
            body.index("البريد الإلكتروني مسجل مسبقاً".encode("utf-8"))
        assert _user_count(app) == before
        assert _user_snapshot(app, username="t_eng")["email"] == "t_eng@t.com"
        assert _user_snapshot(app, email="t_admin@t.com")["username"] == "t_admin"

    def test_duplicate_email_is_case_insensitive(self, client, app):
        before = _user_count(app)
        r = client.post("/auth/register", data=dict(
            VALID_REGISTRATION, email="T_ADMIN@T.COM"))
        assert r.status_code == 200
        assert "البريد الإلكتروني مسجل مسبقاً".encode("utf-8") in r.data
        assert _user_count(app) == before

    def test_all_validation_errors_accumulate_in_one_response(self, client, app):
        before = _user_count(app)
        r = client.post("/auth/register", data={
            "username": "ab",                       # too short
            "email": "not-an-email",                # malformed
            "full_name": "Short Name",              # fewer than four parts
            "password": "123",                      # too short
            "confirm": "456",                       # mismatch
            "role": "site_engineer",
        })
        assert r.status_code == 200
        body = r.data
        for fragment in (
                "يرجى إدخال الاسم الرباعي الكامل",    # full name
                "اسم المستخدم يجب أن يكون 3 أحرف",    # username
                "البريد الإلكتروني غير صالح",           # email
                "كلمة المرور يجب أن تكون 8 أحرف",       # password
                "تأكيد كلمة المرور غير متطابق",          # confirm
        ):
            assert fragment.encode("utf-8") in body, fragment
        assert body.count(FLASH_MARKER) == 5
        assert _user_count(app) == before
        assert _user_snapshot(app, username="ab") is None

    def test_password_minimum_is_enforced(self, client, app):
        r = client.post("/auth/register", data=dict(
            VALID_REGISTRATION, password="1234567", confirm="1234567"))
        assert r.status_code == 200
        assert "كلمة المرور يجب أن تكون 8 أحرف".encode("utf-8") in r.data
        assert _user_snapshot(app, username=VALID_REGISTRATION["username"]) is None

    def test_role_choices_expose_only_self_registerable_roles(self, client):
        body = client.get("/auth/register").get_data(as_text=True)
        for role in SELF_REGISTER_ROLES:
            assert 'value="%s"' % role in body, role
        for forbidden in ("admin", "superadmin", "project_director",
                          "qa_qc_inspector", "senior_consultant",
                          "procurement_officer"):
            assert 'value="%s"' % forbidden not in body, forbidden


# ======================================================================
# 7. roles_required — 401 vs 403
# ======================================================================
class TestRolesRequired:
    """app/utils/decorators.py::roles_required"""

    @pytest.mark.parametrize("path", [
        "/ops/cost-variances", "/reports/dyn/1", "/admin/api/users",
    ])
    def test_unauthenticated_api_caller_gets_401_json(self, app, path):
        view = _gated(roles_required, "admin")
        with _request_as(app, path):
            response, status = view()
            assert status == 401
            assert response.get_json() == JSON_401
            assert response.mimetype == "application/json"

    def test_unauthenticated_page_caller_gets_login_redirect(self, app):
        view = _gated(roles_required, "admin")
        with _request_as(app, "/admin/users", method="POST", data={"x": "1"}):
            response = view()
            assert response.status_code == 302
            assert response.headers["Location"] == DASHBOARD
            assert get_flashed_messages(with_categories=True) == [
                ("warning", FLASH_LOGIN_REQUIRED)]

    def test_authenticated_wrong_role_gets_403_json(self, app):
        view = _gated(roles_required, "admin")
        with _request_as(app, "/admin/api/users", username="t_eng"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403
            assert get_flashed_messages() == []   # no page flash for API callers

    def test_authenticated_wrong_role_page_denial_flashes_danger(self, app):
        view = _gated(roles_required, "admin")
        with _request_as(app, "/admin/users", username="t_eng"):
            response = view()
            assert response.status_code == 302
            assert response.headers["Location"] == DASHBOARD
            assert get_flashed_messages(with_categories=True) == [
                ("danger", FLASH_NO_PERMISSION)]

    @pytest.mark.parametrize("username", ["t_owner", "t_admin", "t_pm"])
    def test_legacy_admin_gate_admits_the_manager_tier(self, app, username):
        view = _gated(roles_required, "admin")
        with _request_as(app, "/admin/api/users", username=username):
            assert view() == ALLOWED

    @pytest.mark.parametrize("username", ["t_eng", "t_eng2", "t_safety"])
    def test_legacy_admin_gate_denies_the_field_tier(self, app, username):
        view = _gated(roles_required, "admin")
        with _request_as(app, "/admin/api/users", username=username):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    @pytest.mark.parametrize("username,role", [
        ("t_owner", "superadmin"), ("t_admin", "admin"), ("t_pm", "project_manager"),
    ])
    def test_exact_role_gate_admits_only_the_listed_role(self, app, username, role):
        allowed = _gated(roles_required, role)
        with _request_as(app, "/ops/registry", username=username):
            assert allowed() == ALLOWED
        other = _gated(roles_required, "qa_qc_inspector")
        with _request_as(app, "/ops/registry", username=username):
            response, status = other()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_empty_role_gate_denies_everyone(self, app):
        view = _gated(roles_required)
        with _request_as(app, "/ops/registry", username="t_owner"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_superadmin_alias_denies_admins(self, app):
        view = _gated_by(superadmin_required)
        with _request_as(app, "/ops/registry", username="t_admin"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_superadmin_alias_admits_the_owner(self, app):
        view = _gated_by(superadmin_required)
        with _request_as(app, "/ops/registry", username="t_owner"):
            assert view() == ALLOWED

    def test_legacy_user_role_is_normalized_before_comparison(self, app):
        with app.app_context():
            from app.extensions import db
            from app.models import User
            legacy = User(username="t_legacy", email="t_legacy@t.com",
                          full_name="مستخدم قديم باسم رباعي كامل", role="user")
            legacy.set_password("pw12345")
            db.session.add(legacy)
            db.session.commit()
        engineer_view = _gated(roles_required, "site_engineer")
        with _request_as(app, "/ops/registry", username="t_legacy"):
            assert engineer_view() == ALLOWED
        admin_view = _gated(roles_required, "admin")
        with _request_as(app, "/admin/api/users", username="t_legacy"):
            response, status = admin_view()
            assert status == 403
            assert response.get_json() == JSON_403


# ======================================================================
# 8. any_permission_required — 401 vs 403
# ======================================================================
class TestAnyPermissionRequired:
    """app/utils/decorators.py::any_permission_required"""

    def test_unauthenticated_api_caller_gets_401_json(self, app):
        view = _gated(any_permission_required, "edit_own_reports")
        with _request_as(app, "/ops/cost-variances/1"):
            response, status = view()
            assert status == 401
            assert response.get_json() == JSON_401

    def test_unauthenticated_page_caller_gets_login_redirect(self, app):
        view = _gated(any_permission_required, "edit_own_reports")
        with _request_as(app, "/archive"):
            response = view()
            assert response.status_code == 302
            assert response.headers["Location"] == DASHBOARD
            assert get_flashed_messages(with_categories=True) == [
                ("warning", FLASH_LOGIN_REQUIRED)]

    def test_single_matching_permission_passes(self, app):
        view = _gated(any_permission_required, "edit_own_reports",
                      "edit_all_reports")
        with _request_as(app, "/ops/cost-variances/1", username="t_eng"):
            assert view() == ALLOWED

    def test_any_semantics_admit_a_match_on_the_last_perm(self, app):
        # t_eng lacks edit_all_reports but owns delete_own_reports
        view = _gated(any_permission_required, "edit_all_reports",
                      "delete_own_reports")
        with _request_as(app, "/ops/cost-variances/1", username="t_eng"):
            assert view() == ALLOWED

    @pytest.mark.parametrize("username", ["t_safety", "t_eng2"])
    def test_role_without_any_matching_permission_gets_403(self, app, username):
        # neither safety_officer nor site_engineer may approve/manage users
        view = _gated(any_permission_required, "approve_reports", "manage_users")
        with _request_as(app, "/ops/cost-variances/1", username=username):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_unauthenticated_caller_is_checked_before_permissions(self, app):
        # 401 wins over 403 even for a permission nobody holds
        view = _gated(any_permission_required, "manage_settings", "no_such_perm")
        with _request_as(app, "/ops/cost-variances/1"):
            response, status = view()
            assert status == 401
            assert response.get_json() == JSON_401

    def test_unknown_permission_names_fail_closed(self, app):
        view = _gated(any_permission_required, "manage_settings", "no_such_perm")
        with _request_as(app, "/ops/cost-variances/1", username="t_eng"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_empty_permission_list_fails_closed(self, app):
        view = _gated(any_permission_required)
        with _request_as(app, "/ops/cost-variances/1", username="t_owner"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_superadmin_passes_admin_only_permission(self, app):
        view = _gated(any_permission_required, "manage_settings")
        with _request_as(app, "/ops/cost-variances/1", username="t_owner"):
            assert view() == ALLOWED

    def test_admin_lacks_manage_settings(self, app):
        view = _gated(any_permission_required, "manage_settings")
        with _request_as(app, "/ops/cost-variances/1", username="t_admin"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_page_denial_flashes_danger_and_json_denial_does_not(self, app):
        view = _gated(any_permission_required, "edit_all_reports")
        with _request_as(app, "/archive", username="t_safety"):
            response = view()
            assert response.status_code == 302
            assert response.headers["Location"] == DASHBOARD
            assert get_flashed_messages(with_categories=True) == [
                ("danger", FLASH_NO_PERMISSION)]
        with _request_as(app, "/ops/cost-variances/1", username="t_safety"):
            denied, status = view()
            assert status == 403
            assert denied.get_json() == JSON_403
            assert get_flashed_messages() == []


# ======================================================================
# 9. permission_required — ALL semantics
# ======================================================================
class TestPermissionRequired:
    """app/utils/decorators.py::permission_required"""

    def test_unauthenticated_api_caller_gets_401_json(self, app):
        view = _gated(permission_required, "view_reports")
        with _request_as(app, "/ops/cost-variances"):
            response, status = view()
            assert status == 401
            assert response.get_json() == JSON_401

    def test_missing_one_of_the_required_perms_is_403(self, app):
        # t_eng has view_reports but not manage_users
        view = _gated(permission_required, "view_reports", "manage_users")
        with _request_as(app, "/ops/cost-variances", username="t_eng"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403

    def test_all_required_perms_granted_passes(self, app):
        view = _gated(permission_required, "view_reports", "manage_users")
        with _request_as(app, "/ops/cost-variances", username="t_admin"):
            assert view() == ALLOWED

    def test_single_perm_pass_and_fail(self, app):
        denied = _gated(permission_required, "approve_reports")
        with _request_as(app, "/ops/cost-variances/1", username="t_safety"):
            response, status = denied()
            assert status == 403
            assert response.get_json() == JSON_403
        allowed = _gated(permission_required, "approve_reports")
        with _request_as(app, "/ops/cost-variances/1", username="t_admin"):
            assert allowed() == ALLOWED


# ======================================================================
# 10. denial shape: JSON vs HTML
# ======================================================================
class TestDenialResponseShape:
    """app/utils/decorators.py::_deny / _is_json_request"""

    @pytest.mark.parametrize("path", [
        "/ops/cost-variances", "/reports/dyn/1", "/admin/api/users",
    ])
    def test_api_prefixes_deny_with_json_body(self, app, path):
        view = _gated(any_permission_required, "manage_settings")
        with _request_as(app, path, username="t_safety"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403
            assert response.headers["Content-Type"].startswith("application/json")
            assert response.get_data() == b'{"error":"insufficient permissions"}\n'

    def test_page_path_deny_is_a_bare_redirect(self, app):
        view = _gated(any_permission_required, "manage_settings")
        with _request_as(app, "/admin/users", username="t_safety"):
            response = view()
            assert response.status_code == 302
            assert response.headers["Location"] == DASHBOARD
            assert response.headers["Content-Type"].startswith("text/html")
            assert b'"error"' not in response.get_data()

    def test_api_prefix_requires_the_trailing_slash(self, app):
        # "/ops" is not a JSON API prefix: page-style denial
        view = _gated(any_permission_required, "manage_settings")
        with _request_as(app, "/ops", username="t_safety"):
            response = view()
            assert response.status_code == 302
            assert response.headers["Location"] == DASHBOARD
            assert get_flashed_messages(with_categories=True) == [
                ("danger", FLASH_NO_PERMISSION)]

    def test_json_content_type_outside_prefix_still_denies_with_json(self, app):
        view = _gated(any_permission_required, "manage_settings")
        with _request_as(app, "/custom/page", method="POST", json={"a": 1},
                         username="t_safety"):
            response, status = view()
            assert status == 403
            assert response.get_json() == JSON_403
            assert get_flashed_messages() == []

    def test_unauthenticated_json_denial_body_is_the_401_contract(self, app):
        view = _gated(roles_required, "superadmin")
        with _request_as(app, "/custom/page", method="POST", json={}):
            response, status = view()
            assert status == 401
            assert response.get_json() == JSON_401
            assert response.get_data() == b'{"error":"authentication required"}\n'
            assert get_flashed_messages() == []


# ======================================================================
# 11. role helpers
# ======================================================================
class TestRoleHelpers:
    """app/utils/decorators.py::norm_role / has_role"""

    @pytest.mark.parametrize("raw,expected", [
        ("site_engineer", "site_engineer"),
        ("project_manager", "project_manager"),
        ("superadmin", "superadmin"),
        ("user", "site_engineer"),        # LEGACY_ROLE_MAP
        (None, "site_engineer"),
        ("", "site_engineer"),
        ("root", "site_engineer"),        # unknown -> fail-closed default
        ("SUPERADMIN", "site_engineer"),   # roles are case-sensitive
    ])
    def test_norm_role_falls_back_to_site_engineer(self, raw, expected):
        assert norm_role(raw) == expected

    def test_has_role_requires_an_authenticated_user(self, app):
        with _request_as(app, "/ops/registry"):
            assert has_role("site_engineer") is False
            assert has_role() is False

    def test_has_role_uses_the_normalized_role(self, app):
        with _request_as(app, "/ops/registry", username="t_eng"):
            assert has_role("site_engineer") is True
            assert has_role("admin", "site_engineer") is True
            assert has_role("admin") is False

    def test_has_role_with_no_roles_requested_is_false(self, app):
        with _request_as(app, "/ops/registry", username="t_owner"):
            assert has_role() is False
            assert has_role("superadmin") is True
