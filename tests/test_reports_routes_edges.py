"""app/reports/routes.py — the branches a malformed submission runs into.

Six statements here had never executed, and they are the ones that decide
whether bad input becomes a stored submission or a readable error.

The interesting ones are the checks that only fire on a specific shape of
input. A checklist row that ticks both "done" and "not done" is contradictory;
nobody types it by accident, so it survived every happy-path test. And the
geolocation auto-tag is wrapped in a bare `except` for a reason - it must never
take the submission down with it.
"""
import pytest
from flask import url_for

from app.reports import routes
from app.reports.routes import _collect_dynamic, _table_rows_map


# --------------------------------------------------------------- helpers

def _url(app, endpoint, **kw):
    """url_for outside a request, the way the real code will be called.

    Building a URL needs a request context. Some tests here also leaned on an
    application context left over from an earlier test, which is why they passed
    locally and failed in the CI coverage job where the whole suite shares one
    process.
    """
    with app.test_request_context():
        return url_for(endpoint, **kw)


def _cols():
    return [
        {"key": "item", "label_ar": "البند", "type": "text",
         "required": False, "options": []},
        {"key": "done", "label_ar": "تم", "type": "checkbox",
         "required": False, "options": []},
        {"key": "not_done", "label_ar": "لم يتم", "type": "checkbox",
         "required": False, "options": []},
    ]


def _template_with_checklist(app, key="chk"):
    """A template with one table field carrying done / not_done columns."""
    from app.models import ReportTemplate, DynamicField, db
    with app.app_context():
        tpl = ReportTemplate(key=key, name_ar="قائمة فحص")
        db.session.add(tpl)
        db.session.flush()
        db.session.add(DynamicField(
            template_id=tpl.id, field_key="tbl", label_ar="البنود",
            field_type="table", required=False, position=0,
            sub_fields=_cols()))
        db.session.commit()
        return tpl.id


# ============================ a stored file of a type we do not serve

def test_a_file_of_a_disallowed_type_is_not_served(client, app, monkeypatch,
                                                   tmp_path):
    """dyn_file serves from a fixed allowlist of MIME types.

    The extension is what decides it, so a .txt sitting in the uploads tree -
    or anything an uploader renamed to look harmless - must be a 404 rather
    than a download served as text/plain from our own origin.

    The key has to start with reports/ and name a file that exists, or the
    request is turned away by the two earlier guards and this one is never
    reached - which is what happened the first time this was written.
    """
    from tests.conftest import login_as
    login_as(client, "t_admin")
    note = tmp_path / "note.txt"
    note.write_text("x", encoding="utf-8")
    monkeypatch.setattr(routes, "_abs_dyn_file", lambda k: str(note))
    with app.test_request_context("/reports/dyn/file/reports/note.txt"):
        r = client.get(_url(app, "reports.dyn_file", key="reports/note.txt"))
    assert r.status_code == 404, f"served a disallowed type as {r.status_code}"


def test_a_key_outside_the_reports_directory_is_refused_before_the_type_check(
        client, app, monkeypatch, tmp_path):
    """The guard above the type check, as its own case.

    Without this the test above would pass even if the prefix guard stopped
    existing, because both end in a 404.
    """
    from tests.conftest import login_as
    login_as(client, "t_admin")
    asked = []
    monkeypatch.setattr(
        routes, "_abs_dyn_file",
        lambda k: asked.append(k) or str(tmp_path / "note.txt"))
    with app.test_request_context("/reports/dyn/file/note.txt"):
        r = client.get(_url(app, "reports.dyn_file", key="note.txt"))
    assert r.status_code == 404
    assert not asked, (
        "a key outside reports/ must be refused before any filesystem work")


# ============================ table row rendering and default field order

def test_table_rows_map_defaults_to_the_template_field_order(app):
    """With no explicit field list, the helper reads the template's own order.

    Passing fields= is the override; leaving it out must mean "whatever the
    form was rendered from", not "no tables at all".
    """
    tpl_id = _template_with_checklist(app)
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        rows = _table_rows_map(tpl, {})
    assert isinstance(rows, dict) and "tbl" in rows, (
        "the default branch must still find the template's table fields")


def test_an_explicit_field_list_overrides_the_template_order(app):
    """The same helper, told which fields to look at."""
    tpl_id = _template_with_checklist(app)
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        assert _table_rows_map(tpl, {}, fields=[]) == {}
        assert set(_table_rows_map(tpl, {}, fields=list(tpl.ordered_fields))) \
            == {"tbl"}


# ============================ done and not_done are mutually exclusive

