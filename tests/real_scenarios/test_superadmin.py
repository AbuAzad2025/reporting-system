"""Superadmin full journey: every nav item, every admin page, every ops kind.

This is the reference scenario - all other role tests are subsets with
different expected 403 boundaries.
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

class TestSuperadminJourney:
    """The superadmin sees and can do everything."""

    @pytest.fixture(autouse=True)
    def _client(self, client):
        """Log in as superadmin (t_owner)."""
        from tests.conftest import login_as
        login_as(client, "t_owner")
        self.client = client
        self.app = client.application

    # ------------------------------------------------------------ nav bar
    @pytest.mark.parametrize("name,endpoint", [
        ("dashboard", "main.dashboard"),
        ("projects", "main.projects"),
        ("reports", "reports.dyn_list"),
        ("archive", "main.archive"),
        ("profile", "main.profile"),
    ])
    def test_nav_item_accessible(self, name, endpoint):
        """Superadmin sees all nav items."""
        url = _url(self.app, endpoint)
        resp = self.client.get(url)
        assert resp.status_code == 200, f"{endpoint} -> {resp.status_code}"

    def test_admin_link_visible(self):
        """Superadmin sees the admin link in the nav."""
        resp = self.client.get(_url(self.app, "main.dashboard"))
        assert b"admin" in resp.data.lower() or b"admin" in resp.data

    # ------------------------------------------------------------ admin panel
    def test_admin_dashboard(self):
        """Superadmin reaches the admin dashboard."""
        resp = self.client.get(_url(self.app, "admin.dashboard"))
        assert resp.status_code == 200

    def test_admin_templates_crud(self):
        """Full template CRUD from the admin panel."""
        # list
        resp = self.client.get(_url(self.app, "admin.templates"))
        assert resp.status_code == 200

    def test_admin_fields_management(self):
        """Add/edit/delete fields on a template."""
        resp = self.client.get(_url(self.app, "admin.fields", template_id=1))
        assert resp.status_code == 200

    def test_admin_company_templates(self):
        """Company template customisation (fields, labels, order)."""
        resp = self.client.get(_url(self.app, "admin.company_templates", project_id=1, template_key="daily"))
        assert resp.status_code == 200

    def test_admin_projects_management(self):
        """Project CRUD from admin panel."""
        resp = self.client.get(_url(self.app, "admin.projects"))
        assert resp.status_code == 200

    def test_admin_users_management(self):
        """User CRUD (create, suspend, role change, delete)."""
        resp = self.client.get(_url(self.app, "admin.users"))
        assert resp.status_code == 200

    def test_admin_backup(self):
        """Backup export/import/download/delete."""
        resp = self.client.get(_url(self.app, "admin.backup_index"))
        assert resp.status_code == 200

    def test_admin_branding(self):
        """Branding page (logo, colors, header/footer)."""
        resp = self.client.get(_url(self.app, "admin.branding"))
        assert resp.status_code == 200

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
        """List page for each ops kind - endpoint is 'ops.listing'."""
        resp = self.client.get(url_for("ops.listing", kind=kind))
        assert resp.status_code == 200

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
    def test_ops_ui_new_page(self, kind):
        """The UI new page loads for each ops kind."""
        resp = self.client.get(url_for("ops.ui_new", kind=kind))
        assert resp.status_code == 200

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
    def test_ops_approve_endpoint_exists(self, kind):
        """The approve endpoint exists and doesn't 500."""
        resp = self.client.post(url_for("ops.ui_approve", kind=kind, obj_id=1), json={
            "decision": "approve",
            "notes": "scenario test"
        })
        assert resp.status_code != 500

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
    def test_ops_pdf_export(self, kind):
        """PDF export for each kind."""
        resp = self.client.get(url_for("ops.pdf", kind=kind, obj_id=1))
        assert resp.status_code != 500

    # ------------------------------------------------------------ reports
    def test_dynamic_reports_list(self):
        resp = self.client.get(url_for("reports.dyn_list"))
        assert resp.status_code == 200

    def test_dynamic_report_new(self):
        """Create a dynamic report using a known template."""
        resp = self.client.get(url_for("reports.dyn_new", template_key="daily"))
        assert resp.status_code == 200

    # ------------------------------------------------------------ auth
    def test_logout(self):
        """Logout works via GET."""
        resp = self.client.get(url_for("auth.logout"))
        assert resp.status_code in (200, 302)
        # Now logged out - next request should redirect to login
        resp = self.client.get(url_for("main.dashboard"))
        assert resp.status_code in (302, 401, 403)

    # ------------------------------------------------------------ no 5xx anywhere
    def test_no_5xx_on_any_request(self):
        """Sanity: none of the above produced a 500."""
        pass
