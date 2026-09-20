"""Tests for admin/routes.py — comprehensive coverage."""
import pytest
from tests.conftest import login_as
from flask import url_for
from app.models import User, Project, ReportTemplate, DynamicField, ReportSubmission, Report, ROLES, FIELD_TYPES
from app.extensions import db


class TestAdminDashboard:

    def test_dashboard_requires_login(self, client):
        r = client.get("/admin/")
        assert r.status_code == 302

    def test_dashboard_requires_admin_role(self, client, app):
        with app.app_context():
            # Create non-admin user
            u = User(username="regular", email="reg@test.com", full_name="Regular User Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()

        login_as(client, "t_eng")
        r = client.get("/admin/")
        assert r.status_code == 403

    def test_dashboard_shows_stats(self, client, app):
        with app.app_context():
            db.session.query(User).delete()
            u = User(username="admin", email="admin@test.com", full_name="Admin User Full Name",
                     role="superadmin")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()

        login_as(client, "t_admin")
        r = client.get("/admin/")
        assert r.status_code == 200
        assert "users".encode() in r.data or "users".encode() in r.data.lower()

    def test_dashboard_chart_data(self, client, app):
        with app.app_context():
            # Create some submissions for chart
            from app.models import Project, ReportTemplate, ReportSubmission
            p = Project(name="Test Project")
            db.session.add(p)
            db.session.commit()

            tpl = ReportTemplate(key="test", name_ar="اختبار", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()

            sub = ReportSubmission(project_id=p.id, template_id=tpl.id, submitted_by_id=1)
            db.session.add(sub)
            db.session.commit()

        login_as(client, "t_admin")
        r = client.get("/admin/")
        assert r.status_code == 200


class TestAdminTemplates:

    def test_templates_list_requires_admin(self, client):
        r = client.get("/admin/templates")
        assert r.status_code == 302

    def test_templates_list_shows(self, client, app):
        login_as(client, "t_admin")
        r = client.get("/admin/templates")
        assert r.status_code == 200

    def test_template_new_get(self, client):
        login_as(client, "t_admin")
        r = client.get("/admin/templates/new")
        assert r.status_code == 200

    def test_template_new_post_valid(self, client, app):
        login_as(client, "t_admin")
        r = client.post("/admin/templates/new", data={
            "key": "test_template",
            "name_ar": "قالب اختبار",
            "name_en": "Test Template",
            "description": "Test description",
            "icon": "📋",
            "gradient": "from-sky-500 to-blue-700",
            "is_active": "on"
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            tpl = ReportTemplate.query.filter_by(key="test_template").first()
            assert tpl is not None
            assert tpl.name_ar == "قالب اختبار"

    def test_template_new_post_duplicate_key(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="existing", name_ar="موجود", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()

        login_as(client, "t_admin")
        r = client.post("/admin/templates/new", data={
            "key": "existing",
            "name_ar": "جديد",
        })
        assert r.status_code == 200
        assert "مفتاح".encode() in r.data

    def test_template_new_missing_fields(self, client):
        login_as(client, "t_admin")
        r = client.post("/admin/templates/new", data={})
        assert r.status_code == 200
        assert "مطلوبان".encode() in r.data

    def test_template_edit_get(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="edit_test", name_ar="تعديل", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.get(f"/admin/templates/{tid}/edit")
        assert r.status_code == 200

    def test_template_edit_post(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="edit2", name_ar="أصلي", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/edit", data={
            "name_ar": "معدل",
            "name_en": "Edited",
            "description": "New desc",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            tpl = db.session.get(ReportTemplate, tid)
            assert tpl.name_ar == "معدل"

    def test_template_delete_system_blocked(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="system", name_ar="نظام", is_system=True, created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/delete", follow_redirects=True)
        assert r.status_code == 200
        assert "لا يمكن حذف".encode() in r.data

    def test_template_delete_with_submissions_blocked(self, client, app):
        with app.app_context():
            p = Project(name="P")
            db.session.add(p)
            db.session.commit()
            tpl = ReportTemplate(key="with_su", name_ar=".encode()مع تقديم", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            sub = ReportSubmission(project_id=p.id, template_id=tpl.id, submitted_by_id=1)
            db.session.add(sub)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/delete", follow_redirects=True)
        assert r.status_code == 200
        assert "لا يمكن حذف".encode() in r.data

    def test_template_delete_success(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="deletable", name_ar="قابل للحذف", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/delete", follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(ReportTemplate, tid) is None

    def test_reset_defaults(self, client):
        login_as(client, "t_admin")
        r = client.post("/admin/templates/reset-defaults", follow_redirects=True)
        assert r.status_code == 200


class TestAdminFields:

    def test_fields_get(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="fields_tpl", name_ar="حقول", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.get(f"/admin/templates/{tid}/fields")
        assert r.status_code == 200

    def test_field_add_valid(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="fields2", name_ar="حقول2", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/fields", data={
            "field_key": "test_field",
            "label_ar": "حقل اختبار",
            "field_type": "text",
            "required": "on",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            f = DynamicField.query.filter_by(template_id=tid, field_key="test_field").first()
            assert f is not None
            assert f.required is True

    def test_field_add_missing_key(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="f3", name_ar="ف3", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/fields", data={
            "label_ar": "بدون مفتاح",
        })
        assert r.status_code == 200
        assert "مفتاح".encode() in r.data

    def test_field_add_invalid_type(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="f4", name_ar="ف4", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/fields", data={
            "field_key": "test",
            "label_ar": "اختبار",
            "field_type": "invalid_type",
        })
        assert r.status_code == 200
        assert "غير صالح".encode() in r.data

    def test_field_add_duplicate_key(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="f5", name_ar="ف5", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            f = DynamicField(template_id=tpl.id, field_key="dup", label_ar="أصلي",
                             field_type="text", position=1)
            db.session.add(f)
            db.session.commit()
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/templates/{tid}/fields", data={
            "field_key": "dup",
            "label_ar": "مكرر",
            "field_type": "text",
        })
        assert r.status_code == 200
        assert "مفتاح".encode() in r.data

    def test_field_delete(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="f6", name_ar="ف6", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            f = DynamicField(template_id=tpl.id, field_key="todelete", label_ar="للحذف",
                             field_type="text", position=1)
            db.session.add(f)
            db.session.commit()
            fid = f.id
            tid = tpl.id

        login_as(client, "t_admin")
        r = client.post(f"/fields/{fid}/delete", follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(DynamicField, fid) is None

    def test_field_move_up(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="move", name_ar="نقل", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            f1 = DynamicField(template_id=tpl.id, field_key="a", label_ar="أ", field_type="text", position=1)
            f2 = DynamicField(template_id=tpl.id, field_key="", label_ar=".encode()ب", field_type="text", position=2)
            db.session.add_all([f1, f2])
            db.session.commit()
            fid1, fid2 = f1.id, f2.id

        login_as(client, "t_admin")
        r = client.post(f"/fields/{fid1}/move/down", follow_redirects=True)
        assert r.status_code == 200

    def test_field_column_add_valid(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="tbl", name_ar="جدول", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            f = DynamicField(template_id=tpl.id, field_key="table", label_ar="جدول", field_type="table", position=1)
            db.session.add(f)
            db.session.commit()
            fid = f.id

        login_as(client, "t_admin")
        r = client.post(f"/fields/{fid}/columns", data={
            "col_key": "col1",
            "col_label": "عمود 1",
            "col_type": "text",
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_field_column_add_invalid_type(self, client, app):
        with app.app_context():
            tpl = ReportTemplate(key="tbl2", name_ar="جدول2", created_by_id=1)
            db.session.add(tpl)
            db.session.commit()
            f = DynamicField(template_id=tpl.id, field_key="t", label_ar="ت", field_type="text", position=1)
            db.session.add(f)
            db.session.commit()
            fid = f.id

        login_as(client, "t_admin")
        r = client.post(f"/fields/{fid}/columns", data={
            "col_key": "c",
            "col_label": "ع",
            "col_type": "invalid",
        })
        assert r.status_code == 200
        assert "text".encode() in r.data  # falls back to text


class TestAdminProjects:

    def test_projects_list(self, client):
        login_as(client, "t_admin")
        r = client.get("/admin/projects")
        assert r.status_code == 200

    def test_project_create_valid(self, client, app):
        login_as(client, "t_admin")
        r = client.post("/admin/projects", data={
            "name": "مشروع جديد",
            "location": "الرياض",
            "contractor": "مقاول",
            "client": "عميل",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            p = Project.query.filter_by(name="مشروع جديد").first()
            assert p is not None

    def test_project_create_duplicate(self, client, app):
        with app.app_context():
            p = Project(name="مكرر")
            db.session.add(p)
            db.session.commit()

        login_as(client, "t_admin")
        r = client.post("/admin/projects", data={"name": "مكرر"})
        assert r.status_code == 200
        assert "يوجد مشروع".encode() in r.data

    def test_project_toggle(self, client, app):
        with app.app_context():
            p = Project(name="للتبديل", is_active=True)
            db.session.add(p)
            db.session.commit()
            pid = p.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/projects/{pid}/toggle", follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            p = db.session.get(Project, pid)
            assert p.is_active is False


class TestAdminUsers:

    def test_users_list(self, client):
        login_as(client, "t_admin")
        r = client.get("/admin/users")
        assert r.status_code == 200

    def test_user_role_change_valid(self, client, app):
        with app.app_context():
            u = User(username="touser", email="to@test.com", full_name="To User Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()
            uid = u.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/users/{uid}/role", data={"role": "project_manager"}, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = db.session.get(User, uid)
            assert u.role == "project_manager"

    def test_user_role_change_self_blocked(self, client, app):
        with app.app_context():
            u = User(username="self", email="self@test.com", full_name="Self User Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()
            uid = u.id

        login_as(client, "t_eng")
        r = client.post(f"/admin/users/{uid}/role", data={"role": "admin"}, follow_redirects=True)
        assert r.status_code == 200
        assert "حسابك الخاص".encode() in r.data

    def test_user_role_invalid(self, client, app):
        with app.app_context():
            u = User(username="t2", email="t2@test.com", full_name="Test User Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()
            uid = u.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/users/{u.id}/role", data={"role": "invalid_role"}, follow_redirects=True)
        assert r.status_code == 200
        assert "غير صالح".encode() in r.data

    def test_user_suspend(self, client, app):
        with app.app_context():
            u = User(username="tosuspend", email="suspend@test.com", full_name="Suspend User Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()
            uid = u.id

        login_as(client, "t_admin")
        r = client.post(f"/admin/users/{uid}/suspend", follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = db.session.get(User, uid)
            assert u.is_active is False

    def test_user_delete_superadmin_only(self, client, app):
        with app.app_context():
            u = User(username="todelete", email="del@test.com", full_name="Delete User Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()
            uid = u.id

        # Non-superadmin cannot delete
        login_as(client, "t_admin")
        r = client.post("/admin/users/999/delete", follow_redirects=True)
        assert r.status_code == 403

    def test_user_delete_self_blocked(self, client, app):
        with app.app_context():
            u = User(username="selfdel", email="selfdel@test.com", full_name="Self Delete Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()
            uid = u.id

        login_as(client, "t_eng")
        r = client.post(f"/admin/users/{uid}/delete", follow_redirects=True)
        assert r.status_code == 200
        assert "حسابك الخاص".encode() in r.data


class TestAdminBackup:

    def test_backup_index_superadmin_only(self, client):
        login_as(client, "t_admin")
        r = client.get("/admin/backup")
        assert r.status_code == 403

    def test_backup_export_no_data(self, client, app):
        # superadmin needed
        with app.app_context():
            u = User.query.filter_by(role="superadmin").first()
            if not u:
                u = User(username="super2", email="super2@test.com", full_name="Super Admin Full Name",
                         role="superadmin")
                u.set_password("pass123")
                db.session.add(u)
                db.session.commit()

        login_as(client, "t_owner")
        r = client.post("/admin/backup/export", follow_redirects=True)
        # Should not crash
        assert r.status_code == 200

# Use login_as fixture from conftest.py
