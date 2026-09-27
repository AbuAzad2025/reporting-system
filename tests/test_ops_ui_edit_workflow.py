"""HTML-UI edit/create workflow in app/ops/routes.py: list, new, edit, feedback.

The ops JSON API is covered elsewhere; this file drives the *browser* surface
(`/ops/ui/...`) over real HTTP with the shared ``app`` / ``client`` /
``eng_client`` fixtures and asserts the exact status code, the exact Arabic
flash text and the resulting database rows after every call.

Branches targeted (previously unreached on this module):
  * ui_list      — status filter, empty-tenant branch, unknown module
  * ui_new       — GET form, successful POST, project-link guard, serial clash
  * ui_edit      — GET prefill from the stored row, successful POST, every
                   validation-error shape (enum, range floor, non-numeric,
                   malformed date, several at once), cross-tenant and
                   non-existent project_id, unknown module, anonymous
  * attachment_upload — no file part, empty file part, unusable filename,
                   unsupported type, bytes contradicting the type, storage
                   failure, commit failure, unknown module, anonymous
  * ui_comment_create / comment_delete — missing body key (UI and JSON),
                   unknown module, a comment owned by another record or another
                   kind or another tenant, author/manager gate
  * ui_submit / ui_approve — unknown module, the non-manager approval gate
  * cleanup_orphaned_attachments — a row whose storage key escapes the upload
                   root (the only path into the ``except ValueError`` arm)

DEFECTS FOUND WHILE WRITING THIS FILE (reported, deliberately NOT asserted as
correct behaviour, and no production file was touched):

1. ``POST /ops/ui/<kind>/new`` with an out-of-scope or non-existent
   ``project_id`` answers **200** and flashes the raw Werkzeug string
   ``"404 Not Found: The requested URL was not found on the server. ..."``
   instead of returning HTTP 404. Cause: ``_apply_project_link`` calls
   ``tenant_create_guard``, which ``abort(404)``s; ``ui_new`` wraps the call in
   ``except Exception`` (app/ops/routes.py:827) and ``NotFound`` is an
   ``Exception``, so the abort is downgraded to a 200 form re-render. This
   contradicts the module contract documented in its own docstring
   ("cross-tenant access returns 404") and shows an English internal message
   to Arabic field users. The sibling ``ui_edit`` performs the same guard
   outside any try/except (line 902) and correctly returns 404. Nothing is
   written and the message is identical for "foreign project" and "no such
   project", so there is no existence oracle — only the status code and the
   leaked string are wrong. ``test_new_post_cannot_write_into_another_tenant``
   therefore asserts only the invariant that stays true after a fix.
2. ``app/ops/routes.py:1254-1256`` — the route-level 4 MB guard
   (``{"error": "file exceeds 4 MB limit"}``, 413) is unreachable:
   ``Config.MAX_CONTENT_LENGTH`` is the same 4 MiB, so Werkzeug aborts the
   request first with an HTML 413 page and the JSON contract is never emitted.
   The size limit itself still holds, one layer up. Not asserted here.
3. ``app/ops/routes.py:835`` — ``KIND_MODEL[kind][1] if False else ...`` is dead
   code; ``KIND_MODEL`` maps to model classes, so the guarded branch would
   raise ``TypeError`` if it ever ran.
4. ``templates/ops/form.html:47`` renders a "ملاحظات" textarea for every
   module, but only 3 of the 9 models (site-inspections, material-submittals,
   progress-billings) have a ``notes`` column. On the other six the typed value
   is dropped by ``validate_input``'s free-text passthrough with no warning,
   and the user still gets "تم الحفظ بنجاح.". Not asserted here.
"""
import html as htmllib
import io
import os
import re
from datetime import date

from sqlalchemy.exc import IntegrityError

from tests.conftest import login_as

# --------------------------------------------------------------------- data
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24

FLASH_SAVED = ("success", "تم الحفظ بنجاح.")
FLASH_UPDATED = ("success", "تم التحديث.")
FLASH_DUPLICATE = ("danger", "تعذر الحفظ — سجل مكرر.")
FLASH_EMPTY_COMMENT = ("danger", "لا يمكن إضافة تعليق فارغ.")

#: base.html renders each flash as ``<div role="alert" class="... bg-<tone>-50">
#: <span>message</span>`` (app/../templates/base.html:56-68).
ALERT_RE = re.compile(
    r'<div role="alert" class="([^"]*)"[^>]*>\s*<span>(.*?)</span>', re.S)
TONE_OF = (("bg-green-50", "success"), ("bg-red-50", "danger"),
           ("bg-amber-50", "warning"), ("bg-blue-50", "info"))


# ------------------------------------------------------------------ helpers
def _flashes(client, response):
    """The exact (category, message) pairs the view emitted for the browser.

    A 200 re-render consumes the queue inside base.html, so those are read back
    out of the rendered alert boxes; an unfollowed 302 leaves them in the
    session cookie instead.
    """
    if response.status_code == 302:
        with client.session_transaction() as sess:
            return [tuple(item) for item in sess.pop("_flashes", [])]
    emitted = []
    for classes, message in ALERT_RE.findall(response.get_data(as_text=True)):
        tone = next(cat for needle, cat in TONE_OF if needle in classes)
        emitted.append((tone, htmllib.unescape(message.strip())))
    return emitted


def _login(client, username):
    """tests.conftest.login_as, minus the greeting flash it queues."""
    login_as(client, username)
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)


def _project(app, name):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name=name).one().id


def _row_id(app, model_name, serial):
    from app.ops import models as M
    with app.app_context():
        return getattr(M, model_name).query.filter_by(serial=serial).one().id


