"""Self-service projects: create-first flow + member grants + link guards.

Proves the answer to "reports need a project, but who creates it":
any reporter creates their own project (auto-owner), invites members,
and both the dyn dropdown and ops endpoints honor membership.
"""
from tests.conftest import login_as


def _create(client, name="مشروع الواحة", **kw):
    payload = {"name": name, "location": kw.get("location", "رام الله"),
               "contractor": kw.get("contractor", "مقاول"),
               "client": kw.get("client", "مالك")}
    return client.post("/projects", data=payload, follow_redirects=False)


def _alpha_pid(client):
    from app.models import Project
    with client.application.app_context():
        return Project.query.filter_by(name="Alpha Tower").first().id


# ---- create-first ------------------------------------------------------------

def test_engineer_creates_own_project_and_becomes_owner(client):
    from app.models import Project, User
    from app.ops.models import ProjectMember
    login_as(client, "t_eng")
    r = _create(client)
    assert r.status_code == 302, r.get_data(as_text=True)
    with client.application.app_context():
        p = Project.query.filter_by(name="مشروع الواحة").first()
        assert p is not None
        eng = User.query.filter_by(username="t_eng").first()
        row = ProjectMember.query.filter_by(
            user_id=eng.id, project_id=p.id).first()
        assert row is not None
        assert row.role_in_project == "owner"


def test_duplicate_project_name_rejected(client):
    from app.models import Project
    login_as(client, "t_eng")
    assert _create(client, name="مكرر").status_code == 302
    with client.application.app_context():
        n_before = Project.query.count()
    assert _create(client, name="مكرر").status_code == 302
    with client.application.app_context():
        assert Project.query.count() == n_before


def test_create_requires_login(client):
    r = _create(client, name="x")
    assert r.status_code == 302  # login redirect, no project made
    assert "/auth/login" in r.headers.get("Location", "")


def test_projects_list_shows_only_mine(client):
    login_as(client, "t_eng")
    _create(client, name="خاص بي")
    text = client.get("/projects").get_data(as_text=True)
    assert "خاص بي" in text
    assert "Beta Hospital" not in text  # not a member
    login_as(client, "t_owner")  # platform manager sees all
    text = client.get("/projects").get_data(as_text=True)
    assert "خاص بي" in text and "Beta Hospital" in text


# ---- membership -----------------------------------------------------------------

def _my_project_id(client, username="t_eng"):
    from app.models import User
    from app.ops.models import ProjectMember
    login_as(client, username)
    _create(client, name="للدعوات")
    with client.application.app_context():
        u = User.query.filter_by(username=username).first()
        row = ProjectMember.query.filter_by(
            user_id=u.id, role_in_project="owner").order_by(
                ProjectMember.id.desc()).first()
        return row.project_id


def test_owner_invites_member_by_username(client):
    from app.models import User
    from app.ops.models import ProjectMember
    pid = _my_project_id(client)
    login_as(client, "t_eng")
    r = client.post(f"/projects/{pid}/members",
                    data={"username": "t_safety"}, follow_redirects=False)
    assert r.status_code == 302
    with client.application.app_context():
        s = User.query.filter_by(username="t_safety").first()
        row = ProjectMember.query.filter_by(
            user_id=s.id, project_id=pid).first()
        assert row is not None and row.role_in_project == "member"
    # invited member can now open the detail page
    login_as(client, "t_safety")
    assert client.get(f"/projects/{pid}").status_code == 200


def test_invite_unknown_or_duplicate_user(client):
    from app.ops.models import ProjectMember
    pid = _my_project_id(client)
    login_as(client, "t_eng")
    with client.application.app_context():
        n_before = ProjectMember.query.filter_by(project_id=pid).count()
    client.post(f"/projects/{pid}/members",
                data={"username": "ghost_user"})
    client.post(f"/projects/{pid}/members",
                data={"username": "t_safety"})
    client.post(f"/projects/{pid}/members",
                data={"username": "t_safety"})
    with client.application.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == \
            n_before + 1  # exactly one new row


def test_plain_member_cannot_manage(client):
    from app.models import User
    from app.ops.models import ProjectMember
    pid = _my_project_id(client)
    login_as(client, "t_eng")
    client.post(f"/projects/{pid}/members", data={"username": "t_safety"})
    with client.application.app_context():
        eng2 = User.query.filter_by(username="t_eng2").first()
        n_before = ProjectMember.query.filter_by(project_id=pid).count()
    # t_safety is a plain member: invite + remove both refused
    login_as(client, "t_safety")
    client.post(f"/projects/{pid}/members",
                data={"username": "t_eng2"})
    client.post(f"/projects/{pid}/members/{eng2.id}/remove")
    with client.application.app_context():
        assert ProjectMember.query.filter_by(project_id=pid).count() == \
            n_before


def test_owner_removes_member_but_not_self(client):
    from app.models import User
    from app.ops.models import ProjectMember
    pid = _my_project_id(client)
    login_as(client, "t_eng")
    client.post(f"/projects/{pid}/members", data={"username": "t_safety"})
    with client.application.app_context():
        s = User.query.filter_by(username="t_safety").first()
        e = User.query.filter_by(username="t_eng").first()
    # self-removal barred
    client.post(f"/projects/{pid}/members/{e.id}/remove")
    with client.application.app_context():
        assert ProjectMember.query.filter_by(
            user_id=e.id, project_id=pid).first() is not None
    # removing the guest works
    client.post(f"/projects/{pid}/members/{s.id}/remove")
    with client.application.app_context():
        assert ProjectMember.query.filter_by(
            user_id=s.id, project_id=pid).first() is None
    login_as(client, "t_safety")
    assert client.get(f"/projects/{pid}").status_code == 404


def test_non_member_detail_and_add_are_404(client):
    pid = _my_project_id(client)  # owned by t_eng
    login_as(client, "t_eng2")  # Beta-only outsider
    assert client.get(f"/projects/{pid}").status_code == 404
    assert client.post(f"/projects/{pid}/members",
                       data={"username": "t_safety"}).status_code == 404


# ---- link guards ------------------------------------------------------------------

def test_dyn_dropdown_scoped_to_membership(client):
    login_as(client, "t_eng")
    _create(client, name="خاص بي")
    text = client.get("/reports/dyn/new/daily").get_data(as_text=True)
    assert "خاص بي" in text
    assert "Beta Hospital" not in text
    login_as(client, "t_owner")
    text = client.get("/reports/dyn/new/daily").get_data(as_text=True)
    assert "Beta Hospital" in text


def test_dyn_create_out_of_scope_link_404(client):
    from app.models import Project
    login_as(client, "t_eng2")  # Beta-only
    with client.application.app_context():
        pa = Project.query.filter_by(name="Alpha Tower").first().id
    r = client.post("/reports/dyn/new/daily", data={
        "project_name": "x", "project_id": str(pa),
        "report_date": "2026-09-15", "location": "", "contractor": ""},
        follow_redirects=False)
    assert r.status_code == 404


def test_dyn_create_linked_syncs_name(client):
    from app.models import ReportSubmission
    pid = _my_project_id(client)
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
        assert s.project_name == "للدعوات"  # authoritative, not typed text


def test_ops_create_under_self_made_project(client):
    pid = _my_project_id(client)
    login_as(client, "t_eng")
    r = client.post("/ops/rfis", json={
        "project_id": pid, "subject": "سؤال", "question": "؟",
        "ball_in_court": "consultant"})
    assert r.status_code == 201, r.get_json()
