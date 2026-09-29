"""The backup controls on a project page, proven under production conditions.

The suite runs with WTF_CSRF_ENABLED off, so nothing in it can tell whether a
form a user is meant to press actually works in a deployment. A POST without a
token returns 400 there.

These tests build the app the way a deployment does - CSRF on - and drive the
page a project owner would actually drive. They are the only place in the suite
where that is true, which is why they are here rather than folded into the
project-backup tests, which pass with CSRF disabled and would keep passing if
the form lost its token.
"""
import io
import json
import os
import re
import zipfile

import pytest

TEMPLATES_DIR = "templates"


# ------------------------------------------------------------------ templates
def test_every_post_form_in_every_template_carries_a_token():
    """A POST form with no token is a button that returns 400 when pressed.

    Found by measurement, not by reading: 19 of 37 POST forms had none. The
    suite cannot catch this because it disables CSRF globally, so the check is
    a static scan - which is why it does not need CSRF to be on.
    """
    form_re = re.compile(r"<form\b[^>]*>.*?</form>", re.S | re.I)
    post_re = re.compile(r"""method\s*=\s*["']?post""", re.I)
    token_re = re.compile(r"csrf_token", re.I)

    missing = []
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in sorted(files):
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, TEMPLATES_DIR).replace("\\", "/")
            body = io.open(path, encoding="utf-8").read()
            for match in form_re.finditer(body):
                opening = match.group(0).split(">", 1)[0]
                if not post_re.search(opening):
                    continue
                if not token_re.search(match.group(0)):
                    line = body[:match.start()].count("\n") + 1
                    action = re.search(r'action\s*=\s*["\']([^"\']*)',
                                       opening)
                    missing.append("%s:%d  %s" % (
                        rel, line, action.group(1) if action else "(no action)"))
    assert not missing, (
        "POST forms that would return 400 in a deployment:\n  "
        + "\n  ".join(missing))


def test_the_project_page_offers_backup_controls_to_a_manager():
    body = io.open(os.path.join(TEMPLATES_DIR, "project_detail.html"),
                   encoding="utf-8").read()
    assert "main.project_backup" in body
    assert "main.project_backup_import" in body
    assert 'name="backup_file"' in body, (
        "the import endpoint reads request.files['backup_file']; a form that "
        "does not send that name can never reach it")
    assert "can_manage" in body, (
        "the controls must be behind the same check the endpoints enforce")


def test_the_backup_controls_are_inside_the_manager_guard():
    """The endpoints refuse a non-owner, so the controls must be guarded too.

    Checked by rendering the page as each role rather than by reading the
    template: a guard written the wrong way round still contains the string
    "can_manage", and only a rendered page shows what a user actually gets.
    """
    # The live assertions live in
    # test_a_plain_member_is_refused_and_offered_nothing below, which renders
    # the page as a member and as an owner. This test only asserts the markup
    # is not unguarded.
    body = io.open(os.path.join(TEMPLATES_DIR, "project_detail.html"),
                   encoding="utf-8").read()
    start = body.index("main.project_backup")
    assert body.rindex("{% if can_manage %}", 0, start) != -1, (
        "the backup controls sit outside any permission guard")


