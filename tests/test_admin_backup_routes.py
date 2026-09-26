"""Superadmin-gated platform backup admin routes + project/user admin flashes.

Every assertion checks real state: real DB rows, real ZIP bytes (validated with
``app.services.backup.validate_backup``), real files on disk, or the exact
Arabic flash tuple (category + text) popped out of the session.

The local storage backend is redirected into ``tmp_path`` by monkeypatching
``app.services.storage.BACKUP_LOCAL_DIR`` (the value the routes read at call
time), so no archive or logo ever lands in the repository tree. The admin
routes themselves are never patched.
"""
import io
import json
import os
import zipfile

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models import Project, User
from app.services import storage
from app.services.backup import BACKUP_VERSION, validate_backup
from tests.conftest import login_as

BACKUP_INDEX = "/admin/backup"

FULL_NAMES = {
    "t_owner": "مالك اختبار تجريبي عام",
    "t_admin": "مدير اختبار تجريبي عام",
    "t_pm": "مدير مشروع اختبار عام",
    "t_eng": "مهندس اختبار تجريبي عام",
    "t_eng2": "مهندس ثان اختبار تجريبي",
    "t_safety": "مسؤول سلامة اختبار عام",
}

LOGOUT_FLASH = ("info", "تم تسجيل الخروج بنجاح.")
DENIED_FLASH = ("danger", "لا تملك صلاحية الوصول إلى هذه الصفحة.")
LOGIN_FLASH = ("warning", "يرجى تسجيل الدخول أولاً للوصول إلى هذه الصفحة.")

#: (http method, path) for every superadmin-only platform backup route.
BACKUP_ROUTES = [
    ("get", "/admin/backup"),
    ("post", "/admin/backup/export"),
    ("post", "/admin/backup/import"),
    ("get", "/admin/backup/download/seeded.zip"),
    ("post", "/admin/backup/delete/seeded.zip"),
]


# ------------------------------------------------------------------ helpers
def take_flashes(client):
    """Pop the pending flash messages out of the session as (category, text)."""
    with client.session_transaction() as sess:
        return [tuple(entry) for entry in sess.pop("_flashes", [])]


def login(client, username):
    """Log in and assert the auth flashes, leaving the session flash-free."""
    assert login_as(client, username).status_code == 302
    pending = take_flashes(client)
    assert pending[-1] == ("success", f"مرحباً {FULL_NAMES[username]} 👋")
    assert all(entry == LOGOUT_FLASH for entry in pending[:-1])


def post_flashes(client, path, make_data=None):
    """POST a route, assert the redirect, return its exact flash tuples."""
    kwargs = {} if make_data is None else {"data": make_data()}
    resp = client.post(path, **kwargs)
    assert resp.status_code == 302
    return resp, take_flashes(client)


def post_page(client, path, make_data=None):
    """POST a route and follow the redirect, returning the rendered body."""
    kwargs = {} if make_data is None else {"data": make_data()}
    resp = client.post(path, follow_redirects=True, **kwargs)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def user_id(app, username):
    with app.app_context():
        return User.query.filter_by(username=username).one().id


def make_project(app, name, is_active=True):
    with app.app_context():
        project = Project(name=name, is_active=is_active)
        db.session.add(project)
        db.session.commit()
        return project.id


def project_state(app, name):
    with app.app_context():
        project = Project.query.filter_by(name=name).one()
        return (project.id, project.is_active, project.location,
                project.contractor, project.client, project.logo_path,
                project.logo2_path)


def count_projects(app):
    with app.app_context():
        return Project.query.count()


def png_bytes(size=64):
    """A tiny but real PNG payload (magic bytes + filler)."""
    return b"\x89PNG\r\n\x1a\n" + b"0" * size


def only_backup(directory):
    names = sorted(p.name for p in directory.iterdir())
    assert len(names) == 1, names
    return names[0]


def export_one_backup(client, directory):
    """Run the real export route and return the single archive filename."""
    _, flashes = post_flashes(client, "/admin/backup/export")
    name = only_backup(directory)
    assert flashes == [("success", f"تم إنشاء نسخة احتياطية كاملة: {name}")]
    return name


