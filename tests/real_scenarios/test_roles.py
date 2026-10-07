"""Concrete role journey tests.

Each class inherits from RoleJourney and specifies its role/username.
The base class runs all the common tests with role-appropriate expectations.
"""
import pytest

from tests.real_scenarios.base import RoleJourney


class TestSuperadminJourney(RoleJourney):
    """Superadmin: full access to everything."""
    role = "superadmin"
    username = "t_owner"


class TestAdminJourney(RoleJourney):
    """Admin: everything except superadmin-only (none in current model)."""
    role = "admin"
    username = "t_admin"


class TestProjectManagerJourney(RoleJourney):
    """Project Manager: can manage projects, approve, but not manage users."""
    role = "project_manager"
    username = "t_pm"


class TestSiteEngineerJourney(RoleJourney):
    """Site Engineer: basic reports access, create own, view archive."""
    role = "site_engineer"
    username = "t_eng"


class TestSafetyOfficerJourney(RoleJourney):
    """Safety Officer: same perms as site_engineer in current model."""
    role = "safety_officer"
    username = "t_safety"


class TestAdminNonSuperadminJourney(RoleJourney):
    """Admin but not superadmin - verifies no superadmin-only gaps.

    Currently the model has no superadmin-only permissions beyond manage_users
    which admin also has. This test exists to catch future divergences.
    """
    role = "admin"
    username = "t_admin"

    def test_no_superadmin_only_gaps(self):
        """Admin should have all permissions superadmin has except manage_settings.

        Superadmin has manage_settings (platform settings) which admin doesn't.
        This is the only intentional gap. This test exists to catch future
        unintended divergences.
        """
        from tests.real_scenarios.conftest import ROLE_PERMISSIONS
        super_perms = set(ROLE_PERMISSIONS["superadmin"])
        admin_perms = set(ROLE_PERMISSIONS["admin"])
        diff = super_perms - admin_perms
        assert diff <= {"manage_settings"}, f"Superadmin has extra perms: {diff}"