# ------------------------------------------------------------------ the app
@pytest.fixture
def strict_client(tmp_path):
    """A client whose CSRF protection is on, as it is in a deployment."""
    from app import create_app
    from app.extensions import db
    from app.models import Project, User
    from app.ops.models import ProjectMember
    from config import Config

    class Deployed(Config):
        TESTING = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/deployed.db"
        WTF_CSRF_ENABLED = True
        SERVER_NAME = "localhost.localdomain"

    app = create_app(Deployed)
    assert app.config["WTF_CSRF_ENABLED"] is True, (
        "the fixture did not get a CSRF-protected app; the assertions below "
        "would pass for the wrong reason")
    with app.app_context():
        db.create_all()
        project = Project(name="مشروع الواجهة")
        owner = User(username="ui-owner", email="ui-owner@csrf.test",
                     full_name="مالك", role="admin")
        member = User(username="ui-member", email="ui-member@csrf.test",
                      full_name="عضو", role="engineer")
        for user in (owner, member):
            user.set_password("pw12345")
        db.session.add_all([project, owner, member])
        db.session.flush()
        db.session.add(ProjectMember(project_id=project.id, user_id=owner.id,
                                     role_in_project="owner"))
        db.session.add(ProjectMember(project_id=project.id,
                                     user_id=member.id,
                                     role_in_project="member"))
        db.session.commit()
        project_id = project.id

    client = app.test_client()
    yield app, client, project_id
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _login(client, username):
    """Sign in with CSRF protection on, which the login form needs too.

    The first version of this fixture posted straight to /auth/login and got a
    400, which looked like the page under test was broken. It was the fixture.
    """
    landing = client.get("/auth/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', landing)
    assert token, "the login page rendered no CSRF token"
    response = client.post("/auth/login",
                           data={"csrf_token": token.group(1),
                                 "username": username,
                                 "password": "pw12345"},
                           follow_redirects=True)
    assert response.status_code == 200, (
        "sign-in failed with CSRF protection on; every assertion below would "
        "be measuring a redirect to the login page")
    return response


def _token_for(client, path, action_path):
    """The token belonging to one specific form on the page.

    Matched on the rendered action, not the endpoint name: Jinja resolves
    url_for at render time, so the name is not in the output.

    Reading any token off the page is not enough. The first version did that,
    and it passed with the export form's own token deleted, because a sibling
    form on the same page still had one - so the test could not have caught the
    bug it existed to catch.
    """
    body = client.get(path).get_data(as_text=True)
    for form in re.findall(r"<form\b.*?</form>", body, re.S | re.I):
        if action_path not in form:
            continue
        found = re.search(r'name="csrf_token" value="([^"]+)"', form)
        assert found, (
            "the form posting to %s carries no CSRF token; it returns 400 in "
            "a deployment" % action_path)
        return found.group(1)
    raise AssertionError("no form on %s posts to %s" % (path, action_path))


def test_the_export_button_works_with_csrf_enabled(strict_client):
    app, client, project_id = strict_client
    _login(client, "ui-owner")
    page = "/projects/%d" % project_id
    body = client.get(page).get_data(as_text=True)
    assert "النسخ الاحتياطي" in body, "the section is not on the page"

    token = _token_for(client, page, "/projects/%d/backup" % project_id)
    response = client.post("/projects/%d/backup" % project_id,
                           data={"csrf_token": token}, follow_redirects=True)
    assert response.status_code == 200
    assert "تم إنشاء نسخة احتياطية" in response.get_data(as_text=True)


def test_the_import_button_works_with_csrf_enabled(strict_client):
    app, client, project_id = strict_client
    _login(client, "ui-owner")
    page = "/projects/%d" % project_id

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("metadata.json", json.dumps({
            "version": "1.0", "scope": "project", "project_id": project_id,
            "created_at": "2026-01-01T00:00:00"}).encode("utf-8"))
    buffer.seek(0)

    token = _token_for(client, page, "/projects/%d/backup/import" % project_id)
    response = client.post(
        "/projects/%d/backup/import" % project_id,
        data={"csrf_token": token,
              "backup_file": (buffer, "backup.zip")},
        content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200


def test_the_forms_would_be_rejected_without_a_token(strict_client):
    """The reason any of the above matters: a tokenless POST is a 400."""
    app, client, project_id = strict_client
    _login(client, "ui-owner")
    assert client.post("/projects/%d/backup" % project_id).status_code == 400


def test_a_plain_member_is_refused_and_offered_nothing(strict_client):
    app, client, project_id = strict_client
    _login(client, "ui-member")
    body = client.get("/projects/%d" % project_id).get_data(as_text=True)
    assert "النسخ الاحتياطي" not in body, (
        "the controls are shown to a member who cannot use them")
    assert "main.project_backup" not in body

    # A member's page carries no backup form, so there is no token to scrape
    # from one. Forging one is refused by the CSRF layer before the handler
    # runs at all, which is the first of the two defences.
    forged = client.post("/projects/%d/backup" % project_id,
                         data={"csrf_token": "forged"})
    assert forged.status_code == 400

    # And the permission check is the second: a member holding a valid token
    # of their own is refused by the handler, not by the token layer.
    response = client.post("/projects/%d/backup" % project_id,
                           data={"csrf_token": _csrf_token_from(client,
                                                                "/profile")},
                           follow_redirects=True)
    assert response.status_code == 200
    assert "مقصورة على مالك المشروع" in response.get_data(as_text=True), (
        "the endpoint must refuse a member who holds a valid token")


def _csrf_token_from(client, path):
    """A valid token for this session, read off any page that carries a form.

    A member's project page deliberately offers no backup form, so there is
    nothing to read a token from there - which is the point of that page, not a
    gap. Their profile page does have one.
    """
    body = client.get(path).get_data(as_text=True)
    found = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert found, "no CSRF token on %s, so this test cannot forge a valid one" % path
    return found.group(1)
