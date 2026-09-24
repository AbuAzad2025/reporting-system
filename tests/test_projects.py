"""Project governance: ONE real-world project created ONCE by its manager.

The project manager creates the project; engineers/safety join by
invitation with role permissions and report under the same project.
Nobody duplicates reality: one site = one project row.
"""
from tests.conftest import login_as


def _create(client, name="مشروع المدير", **kw):
    payload = {"name": name, "location": kw.get("location", "رام الله"),
               "contractor": kw.get("contractor", "مقاول"),
               "client": kw.get("client", "مالك")}
    return client.post("/projects", data=payload, follow_redirects=False)


def _pm_project_id(client, name="مشروع المدير"):
    """PM creates a project; returns its id (PM is auto-owner)."""
    from app.models import Project
    login_as(client, "t_pm")
    r = _create(client, name=name)
    assert r.status_code == 302, r.get_data(as_text=True)
    with client.application.app_context():
        return Project.query.filter_by(name=name).first().id


def _invite(client, pid, username, as_user="t_pm"):
    login_as(client, as_user)
    return client.post(f"/projects/{pid}/members",
                       data={"username": username}, follow_redirects=False)


# ---- creation belongs to the manager --------------------------------------------

def test_pm_creates_project_and_becomes_owner(client):
    from app.extensions import db
    from app.models import Project, User
    from app.ops.models import ProjectMember
    pid = _pm_project_id(client, name="مشروع الواحة")
    with client.application.app_context():
        pm = User.query.filter_by(username="t_pm").first()
        row = ProjectMember.query.filter_by(
            user_id=pm.id, project_id=pid).first()
        assert row is not None
        assert row.role_in_project == "owner"
        assert db.session.get(Project, pid).name == "مشروع الواحة"


def test_engineer_cannot_create_project(client):
    """Field roles report; they do not spawn projects (no duplicates)."""
    from app.models import Project
    login_as(client, "t_eng")
    with client.application.app_context():
        n_before = Project.query.count()
    r = _create(client, name="مشروع وهمي")
    assert r.status_code == 302  # denied: flash + redirect, nothing stored
    with client.application.app_context():
        assert Project.query.count() == n_before
        assert Project.query.filter_by(name="مشروع وهمي").first() is None


def test_create_form_hidden_from_engineer(client):
    login_as(client, "t_eng")
    text = client.get("/projects").get_data(as_text=True)
    assert "مشروع جديد" not in text
    login_as(client, "t_pm")
    text = client.get("/projects").get_data(as_text=True)
    assert "مشروع جديد" in text


def test_duplicate_project_name_rejected(client):
    from app.models import Project
    login_as(client, "t_pm")
    assert _create(client, name="مكرر").status_code == 302
    with client.application.app_context():
        n_before = Project.query.count()
    assert _create(client, name="مكرر").status_code == 302
    with client.application.app_context():
        assert Project.query.count() == n_before


def test_create_requires_login(client):
    r = _create(client, name="x")
    assert r.status_code == 302
    assert "/auth/login" in r.headers.get("Location", "")


def test_projects_list_shows_only_mine(client):
    _pm_project_id(client, name="خاص بالمدير")
    client.get("/projects")  # drain creation flash before asserting absence
    login_as(client, "t_eng")  # not a member of the new project
    text = client.get("/projects").get_data(as_text=True)
    assert "خاص بالمدير" not in text
    assert "Alpha Tower" in text  # seeded membership kept
    login_as(client, "t_owner")  # platform manager sees all
    text = client.get("/projects").get_data(as_text=True)
    assert "خاص بالمدير" in text and "Beta Hospital" in text


# ---- invitation: join, don't duplicate ----------------------------------------------

def test_owner_invites_engineer_who_reports(client):
    """The domain flow: PM creates once, engineer joins, engineer reports."""
    from app.models import User
    from app.ops.models import ProjectMember
    pid = _pm_project_id(client)
    assert _invite(client, pid, "t_eng").status_code == 302
    with client.application.app_context():
        e = User.query.filter_by(username="t_eng").first()
        row = ProjectMember.query.filter_by(
            user_id=e.id, project_id=pid).first()
        assert row is not None and row.role_in_project == "member"
    # invited engineer opens the project and files an RFI under it
    login_as(client, "t_eng")
    assert client.get(f"/projects/{pid}").status_code == 200
    r = client.post("/ops/rfis", json={
        "project_id": pid, "subject": "سؤال", "question": "؟",
        "ball_in_court": "consultant"})
    assert r.status_code == 201, r.get_json()


def test_owner_invites_whole_crew_all_roles(client):
    """Anyone related joins: every role invitable, every invitee in scope."""
    from app.ops.models import ProjectMember
    pid = _pm_project_id(client, name="مشروع الطاقم")
    for username in ("t_eng", "t_eng2", "t_safety", "t_admin"):
        assert _invite(client, pid, username).status_code == 302
    with client.application.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == 5
    for username in ("t_eng", "t_eng2", "t_safety"):
        login_as(client, username)
        assert client.get(f"/projects/{pid}").status_code == 200