def _state(app, model_name, row_id, *fields):
    """Selected stored columns of one ops row, read back from the database."""
    from app.extensions import db
    from app.ops import models as M
    model = getattr(M, model_name)
    with app.app_context():
        row = db.session.get(model, row_id)
        return {name: getattr(row, name) for name in fields}


def _count(app, model_name, **filters):
    from app.ops import models as M
    with app.app_context():
        return getattr(M, model_name).query.filter_by(**filters).count()


def _listed_total(html):
    """The ``{{ total }} سجل`` figure the list header renders."""
    match = re.search(r">(\d+) سجل", html)
    assert match, "list header must render a record count"
    return int(match.group(1))


def _select(html, field_id):
    match = re.search(r'<select id="%s".*?</select>' % field_id, html, re.S)
    assert match, "missing <select id=%s>" % field_id
    return match.group(0)


def _input(html, field_id):
    match = re.search(r'<input id="%s"[^>]*>' % field_id, html)
    assert match, "missing <input id=%s>" % field_id
    return match.group(0)


def _textarea(html, field_id):
    match = re.search(
        r'<textarea id="%s"[^>]*>(.*?)</textarea>' % field_id, html, re.S)
    assert match, "missing <textarea id=%s>" % field_id
    return match.group(1).strip()


def _chip(html, label):
    """The rendered ``class`` list of the status chip carrying ``label``."""
    pattern = r'<a href="\?status=[^"]*"[^>]*class="([^"]*)"[^>]*>%s</a>' % label
    match = re.search(pattern, html)
    assert match, "no status chip labelled %r" % label
    return match.group(1)


def _row_by_field(app, model_name, **filters):
    from app.ops import models as M
    with app.app_context():
        return getattr(M, model_name).query.filter_by(**filters).one().id


def _inspection_via_form(client, app, test_type):
    """Create a second site inspection through the HTML form; return its id."""
    _login(client, "t_eng")
    r = client.post("/ops/ui/site-inspections/new", data={
        "project_id": str(_project(app, "Alpha Tower")),
        "report_date": "2026-07-15", "test_category": "concrete",
        "test_type": test_type})
    assert r.status_code == 302, r.get_data(as_text=True)[:200]
    return _row_by_field(app, "SiteInspection", test_type=test_type)


def _consultant_in_alpha(app):
    """A senior_consultant who holds approve_reports but is not a manager.

    The role is the only combination that passes
    ``@permission_required("approve_reports")`` and still fails the
    ``is_platform_manager`` audit gate inside ``ui_approve``.
    """
    from app.extensions import db
    from app.models import Project, User
    from app.ops.models import ProjectMember
    with app.app_context():
        user = User(username="t_consultant", email="t_consultant@t.com",
                    full_name="استشاري اختبار تجريبي",
                    role="senior_consultant")
        user.set_password("pw12345")
        db.session.add(user)
        db.session.flush()
        db.session.add(ProjectMember(
            user_id=user.id,
            project_id=Project.query.filter_by(
                name="Alpha Tower").one().id))
        db.session.commit()
        return user.id


# --------------------------------------------------------------- ui_list
class TestUiListFilters:

    def _draft_rfi(self, app):
        from app.extensions import db
        from app.ops import models as M
        with app.app_context():
            db.session.get(M.RFI, self.rid).status = "draft"
            db.session.commit()

    def test_status_filter_narrows_the_listing_and_highlights_its_chip(
            self, app, client):
        self.rid = _row_id(app, "RFI", "RFI-000001")
        _login(client, "t_eng")
        unfiltered = client.get("/ops/ui/rfis")
        assert unfiltered.status_code == 200
        html = unfiltered.get_data(as_text=True)
        assert _listed_total(html) == 1
        assert "RFI-000001" in html
        assert "لا توجد سجلات" not in html
        # "الكل" chip is the active one while no filter is applied
        assert 'href="?status="' in html
        assert 'bg-navy text-white' in _chip(html, "الكل")

        # a matching filter keeps the row, a non-matching one empties the table
        self._draft_rfi(app)
        draft = client.get("/ops/ui/rfis?status=draft")
        assert draft.status_code == 200
        draft_html = draft.get_data(as_text=True)
        assert _listed_total(draft_html) == 1
        assert "RFI-000001" in draft_html
        assert "bg-amber-500 text-white" in _chip(draft_html, "مسودة")
        assert "bg-navy text-white" not in _chip(draft_html, "الكل")

        approved = client.get("/ops/ui/rfis?status=approved")
        approved_html = approved.get_data(as_text=True)
        assert approved.status_code == 200
        assert _listed_total(approved_html) == 0
        assert "RFI-000001" not in approved_html
        assert "لا توجد سجلات" in approved_html
        assert "bg-emerald-500 text-white" in _chip(approved_html, "معتمد")

    def test_a_whitespace_only_filter_is_treated_as_no_filter(self, app,
                                                               client):
        _login(client, "t_eng")
        r = client.get("/ops/ui/rfis?status=%20%20")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert _listed_total(html) == 1
        assert "RFI-000001" in html
        assert "bg-navy text-white" in _chip(html, "الكل")

    def test_filtered_out_rows_are_not_leaked_into_the_count(self, app,
                                                             client):
        _login(client, "t_eng")
        client.post("/ops/ui/safety-reports/new", data={
            "project_id": str(_project(app, "Alpha Tower")),
            "report_date": "2026-07-02", "area": "الدور الخامس",
            "hazard": "سقوط من الرافعة", "risk_level": "مرتفع"})
        assert _count(app, "SafetyReport", hazard="سقوط من الرافعة") == 1
        everything = client.get("/ops/ui/safety-reports").get_data(as_text=True)
        assert _listed_total(everything) == 2  # HSR-000001 + the new one
        pending_only = client.get(
            "/ops/ui/safety-reports?status=pending").get_data(as_text=True)
        assert _listed_total(pending_only) == 2
        draft_only = client.get(
            "/ops/ui/safety-reports?status=draft").get_data(as_text=True)
        assert _listed_total(draft_only) == 0
        assert "لا توجد سجلات" in draft_only

    def test_listing_shows_the_project_name_of_each_visible_row(
            self, app, eng_client):
        html = eng_client.get("/ops/ui/rfis").get_data(as_text=True)
        assert "Alpha Tower" in html
        assert "Beta Hospital" not in html  # not a member project

    def test_listing_is_tenant_scoped(self, app, client):
        _login(client, "t_eng")
        assert "CVR-000002" not in client.get(
            "/ops/ui/cost-variances").get_data(as_text=True)
        _login(client, "t_eng2")
        other = client.get("/ops/ui/cost-variances").get_data(as_text=True)
        assert _listed_total(other) == 1
        assert "CVR-000002" in other
        assert "CVR-000001" not in other

    def test_listing_for_an_unknown_module_is_404(self, eng_client):
        r = eng_client.get("/ops/ui/not-a-module")
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}
        detail = eng_client.get("/ops/ui/not-a-module/1")
        assert detail.status_code == 404
        assert detail.get_json() == {"error": "unknown module"}

    def test_detail_page_renders_the_redirect_target_of_a_form_post(self, app,
                                                                    eng_client):
        r = eng_client.post("/ops/ui/rfis/new", data={
            "project_id": str(_project(app, "Alpha Tower")),
            "report_date": "2026-08-07", "subject": "استفسار بعد الحفظ",
            "question": "هل مخطط التنفيذ محدّث؟", "ball_in_court": "client",
            "priority": "low"})
        assert r.status_code == 302
        page = eng_client.get(r.headers["Location"])
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "طلبات الاستفسار (RFI)" in html  # module title
        assert "Alpha Tower" in html  # resolved project name, not the id
        assert "RFI-000002" in html
        assert "استفسار بعد الحفظ" in html
        assert "قيد المراجعة" in html  # default workflow status
        assert "مهندس اختبار تجريبي عام" in html  # signatory snapshot
        new_id = r.headers["Location"].rsplit("/", 1)[-1]
        assert f'/ops/ui/rfis/{new_id}/edit' in html
        assert f'/ops/rfis/{new_id}/pdf' in html

    def test_listing_requires_login(self, client):
        client.get("/auth/logout")
        r = client.get("/ops/ui/rfis")
        assert r.status_code == 401
        assert r.get_json() == {"error": "authentication required"}


