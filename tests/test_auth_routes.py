"""Tests for auth/routes.py — full coverage."""
import pytest
from flask import url_for


class TestAuthLogin:

    def test_login_get_shows_form(self, client):
        r = client.get("/auth/login")
        assert r.status_code == 200

    def test_login_post_success(self, client, app):
        with app.app_context():
            from app.models import User
            u = User(username="testuser", email="test@test.com", full_name="Test User Full Name",
                     role="site_engineer")
            u.set_password("password123")
            from app.extensions import db
            db.session.add(u)
            db.session.commit()

        r = client.post("/auth/login", data={
            "username": "testuser",
            "password": "password123"
        }, follow_redirects=True)
        assert r.status_code == 200
        assert "مرحباً".encode() in r.data

    def test_login_post_invalid_credentials(self, client):
        r = client.post("/auth/login", data={
            "username": "nonexistent",
            "password": "wrongpass"
        })
        assert r.status_code == 200
        assert "غير صحيحة".encode() in r.data

    def test_login_post_inactive_user(self, app):
        with app.app_context():
            from app.models import User
            from app.extensions import db
            u = User(username="inactive", email="inactive@test.com", full_name="Inactive User Full Name",
                     role="site_engineer", is_active=False)
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()

        with app.test_client() as c:
            r = c.post("/auth/login", data={"username": "inactive", "password": "pass123"})
            assert r.status_code == 200
            assert "إيقاف هذا الحساب".encode() in r.data


class TestAuthRegister:

    def test_register_get_shows_form(self, client):
        r = client.get("/auth/register")
        assert r.status_code == 200

    def test_register_post_valid_first_user_becomes_superadmin(self, client, app):
        with app.app_context():
            from app.models import User
            from app.extensions import db
            db.session.query(User).delete()
            db.session.commit()

        r = client.post("/auth/register", data={
            "username": "firstuser",
            "email": "first@test.com",
            "full_name": "First User Full Name Here",
            "password": "password123",
            "confirm": "password123",
            "role": "site_engineer",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            from app.models import User
            u = User.query.filter_by(username="firstuser").first()
            assert u is not None
            assert u.role == "superadmin"

    def test_register_post_valid_regular_user(self, client, app):
        with app.app_context():
            from app.models import User
            from app.extensions import db
            if User.query.count() == 0:
                u = User(username="existing", email="exist@test.com", full_name="Existing User Full Name",
                         role="site_engineer")
                u.set_password("pass123")
                db.session.add(u)
                db.session.commit()

        r = client.post("/auth/register", data={
            "username": "newuser",
            "email": "new@test.com",
            "full_name": "New User Full Name Here",
            "password": "password123",
            "confirm": "password123",
            "role": "site_engineer",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            from app.models import User
            u = User.query.filter_by(username="newuser").first()
            assert u is not None
            assert u.role != "superadmin"

    def test_register_post_invalid_short_full_name(self, client):
        r = client.post("/auth/register", data={
            "username": "user1",
            "email": "a@b.com",
            "full_name": "Short",
            "password": "password123",
            "confirm": "password123",
        })
        assert r.status_code == 200
        assert "رباعي".encode() in r.data or "أربعة".encode() in r.data

    def test_register_post_short_username(self, client):
        r = client.post("/auth/register", data={
            "username": "ab",
            "email": "a@b.com",
            "full_name": "Full Name Four Parts",
            "password": "password123",
            "confirm": "password123",
        })
        assert r.status_code == 200
        assert "3 أحرف".encode() in r.data

    def test_register_post_invalid_email(self, client):
        r = client.post("/auth/register", data={
            "username": "user1",
            "email": "invalid-email",
            "full_name": "Full Name Four Parts",
            "password": "password123",
            "confirm": "password123",
        })
        assert r.status_code == 200
        assert "غير صالح".encode() in r.data

    def test_register_post_short_password(self, client):
        r = client.post("/auth/register", data={
            "username": "user1",
            "email": "a@b.com",
            "full_name": "Full Name Four Parts",
            "password": "123",
            "confirm": "123",
        })
        assert r.status_code == 200
        assert "6 أحرف".encode() in r.data

    def test_register_post_password_mismatch(self, client):
        r = client.post("/auth/register", data={
            "username": "user1",
            "email": "a@b.com",
            "full_name": "Full Name Four Parts",
            "password": "password123",
            "confirm": "different",
        })
        assert r.status_code == 200
        assert "غير متطابق".encode() in r.data

    def test_register_post_duplicate_username(self, client, app):
        with app.app_context():
            from app.models import User
            from app.extensions import db
            u = User(username="taken", email="taken@test.com", full_name="Taken User Full Name",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()

        r = client.post("/auth/register", data={
            "username": "taken",
            "email": "different@test.com",
            "full_name": "Another Full Name Here",
            "password": "password123",
            "confirm": "password123",
        })
        assert r.status_code == 200
        assert "مسجل مسبقاً".encode() in r.data

    def test_register_post_duplicate_email(self, client, app):
        with app.app_context():
            from app.models import User
            from app.extensions import db
            u = User(username="existing", email="taken@test.com", full_name="Existing Full Name Here",
                     role="site_engineer")
            u.set_password("pass123")
            db.session.add(u)
            db.session.commit()

        r = client.post("/auth/register", data={
            "username": "different",
            "email": "taken@test.com",
            "full_name": "Another Full Name Here",
            "password": "password123",
            "confirm": "password123",
        })
        assert r.status_code == 200
        assert "مسجل مسبقاً".encode() in r.data


class TestAuthLogout:

    def test_logout_redirects_to_login(self, client):
        r = client.get("/auth/logout", follow_redirects=True)
        assert r.status_code == 200
        # Should redirect to login page (has login form)
        assert "تسجيل الدخول".encode() in r.data or "login".encode() in r.data