def platform_archive(projects=(), users=()):
    """A minimal, valid platform-scope backup archive (in-memory bytes)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps({
            "version": BACKUP_VERSION,
            "scope": "platform",
            "project_id": None,
            "created_at": "2026-01-01T00:00:00",
            "generator": "tests/test_admin_backup_routes.py",
        }, ensure_ascii=False))
        archive.writestr("projects.json",
                         json.dumps(list(projects), ensure_ascii=False))
        archive.writestr("users.json",
                         json.dumps(list(users), ensure_ascii=False))
    return buf.getvalue()


RESTORED_PROJECT = {"name": "مشروع مستورد", "location": "الرياض",
                    "contractor": "مقاول مستورد", "client": "عميل مستورد"}
RESTORED_USER = {"username": "t_restored", "email": "t_restored@t.com",
                 "password_hash": "not-a-real-hash",
                 "full_name": "مستخدم مستورد تجريبي", "role": "site_engineer"}

EMPTY_SUMMARY = (
    "project_members: 0, report_templates: 0, dynamic_fields: 0, "
    "report_submissions: 0, legacy_reports: 0, site_inspections: 0, "
    "material_submittals: 0, rfis: 0, cost_variances: 0, progress_billings: 0, "
    "subcontractor_performances: 0, daily_site_reports: 0, "
    "variation_orders: 0, safety_reports: 0, attachments: 0")


# ------------------------------------------------------------------ fixtures
@pytest.fixture()
def backup_dir(tmp_path, monkeypatch):
    """Isolate the local backup backend inside tmp_path."""
    target = tmp_path / "backups"
    monkeypatch.setattr(storage, "BACKUP_LOCAL_DIR", str(target))
    return target


@pytest.fixture()
def broken_backup_dir(tmp_path, monkeypatch):
    """Point the backend at an un-creatable path (parent is a regular file)."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(storage, "BACKUP_LOCAL_DIR", str(blocker / "backups"))
    return blocker


# ------------------------------------------------------------------ listing
class TestBackupIndex:
    def test_listing_renders_empty_state(self, client, backup_dir):
        login(client, "t_owner")
        backup_dir.mkdir(parents=True)
        resp = client.get(BACKUP_INDEX)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "إدارة النسخ الاحتياطي" in body
        assert "لا توجد نسخ احتياطية محفوظة حالياً." in body
        assert backup_dir.is_dir()
        assert list(backup_dir.iterdir()) == []

    def test_listing_renders_stored_archives(self, client, backup_dir):
        login(client, "t_owner")
        name = export_one_backup(client, backup_dir)
        assert storage.list_backups() == [name]
        resp = client.get(BACKUP_INDEX)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert name in body
        assert f"/admin/backup/download/{name}" in body
        assert f"/admin/backup/delete/{name}" in body

    def test_unreachable_storage_flashes_danger(self, client, broken_backup_dir):
        login(client, "t_owner")
        with pytest.raises(OSError):
            os.makedirs(str(broken_backup_dir / "backups"), exist_ok=True)
        resp = client.get(BACKUP_INDEX)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "تعذر جلب قائمة النسخ الاحتياطية. حدّث الصفحة أو تحقق من إعدادات التخزين." in body
        assert "لا توجد نسخ احتياطية محفوظة حالياً." in body