def _chip(html, label):
    """The rendered ``class`` list of the status chip carrying ``label``."""
    pattern = r'<a href="\?status=[^"]*"[^>]*class="([^"]*)"[^>]*>%s</a>' % label
    match = re.search(pattern, html)
    assert match, "no status chip labelled %r" % label
    return match.group(1)


# ---------------------------------------------------------------- ui_edit
class TestUiEditFormRendering:

    def test_edit_form_is_prefilled_from_the_stored_record(self, app,
                                                           client):
        rid = _row_id(app, "RFI", "RFI-000001")
        stored = _state(app, "RFI", rid, "subject", "question",
                        "ball_in_court", "priority", "report_date")
        alpha = _project(app, "Alpha Tower")
        _login(client, "t_eng")
        r = client.get(f"/ops/ui/rfis/{rid}/edit")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "✏️ تعديل طلبات الاستفسار (RFI)" in html
        assert "💾 تحديث" in html
        # picker: the record's own project is preselected, and only projects the
        # user is a member of are offered
        picker = _select(html, "project_id")
        assert '<option value="%d" selected>Alpha Tower</option>' % alpha \
            in picker
        assert "Beta Hospital" not in html
        # text / textarea / enum / date fields all carry the stored value
        assert 'value="%s"' % stored["subject"] in _input(html, "f_subject")
        assert _textarea(html, "f_question") == stored["question"]
        assert '<option value="%s" selected>' % stored["ball_in_court"] \
            in _select(html, "f_ball_in_court")
        assert '<option value="%s" selected>' % stored["priority"] \
            in _select(html, "f_priority")
        assert 'value="%s"' % stored["report_date"].isoformat() in \
            re.search(r'<input id="report_date"[^>]*>', html).group(0)
        # Arabic labels, never the raw schema key
        assert '<label class="form-label" for="f_subject">الموضوع' in html

    def test_edit_form_renders_no_audit_or_workflow_input(self, app, eng_client):
        rid = _row_id(app, "RFI", "RFI-000001")
        html = eng_client.get(f"/ops/ui/rfis/{rid}/edit").get_data(as_text=True)
        for protected in ("serial", "status", "version", "root_id",
                          "supersedes_id", "user_id", "reviewed_by_id",
                          "reviewed_at", "signatory_name", "review_notes",
                          "created_at", "updated_at"):
            assert 'name="%s"' % protected not in html, protected

    def test_manager_picker_offers_every_project_but_preselects_the_stored_one(
            self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        alpha = _project(app, "Alpha Tower")
        beta = _project(app, "Beta Hospital")
        _login(client, "t_admin")
        r = client.get(f"/ops/ui/rfis/{rid}/edit")
        assert r.status_code == 200
        picker = _select(r.get_data(as_text=True), "project_id")
        assert '<option value="%d" selected>Alpha Tower</option>' % alpha \
            in picker
        assert '<option value="%d" >Beta Hospital</option>' % beta in picker

    def test_edit_form_of_another_tenant_is_404(self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        _login(client, "t_eng2")
        r = client.get(f"/ops/ui/rfis/{rid}/edit")
        assert r.status_code == 404
        assert _state(app, "RFI", rid, "subject")["subject"] == "clash"

    def test_edit_form_for_an_unknown_module_is_404(self, eng_client):
        r = eng_client.get("/ops/ui/not-a-module/1/edit")
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}

    def test_edit_form_requires_login(self, client):
        client.get("/auth/logout")
        r = client.get("/ops/ui/rfis/1/edit")
        assert r.status_code == 401
        assert r.get_json() == {"error": "authentication required"}


# ------------------------------------------------------- ui_edit: the POST
class TestUiEditUpdate:

    def test_valid_post_updates_the_record_and_redirects_to_the_detail_page(
            self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        before = _state(app, "RFI", rid, "serial", "status", "version",
                        "user_id", "subject")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"subject": "تعارض مع خط الأنابيب",
                              "question": "خط الأنابيب يقطع البلاطة",
                              "delay_days": "6", "priority": "critical"})
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/ops/ui/rfis/{rid}")
        assert _flashes(client, r) == [FLASH_UPDATED]
        after = _state(app, "RFI", rid, "subject", "question", "delay_days",
                       "priority")
        assert after == {"subject": "تعارض مع خط الأنابيب",
                         "question": "خط الأنابيب يقطع البلاطة",
                         "delay_days": 6.0, "priority": "critical"}
        untouched = _state(app, "RFI", rid, "serial", "status", "version",
                           "user_id")
        assert untouched == {k: before[k] for k in untouched}
        # the redirect target really renders the new values
        page = client.get(r.headers["Location"])
        assert page.status_code == 200
        assert "تعارض مع خط الأنابيب" in page.get_data(as_text=True)

    def test_re_posting_the_same_project_is_accepted(self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        alpha = _project(app, "Alpha Tower")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"project_id": str(alpha), "priority": "low"})
        assert r.status_code == 302
        assert _flashes(client, r) == [FLASH_UPDATED]
        state = _state(app, "RFI", rid, "project_id", "priority")
        assert state == {"project_id": alpha, "priority": "low"}

    def test_a_rejected_enum_re_renders_the_form_and_keeps_the_row(
            self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        before = _state(app, "RFI", rid, "subject", "priority", "version")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"subject": "مسودة لم تُحفظ",
                              "priority": "urgent"})
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger", "قيمة غير مسموحة في «الأولوية» — المسموح: "
            "منخفضة، عادية، عالية، حرجة.")]
        html = r.get_data(as_text=True)
        assert "✏️ تعديل" in html  # the edit form, not a redirect
        assert 'value="مسودة لم تُحفظ"' in html  # the user's input survives
        after = _state(app, "RFI", rid, "subject", "priority", "version")
        assert after == before

    def test_a_number_below_the_allowed_floor_is_refused(self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"delay_days": "-5", "subject": "سالب"})
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "«أيام التأخير» يجب أن يكون ≥ 0.")]
        assert _state(app, "RFI", rid, "delay_days", "subject") == \
            {"delay_days": 0.0, "subject": "clash"}

    def test_a_non_numeric_field_is_refused(self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit", data={"delay_days": "أربع"})
        assert r.status_code == 200
        assert _flashes(client, r) == [("danger", "«أيام التأخير» يجب أن يكون رقماً.")]
        assert _state(app, "RFI", rid, "delay_days")["delay_days"] == 0.0

    def test_a_malformed_date_is_refused(self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"reply_due": "20/06/2026"})
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger", "التاريخ غير صالح في «تاريخ الرد المطلوب» — "
            "الصيغة المطلوبة YYYY-MM-DD.")]
        assert _state(app, "RFI", rid, "reply_due")["reply_due"] is None

    def test_several_errors_are_all_reported_in_order(self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"priority": "urgent", "delay_days": "-2",
                              "reply_due": "20-06-2026"})
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "قيمة غير مسموحة في «الأولوية» — المسموح: "
             "منخفضة، عادية، عالية، حرجة."),
            ("danger", "«أيام التأخير» يجب أن يكون ≥ 0."),
            ("danger", "التاريخ غير صالح في «تاريخ الرد المطلوب» — "
             "الصيغة المطلوبة YYYY-MM-DD."),
        ]
        state = _state(app, "RFI", rid, "priority", "delay_days", "reply_due")
        assert state == {"priority": "normal", "delay_days": 0.0,
                         "reply_due": None}

    def test_a_cross_tenant_project_id_in_the_form_is_refused(self, app,
                                                              client):
        rid = _row_id(app, "RFI", "RFI-000001")
        alpha = _project(app, "Alpha Tower")
        beta = _project(app, "Beta Hospital")
        before = _state(app, "RFI", rid, "project_id", "subject", "priority")
        assert before["project_id"] == alpha
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"project_id": str(beta), "subject": "نقل"})
        assert r.status_code == 404
        after = _state(app, "RFI", rid, "project_id", "subject", "priority")
        assert after == before  # nothing moved, nothing overwritten
        assert _count(app, "RFI") == 1

    def test_a_non_existent_project_id_is_refused(self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        alpha = _project(app, "Alpha Tower")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit",
                        data={"project_id": "987654"})
        assert r.status_code == 404
        assert _state(app, "RFI", rid, "project_id")["project_id"] == alpha

    def test_an_empty_form_submits_nothing_but_still_confirms(self, app,
                                                              client):
        rid = _row_id(app, "RFI", "RFI-000001")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/rfis/{rid}/edit", data={})
        assert r.status_code == 302
        assert _flashes(client, r) == [FLASH_UPDATED]
        state = _state(app, "RFI", rid, "subject", "question", "priority",
                       "project_id", "serial", "version")
        assert state == {"subject": "clash", "question": "duct vs beam?",
                         "priority": "normal",
                         "project_id": _project(app, "Alpha Tower"),
                         "serial": "RFI-000001", "version": 1}

    def test_edit_post_for_an_unknown_module_is_404(self, client):
        _login(client, "t_eng")
        r = client.post("/ops/ui/not-a-module/1/edit", data={"subject": "x"})
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}

    def test_edit_post_requires_login(self, client):
        client.get("/auth/logout")
        r = client.post("/ops/ui/rfis/1/edit", data={"subject": "x"})
        assert r.status_code == 401
        assert r.get_json() == {"error": "authentication required"}


