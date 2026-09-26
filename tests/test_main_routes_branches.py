"""Branch coverage for the last reachable paths of ``app/main/routes.py``.

Every case drives a real HTTP request through the Flask test client and then
asserts the exact status code, the exact Arabic flash substring, and the
resulting database state. No mocking of route internals: only the two
filesystem anchors are redirected into ``tmp_path`` so nothing is written into
the repository tree —

* avatars, which the route derives from ``app.main.routes.__file__``;
* backup ZIPs, via ``app.services.storage.BACKUP_LOCAL_DIR``.

Branches pinned here (app/main/routes.py):

* 19    — ``index`` redirects a signed-in user to the dashboard.
* 180   — ``_save_avatar`` empty-upload guard (unreachable over HTTP, see the
          test docstring: the only caller guards it first at line 227).
* 259-260 + 265 — ``remove_avatar`` swallows filesystem errors and still
          clears the column, plus the "no avatar" warning.
* 206-207 / 208-244 — profile POST rejection and the full save.
* 284 / 296-297 / 299-300 — role-toggling refusals: self-change, legacy role
          normalisation, and the Superadmin promotion guard.
* 335   — project creation without a name.
* 390-405 / 419-433 — member invite and removal roster governance.
* 455-459 — backup export when storage refuses the write.
* 480-487 — backup import of a nameless file part and of a corrupt archive
          (both are stopped by the validator, never by the restore).
* 490-494 — the fail-closed restore error path: an archive that passes
          validation but cannot be restored (incompatible version, and a
          purge followed by a row that violates a NOT NULL column).
"""
import io
import json
import re
import zipfile

import pytest

from tests.conftest import login_as


# =============================================================== helpers
def _project_id(app, name):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name=name).one().id


def _user_id(app, username):
    from app.models import User
    with app.app_context():
        return User.query.filter_by(username=username).one().id


def _role_of(app, username):
    from app.models import User
    with app.app_context():
        return User.query.filter_by(username=username).one().role


def _add_user(app, username, role, full_name, is_active=True):
    """Create a real user row (for role-cycle and suspension branches)."""
    from app.extensions import db
    from app.models import User
    with app.app_context():
        user = User(username=username, email=f"{username}@t.com",
                    full_name=full_name, role=role, is_active=is_active)
        user.set_password("pw12345")
        db.session.add(user)
        db.session.commit()
        return user.id