# ------------------------------------------------------------------ export
class TestBackupExport:
    def test_export_writes_valid_platform_archive(self, client, backup_dir):
        login(client, "t_owner")
        resp, flashes = post_flashes(client, "/admin/backup/export")
        assert resp.headers["Location"] == BACKUP_INDEX

        name = only_backup(backup_dir)
        assert name.startswith("azadexa-platform-")
        assert name.endswith(".zip")
        assert flashes == [("success", f"تم إنشاء نسخة احتياطية كاملة: {name}")]

        blob = (backup_dir / name).read_bytes()
        assert blob[:2] == b"PK"
        report = validate_backup(blob)
        assert report["ok"] is True, report["error"]
        assert report["size"] == len(blob)
        assert report["metadata"]["version"] == BACKUP_VERSION
        assert report["metadata"]["scope"] == "platform"
        assert report["metadata"]["project_id"] is None

        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            assert archive.testzip() is None
            members = set(archive.namelist())
            assert {"metadata.json", "users.json", "projects.json",
                    "project_members.json", "report_templates.json",
                    "dynamic_fields.json", "ops_records/rfis.json",
                    "attachments.json"} <= members
            archived_users = json.loads(archive.read("users.json"))
            archived_projects = json.loads(archive.read("projects.json"))
        assert {u["username"] for u in archived_users} >= set(FULL_NAMES)
        assert {p["name"] for p in archived_projects} >= {"Alpha Tower",
                                                          "Beta Hospital"}
        assert storage.download(name) == blob

    def test_export_upload_failure_flashes_danger(self, client, broken_backup_dir):
        login(client, "t_owner")
        resp, flashes = post_flashes(client, "/admin/backup/export")
        assert resp.headers["Location"] == BACKUP_INDEX
        assert flashes == [("danger", "فشل الرفع إلى التخزين. تحقق من الاتصال "
                                     "وإعدادات التخزين ثم أعد المحاولة.")]
        assert not (broken_backup_dir / "backups").exists()

    def test_export_reaches_the_listing_after_success(self, client, backup_dir):
        login(client, "t_owner")
        body = post_page(client, "/admin/backup/export")
        name = only_backup(backup_dir)
        assert f"تم إنشاء نسخة احتياطية كاملة: {name}" in body
        assert name in body


# ------------------------------------------------------------------ import
class TestBackupImport:
    def test_valid_minimal_archive_restores_rows(self, client, app):
        archive = platform_archive(projects=[RESTORED_PROJECT],
                                   users=[RESTORED_USER])
        assert validate_backup(archive)["ok"] is True

        login(client, "t_owner")
        expected = ("success", f"تم استعادة النسخة بنجاح — users: 1, "
                    f"projects: 1, {EMPTY_SUMMARY}")

        body = post_page(client, "/admin/backup/import",
                         lambda: {"backup_file": (io.BytesIO(archive),
                                                  "platform-min.zip")})
        assert expected[1] in body

        _, flashes = post_flashes(client, "/admin/backup/import",
                                  lambda: {"backup_file": (io.BytesIO(archive),
                                                           "platform-min.zip")})
        assert flashes == [expected]

        with app.app_context():
            restored = Project.query.filter_by(name="مشروع مستورد").one()
            assert restored.location == "الرياض"
            assert restored.contractor == "مقاول مستورد"
            assert restored.client == "عميل مستورد"
            user = User.query.filter_by(username="t_restored").one()
            assert user.email == "t_restored@t.com"
            assert user.full_name == "مستخدم مستورد تجريبي"
            assert user.role == "site_engineer"
            # the pre-existing tenant rows survived the restore
            assert Project.query.filter_by(name="Alpha Tower").count() == 1
            assert User.query.filter_by(username="t_owner").count() == 1
            assert User.query.filter_by(username="t_admin").count() == 1

    def test_corrupt_archive_flashes_danger(self, client, app):
        corrupt = b"PK\x03\x04 this is not a real zip payload"
        error = validate_backup(corrupt)["error"]
        assert error == "File is not a zip file"
        assert validate_backup(corrupt)["ok"] is False

        login(client, "t_owner")
        resp, flashes = post_flashes(
            client, "/admin/backup/import",
            lambda: {"backup_file": (io.BytesIO(corrupt), "broken.zip")})
        assert resp.headers["Location"] == BACKUP_INDEX
        assert flashes == [("danger", f"الملف غير صالح: {error}")]
        with app.app_context():
            assert Project.query.filter_by(name="مشروع مستورد").count() == 0
            assert User.query.filter_by(username="t_restored").count() == 0

    def test_missing_file_field_flashes_danger(self, client):
        login(client, "t_owner")
        expected = ("danger", "لم يتم اختيار ملف نسخة احتياطية.")
        body = post_page(client, "/admin/backup/import", lambda: {})
        assert expected[1] in body
        resp, flashes = post_flashes(client, "/admin/backup/import", lambda: {})
        assert resp.headers["Location"] == BACKUP_INDEX
        assert flashes == [expected]

    def test_empty_filename_flashes_danger(self, client):
        login(client, "t_owner")
        resp, flashes = post_flashes(
            client, "/admin/backup/import",
            lambda: {"backup_file": (io.BytesIO(b""), "")})
        assert resp.headers["Location"] == BACKUP_INDEX
        assert flashes == [("danger", "لم يتم اختيار ملف نسخة احتياطية.")]

    def test_restorable_zip_with_broken_rows_flashes_danger(self, client, app):
        """A ZIP that passes validate_backup but cannot be inserted: the
        restore raises, rolls back and the route reports the failure."""
        archive = platform_archive(users=[{}])
        assert validate_backup(archive)["ok"] is True
        login(client, "t_owner")
        resp, flashes = post_flashes(
            client, "/admin/backup/import",
            lambda: {"backup_file": (io.BytesIO(archive), "half-baked.zip")})
        assert resp.headers["Location"] == BACKUP_INDEX
        assert flashes == [("danger", "فشل الاستعادة. تأكد من سلامة الملف "
                                     "وأعد المحاولة.")]
        with app.app_context():
            assert User.query.count() == len(FULL_NAMES)
            assert Project.query.count() == 2