# ---------------------------------------------------------------- ui_new
class TestUiNew:

    def test_new_form_renders_an_unselected_picker_and_no_stored_values(
            self, eng_client):
        r = eng_client.get("/ops/ui/rfis/new")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "➕ إنشاء طلبات الاستفسار (RFI)" in html
        assert "💾 حفظ" in html
        picker = _select(html, "project_id")
        assert "selected" not in picker
        assert "Alpha Tower" in picker and "Beta Hospital" not in picker
        assert 'name="report_date" type="date" required value=""' in html
        assert 'value="" class="form-control">' in _input(html, "f_subject")
        assert '<option value="">— اختر —</option>' in \
            _select(html, "f_ball_in_court")

    def test_daily_report_form_omits_the_json_workflow_tables(self, eng_client):
        html = eng_client.get("/ops/ui/daily-reports/new").get_data(as_text=True)
        assert '<select id="f_weather"' in html
        assert "مشمس" in html  # the reference-data enum, not a free-text input
        for table in ("labor_table", "equipment_table", "work_fronts"):
            assert 'name="%s"' % table not in html, table
        assert 'id="f_labor_count"' in html

    def test_rfi_form_post_creates_the_row_and_redirects_to_the_detail_page(
            self, app, client):
        alpha = _project(app, "Alpha Tower")
        _login(client, "t_eng")
        r = client.post("/ops/ui/rfis/new", data={
            "project_id": str(alpha), "report_date": "2026-08-03",
            "subject": "تداخل التكييف مع Beam",
            "question": "مجرى الهواء يمر داخل Beam؟",
            "ball_in_court": "consultant", "priority": "high",
            "cost_impact": "pending", "discipline": "MEP",
            "reply_due": "2026-08-20"})
        assert r.status_code == 302
        assert _flashes(client, r) == [FLASH_SAVED]
        rec_id = _row_by_field(app, "RFI", subject="تداخل التكييف مع Beam")
        from app.models import User
        with app.app_context():
            author = User.query.filter_by(username="t_eng").one()
        assert r.headers["Location"].endswith(f"/ops/ui/rfis/{rec_id}")
        state = _state(app, "RFI", rec_id, "serial", "project_id", "status",
                       "version", "user_id", "signatory_name", "report_date",
                       "subject", "question", "ball_in_court", "priority",
                       "cost_impact", "discipline", "reply_due", "delay_days",
                       "reviewed_by_id", "reviewed_at")
        assert state == {
            "serial": "RFI-000002", "project_id": alpha, "status": "pending",
            "version": 1, "user_id": author.id,
            "signatory_name": "مهندس اختبار تجريبي عام",
            "report_date": date(2026, 8, 3),
            "subject": "تداخل التكييف مع Beam",
            "question": "مجرى الهواء يمر داخل Beam؟",
            "ball_in_court": "consultant", "priority": "high",
            "cost_impact": "pending", "discipline": "mep",
            "reply_due": date(2026, 8, 20), "delay_days": 0.0,
            "reviewed_by_id": None, "reviewed_at": None}
        page = client.get(r.headers["Location"])
        assert page.status_code == 200
        assert "RFI-000002" in page.get_data(as_text=True)

    def test_site_inspection_form_post_creates_the_row_with_cast_numbers(
            self, app, client):
        alpha = _project(app, "Alpha Tower")
        _login(client, "t_eng")
        r = client.post("/ops/ui/site-inspections/new", data={
            "project_id": str(alpha), "report_date": "2026-08-04",
            "test_category": "concrete", "test_type": "cube 28d",
            "result_value": "31", "acceptance_min": "25",
            "acceptance_max": "35", "slump": "75", "verdict": "pass",
            "lab_name": "مختبر الرياض", "notes": "مرفق كسرات المكعبات"})
        assert r.status_code == 302
        assert _flashes(client, r) == [FLASH_SAVED]
        rec_id = _row_by_field(app, "SiteInspection", test_type="cube 28d")
        state = _state(app, "SiteInspection", rec_id, "serial", "status",
                       "result_value", "acceptance_min", "acceptance_max",
                       "slump", "verdict", "lab_name", "notes",
                       "test_category", "project_id")
        assert state == {
            "serial": "SIR-000002", "status": "pending", "result_value": 31.0,
            "acceptance_min": 25.0, "acceptance_max": 35.0, "slump": 75.0,
            "verdict": "pass", "lab_name": "مختبر الرياض",
            "notes": "مرفق كسرات المكعبات", "test_category": "concrete",
            "project_id": alpha}
        assert r.headers["Location"].endswith(
            f"/ops/ui/site-inspections/{rec_id}")

    def test_missing_required_fields_are_all_listed_and_nothing_is_written(
            self, app, client):
        _login(client, "t_eng")
        r = client.post("/ops/ui/rfis/new", data={"project_id": ""})
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "«المشروع» حقل مطلوب."),
            ("danger", "«الموضوع» حقل مطلوب."),
            ("danger", "«نص الاستفسار» حقل مطلوب."),
            ("danger", "«المشروع» يجب أن يكون رقم مشروع صالح — اختره من القائمة."),
        ]
        assert "➕ إنشاء" in r.get_data(as_text=True)
        assert _count(app, "RFI") == 1  # only the seeded row

    def test_a_result_below_the_acceptance_window_is_refused(
            self, app, client):
        alpha = _project(app, "Alpha Tower")
        _login(client, "t_eng")
        r = client.post("/ops/ui/site-inspections/new", data={
            "project_id": str(alpha), "report_date": "2026-08-05",
            "test_category": "concrete", "test_type": "cube 14d",
            "result_value": "10", "acceptance_min": "25"})
        assert r.status_code == 200
        assert _flashes(client, r) == [(
            "danger", "نتيجة القياس (10.0) أقل من الحد الأدنى للقبول (25.0) — "
            "يتطلب تقرير عدم مطابقة (NCR).")]
        assert _count(app, "SiteInspection", test_type="cube 14d") == 0

    def test_a_duplicate_serial_is_reported_without_writing(
            self, app, client, monkeypatch):
        from app.ops import routes
        alpha = _project(app, "Alpha Tower")
        _login(client, "t_eng")
        monkeypatch.setattr(routes, "next_serial",
                            lambda *a, **k: "RFI-000001")
        r = client.post("/ops/ui/rfis/new", data={
            "project_id": str(alpha), "subject": "تكرار",
            "question": "سؤال"})
        assert r.status_code == 200
        assert _flashes(client, r) == [FLASH_DUPLICATE]
        assert _count(app, "RFI") == 1
        assert _count(app, "RFI", subject="تكرار") == 0
        assert "➕ إنشاء" in r.get_data(as_text=True)

    def test_new_post_cannot_write_into_another_tenant(self, app, eng_client):
        """Security invariant only — see DEFECT 1 in the module docstring.

        Asserted: nothing is created for the foreign project and the request
        never hands back a redirect to a new record. Deliberately *not*
        asserted: the status code, which is 200 today because ``ui_new``
        swallows the ``abort(404)`` of ``tenant_create_guard``.
        """
        beta = _project(app, "Beta Hospital")
        r = eng_client.post("/ops/ui/rfis/new", data={
            "project_id": str(beta), "subject": "تسريب عبر النموذج",
            "question": "سؤال"})
        assert "Location" not in r.headers
        assert _count(app, "RFI") == 1
        assert _count(app, "RFI", project_id=beta) == 0
        assert _count(app, "RFI", subject="تسريب عبر النموذج") == 0

    def test_a_non_numeric_project_id_is_refused_without_writing(self, app,
                                                                 client):
        _login(client, "t_eng")
        r = client.post("/ops/ui/rfis/new", data={
            "project_id": "ألف", "subject": "مشروع غير رقمي", "question": "سؤال"})
        assert r.status_code == 200
        assert _flashes(client, r) == [
            ("danger", "«المشروع» يجب أن يكون رقم مشروع صالح — اختره من القائمة.")]
        assert _count(app, "RFI", subject="مشروع غير رقمي") == 0

    def test_new_for_an_unknown_module_is_404_on_both_verbs(self, eng_client):
        assert eng_client.get("/ops/ui/not-a-module/new").status_code == 404
        r = eng_client.post("/ops/ui/not-a-module/new", data={"subject": "x"})
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}

    def test_new_requires_login(self, client):
        client.get("/auth/logout")
        for method in (client.get, client.post):
            r = method("/ops/ui/rfis/new")
            assert r.status_code == 401
            assert r.get_json() == {"error": "authentication required"}


