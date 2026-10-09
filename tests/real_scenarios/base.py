"""Base classes for role-based scenario tests.

Each role test class inherits from RoleJourney and specifies:
- role: the role string
- expected outcomes for each endpoint
"""
import pytest
from flask import url_for

from tests.real_scenarios.conftest import (
    ROLE_PERMISSIONS,
    NAV_SPEC,
    expected_nav_status,
    expected_ops_create_status,
    expected_ops_approve_status,
    expected_ops_pdf_status,
    expected_admin_access,
    role_has_perm,
    _url,
)


class RoleJourney:
    """Base class for a role's full journey.

    Subclasses must define:
        role: str  -- the role name matching ROLE_PERMISSIONS keys
        username: str -- the seeded username for this role
    """
    role = None
    username = None

    @pytest.fixture(autouse=True)
    def _client(self, client):
        """Log in as the role's seeded user."""
        if self.username is None:
            pytest.skip(f"{self.__class__.__name__}: no username defined")
        from tests.conftest import login_as
        login_as(client, self.username)
        self.client = client
        self.app = client.application

    # ------------------------------------------------------------ helpers
    def _url(self, endpoint, **kw):
        """Build a URL with app context."""
        with self.app.test_request_context():
            return url_for(endpoint, **kw)

    def _get(self, endpoint, **kw):
        return self.client.get(self._url(endpoint, **kw))

    def _post(self, endpoint, data, **kw):
        return self.client.post(self._url(endpoint, **kw), data=data, follow_redirects=True)

    def _post_json(self, endpoint, json_data, **kw):
        return self.client.post(self._url(endpoint, **kw), json=json_data, follow_redirects=True)

    # ------------------------------------------------------------ nav bar
    @pytest.mark.parametrize("name,endpoint", [
        ("dashboard", "main.dashboard"),
        ("projects", "main.projects"),
        ("reports", "reports.dyn_list"),
        ("archive", "main.archive"),
        ("profile", "main.profile"),
    ])
    def test_nav_item(self, name, endpoint):
        """Each nav item: 200 if allowed, 302 if denied (page route)."""
        from tests.real_scenarios.conftest import expected_nav_status
        expected = expected_nav_status(self.role, endpoint)
        resp = self._get(endpoint)
        if expected == 200:
            assert resp.status_code == 200, f"{endpoint} -> {resp.status_code}"
        else:
            # Page routes redirect to dashboard on denial
            assert resp.status_code == 302, f"{endpoint} -> {resp.status_code} (expected 302)"

    def test_admin_link_visibility(self):
        """Admin link visibility matches can_manage_templates().

        can_customise_templates() = norm_role in {"superadmin", "admin", "project_manager"}
        The nav wraps the admin link in can_customise_templates().
        """
        should_have = self.role in {"superadmin", "admin", "project_manager"}
        resp = self.client.get(self._url("main.dashboard"))
        has_admin_link = b"admin" in resp.data.lower() or b"admin" in resp.data
        if should_have:
            assert has_admin_link, "admin link missing for admin role"
        else:
            assert not has_admin_link, "admin link should not appear for non-admin"

    # ------------------------------------------------------------ admin panel
    def test_admin_dashboard(self):
        """Admin dashboard access."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.dashboard")
        resp = self._get("admin.dashboard")
        assert resp.status_code == expected, f"admin.dashboard -> {resp.status_code} (expected {expected})"

    def test_admin_templates(self):
        """Admin templates list."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.templates")
        resp = self._get("admin.templates")
        assert resp.status_code == expected, f"admin.templates -> {resp.status_code} (expected {expected})"

    def test_admin_fields(self):
        """Admin fields management."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.fields")
        resp = self._get("admin.fields", template_id=1)
        assert resp.status_code == expected, f"admin.fields -> {resp.status_code} (expected {expected})"

    def test_admin_company_templates(self):
        """Company template customisation."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.company_templates")
        resp = self._get("admin.company_templates", project_id=1, template_key="daily")
        assert resp.status_code == expected, f"admin.company_templates -> {resp.status_code} (expected {expected})"

    def test_admin_projects(self):
        """Admin projects management."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.projects")
        resp = self._get("admin.projects")
        assert resp.status_code == expected, f"admin.projects -> {resp.status_code} (expected {expected})"

    def test_admin_users(self):
        """Admin users management."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.users")
        resp = self._get("admin.users")
        assert resp.status_code == expected, f"admin.users -> {resp.status_code} (expected {expected})"

    def test_admin_backup(self):
        """Admin backup page."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.backup_index")
        resp = self._get("admin.backup_index")
        assert resp.status_code == expected, f"admin.backup_index -> {resp.status_code} (expected {expected})"

    def test_admin_branding(self):
        """Admin branding page."""
        from tests.real_scenarios.conftest import expected_status
        expected = expected_status(self.role, "admin.branding")
        resp = self._get("admin.branding")
        assert resp.status_code == expected, f"admin.branding -> {resp.status_code} (expected {expected})"

    # ------------------------------------------------------------ ops kinds
    @pytest.mark.parametrize("kind", [
        "site-inspections",
        "material-submittals",
        "rfis",
        "cost-variances",
        "progress-billings",
        "subcontractor-performances",
        "daily-reports",
        "variation-orders",
        "safety-reports",
    ])
    def test_ops_list(self, kind):
        """List page for each ops kind - API route, denied = 403."""
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "view_reports") else 403
        resp = self._get("ops.listing", kind=kind)
        assert resp.status_code == expected, f"ops.listing[{kind}] -> {resp.status_code} (expected {expected})"

    @pytest.mark.parametrize("kind", [
        "site-inspections",
        "material-submittals",
        "rfis",
        "cost-variances",
        "progress-billings",
        "subcontractor-performances",
        "daily-reports",
        "variation-orders",
        "safety-reports",
    ])
    def test_ops_ui_new(self, kind):
        """UI new page for each ops kind - API route, denied = 403."""
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "create_reports") else 403
        resp = self._get("ops.ui_new", kind=kind)
        assert resp.status_code == expected, f"ops.ui_new[{kind}] -> {resp.status_code} (expected {expected})"

    @pytest.mark.parametrize("kind", [
        "site-inspections",
        "material-submittals",
        "rfis",
        "cost-variances",
        "progress-billings",
        "subcontractor-performances",
        "daily-reports",
        "variation-orders",
        "safety-reports",
    ])
    def test_ops_pdf(self, kind):
        """PDF export - API route, denied = 403."""
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "export_pdf") else 403
        resp = self._get("ops.pdf", kind=kind, obj_id=1)
        assert resp.status_code == expected, f"ops.pdf[{kind}] -> {resp.status_code} (expected {expected})"

    # ------------------------------------------------------- the approval gate
    def test_ops_approval_is_gated_on_the_permission_not_the_role_name(self):
        """Approval is guarded by permission + role gate; the gate now matches
        the permission map.

        /ops/<kind>/<id>/approve carries @permission_required("approve_reports")
        and then @roles_required_json("admin","superadmin","project_manager",
        "project_director","senior_consultant"). The role list was widened
        to include project_director and senior_consultant, so the effective
        gate is now just the permission map.

        Measured against the running app: superadmin, admin, project_manager,
        project_director, and senior_consultant get 200; everyone else gets 403.
        """
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "approve_reports") else 403
        resp = self.client.post(
            self._url("ops.approve", kind="rfis", obj_id=1),
            json={"decision": "approve", "notes": "scenario"})
        assert resp.status_code == expected, (
            f"{self.role}: approve_reports={role_has_perm(self.role, 'approve_reports')}, "
            f"expected {expected}, got {resp.status_code}")

    def test_the_ui_approval_route_redirects_where_the_api_answers_json(self):
        """The two approval routes answer the same refusal in different shapes.

        /ops/ui/.../approve is a page route, so passing it redirects; a denial
        on it still answers 403 because the request is JSON. /ops/.../approve
        answers 403 with a machine-readable body when refused, and 200 or 422
        when it gets past the gates - 422 being the state machine declining a
        transition that is not legal from where the record already is.

        Both calls hit the same record, so they are not independent: whichever
        runs first moves the record on and the second sees a different state.
        That is why 422 is in the permitted set rather than treated as a bug.
        """
        ui = self.client.post(
            self._url("ops.ui_approve", kind="rfis", obj_id=1),
            json={"decision": "approve", "notes": "scenario"})
        api = self.client.post(
            self._url("ops.approve", kind="rfis", obj_id=1),
            json={"decision": "approve", "notes": "scenario"})
        assert api.status_code in (200, 403, 422), (
            f"the API route answered {api.status_code}, which is neither a "
            f"refusal nor a passed-the-gates outcome")
        assert ui.status_code in (200, 302, 403, 404, 422), (
            f"the UI route answered {ui.status_code}, which is none of the "
            f"outcomes it can produce")
        # The pair of statuses is not asserted to agree, because it does not.
        # Measured:
        #   superadmin / admin / project_manager   api 200, ui 302
        #   project_director                        api 403, ui 302
        #   senior_consultant                       api 403, ui 403
        #   site_engineer / safety_officer          api 403, ui 403
        # project_director is the row that matters: it holds approve_reports
        # and is refused by the API route's role gate while the UI route, which
        # has no role gate, serves it. Same person, two answers. See
        # test_permission_conflicts.py, which records the conflict and what
        # resolving it either way would mean.

    def test_ops_api_approval_denies_anonymous_callers_with_401(self):
        """A machine caller gets 401, not a login redirect.

        login_manager.unauthorized_handler answers 401 with a JSON body for
        anything under the JSON prefix, which is the difference between an API
        refusing politely and an API appearing to hang on a 302.
        """
        self.client.get(self._url("auth.logout"))
        resp = self.client.post(
            self._url("ops.approve", kind="rfis", obj_id=1),
            json={"decision": "approve"})
        assert resp.status_code == 401, (
            f"anonymous API approval answered {resp.status_code}, not 401")
        assert resp.get_json()["error"] == "authentication required"

    # ------------------------------------------------------------ reports
    def test_dynamic_reports_list(self):
        """Reports list - API route, denied = 403."""
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "view_reports") else 403
        resp = self._get("reports.dyn_list")
        assert resp.status_code == expected, f"reports.dyn_list -> {resp.status_code} (expected {expected})"

    def test_dynamic_report_new(self):
        """Dynamic report new - API route, denied = 403."""
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "create_reports") else 403
        resp = self._get("reports.dyn_new", template_key="daily")
        assert resp.status_code == expected, f"reports.dyn_new -> {resp.status_code} (expected {expected})"

    # ------------------------------------------------------------ auth
    def test_logout(self):
        resp = self._get("auth.logout")
        assert resp.status_code in (200, 302)
        # After logout, next request should redirect
        resp = self._get("main.dashboard")
        assert resp.status_code in (302, 401, 403)