# ------------------------------------------------------------------ download
class TestBackupDownload:
    def test_download_returns_identical_zip(self, client, backup_dir):
        login(client, "t_owner")
        name = export_one_backup(client, backup_dir)
        blob = (backup_dir / name).read_bytes()

        resp = client.get(f"/admin/backup/download/{name}")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/zip"
        disposition = resp.headers["Content-Disposition"]
        assert disposition.startswith("attachment")
        assert f"filename={name}" in disposition
        assert resp.data == blob
        assert validate_backup(resp.data)["ok"] is True

    def test_download_uses_basename_for_nested_keys(self, client, backup_dir):
        login(client, "t_owner")
        export_one_backup(client, backup_dir)
        name = only_backup(backup_dir)
        payload = (backup_dir / name).read_bytes()
        stored = storage.upload(payload, f"nested/{name}")
        assert os.path.normpath(stored) == str(backup_dir / "nested" / name)
        assert os.path.isfile(stored)

        resp = client.get(f"/admin/backup/download/nested/{name}")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "application/zip"
        assert f"filename={name}" in resp.headers["Content-Disposition"]
        assert "nested/" not in resp.headers["Content-Disposition"]
        assert resp.data == payload

    def test_missing_key_redirects_with_danger(self, client, backup_dir):
        with pytest.raises(FileNotFoundError):
            storage.download("absent.zip")
        login(client, "t_owner")
        resp = client.get("/admin/backup/download/absent.zip")
        assert resp.status_code == 302
        assert resp.headers["Location"] == BACKUP_INDEX
        assert take_flashes(client) == [("danger",
                                        "تعذر تنزيل النسخة. أعد المحاولة.")]

    def test_traversal_key_is_refused(self, client, backup_dir, tmp_path):
        outside = tmp_path / "outside.zip"
        outside.write_bytes(b"top-secret-bytes")
        login(client, "t_owner")
        with pytest.raises(ValueError):
            storage.download("../outside.zip")

        resp = client.get("/admin/backup/download/..%2Foutside.zip")
        assert resp.status_code == 302
        assert resp.headers["Location"] == BACKUP_INDEX
        assert take_flashes(client) == [("danger",
                                        "تعذر تنزيل النسخة. أعد المحاولة.")]
        assert outside.read_bytes() == b"top-secret-bytes"


# ------------------------------------------------------------------ delete
class TestBackupDelete:
    def test_delete_removes_the_archive(self, client, backup_dir):
        login(client, "t_owner")
        name = export_one_backup(client, backup_dir)
        resp, flashes = post_flashes(client, f"/admin/backup/delete/{name}")
        assert resp.headers["Location"] == BACKUP_INDEX
        assert flashes == [("info", f"تم حذف النسخة: {name}")]
        assert not (backup_dir / name).exists()
        assert list(backup_dir.iterdir()) == []
        assert storage.list_backups() == []

    def test_delete_missing_archive_flashes_danger(self, client, backup_dir):
        with pytest.raises(FileNotFoundError):
            storage.delete("never-existed.zip")
        login(client, "t_owner")
        resp, flashes = post_flashes(
            client, "/admin/backup/delete/never-existed.zip")
        assert resp.headers["Location"] == BACKUP_INDEX
        assert flashes == [("danger", "تعذر حذف النسخة. أعد المحاولة.")]