# -------------------------------------------------------- attachment upload
class TestAttachmentUploadRejections:
    """Every refusal path of POST /ops/<kind>/<id>/attachments.

    Each one must answer before a row or a byte reaches the disk.
    """

    URL = "/ops/site-inspections/{rid}/attachments"

    def _upload(self, client, rid, data):
        return client.post(self.URL.format(rid=rid), data=data)

    def _none_stored(self, app, rid):
        assert _count(app, "Attachment", record_id=rid) == 0

    def _files_on_disk(self, app):
        root = os.path.join(app.config["UPLOAD_FOLDER"], "ops")
        found = []
        for dirpath, _dirs, names in os.walk(root):
            found.extend(os.path.join(dirpath, n) for n in names)
        return found

    def test_a_request_without_a_file_part_is_400(self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        r = self._upload(eng_client, rid, {})
        assert r.status_code == 400
        assert r.get_json() == {"error": "no file part"}
        self._none_stored(app, rid)
        assert self._files_on_disk(app) == []

    def test_a_file_part_that_is_present_but_empty_is_400(self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        r = self._upload(eng_client, rid, {"file": (io.BytesIO(b""), "")})
        assert r.status_code == 400
        assert r.get_json() == {"error": "empty filename"}
        self._none_stored(app, rid)
        assert self._files_on_disk(app) == []

    def test_a_filename_with_no_usable_character_is_400(self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        r = self._upload(eng_client, rid, {"file": (io.BytesIO(JPEG), "...")})
        assert r.status_code == 400
        assert r.get_json() == {"error": "invalid filename"}
        self._none_stored(app, rid)
        assert self._files_on_disk(app) == []

    def test_a_declared_type_outside_the_allow_list_is_415(self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        r = self._upload(eng_client, rid,
                         {"file": (io.BytesIO(b"plain text"),
                                   "evidence.txt")})
        assert r.status_code == 415
        assert r.get_json() == {"error": "unsupported type: text/plain"}
        self._none_stored(app, rid)

    def test_bytes_contradicting_the_declared_type_are_415(self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        r = self._upload(eng_client, rid, {"file": (io.BytesIO(PNG), "shot.jpg")})
        assert r.status_code == 415
        assert r.get_json() == {
            "error": "content does not match type: image/jpeg"}
        self._none_stored(app, rid)
        assert self._files_on_disk(app) == []
        r2 = self._upload(eng_client, rid,
                          {"file": (io.BytesIO(b"MZ exe"), "x.jpg")})
        assert r2.status_code == 415
        assert r2.get_json() == {
            "error": "content does not match type: image/jpeg"}
        self._none_stored(app, rid)

    def test_an_unwritable_storage_path_answers_500_and_stores_nothing(
            self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        # a regular file where the per-record directory must be created
        blocker = os.path.join(app.config["UPLOAD_FOLDER"], "ops",
                               "site-inspections", str(rid))
        os.makedirs(os.path.dirname(blocker), exist_ok=True)
        with open(blocker, "wb") as fh:
            fh.write(b"not-a-directory")
        r = self._upload(eng_client, rid, {"file": (io.BytesIO(JPEG), "shot.jpg")})
        assert r.status_code == 500
        assert r.get_json() == {"error": "storage failure"}
        self._none_stored(app, rid)
        with open(blocker, "rb") as fh:
            assert fh.read() == b"not-a-directory"  # the blocker survives

    def test_a_commit_failure_rolls_back_the_row_and_removes_the_bytes(
            self, app, eng_client, monkeypatch):
        from app.extensions import db
        rid = _row_id(app, "SiteInspection", "SIR-000001")

        def boom():
            raise IntegrityError("INSERT", {}, Exception("uq_storage_key"))

        monkeypatch.setattr(db.session, "commit", boom)
        r = self._upload(eng_client, rid, {"file": (io.BytesIO(JPEG), "shot.jpg")})
        assert r.status_code == 500
        assert r.get_json() == {"error": "could not save attachment"}
        monkeypatch.undo()
        self._none_stored(app, rid)
        assert self._files_on_disk(app) == []  # no orphan bytes

    def test_upload_for_an_unknown_module_is_404(self, eng_client):
        r = eng_client.post("/ops/not-a-module/1/attachments",
                            data={"file": (io.BytesIO(JPEG), "shot.jpg")})
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}

    def test_upload_for_another_tenant_is_404(self, app, client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        _login(client, "t_eng2")
        r = self._upload(client, rid, {"file": (io.BytesIO(JPEG), "shot.jpg")})
        assert r.status_code == 404
        self._none_stored(app, rid)

    def test_upload_requires_login(self, client):
        client.get("/auth/logout")
        r = client.post("/ops/site-inspections/1/attachments",
                        data={"file": (io.BytesIO(JPEG), "shot.jpg")})
        assert r.status_code == 401
        assert r.get_json() == {"error": "authentication required"}

    def test_every_attachment_endpoint_rejects_an_unknown_module(self, app,
                                                                 eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        att = eng_client.post(f"/ops/site-inspections/{rid}/attachments",
                              data={"file": (io.BytesIO(JPEG), "shot.jpg")})
        assert att.status_code == 201
        att_id = att.get_json()["id"]
        calls = (eng_client.get("/ops/not-a-module/1/attachments"),
                 eng_client.get("/ops/not-a-module/1/attachments/1/download"),
                 eng_client.delete("/ops/not-a-module/1/attachments/1"))
        for r in calls:
            assert r.status_code == 404, r
            assert r.get_json() == {"error": "unknown module"}
        # the live attachment is untouched by the unknown-module probes
        assert _count(app, "Attachment", id=att_id) == 1


# --------------------------------------------------------------- feedback
class TestCommentBranches:

    def test_ui_comment_without_a_body_key_is_refused(self, app, client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        _login(client, "t_eng")
        r = client.post(f"/ops/ui/site-inspections/{rid}/comment", data={})
        assert r.status_code == 302
        assert r.headers["Location"].endswith(f"/ops/ui/site-inspections/{rid}")
        assert _flashes(client, r) == [FLASH_EMPTY_COMMENT]
        assert _count(app, "OpsRecordComment", record_id=rid) == 0

    def test_json_comment_without_a_body_key_is_422(self, app, client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        _login(client, "t_eng")
        r = client.post(f"/ops/site-inspections/{rid}/comments",
                        data={"note": "خطأ في اسم الحقل"})
        assert r.status_code == 422
        assert r.get_json() == {"error": "validation failed",
                                "details": ["نص التعليق مطلوب."]}
        assert _count(app, "OpsRecordComment", record_id=rid) == 0

    def test_a_comment_is_still_written_when_the_body_key_is_present(
            self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        r = eng_client.post(f"/ops/site-inspections/{rid}/comments",
                            data={"body": "   يتبع الرفع   "})
        assert r.status_code == 201
        body = r.get_json()
        assert body["body"] == "يتبع الرفع"  # stripped
        assert body["record_id"] == rid
        assert body["party"] == "contractor"
        assert _state(app, "OpsRecordComment", body["id"],
                      "body")["body"] == "يتبع الرفع"

    def test_comment_on_an_unknown_module_is_404(self, app, client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        _login(client, "t_eng")
        ui = client.post("/ops/ui/not-a-module/1/comment", data={"body": "x"})
        assert ui.status_code == 404
        assert ui.get_json() == {"error": "unknown module"}
        api = client.post("/ops/not-a-module/1/comments", json={"body": "x"})
        assert api.status_code == 404
        assert api.get_json() == {"error": "unknown module"}
        assert _count(app, "OpsRecordComment", record_id=rid) == 0

    def test_deleting_a_comment_belonging_to_another_record_is_404(
            self, app, client):
        first = _row_id(app, "SiteInspection", "SIR-000001")
        second = _inspection_via_form(client, app, "cube 90d")
        rfi = _row_id(app, "RFI", "RFI-000001")
        assert len({first, second}) == 2
        _login(client, "t_eng")
        cmt = client.post(f"/ops/site-inspections/{first}/comments",
                          json={"body": "ملاحظة على الفحص"}).get_json()
        # same module, a different record
        r = client.delete(
            f"/ops/site-inspections/{second}/comments/{cmt['id']}")
        assert r.status_code == 404
        assert r.get_json() == {"error": "not found"}
        # a different module, the same record
        r2 = client.delete(f"/ops/rfis/{first}/comments/{cmt['id']}")
        assert r2.status_code == 404
        assert r2.get_json() == {"error": "not found"}
        # and a record the user is not even a member of: the tenant guard
        # aborts before the JSON branch, so the body is the 404 page
        _login(client, "t_eng2")
        r3 = client.delete(
            f"/ops/site-inspections/{first}/comments/{cmt['id']}")
        assert r3.status_code == 404
        assert r3.mimetype == "text/html"
        assert "الصفحة غير موجودة" in r3.get_data(as_text=True)
        assert _count(app, "OpsRecordComment", id=cmt["id"]) == 1
        assert _state(app, "OpsRecordComment", cmt["id"],
                      "body")["body"] == "ملاحظة على الفحص"

    def test_comment_delete_needs_the_author_or_a_platform_manager(self, app,
                                                                    client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        _login(client, "t_eng")
        cmt = client.post(f"/ops/site-inspections/{rid}/comments",
                          json={"body": "ملاحظة مهندس"}).get_json()
        _login(client, "t_safety")
        denied = client.delete(
            f"/ops/site-inspections/{rid}/comments/{cmt['id']}")
        assert denied.status_code == 403
        assert denied.get_json() == {
            "error": "only author or manager may delete"}
        assert _count(app, "OpsRecordComment", id=cmt["id"]) == 1
        _login(client, "t_admin")
        allowed = client.delete(
            f"/ops/site-inspections/{rid}/comments/{cmt['id']}")
        assert allowed.status_code == 200
        assert allowed.get_json() == {"deleted": cmt["id"]}
        assert _count(app, "OpsRecordComment", id=cmt["id"]) == 0

    def test_comment_delete_for_an_unknown_module_is_404(self, app, client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        _login(client, "t_eng")
        cmt = client.post(f"/ops/site-inspections/{rid}/comments",
                          json={"body": "ملاحظة"}).get_json()
        r = client.delete(f"/ops/not-a-module/1/comments/{cmt['id']}")
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}
        assert _count(app, "OpsRecordComment", id=cmt["id"]) == 1

    def test_comment_endpoints_require_login(self, client):
        client.get("/auth/logout")
        calls = (client.post("/ops/site-inspections/1/comments",
                             json={"body": "x"}),
                 client.post("/ops/ui/site-inspections/1/comment",
                             data={"body": "x"}),
                 client.delete("/ops/site-inspections/1/comments/1"))
        for r in calls:
            assert r.status_code == 401
            assert r.get_json() == {"error": "authentication required"}

    def test_comment_list_rejects_an_unknown_module(self, app, eng_client):
        rid = _row_id(app, "SiteInspection", "SIR-000001")
        r = eng_client.get("/ops/not-a-module/1/comments")
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}
        assert _count(app, "OpsRecordComment", record_id=rid) == 0


# ------------------------------------------------- submit / approve guards
class TestUiWorkflowEndpoints:
    """The remaining HTML-UI verbs next to edit: submit and approve."""

    def test_submit_rejects_an_unknown_module(self, eng_client):
        r = eng_client.post("/ops/ui/not-a-module/1/submit")
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}

    def test_approve_rejects_an_unknown_module(self, client):
        # approve_reports is required to reach the resolver at all
        _login(client, "t_admin")
        r = client.post("/ops/ui/not-a-module/1/approve")
        assert r.status_code == 404
        assert r.get_json() == {"error": "unknown module"}

    def test_approve_is_permission_gated_before_the_module_is_resolved(
            self, client):
        _login(client, "t_eng")
        r = client.post("/ops/ui/rfis/1/approve")
        assert r.status_code == 403
        assert r.get_json() == {"error": "insufficient permissions"}

    def test_approve_is_refused_for_an_approver_that_is_not_a_manager(
            self, app, client):
        rid = _row_id(app, "RFI", "RFI-000001")
        _consultant_in_alpha(app)
        _login(client, "t_consultant")
        r = client.post(f"/ops/ui/rfis/{rid}/approve")
        assert r.status_code == 403
        assert r.mimetype == "text/html"
        assert "لا تملك صلاحية الوصول" in r.get_data(as_text=True)
        state = _state(app, "RFI", rid, "status", "reviewed_by_id",
                       "reviewed_at", "version")
        assert state == {"status": "pending", "reviewed_by_id": None,
                         "reviewed_at": None, "version": 1}


# ------------------------------------------------- orphan cleanup (CLI path)
class TestCleanupTamperedStorageKey:
    """``cleanup_orphaned_attachments`` on a row whose key escapes the root.

    ``_abs_path`` raises ValueError for such a key, so the file must be
    reported as missing and the row must survive: it is a live attachment for
    a live record, not an orphan.
    """

    def test_cli_counts_a_tampered_key_as_missing_and_keeps_the_row(
            self, app, client):
        from app.extensions import db
        from app.ops.models import Attachment
        _login(client, "t_admin")
        with app.app_context():
            db.session.add(Attachment(
                record_kind="site-inspections", record_id=1, project_id=1,
                filename="tampered.jpg",
                storage_key="../../../../escaped.jpg",
                mime_type="image/jpeg", byte_size=10, uploaded_by=1))
            db.session.commit()
            before = Attachment.query.count()
        result = app.test_cli_runner().invoke(
            args=["cleanup-orphaned-attachments"])
        assert result.exit_code == 0
        assert "orphan rows: 0" in result.output
        assert "orphan files: 0" in result.output
        assert "rows missing files: 1" in result.output
        with app.app_context():
            assert Attachment.query.count() == before
            assert Attachment.query.filter_by(
                filename="tampered.jpg").one().storage_key == \
                "../../../../escaped.jpg"