def test_a_checklist_row_cannot_be_done_and_not_done_at_once(app):
    """Ticking both boxes on one row is a contradiction, and it is the sort of
    thing that gets typed on purpose by someone in a hurry.

    The rows themselves are still returned, so the form redisplays what the
    person entered - only the contradiction is reported.
    """
    tpl_id = _template_with_checklist(app)
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        payload, errors = _collect_dynamic(
            tpl, {"tbl": [{"item": "سلم", "done": "yes", "not_done": "yes"}]})
    assert any("لا يمكن تحديد" in e for e in errors), (
        f"ticking both boxes must be refused; errors were {errors}")
    assert payload["tbl"][0]["item"] == "سلم", (
        "the row must survive so the form can show it back")


def test_a_checklist_row_ticking_one_box_is_accepted(app):
    """The control: one box, no error. Without this, the test above would also
    pass if the check fired on every row."""
    tpl_id = _template_with_checklist(app)
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        _payload, errors = _collect_dynamic(
            tpl, {"tbl": [{"item": "سلم", "done": "yes", "not_done": ""}]})
    assert not errors, f"a single ticked box must be accepted, got {errors}"


def test_the_contradiction_check_only_ever_sees_strings(app):
    """_is_yes guards stored rows, but the rows are rebuilt from the form first.

    _extract_table_rows stringifies every cell on the way in, so the branch
    inside _is_yes that tested `v is True` could never fire - it was removed,
    and this test is what keeps it removed. If extraction ever starts passing
    raw values through, this fails and the branch has to come back.
    """
    tpl_id = _template_with_checklist(app, key="strat")
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        payload, _errors = _collect_dynamic(
            tpl, {"tbl": [{"item": "سلم", "done": True, "not_done": True}]})
    assert isinstance(payload["tbl"][0]["done"], str), (
        "extraction must stringify cells; a raw bool here would mean "
        "_is_yes needs a real bool branch again")


def test_the_contradiction_check_understands_every_spelling_of_yes(app):
    """The check reads stored values, not just the ones the form submits.

    Old rows hold real booleans and checkbox strings; both must count as yes,
    or the guard only protects submissions and silently rewrites history.
    """
    tpl_id = _template_with_checklist(app)
    yes_values = [True, "1", "true", "on", "checked", "نعم", "☒"]
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        for value in yes_values:
            _p, errors = _collect_dynamic(
                tpl, {"tbl": [{"item": "x", "done": value,
                               "not_done": value}]})
            assert errors, f"{value!r} was not read as yes"
    # and the value that is not yes
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        _p, errors = _collect_dynamic(
            tpl, {"tbl": [{"item": "x", "done": "no", "not_done": "0"}]})
    assert not errors, f"'no' and '0' must not count as yes, got {errors}"


# ============================ geolocation must never sink a submission

class _PayloadThatRefusesCoordinates(dict):
    """Stands in for the payload dict the auto-tag writes into."""

    def __setitem__(self, key, value):
        if key in ("geo_lat", "geo_lng"):
            raise RuntimeError("coordinate storage is unavailable")
        return super().__setitem__(key, value)


def test_a_failing_geolocation_step_does_not_sink_the_submission(
        client, app, monkeypatch, caplog):
    """The auto-tag is a convenience, not a requirement.

    Its whole try/except exists so that a failure here leaves the submission
    alone. If the exception escaped, one broken coordinate would cost the user
    the entire report.
    """
    from tests.conftest import login_as
    from app.models import ReportTemplate
    with app.app_context():
        tpl = ReportTemplate.query.first()
        key = tpl.key
        name_ar = tpl.name_ar
    login_as(client, "t_admin")
    monkeypatch.setattr(
        routes, "_collect_dynamic",
        lambda *a, **k: (_PayloadThatRefusesCoordinates(), []))

    with app.test_request_context("/reports/dyn/new/" + key):
        with caplog.at_level("DEBUG"):
            resp = client.post(
                _url(app, "reports.dyn_new", template_key=key),
                data={"name_ar": "تقرير", "report_date": "2026-01-15",
                      "location": "بغداد", "contractor": "شركة",
                      "geo_lat": " 33.315 ", "geo_lng": " 44.366 "},
                follow_redirects=False)
    assert resp.status_code in (200, 302, 422), (
        f"a broken coordinate step changed the submission into "
        f"{resp.status_code}")
    assert any("geolocation auto-tag skipped" in r.message
               for r in caplog.records), (
        "the failure was swallowed without being recorded, so nobody would "
        "know the coordinates were dropped")


def test_a_submission_with_coordinates_keeps_them(app):
    """The control for the test above: with nothing broken, collection returns
    normally, so the previous test cannot pass for the wrong reason."""
    tpl_id = _template_with_checklist(app, key="coords")
    with app.test_request_context():
        from app.models import ReportTemplate
        tpl = ReportTemplate.query.get(tpl_id)
        payload, errors = _collect_dynamic(tpl, {})
    assert not errors, errors
    assert payload == {"tbl": []}, (
        "an unasked table field collects to an empty list")