# ------------------------------------------------------------------ denials
class TestBackupRouteDenials:
    @pytest.mark.parametrize("method,path", BACKUP_ROUTES,
                             ids=[f"{m}-{p}" for m, p in BACKUP_ROUTES])
    def test_plain_admin_is_denied(self, client, method, path):
        login(client, "t_admin")
        resp = getattr(client, method)(path)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/dashboard"
        assert take_flashes(client) == [DENIED_FLASH]

    @pytest.mark.parametrize("method,path", BACKUP_ROUTES,
                             ids=[f"{m}-{p}" for m, p in BACKUP_ROUTES])
    def test_engineer_is_denied(self, client, method, path):
        login(client, "t_eng")
        resp = getattr(client, method)(path)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/dashboard"
        assert take_flashes(client) == [DENIED_FLASH]

    @pytest.mark.parametrize("method,path", BACKUP_ROUTES,
                             ids=[f"{m}-{p}" for m, p in BACKUP_ROUTES])
    def test_anonymous_is_denied(self, client, method, path):
        resp = getattr(client, method)(path)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/auth/login"
        assert take_flashes(client) == [LOGIN_FLASH]


# ------------------------------------------------------------------ projects
class TestProjectToggle:
    def test_toggle_flips_is_active_both_ways(self, client, app):
        pid = make_project(app, "مشروع التبديل")
        login(client, "t_admin")

        resp, flashes = post_flashes(client, f"/admin/projects/{pid}/toggle")
        assert resp.headers["Location"] == "/admin/projects"
        assert flashes == [("success", "تم أرشفة المشروع «مشروع التبديل».")]
        assert project_state(app, "مشروع التبديل")[1] is False
        listing = client.get("/admin/projects")
        assert listing.status_code == 200
        assert "مؤرشف" in listing.get_data(as_text=True)

        body = post_page(client, f"/admin/projects/{pid}/toggle")
        assert "تم تفعيل المشروع «مشروع التبديل»." in body
        assert project_state(app, "مشروع التبديل")[1] is True
        listing = client.get("/admin/projects")
        assert listing.status_code == 200
        assert "مؤرشف" not in listing.get_data(as_text=True)

    def test_toggle_unknown_project_is_404(self, client):
        login(client, "t_admin")
        resp = client.post("/admin/projects/987654/toggle")
        assert resp.status_code == 404

    def test_toggle_denied_for_engineer(self, client, app):
        pid = make_project(app, "مشروع محمي")
        login(client, "t_eng")
        resp = client.post(f"/admin/projects/{pid}/toggle")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/dashboard"
        assert take_flashes(client) == [DENIED_FLASH]
        assert project_state(app, "مشروع محمي")[1] is True