def _archive_bytes(entries):
    """Build ZIP bytes from a {member_name: json_payload} mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return buf.getvalue()


def _member_count(app, project_id):
    from app.ops.models import ProjectMember
    with app.app_context():
        return ProjectMember.query.filter_by(project_id=project_id).count()


def _has_membership(app, project_id, username):
    from app.models import User
    from app.ops.models import ProjectMember
    with app.app_context():
        uid = User.query.filter_by(username=username).one().id
        return ProjectMember.query.filter_by(
            user_id=uid, project_id=project_id).first() is not None


def _page(client, url):
    """GET a page and return its text (used to read drained flash messages)."""
    response = client.get(url)
    assert response.status_code == 200, response.status_code
    return response.get_data(as_text=True)


# =============================================================== fixtures
@pytest.fixture()
def avatar_tmp_client(client, tmp_path, monkeypatch):
    """Avatar uploads are anchored to routes.__file__ -> move that under tmp."""
    import app.main.routes as main_routes
    fake_module = tmp_path / "app" / "main" / "routes.py"
    fake_module.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_routes, "__file__", str(fake_module))
    return client


@pytest.fixture()
def backup_tmp_client(client, tmp_path, monkeypatch):
    """Local backup storage -> tmp, so no ZIP is written into the repo."""
    import app.services.storage as storage
    monkeypatch.setattr(storage, "BACKUP_LOCAL_DIR", str(tmp_path / "backups"))
    return client


# =============================================================== index (19)
def test_signed_in_landing_redirects_to_dashboard(app, client):
    """Guests get the marketing page; a session is bounced to /dashboard."""
    assert client.get("/").status_code == 200
    login_as(client, "t_eng")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/dashboard")
    from app.models import User
    with app.app_context():
        full_name = User.query.filter_by(username="t_eng").one().full_name
    assert full_name in _page(client, "/dashboard")


# ======================================================= avatar (180, 259-265)
def test_remove_avatar_deletes_the_file_and_clears_the_key(app, avatar_tmp_client,
                                                           tmp_path):
    """A stored avatar is unlinked from disk and from the user row."""
    from app.extensions import db
    from app.models import User
    with app.app_context():
        user = User.query.filter_by(username="t_eng").one()
        key = "avatars/%d_1700000000.png" % user.id
        user.avatar = key
        db.session.commit()
    stored = tmp_path / "app" / "static" / "uploads" / key
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(b"\x89PNG\r\n\x1a\nstale-avatar")

    login_as(avatar_tmp_client, "t_eng")
    r = avatar_tmp_client.post("/profile/avatar/remove", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/profile")
    assert "تم حذف الصورة الشخصية." in _page(avatar_tmp_client, "/profile")
    with app.app_context():
        assert User.query.filter_by(username="t_eng").one().avatar == ""
    assert not stored.exists()


def test_remove_avatar_keeps_the_column_clean_when_unlink_fails(app,
                                                                avatar_tmp_client,
                                                                tmp_path):
    """Lines 259-260: an OSError from the filesystem is swallowed, the row is
    still cleared, and the success flash is still shown."""
    from app.extensions import db
    from app.models import User
    with app.app_context():
        user = User.query.filter_by(username="t_eng").one()
        key = "avatars/%d_blocked.png" % user.id
        user.avatar = key
        db.session.commit()
    # a directory where the avatar file should be: os.remove() raises OSError
    blocked = tmp_path / "app" / "static" / "uploads" / key
    blocked.mkdir(parents=True)

    login_as(avatar_tmp_client, "t_eng")
    r = avatar_tmp_client.post("/profile/avatar/remove", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/profile")
    text = _page(avatar_tmp_client, "/profile")
    assert "تم حذف الصورة الشخصية." in text
    assert "لا توجد صورة لحذفها." not in text
    with app.app_context():
        assert User.query.filter_by(username="t_eng").one().avatar == ""
    assert blocked.is_dir()  # nothing was removed from disk


def test_remove_avatar_without_an_avatar_warns(app, client):
    """The 'nothing to delete' branch: warning flash, key untouched."""
    from app.models import User
    login_as(client, "t_eng")
    r = client.post("/profile/avatar/remove", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/profile")
    text = _page(client, "/profile")
    assert "لا توجد صورة لحذفها." in text
    assert "تم حذف الصورة الشخصية." not in text
    with app.app_context():
        assert User.query.filter_by(username="t_eng").one().avatar == ""


def test_save_avatar_helper_guards_an_empty_upload(app, avatar_tmp_client,
                                                   tmp_path):
    """Line 180 is dead code over HTTP: the only caller (``profile``) already
    rejects a nameless/empty upload at line 227, and ``FileStorage.__bool__``
    is False exactly for that case. The guard is pinned directly instead."""
    import app.main.routes as main_routes
    from werkzeug.datastructures import FileStorage
    with app.app_context():
        assert main_routes._save_avatar(None) == ""
        assert main_routes._save_avatar(FileStorage(io.BytesIO(b"x"), "")) == ""
    assert not (tmp_path / "app" / "static" / "uploads").exists()


# ================================================== profile POST (206-244)
def test_profile_post_rejects_a_three_part_name(app, client):
    """Below four name parts nothing is written and the form comes back."""
    from app.models import User
    login_as(client, "t_eng")
    r = client.post("/profile", data={"full_name": "خالد سعيد محمود",
                                      "phone": "+966500000001"},
                    follow_redirects=False)
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert "الاسم الرباعي يجب أن يتكون من أربعة مقاطع على الأقل." in text
    assert "تم تحديث الملف الشخصي بنجاح." not in text
    with app.app_context():
        user = User.query.filter_by(username="t_eng").one()
        assert user.full_name == "مهندس اختبار تجريبي عام"
        assert user.phone != "+966500000001"


def test_profile_post_persists_every_field_and_notification_pref(app, client):
    """The happy path stores the profile columns and the pref flags."""
    from app.models import User
    login_as(client, "t_eng")
    r = client.post("/profile", data={
        "full_name": "خالد سعيد محمود عبدالله",
        "phone": "+966500000002",
        "company": "شركة الإنشاءات",
        "job_title": "مهندس موقع",
        "department": "الهندسة",
        "certification": "PMP",
        "notify_email": "on"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/profile")
    assert "تم تحديث الملف الشخصي بنجاح." in _page(client, "/profile")
    with app.app_context():
        user = User.query.filter_by(username="t_eng").one()
        assert user.full_name == "خالد سعيد محمود عبدالله"
        assert user.phone == "+966500000002"
        assert user.company == "شركة الإنشاءات"
        assert user.job_title == "مهندس موقع"
        assert user.department == "الهندسة"
        assert user.certification == "PMP"
        assert user.notification_prefs == {"email": True, "sms": False,
                                           "push": False, "in_app": False}


# ================================================ role cycle (284, 296-300)
def test_admin_cannot_toggle_their_own_role(app, client):
    """Line 284: self-service role change refused, role stays put."""
    from app.models import User
    own_id = _user_id(app, "t_admin")
    login_as(client, "t_admin")
    r = client.post(f"/admin/users/{own_id}/toggle-role", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/admin/users")
    text = _page(client, "/admin/users")
    assert "لا يمكنك تغيير دور حسابك الخاص." in text
    assert "تم تحديث دور" not in text
    with app.app_context():
        user = User.query.filter_by(username="t_admin").one()
        assert user.role == "admin"
        assert user.full_name == "مدير اختبار تجريبي عام"


def test_role_cycle_normalises_a_legacy_unknown_role(app, client):
    """Lines 296-297: a role outside the cycle ('user' legacy alias) is
    rewritten to site_engineer and the success flash carries role_ar."""
    from app.models import ROLES
    uid = _add_user(app, "t_legacy", "user", "مستخدم قديم باسم رباعي كامل")
    login_as(client, "t_admin")
    r = client.post(f"/admin/users/{uid}/toggle-role", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/admin/users")
    text = _page(client, "/admin/users")
    expected = ("تم تحديث دور مستخدم قديم باسم رباعي كامل إلى ("
                + ROLES["site_engineer"] + ").")
    assert expected in text
    assert _role_of(app, "t_legacy") == "site_engineer"


def test_admin_cannot_promote_someone_to_superadmin(app, client):
    """Lines 299-300: an admin acting on an admin is demoted back to admin
    instead of gaining the platform-owner role, and nothing is committed."""
    uid = _add_user(app, "t_admin2", "admin", "مدير ثان باسم رباعي كامل")
    login_as(client, "t_admin")
    r = client.post(f"/admin/users/{uid}/toggle-role", follow_redirects=False)
    assert r.status_code == 302
    text = _page(client, "/admin/users")
    assert "ترقية Superadmin مقصورة على مالك المنصة." in text
    assert "تم تحديث دور" not in text
    assert _role_of(app, "t_admin2") == "admin"
    assert _role_of(app, "t_admin") == "admin"


def test_superadmin_owner_may_still_promote_to_superadmin(app, client):
    """Contrast for the guard above: the platform owner is allowed."""
    from app.models import ROLES
    uid = _add_user(app, "t_admin3", "admin", "مدير ثالث باسم رباعي كامل")
    login_as(client, "t_owner")
    r = client.post(f"/admin/users/{uid}/toggle-role", follow_redirects=False)
    assert r.status_code == 302
    text = _page(client, "/admin/users")
    assert ("تم تحديث دور مدير ثالث باسم رباعي كامل إلى ("
            + ROLES["superadmin"] + ").") in text
    assert _role_of(app, "t_admin3") == "superadmin"


# ============================================================ project (335)
def test_project_create_without_a_name_is_refused(app, client):
    """Line 335: blank/whitespace/missing name flashes and creates no row."""
    from app.models import Project
    login_as(client, "t_pm")
    with app.app_context():
        before = Project.query.count()
    for payload in ({"name": "   ", "location": "الرياض"},
                    {"location": "الرياض"}):
        r = client.post("/projects", data=payload, follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/projects")
    text = _page(client, "/projects")
    assert text.count("اسم المشروع مطلوب.") == 2
    assert "يوجد مشروع بنفس الاسم." not in text
    with app.app_context():
        assert Project.query.count() == before
        assert Project.query.filter_by(name="").first() is None
        assert Project.query.filter_by(name="   ").first() is None


# ====================================================== member add (390-405)
def test_project_owner_adds_member_by_username(app, client):
    """The invite success path writes a 'member' row and names the user."""
    pid = _project_id(app, "Alpha Tower")
    before = _member_count(app, pid)
    login_as(client, "t_pm")
    r = client.post(f"/projects/{pid}/members",
                    data={"username": "t_eng2"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(client, f"/projects/{pid}")
    assert "تمت إضافة مهندس ثان اختبار تجريبي إلى المشروع." in text
    assert _member_count(app, pid) == before + 1
    with app.app_context():
        from app.models import User
        from app.ops.models import ProjectMember
        uid = User.query.filter_by(username="t_eng2").one().id
        row = ProjectMember.query.filter_by(
            user_id=uid, project_id=pid).one()
        assert row.role_in_project == "member"


def test_member_add_refuses_unknown_and_suspended_users(app, client):
    """Both halves of the guard: no such user, and a suspended account."""
    pid = _project_id(app, "Alpha Tower")
    before = _member_count(app, pid)
    _add_user(app, "t_suspended", "site_engineer",
              "مهندس موقوف باسم رباعي كامل", is_active=False)
    login_as(client, "t_pm")
    for username in ("ghost", "t_suspended", ""):
        r = client.post(f"/projects/{pid}/members",
                        data={"username": username}, follow_redirects=False)
        assert r.status_code == 302
    text = _page(client, f"/projects/{pid}")
    assert text.count("المستخدم غير موجود أو موقوف.") == 3
    assert _member_count(app, pid) == before
    assert _has_membership(app, pid, "t_suspended") is False


def test_member_add_refuses_an_existing_member(app, client):
    """The duplicate branch: t_safety already sits on Alpha Tower."""
    pid = _project_id(app, "Alpha Tower")
    before = _member_count(app, pid)
    login_as(client, "t_pm")
    r = client.post(f"/projects/{pid}/members",
                    data={"username": "t_safety"}, follow_redirects=False)
    assert r.status_code == 302
    text = _page(client, f"/projects/{pid}")
    assert "هذا المستخدم عضو بالفعل." in text
    assert _member_count(app, pid) == before


# =================================================== member remove (419-433)
def test_plain_member_cannot_manage_the_roster(app, client):
    """A field member may neither invite nor remove; the roster is intact."""
    pid = _project_id(app, "Alpha Tower")
    eng2_id = _user_id(app, "t_eng2")
    before = _member_count(app, pid)
    login_as(client, "t_eng")
    for url in (f"/projects/{pid}/members",
                f"/projects/{pid}/members/{eng2_id}/remove"):
        r = client.post(url, data={"username": "t_safety"},
                        follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(client, f"/projects/{pid}")
    assert text.count("إدارة الأعضاء مقصورة على مالك المشروع.") == 2
    assert _member_count(app, pid) == before
    assert _has_membership(app, pid, "t_safety") is True


def test_owner_cannot_remove_themselves(app, client):
    """Line 424: self-removal is barred even for the project owner."""
    pid = _project_id(app, "Alpha Tower")
    pm_id = _user_id(app, "t_pm")
    login_as(client, "t_pm")
    r = client.post(f"/projects/{pid}/members/{pm_id}/remove",
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(client, f"/projects/{pid}")
    assert "لا يمكنك إزالة نفسك من المشروع." in text
    assert "تمت إزالة العضو." not in text
    assert _has_membership(app, pid, "t_pm") is True


def test_owner_remove_of_a_non_existent_membership_warns(app, client):
    """Line 429: t_eng2 is only on Beta Hospital, so Alpha has no such row."""
    pid = _project_id(app, "Alpha Tower")
    eng2_id = _user_id(app, "t_eng2")
    before = _member_count(app, pid)
    login_as(client, "t_pm")
    r = client.post(f"/projects/{pid}/members/{eng2_id}/remove",
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(client, f"/projects/{pid}")
    assert "العضوية غير موجودة." in text
    assert "تمت إزالة العضو." not in text
    assert _member_count(app, pid) == before
    assert _has_membership(app, pid, "t_eng2") is False


def test_project_owner_removes_a_member(app, client):
    """Lines 431-433: the row is deleted and the ex-member loses access."""
    pid = _project_id(app, "Alpha Tower")
    safety_id = _user_id(app, "t_safety")
    before = _member_count(app, pid)
    login_as(client, "t_pm")
    r = client.post(f"/projects/{pid}/members/{safety_id}/remove",
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    assert "تمت إزالة العضو." in _page(client, f"/projects/{pid}")
    assert _member_count(app, pid) == before - 1
    assert _has_membership(app, pid, "t_safety") is False
    login_as(client, "t_safety")
    assert client.get(f"/projects/{pid}").status_code == 404


# ================================================== backup export (455-459)
def test_backup_export_writes_the_zip_into_the_redirected_storage(
        app, backup_tmp_client, tmp_path):
    """The success path stores a project-scoped ZIP outside the repo tree."""
    pid = _project_id(app, "Alpha Tower")
    login_as(backup_tmp_client, "t_pm")
    r = backup_tmp_client.post(f"/projects/{pid}/backup",
                               follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(backup_tmp_client, f"/projects/{pid}")
    assert "تم إنشاء نسخة احتياطية للمشروع «Alpha Tower»." in text
    files = sorted((tmp_path / "backups").iterdir())
    assert len(files) == 1
    assert re.fullmatch(rf"azadexa-project-{pid}-\d{{8}}-\d{{6}}\.zip",
                        files[0].name)
    with zipfile.ZipFile(files[0]) as zf:
        assert json.loads(zf.read("metadata.json"))["scope"] == "project"


def test_backup_export_reports_a_storage_failure(app, client, tmp_path,
                                                 monkeypatch):
    """Lines 455-459: an unwritable storage dir is logged, flashed as a
    failure, and the project rows are left untouched."""
    import app.services.storage as storage
    from app.ops.models import ProjectMember
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("this is a file, not a folder")
    monkeypatch.setattr(storage, "BACKUP_LOCAL_DIR", str(blocker / "backups"))
    pid = _project_id(app, "Alpha Tower")
    with app.app_context():
        before = ProjectMember.query.filter_by(project_id=pid).count()
    login_as(client, "t_pm")
    r = client.post(f"/projects/{pid}/backup", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(client, f"/projects/{pid}")
    assert "فشل حفظ النسخة الاحتياطية. تحقق من التخزين ثم أعد المحاولة." in text
    assert "تم إنشاء نسخة احتياطية" not in text
    assert blocker.is_file()  # no directory was created
    with app.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == before


# ==================================================== backup import (480-494)
def test_backup_import_rejects_a_corrupt_archive(app, backup_tmp_client):
    """A payload that is not a ZIP is refused by the validator, DB intact."""
    from app.services.backup import validate_backup
    pid = _project_id(app, "Alpha Tower")
    payload = b"PK\x03\x04 definitely-not-a-real-zip-body"
    report = validate_backup(payload)
    assert report["ok"] is False
    before = _member_count(app, pid)
    login_as(backup_tmp_client, "t_pm")
    r = backup_tmp_client.post(f"/projects/{pid}/backup/import", data={
        "backup_file": (io.BytesIO(payload), "broken.zip")},
        follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(backup_tmp_client, f"/projects/{pid}")
    assert "الملف غير صالح: " + report["error"] in text
    assert "فشل الاستعادة" not in text
    assert _member_count(app, pid) == before


def test_backup_import_rejects_a_file_without_a_name(app, backup_tmp_client):
    """A file part with an empty filename never reaches the validator."""
    from app.services.backup import validate_backup
    pid = _project_id(app, "Alpha Tower")
    before = _member_count(app, pid)
    login_as(backup_tmp_client, "t_pm")
    r = backup_tmp_client.post(f"/projects/{pid}/backup/import", data={
        "backup_file": (io.BytesIO(b"anything"), "")}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(backup_tmp_client, f"/projects/{pid}")
    assert "لم يتم اختيار ملف نسخة احتياطية." in text
    assert "الملف غير صالح" not in text
    assert validate_backup(b"anything")["ok"] is False
    assert _member_count(app, pid) == before


def test_backup_import_of_an_incompatible_version_fails_closed(
        app, backup_tmp_client):
    """A wrong format version is rejected by validate_backup itself, so the
    restore is never attempted and the project is left untouched."""
    from app.models import Project
    from app.ops.models import ProjectMember, SiteInspection
    pid = _project_id(app, "Alpha Tower")
    payload = _archive_bytes({"metadata.json": {
        "version": "0.9", "scope": "project", "project_id": pid}})
    login_as(backup_tmp_client, "t_pm")
    r = backup_tmp_client.post(f"/projects/{pid}/backup/import", data={
        "backup_file": (io.BytesIO(payload), "old.zip")},
        follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(backup_tmp_client, f"/projects/{pid}")
    assert "الملف غير صالح" in text
    assert "Backup version mismatch" in text
    assert "فشل الاستعادة" not in text
    with app.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == 3
        assert SiteInspection.query.filter_by(
            project_id=pid, serial="SIR-000001").count() == 1
        assert Project.query.filter_by(name="Alpha Tower").one().location \
            == "Riyadh"


def test_backup_import_that_fails_mid_restore_rolls_everything_back(
        app, backup_tmp_client):
    """Lines 490-494 with a partially applied restore: the archive passes
    validation, the purge runs, then the insert of a row that violates a NOT
    NULL column fails — the rollback must undo the purge."""
    from app.models import Project
    from app.ops.models import CostVariance, ProjectMember, RFI, SiteInspection
    pid = _project_id(app, "Alpha Tower")
    payload = _archive_bytes({
        "metadata.json": {"version": "1.0", "scope": "project",
                          "project_id": pid},
        # a valid tenant row: re-inserted (as 'sandbox') by the failed restore
        "ops_records/site_inspections.json": [{
            "id": 900, "project_id": pid, "serial": "SIR-000001",
            "user_id": 1, "report_date": "2026-03-01", "test_category": "soil",
            "test_type": "sandbox"}],
        # RFI.subject and OpsRecordMixin.user_id are NOT NULL -> insert fails
        "ops_records/rfis.json": [{"id": 901, "project_id": pid,
                                   "serial": "RFI-BROKEN-1",
                                   "report_date": "2026-03-02"}],
    })
    login_as(backup_tmp_client, "t_pm")
    r = backup_tmp_client.post(f"/projects/{pid}/backup/import", data={
        "backup_file": (io.BytesIO(payload), "half-broken.zip")},
        follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/projects/{pid}")
    text = _page(backup_tmp_client, f"/projects/{pid}")
    assert "فشل الاستعادة. تأكد من سلامة الملف وأعد المحاولة." in text
    assert "تم استعادة المشروع" not in text
    with app.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == 3
        inspection = SiteInspection.query.filter_by(
            project_id=pid, serial="SIR-000001").one()
        assert inspection.test_type == "cube 7d"      # the purged row is back
        assert RFI.query.filter_by(project_id=pid).count() == 1
        assert CostVariance.query.filter_by(
            project_id=pid, serial="CVR-000001").count() == 1
        assert RFI.query.filter_by(serial="RFI-BROKEN-1").count() == 0
        assert Project.query.count() == 2