def test_directory_visible_to_manager_only(client):
    pid = _pm_project_id(client)
    _invite(client, pid, "t_safety")
    login_as(client, "t_pm")
    text = client.get(f"/projects/{pid}").get_data(as_text=True)
    assert "user-directory" in text
    assert "t_safety" in text
    login_as(client, "t_safety")  # plain member: roster yes, directory no
    text = client.get(f"/projects/{pid}").get_data(as_text=True)
    assert "user-directory" not in text


def test_invite_unknown_or_duplicate_user(client):
    from app.ops.models import ProjectMember
    pid = _pm_project_id(client)
    login_as(client, "t_pm")
    with client.application.app_context():
        n_before = ProjectMember.query.filter_by(project_id=pid).count()
    client.post(f"/projects/{pid}/members", data={"username": "ghost"})
    client.post(f"/projects/{pid}/members", data={"username": "t_safety"})
    client.post(f"/projects/{pid}/members", data={"username": "t_safety"})
    with client.application.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == \
            n_before + 1  # exactly one new row


def test_plain_member_cannot_manage(client):
    from app.models import User
    from app.ops.models import ProjectMember
    pid = _pm_project_id(client)
    _invite(client, pid, "t_safety")
    with client.application.app_context():
        eng2 = User.query.filter_by(username="t_eng2").first()
        n_before = ProjectMember.query.filter_by(project_id=pid).count()
    login_as(client, "t_safety")  # plain member: manage refused
    client.post(f"/projects/{pid}/members", data={"username": "t_eng2"})
    client.post(f"/projects/{pid}/members/{eng2.id}/remove")
    with client.application.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == \
            n_before


def test_owner_removes_member_but_not_self(client):
    from app.models import User
    from app.ops.models import ProjectMember
    pid = _pm_project_id(client)
    _invite(client, pid, "t_safety")
    login_as(client, "t_pm")
    with client.application.app_context():
        s = User.query.filter_by(username="t_safety").first()
        pm = User.query.filter_by(username="t_pm").first()
    client.post(f"/projects/{pid}/members/{pm.id}/remove")
    with client.application.app_context():
        assert ProjectMember.query.filter_by(
            user_id=pm.id, project_id=pid).first() is not None
    client.post(f"/projects/{pid}/members/{s.id}/remove")
    with client.application.app_context():
        assert ProjectMember.query.filter_by(
            user_id=s.id, project_id=pid).first() is None
    login_as(client, "t_safety")
    assert client.get(f"/projects/{pid}").status_code == 404


def test_non_member_detail_and_add_are_404(client):
    pid = _pm_project_id(client)  # PM-owned; t_eng is an outsider here
    login_as(client, "t_eng")
    assert client.get(f"/projects/{pid}").status_code == 404
    assert client.post(f"/projects/{pid}/members",
                       data={"username": "t_safety"}).status_code == 404


# ---- link guards ------------------------------------------------------------------

def test_dyn_dropdown_scoped_to_membership(client):
    _pm_project_id(client, name="خاص بالمدير")
    client.get("/projects")  # drain creation flash before asserting absence
    login_as(client, "t_eng")
    text = client.get("/reports/dyn/new/daily").get_data(as_text=True)
    assert "خاص بالمدير" not in text
    login_as(client, "t_pm")
    text = client.get("/reports/dyn/new/daily").get_data(as_text=True)
    assert "خاص بالمدير" in text


def test_dyn_create_out_of_scope_link_404(client):
    login_as(client, "t_eng2")  # Beta-only
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "x", "project_id": str(_pm_pid_alpha(client)),
        "report_date": "2026-09-15", "location": "", "contractor": ""},
        follow_redirects=False)
    assert r.status_code == 404


def _pm_pid_alpha(client):
    from app.models import Project
    with client.application.app_context():
        return Project.query.filter_by(name="Alpha Tower").first().id


def test_dyn_create_linked_syncs_name(client):
    from app.models import ReportSubmission
    pid = _pm_project_id(client, name="مشروع الربط")
    _invite(client, pid, "t_eng")
    login_as(client, "t_eng")
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "اسم مخالف", "project_id": str(pid),
        "report_date": "2026-09-15", "location": "", "contractor": "",
        "f_manpower": "طاقم", "f_works_completed": "أعمال"},
        follow_redirects=False)
    assert r.status_code == 302
    with client.application.app_context():
        s = ReportSubmission.query.order_by(
            ReportSubmission.id.desc()).first()
        assert s.project_id == pid
        assert s.project_name == "مشروع الربط"  # authoritative, not typed