class TestProjectCreateFlashPaths:
    def test_blank_name_flashes_danger(self, client, app):
        login(client, "t_admin")
        before = count_projects(app)
        expected = ("danger", "اسم المشروع مطلوب.")
        body = post_page(client, "/admin/projects", lambda: {"name": "   "})
        assert expected[1] in body
        _, flashes = post_flashes(client, "/admin/projects",
                                  lambda: {"name": "   "})
        assert flashes == [expected]
        assert count_projects(app) == before

    def test_duplicate_name_flashes_danger(self, client, app):
        login(client, "t_admin")
        before = count_projects(app)
        expected = ("danger", "يوجد مشروع بنفس الاسم.")
        body = post_page(client, "/admin/projects",
                         lambda: {"name": "Alpha Tower"})
        assert expected[1] in body
        _, flashes = post_flashes(client, "/admin/projects",
                                  lambda: {"name": "Alpha Tower"})
        assert flashes == [expected]
        assert count_projects(app) == before

    def test_valid_logo_upload_stores_real_file(self, client, app, backup_dir):
        login(client, "t_admin")
        _, flashes = post_flashes(
            client, "/admin/projects",
            lambda: {"name": "مشروع الشعار", "location": "الدمام",
                     "contractor": "مقاول الاختبار", "client": "عميل",
                     "logo": (io.BytesIO(png_bytes()), "logo.png")})
        assert flashes == [("success", "تمت إضافة المشروع «مشروع الشعار».")]

        _, _, location, contractor, owner, logo, logo2 = project_state(
            app, "مشروع الشعار")
        assert location == "الدمام"
        assert contractor == "مقاول الاختبار"
        assert owner == "عميل"
        assert logo2 == ""
        assert logo.startswith(str(backup_dir))
        assert os.path.isfile(logo)
        assert open(logo, "rb").read().startswith(b"\x89PNG")
        with app.app_context():
            project = Project.query.filter_by(name="مشروع الشعار").one()
            assert project.is_active is True

    def test_unsupported_logo_extension_warns_but_creates(
            self, client, app, backup_dir):
        login(client, "t_admin")
        _, flashes = post_flashes(
            client, "/admin/projects",
            lambda: {"name": "مشروع الشعار السيئ",
                     "logo": (io.BytesIO(png_bytes()), "logo.txt")})
        assert flashes == [
            ("warning", "صيغة الشعار logo.txt غير مدعومة (png/jpg/webp/svg فقط)."),
            ("success", "تمت إضافة المشروع «مشروع الشعار السيئ»."),
        ]
        assert project_state(app, "مشروع الشعار السيئ")[5] == ""
        assert not (backup_dir / "images").exists()

    def test_oversized_upload_is_rejected_by_content_length(self, client, app):
        """The route's own >5MB guard (routes.py:331-333) is unreachable:
        Config.MAX_CONTENT_LENGTH (4MB) rejects the body first."""
        assert app.config["MAX_CONTENT_LENGTH"] == 4 * 1024 * 1024
        login(client, "t_admin")
        before = count_projects(app)
        resp = client.post(
            "/admin/projects",
            data={"name": "مشروع شعار ضخم",
                  "logo": (io.BytesIO(png_bytes(5 * 1024 * 1024 + 1)),
                           "big.png")})
        assert resp.status_code == 413
        assert count_projects(app) == before

    def test_legacy_schema_breaks_before_the_alter_blocks(self, client, app):
        """routes.py:303-314/338-344 are dead code: the duplicate-name SELECT
        at line 299 already selects logo_path/logo2_path, so a DB that
        lacks those columns never reaches the self-migration."""
        with app.app_context():
            before = db.session.execute(
                text("SELECT count(*) FROM projects")).scalar()
            db.session.execute(text("ALTER TABLE projects DROP COLUMN logo_path"))
            db.session.execute(text("ALTER TABLE projects DROP COLUMN logo2_path"))
            db.session.commit()

        login(client, "t_admin")
        with pytest.raises(OperationalError, match="logo_path"):
            client.post("/admin/projects", data={"name": "مشروع قديم"})
        with app.app_context():
            after = db.session.execute(
                text("SELECT count(*) FROM projects")).scalar()
            assert after == before

    def test_logo_storage_failure_still_creates_project(
            self, client, app, broken_backup_dir):
        login(client, "t_admin")
        _, flashes = post_flashes(
            client, "/admin/projects",
            lambda: {"name": "مشروع شعار فاشل",
                     "location": "مكة",
                     "logo": (io.BytesIO(png_bytes()), "logo.png")})
        assert flashes == [("success", "تمت إضافة المشروع «مشروع شعار فاشل».")]
        _, _, location, _, _, logo, logo2 = project_state(
            app, "مشروع شعار فاشل")
        assert location == "مكة"
        assert logo == ""
        assert logo2 == ""


