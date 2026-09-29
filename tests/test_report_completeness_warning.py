"""The daily report warns about a hollow report instead of refusing it.

The standard's must-not-be-missing sections are a reminder, not a gate: a
compliance officer who has to tick eighty boxes to press Save stops
submitting, and a half-filled report beats no report. So the form keeps every
field optional, shows what is missing, and lets the print step hide whatever
was left out.
"""
from tests.test_projects import _invite, _pm_project_id
from tests.conftest import login_as


def _post_daily(client, pid, **extra):
    data = {"project_name": "مشروع التنبيه", "project_id": str(pid),
            "report_date": "2026-09-29", "location": "", "contractor": ""}
    data.update(extra)
    return client.post("/reports/dyn/new/daily", data=data,
                       follow_redirects=False)


def _daily_ids(client):
    from app.models import ReportTemplate
    with client.application.app_context():
        return ReportTemplate.query.filter_by(key="daily").first().id


def test_empty_daily_report_still_saves(client):
    """A report with nothing in it is still worth keeping."""
    pid = _pm_project_id(client, name="مشروع التنبيه")
    _invite(client, pid, "t_eng")
    login_as(client, "t_eng")
    r = _post_daily(client, pid)
    assert r.status_code == 302, r.get_data(as_text=True)[:400]


def test_missing_sections_are_named_after_saving(client):
    """The reading page says what the printed report will not carry.

    Not a flash: the reader who opens the report later is the one who needs
    to know a section is absent, and a message that greets you once on save
    is gone by the time anyone reviews it.
    """
    from app.models import ReportSubmission

    pid = _pm_project_id(client, name="مشروع التنبيه")
    _invite(client, pid, "t_eng")
    login_as(client, "t_eng")
    _post_daily(client, pid)
    with client.application.app_context():
        sub_id = ReportSubmission.query.order_by(
            ReportSubmission.id.desc()).first().id
    body = client.get(f"/reports/dyn/{sub_id}").get_data(as_text=True)
    assert "لم تُملأ" in body and "لن تظهر" in body
    # A name the reader can act on, not just a count.
    assert "وصف أنشطة البناء" in body


def test_filled_sections_produce_no_warning(client):
    """Fill every critical section and the warning has nothing to say."""
    from app.services.report_completeness import missing_critical_fields

    pid = _pm_project_id(client, name="مشروع ممتلئ")
    _invite(client, pid, "t_eng")
    login_as(client, "t_eng")
    tpl_id = _daily_ids(client)

    filled = {
        "eshs_desc_81": "صبّ خرسانة في الطابق الثاني",
        "eshs_location_82": "المبنى أ، الاتجاه الشمالي",
        "weather_esha": [{"condition": "صافي", "temp": "31"}],
        "staff_esha": [{"company": "المقاول", "role": "نجار",
                        "name": "12", "hours": "8"}],
        "work_progress_esha": [{"activity": "أعمال النجارة",
                                "drawing_ref": "A-201"}],
        "safety_team_esha": [{"role": "مسؤول السلامة",
                              "status": "متواجد - دوام كامل"}],
        "signatures_esha": [{"entity": "اعداد المقاول",
                             "name_title": "أ. خالد",
                             "signature": "توقيع"}],
    }
    data = {"project_name": "مشروع ممتلئ", "project_id": str(pid),
            "report_date": "2026-09-29"}
    data.update({f"f_{k}": v for k, v in filled.items()
                 if not isinstance(v, list)})
    # table fields arrive as flat f_<key>__<row>__<col> params
    for key, rows in filled.items():
        if not isinstance(rows, list):
            continue
        for rix, row in enumerate(rows):
            for col, val in row.items():
                data[f"f_{key}__{rix}__{col}"] = val
    r = client.post("/reports/dyn/new/daily", data=data,
                    follow_redirects=False)
    if r.status_code != 302:
        import re as _re
        body = r.get_data(as_text=True)
        flash = _re.findall(r'class="flash-msg[^"]*"[^>]*>\s*<span>(.*?)</span>',
                            body, _re.S)
        raise AssertionError(f"rejected: {flash}")
    assert r.status_code == 302

    with client.application.app_context():
        from app.models import ReportSubmission
        s = ReportSubmission.query.filter_by(template_id=tpl_id).first()
        assert missing_critical_fields(s.template, s.data or {}) == []


def test_not_applicable_counts_as_decided(client):
    """Declining a section is a decision; leaving it blank is an omission."""
    from app.services.report_completeness import missing_critical_fields
    from app.models import ReportTemplate

    with client.application.app_context():
        tpl = ReportTemplate.query.filter_by(key="daily").first()
        keys = {f.field_key for f in tpl.ordered_fields}
        assert "eshs_desc_81" in keys
        out = missing_critical_fields(tpl, {"eshs_desc_81": "لا ينطبق"})
        assert all(k != "eshs_desc_81" for k, _ in out)


def test_both_entry_pages_render(client):
    """The new and edit forms must render on a plain GET.

    The warning reads a variable that only exists on a POST. Binding it at the
    render site instead of at the branch is what let the first GET through
    green locally — the POST paths were the only ones the new tests exercised,
    and a form that cannot be opened is not a form.
    """
    from app.models import ReportSubmission

    pid = _pm_project_id(client, name="مشروع العرض")
    _invite(client, pid, "t_eng")
    login_as(client, "t_eng")
    assert _post_daily(client, pid).status_code == 302

    with client.application.app_context():
        sub_id = ReportSubmission.query.order_by(
            ReportSubmission.id.desc()).first().id

    new_form = client.get("/reports/dyn/new/daily")
    assert new_form.status_code == 200
    # The important sections are marked on the form itself, so the user sees
    # which ones matter while filling rather than only after saving.
    assert "مهم" in new_form.get_data(as_text=True)
    edit_form = client.get(f"/reports/dyn/{sub_id}/edit")
    assert edit_form.status_code == 200
    # The saved report is empty, so the page says so rather than hiding it.
    assert "لم تُملأ" in edit_form.get_data(as_text=True)
