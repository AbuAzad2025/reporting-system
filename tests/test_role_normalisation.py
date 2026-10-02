"""There is one definition of what a role value means.

Four normalisers existed and they disagreed about the only question that
matters for access control: what an unrecognised role is. Two of them coerced
it to `site_engineer`, two passed the raw string through.

That disagreement was mostly invisible because both readings deny a mistyped
role - `is_admin` is False either way, and the gate decorators coerce before
comparing. The risk was not a hole that existed; it was a fifth caller
inheriting the permissive reading without anyone deciding which reading was
intended. So the value is now defined once, fail-closed, in
`app.models.normalise_role`, and these tests pin that down.

The behavioural-equivalence tests matter as much as the unification: they
assert that every role the system knows still resolves to itself, and that the
roles which were only ever reachable through a gate still are.
"""
import pytest

from app.models import (FALLBACK_ROLE, LEGACY_ROLE_MAP, MANAGER_ROLES,
                        ROLE_KEYS, User, normalise_role)
from app.ops import isolation as isolation_module
from app.ops.models import comment_party
from app.utils import decorators as decorators_module


class TestOneDefinition:
    def test_the_three_callers_are_the_same_function(self, app):
        """The properties, the gates and the tenant scope read one value.

        Checked by output rather than by identity: three wrappers delegating to
        one function is the shape we want, and three wrappers delegating to
        three functions is not distinguishable by ``is`` once they are wrapped.
        """
        for role in ROLE_KEYS + ["user", "typo", "", None]:
            expected = normalise_role(role)
            assert decorators_module.norm_role(role) == expected
            assert isolation_module._norm_role(
                type("U", (), {"role": role})()) == expected

    def test_a_known_role_is_itself(self, app):
        for role in ROLE_KEYS:
            assert normalise_role(role) == role

    def test_the_legacy_alias_still_resolves(self, app):
        assert LEGACY_ROLE_MAP == {"user": "site_engineer"}
        assert normalise_role("user") == "site_engineer"

    def test_an_unknown_role_fails_closed(self, app):
        for value in ("typo", "", None, "SUPERADMIN", "admin "):
            assert normalise_role(value) == FALLBACK_ROLE

    def test_the_fallback_is_not_itself_privileged(self, app):
        """Falling back to site_engineer must not fall back to power."""
        assert FALLBACK_ROLE == "site_engineer"
        assert FALLBACK_ROLE not in MANAGER_ROLES

    def test_no_module_carries_its_own_legacy_map(self, app):
        """The duplicate that started this is gone."""
        import inspect
        for module in (isolation_module, decorators_module):
            source = inspect.getsource(module)
            assert '{"user": "site_engineer"}' not in source, (
                f"{module.__name__} defines its own legacy-role map again")


class TestNoBehaviourChanged:
    """A gate must not admit or refuse anything it did not before."""

    def test_every_privileged_role_is_still_privileged(self, app):
        # is_platform_manager is checked with a stand-in because it takes the
        # user. has_role reads flask_login's current_user, so the gate side is
        # exercised through real logins in the end-to-end test below and in
        # test_rbac.py rather than with a fake object.
        for role in ("superadmin", "admin", "project_manager",
                     "project_director"):
            user = type("U", (), {"role": role, "is_authenticated": True})()
            assert isolation_module.is_platform_manager(user) is True
            assert normalise_role(role) in MANAGER_ROLES

    def test_every_unprivileged_role_is_still_unprivileged(self, app):
        for role in ("qa_qc_inspector", "senior_consultant",
                     "procurement_officer", "safety_officer",
                     "site_engineer", "user", "typo"):
            user = type("U", (), {"role": role, "is_authenticated": True})()
            assert isolation_module.is_platform_manager(user) is False

    def test_an_anonymous_user_is_not_a_manager(self, app):
        user = type("U", (), {"role": "superadmin", "is_authenticated": False})()
        assert isolation_module.is_platform_manager(user) is False

    def test_user_properties_agree_with_the_gates(self, app):
        """The divergence this fixes: the same user read two ways.

        ``User.norm_role`` used to pass an unknown role through while the gate
        decorators coerced it, so a mistyped role had two identities depending on
        which one asked.
        """
        with app.app_context():
            for role in ROLE_KEYS + ["user", "typo"]:
                user = User(username="probe", email="probe@t.com",
                            full_name="Probe Probe Probe Probe", role=role)
                user.set_password("pw12345")
                assert user.norm_role == normalise_role(role)
                assert user.is_admin == (normalise_role(role) in MANAGER_ROLES
                                         or role == "admin")
                assert user.is_superadmin == (normalise_role(role) == "superadmin")


class TestCommentParty:
    """The fourth copy of the alias map, folded in."""

    def test_supervision_and_execution_sides_are_unchanged(self, app):
        from app.ops.models import SUPERVISION_ROLES
        for role in SUPERVISION_ROLES:
            assert comment_party(role) == "consultant"
        for role in ("site_engineer", "safety_officer", "typo", "", None):
            assert comment_party(role) == "contractor"

    def test_the_legacy_alias_is_resolved_before_the_side_is_chosen(self, app):
        # "user" is site_engineer, which is the execution side. Resolving it
        # matters because the two copies disagreed on whether it was mapped.
        assert comment_party("user") == comment_party("site_engineer")


class TestNoSilentPrivilegeChange:
    def test_a_user_with_a_typo_in_the_role_gets_no_admin_pages(self, app):
        """End to end: the mistyped-role user is refused, as before."""
        from app.extensions import db
        from tests.conftest import login_as
        with app.app_context():
            user = User(username="typo_role", email="typo@t.com",
                        full_name="مستخدم خطأNc", role="typo")
            user.set_password("pw12345")
            db.session.add(user)
            db.session.commit()
            assert user.is_admin is False
        client = app.test_client()
        login_as(client, "typo_role")
        assert client.get("/admin/users").status_code in (302, 403)