# ------------------------------------------------------------------ users
class TestUserManagement:
    def test_user_index_lists_every_user(self, client):
        login(client, "t_admin")
        resp = client.get("/admin/users")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        for username, full in FULL_NAMES.items():
            assert username in body
            assert full in body
        assert "مفتش جودة / QC" in body          # ROLES labels are rendered
        assert body.count("(حسابك)") == 1          # t_admin is the signed-in user

    def test_shadowed_admin_user_index_view_renders(self, app):
        """`admin.users` is unreachable over HTTP: `main.users` registers the
        same /admin/users rule first, so the admin view is called directly."""
        from flask_login import login_user
        from app.admin import routes as admin_routes

        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()
                     if rule.rule == "/admin/users"}
        assert endpoints == {"main.users", "admin.users"}
        assert app.url_map.bind("localhost").match(
            "/admin/users", method="GET")[0] == "main.users"

        with app.test_request_context("/admin/users"):
            admin_user = User.query.filter_by(username="t_admin").one()
            login_user(admin_user)
            body = admin_routes.users()
        for username, full in FULL_NAMES.items():
            assert username in body
            assert full in body
        assert "مفتش جودة / QC" in body
        assert body.count("(حسابك)") == 1

    def test_invalid_role_flashes_danger(self, client, app):
        uid = user_id(app, "t_eng")
        login(client, "t_admin")
        body = post_page(client, f"/admin/users/{uid}/role",
                         lambda: {"role": "root"})
        assert "الدور غير صالح." in body
        _, flashes = post_flashes(client, f"/admin/users/{uid}/role",
                                  lambda: {"role": "root"})
        assert flashes == [("danger", "الدور غير صالح.")]
        with app.app_context():
            assert db.session.get(User, uid).role == "site_engineer"

    def test_self_role_change_is_blocked(self, client, app):
        uid = user_id(app, "t_admin")
        login(client, "t_admin")
        _, flashes = post_flashes(client, f"/admin/users/{uid}/role",
                                  lambda: {"role": "superadmin"})
        assert flashes == [("warning", "لا يمكنك تغيير دور حسابك الخاص.")]
        with app.app_context():
            user = db.session.get(User, uid)
            assert user.role == "admin"
            assert user.is_superadmin is False

    def test_non_superadmin_cannot_promote_to_superadmin(self, client, app):
        uid = user_id(app, "t_eng")
        login(client, "t_admin")
        body = post_page(client, f"/admin/users/{uid}/role",
                         lambda: {"role": "superadmin"})
        assert "ترقية Superadmin مقصورة على مالك المنصة." in body
        _, flashes = post_flashes(client, f"/admin/users/{uid}/role",
                                  lambda: {"role": "superadmin"})
        assert flashes == [("danger",
                            "ترقية Superadmin مقصورة على مالك المنصة.")]
        with app.app_context():
            user = db.session.get(User, uid)
            assert user.role == "site_engineer"
            assert user.is_superadmin is False

    def test_valid_role_change_persists(self, client, app):
        uid = user_id(app, "t_eng2")
        login(client, "t_admin")
        _, flashes = post_flashes(client, f"/admin/users/{uid}/role",
                                  lambda: {"role": "qa_qc_inspector"})
        assert flashes == [("success", "تم تعيين مهندس ثان اختبار تجريبي "
                                      "كـ (مفتش جودة / QC).")]
        with app.app_context():
            assert db.session.get(User, uid).role == "qa_qc_inspector"

    def test_suspend_self_is_blocked(self, client, app):
        uid = user_id(app, "t_admin")
        login(client, "t_admin")
        _, flashes = post_flashes(client, f"/admin/users/{uid}/suspend")
        assert flashes == [("warning", "لا يمكنك إيقاف حسابك الخاص.")]
        with app.app_context():
            assert db.session.get(User, uid).is_active is True

    def test_suspend_toggles_is_active(self, client, app):
        uid = user_id(app, "t_eng")
        login(client, "t_admin")
        resp, flashes = post_flashes(client, f"/admin/users/{uid}/suspend")
        assert resp.headers["Location"] == "/admin/users"
        assert flashes == [("success",
                            "تم إيقاف حساب مهندس اختبار تجريبي عام.")]
        with app.app_context():
            assert db.session.get(User, uid).is_active is False

        body = post_page(client, f"/admin/users/{uid}/suspend")
        assert "تم تفعيل حساب مهندس اختبار تجريبي عام." in body
        assert "موقوف" not in body
        with app.app_context():
            assert db.session.get(User, uid).is_active is True

    def test_user_admin_denied_for_engineer(self, client, app):
        uid = user_id(app, "t_safety")
        login(client, "t_eng")
        for path in ("/admin/users", f"/admin/users/{uid}/role",
                     f"/admin/users/{uid}/suspend"):
            method = "get" if path == "/admin/users" else "post"
            resp = getattr(client, method)(path)
            assert resp.status_code == 302
            assert resp.headers["Location"] == "/dashboard"
            assert take_flashes(client) == [DENIED_FLASH]
        with app.app_context():
            user = db.session.get(User, uid)
            assert user.role == "safety_officer"
            assert user.is_active is True
