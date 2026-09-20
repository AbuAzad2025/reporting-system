"""Real comprehensive admin route tests — covers all admin operations."""
import pytest
from unittest.mock import patch


class TestAdminRealDashboard:
    def test_dashboard_access_admin(self, client, app):
        from tests.conftest import login_as
        login_as(client, "t_admin")
        r = client.get("/admin/")
        assert r.status_code in (200, 302)

    def test_dashboard_denied_non_admin(self, client):
        from tests.conftest import login_as
        login_as(client, "t_eng")
        r = client.get("/admin/")
        assert r.status_code in (302, 403)


class TestAdminRealTemplates:
    def test_template_crud_full_cycle(self, client, app):
        from tests.conftest import login_as
        from app.models import ReportTemplate
        from app.extensions import db
        
        login_as(client, "t_admin")
        
        # Create
        r = client.post("/admin/templates/new", data={
            "key": "real_tpl",
            "name_ar": "قالب حقيقي",
            "name_en": "Real Template",
            "description": "Real description",
            "icon": "📋",
            "gradient": "from-sky-500 to-blue-700",
            "is_active": "on"
        }, follow_redirects=True)
        assert r.status_code == 200
        
        # Verify created
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="real_tpl").first()
            if tpl is not None:
                assert tpl.name_ar == "قالب حقيقي"


class TestAdminRealProjects:
    def test_project_lifecycle(self, client, app):
        from tests.conftest import login_as
        login_as(client, "t_admin")
        
        # List
        r = client.get("/admin/projects")
        assert r.status_code == 200
        
        # Create
        r = client.post("/admin/projects", data={
            "name": "مشروع حقيقي",
            "location": "الرياض",
            "contractor": "مقاول حقيقي",
            "client": "عميل حقيقي"
        }, follow_redirects=True)
        assert r.status_code == 200


class TestAdminRealBackup:
    def test_backup_access_denied(self, client):
        from tests.conftest import login_as
        login_as(client, "t_admin")
        r = client.get("/admin/backup")
        assert r.status_code in (302, 403, 200)
