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

        can_manage_templates() = norm_role in {"superadmin", "admin"}
        The nav wraps the admin link in {%- if current_user.can_manage_templates() %}.
        """
        should_have = self.role in {"superadmin", "admin"}
        resp = self.client.get(url_for("main.dashboard"))
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
        resp = self.client.get(url_for("ops.listing", kind=kind))
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
        resp = self.client.get(url_for("ops.ui_new", kind=kind))
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
        resp = self.client.get(url_for("ops.pdf", kind=kind, obj_id=1))
        assert resp.status_code == expected, f"ops.pdf[{kind}] -> {resp.status_code} (expected {expected})"

    # ------------------------------------------------------------ reports
    def test_dynamic_reports_list(self):
        """Reports list - API route, denied = 403."""
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "view_reports") else 403
        resp = self.client.get(url_for("reports.dyn_list"))
        assert resp.status_code == expected, f"reports.dyn_list -> {resp.status_code} (expected {expected})"

    def test_dynamic_report_new(self):
        """Dynamic report new - API route, denied = 403."""
        from tests.real_scenarios.conftest import role_has_perm
        expected = 200 if role_has_perm(self.role, "create_reports") else 403
        resp = self.client.get(url_for("reports.dyn_new", template_key="daily"))
        assert resp.status_code == expected, f"reports.dyn_new -> {resp.status_code} (expected {expected})"

    # ------------------------------------------------------------ auth
    def test_logout(self):
        resp = self.client.get(url_for("auth.logout"))
        assert resp.status_code in (200, 302)
        # After logout, next request should redirect
        resp = self.client.get(url_for("main.dashboard"))
        assert resp.status_code in (302, 401, 403)
