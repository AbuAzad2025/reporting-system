"""Roles granted a permission the routes will not honour.

This is a discrepancy report, written as a test so that it cannot rot quietly.

ROLE_PERMISSIONS in app/models.py grants approve_reports to project_director
and senior_consultant. The /ops approval route also carries

    @roles_required_json("admin", "superadmin", "project_manager")

and roles_required_json widens "admin" to those three and no further. Both
guards must pass, so the two roles are refused by the API route while holding a
permission that says they may approve. The UI route has no role gate, only
@permission_required("approve_reports"), so it admits them. The same person is
therefore told yes on one screen and no on the other.

Nothing here decides which side is right. Widening the route makes a project
director able to approve anything on any tenant they can reach, which is a
deliberate change to who holds that power; dropping the permission makes the
map honest and is the narrower fix. That is a decision for whoever owns the
policy, so the test states the conflict and asserts only that it has not been
resolved by accident.

When one side is changed, this test fails and says which way it moved.
"""
import pytest

from tests.real_scenarios.conftest import (ROLE_PERMISSIONS,
                                            APPROVE_ROLE_GATE,
                                            role_has_perm)

#: roles holding approve_reports but outside the route's role gate
ORPHANED = {
    "project_director",
    "senior_consultant",
}


def test_the_conflict_is_still_exactly_the_one_we_found():
    """Guard against the test going stale in either direction.

    If someone widens the gate to include project_director, or drops
    approve_reports from senior_consultant, the set changes and this fails -
    which is the point. It fails because the disagreement was resolved on
    purpose rather than by accident, and the fix should delete or rewrite
    this file at the same time.
    """
    granted_but_gated_out = {
        role for role, perms in ROLE_PERMISSIONS.items()
        if "approve_reports" in perms and role not in APPROVE_ROLE_GATE
    }
    assert granted_but_gated_out == ORPHANED, (
        f"the approve_reports conflict changed. Now the roles holding the "
        f"permission while being outside the route gate are "
        f"{sorted(granted_but_gated_out)}, expected {sorted(ORPHANED)}")


@pytest.mark.parametrize("role", sorted(ORPHANED))
def test_the_permission_map_alone_would_admit_them(client, app, role):
    """Both halves of the conflict, checked from the code rather than assumed.

    The map says yes. The route says no. A reviewer reading either one in
    isolation would reach the opposite conclusion, which is what makes this
    worth a test.
    """
    assert role_has_perm(role, "approve_reports") is True
    assert role in ROLE_PERMISSIONS, f"{role} is not a known role"
    assert role not in APPROVE_ROLE_GATE, (
        f"{role} is now in the route gate, so it can approve; the conflict this "
        f"file documents has been resolved and the file should be deleted")
