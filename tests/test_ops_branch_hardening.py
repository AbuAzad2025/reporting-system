"""Branch-hardening behaviour tests for app/ops/routes.py.

These tests pin the guard rails that a status-code-only suite never
proves:

  1. the ``_resolve_kind`` unknown-module contract on *every* JSON and UI
     controller (exact 404 + ``{"error": "unknown module"}`` body),
  2. the exact Arabic validation messages produced by ``validate_input``
     and ``_validate_table`` for malformed table rows, non-numeric schema
     numbers and a non-numeric ``project_id``,
  3. the create path with an empty ``report_date`` and a form-encoded body
     (coercion, not a bypass of validation),
  4. the submit transition matrix: 403 author gate plus the 422
     "cannot submit from status ..." state codes,
  5. safe parameter clamping in ``/ops/api/archive`` pagination and in
     the listing filter guards (no 500, no silent full-table leak),
  6. comment create/delete mismatch 404s (wrong record, wrong kind,
     missing row) with proof that nothing was persisted or deleted.

Every assertion checks observable behaviour — exact error strings,
persisted rows, transition outcomes — and no test uses xfail or
monkeypatches the code under test.
"""
from datetime import date

import pytest

from tests.conftest import login_as

# ---------------------------------------------------------------- helpers

ENGINEER_FULL_NAME = "مهندس اختبار تجريبي عام"

#: a kind that is registered in neither KIND_MODEL nor SCHEMAS
UNKNOWN = "not-a-real-module"

#: required-field payloads per kind (so validation tests only exercise
#: the branch under test, never an unrelated "required field missing").
BASE_PAYLOAD = {
    "site-inspections": {"test_category": "concrete", "test_type": "cube 7d"},
    "material-submittals": {"material_name": "rebar"},
    "rfis": {"subject": "موضوع", "question": "نص الاستفسار"},
    "cost-variances": {"boq_item": "بند"},
    "progress-billings": {"work_item": "بند أعمال"},
    "subcontractor-performances": {"subcontractor": "مقاول"},
    "daily-reports": {"weather": "مشمس"},
    "variation-orders": {"title": "أمر تغيير"},
    "safety-reports": {"area": "المنطقة"},
}


def _alpha(app):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name="Alpha Tower").first().id


def _beta(app):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name="Beta Hospital").first().id


def _record_id(app, model, serial):
    with app.app_context():
        rec = model.query.filter_by(serial=serial).first()
        assert rec is not None, f"seeded record {serial} missing"
        return rec.id


def _count(app, model):
    with app.app_context():
        return model.query.count()


def _status_of(app, model, record_id):
    with app.app_context():
        return db_get(model, record_id).status


def db_get(model, record_id):
    from app.extensions import db
    return db.session.get(model, record_id)


def _force_status(app, model, record_id, status):
    """Directly park a record in a workflow state (test fixture data)."""
    with app.app_context():
        rec = db_get(model, record_id)
        rec.status = status
        from app.extensions import db
        db.session.commit()
        return rec.serial


# ------------------------------------------------- 1. unknown-kind guards
# Every controller opens with _resolve_kind(); an unregistered module must
# be rejected *before* any tenant query, model attribute access or insert.
JSON_UNKNOWN_KIND_ROUTES = [
    ("GET", "/ops/{k}"),
    ("POST", "/ops/{k}"),
    ("GET", "/ops/{k}/meta"),
    ("GET", "/ops/{k}/1"),
    ("PUT", "/ops/{k}/1"),
    ("PATCH", "/ops/{k}/1"),
    ("DELETE", "/ops/{k}/1"),
    ("POST", "/ops/{k}/1/submit"),
    ("GET", "/ops/{k}/1/history"),
    ("GET", "/ops/{k}/1/pdf"),
    ("GET", "/ops/{k}/1/attachments"),
    ("POST", "/ops/{k}/1/attachments"),
    ("DELETE", "/ops/{k}/1/attachments/1"),
    ("GET", "/ops/{k}/1/attachments/1/download"),
    ("GET", "/ops/{k}/1/comments"),
    ("POST", "/ops/{k}/1/comments"),
    ("DELETE", "/ops/{k}/1/comments/1"),
]

UI_UNKNOWN_KIND_ROUTES = [
    ("GET", "/ops/ui/{k}"),
    ("GET", "/ops/ui/{k}/new"),
    ("POST", "/ops/ui/{k}/new"),
    ("GET", "/ops/ui/{k}/1"),
    ("GET", "/ops/ui/{k}/1/edit"),
    ("POST", "/ops/ui/{k}/1/edit"),
    ("POST", "/ops/ui/{k}/1/submit"),
]


@pytest.mark.parametrize("method,url", JSON_UNKNOWN_KIND_ROUTES)
def test_unknown_kind_json_routes_404_with_exact_error(eng_client, method, url):
    body = {} if method in ("POST", "PUT", "PATCH") else None
    r = eng_client.open(url.format(k=UNKNOWN), method=method, json=body)
    assert r.status_code == 404, url
    assert r.get_json() == {"error": "unknown module"}


@pytest.mark.parametrize("method,url", UI_UNKNOWN_KIND_ROUTES)
def test_unknown_kind_ui_routes_404_with_exact_error(eng_client, method, url):
    """The HTML surface returns the same machine-readable body, not a page."""
    form = {} if method == "POST" else None
    r = eng_client.open(url.format(k=UNKNOWN), method=method, data=form)
    assert r.status_code == 404, url
    assert r.get_json() == {"error": "unknown module"}


def test_unknown_kind_never_reaches_the_database(eng_client, app):
    """A rejected module must not touch the mixin tables (no phantom rows)."""
    from app.ops.models import CostVariance, RFI
    before = (_count(app, CostVariance), _count(app, RFI))
    r = eng_client.post(f"/ops/{UNKNOWN}",
                        json={"project_id": _alpha(app), "boq_item": "x"})
    assert r.status_code == 404
    assert r.get_json() == {"error": "unknown module"}
    assert (_count(app, CostVariance), _count(app, RFI)) == before


def test_unknown_kind_meta_leaks_no_schema(eng_client):
    """The meta controller must not echo a schema for an unregistered kind."""
    r = eng_client.get(f"/ops/{UNKNOWN}/meta")
    assert r.status_code == 404
    body = r.get_json()
    assert body == {"error": "unknown module"}
    assert "schema" not in body and "statuses" not in body


def test_known_kind_meta_still_served(eng_client):
    """Guard: the unknown-kind rejections above are kind-specific, not a
    blanket 404 on the whole /ops surface."""
    r = eng_client.get("/ops/rfis/meta")
    assert r.status_code == 200
    body = r.get_json()
    assert body["kind"] == "rfis"
    assert body["prefix"] == "RFI"
    assert set(body) == {"kind", "prefix", "name_ar", "name_en", "schema",
                         "statuses"}
    assert "required" in body["schema"]


def test_unknown_kind_ui_approve_gate_precedes_kind_resolution(client):
    """ui_approve is permission-gated, so RBAC answers before the kind guard."""
    login_as(client, "t_eng")
    r = client.post(f"/ops/ui/{UNKNOWN}/1/approve")
    assert r.status_code == 403
    login_as(client, "t_admin")
    r = client.post(f"/ops/ui/{UNKNOWN}/1/approve")
    assert r.status_code == 404
    assert r.get_json() == {"error": "unknown module"}


def test_approve_gate_precedes_kind_resolution(client):
    """Decorator order: RBAC is evaluated *before* _resolve_kind(), so an
    unprivileged caller gets 403 (not 404) on an unknown module."""
    login_as(client, "t_eng")
    r = client.post(f"/ops/{UNKNOWN}/1/approve", json={"decision": "approve"})
    assert r.status_code == 403
    assert r.get_json() == {"error": "insufficient permissions"}
    # the privileged caller then reaches the kind guard itself
    login_as(client, "t_admin")
    r = client.post(f"/ops/{UNKNOWN}/1/approve", json={"decision": "approve"})
    assert r.status_code == 404
    assert r.get_json() == {"error": "unknown module"}


# ------------------------------------------------- 2. validation failures
MALFORMED_TABLE_CASES = [
    # not a list at all -> the whole-table message (no row index)
    ("labor_table", "nope", "«جدول العمالة» يجب أن يكون قائمة بنود."),
    # a scalar string where a row object is required
    ("labor_table", ["حدادة"], "الصف 1 في «جدول العمالة» غير صالح."),
    # explicit JSON null row
    ("work_fronts", [None], "الصف 1 في «جبهات العمل» غير صالح."),
    # text column given a number
    ("labor_table", [{"trade": 12, "count": 3}],
     "الصف 1 في «جدول العمالة»: «التخصص» يجب أن يكون نصاً."),
    # numeric column given an unparseable string
    ("labor_table", [{"trade": "حدادة", "count": "ثمانية"}],
     "الصف 1 في «جدول العمالة»: «count» يجب أن يكون رقماً."),
    ("equipment_table", [{"eq_type": "رافعة", "qty": "zz"}],
     "الصف 1 في «جدول المعدات»: «qty» يجب أن يكون رقماً."),
    ("work_fronts", [{"area": "الدور", "progress_pct": "نصف"}],
     "الصف 1 في «جبهات العمل»: «نسبة الإنجاز (%)» يجب أن يكون رقماً."),
]


@pytest.mark.parametrize("table,rows,expected",
                         MALFORMED_TABLE_CASES)
def test_malformed_table_rows_422_with_row_level_message(
        eng_client, app, table, rows, expected):
    from app.ops.models import DailySiteReport
    before = _count(app, DailySiteReport)
    r = eng_client.post("/ops/daily-reports", json={
        "project_id": _alpha(app), "weather": "مشمس", table: rows})
    assert r.status_code == 422, r.get_json()
    body = r.get_json()
    assert body["error"] == "validation failed"
    assert body["details"] == [expected]
    # nothing half-written: the rejected table never reaches a row
    assert _count(app, DailySiteReport) == before


def test_table_error_reports_one_based_row_index(eng_client, app):
    """Row numbers in the Arabic message are 1-based and point at the
    offending row, not the first one."""
    rows = [{"trade": "حدادة", "count": 1},
            {"trade": "نجارة", "count": 2},
            42]
    r = eng_client.post("/ops/daily-reports", json={
        "project_id": _alpha(app), "labor_table": rows})
    assert r.status_code == 422
    assert r.get_json()["details"] == [
        "الصف 3 في «جدول العمالة» غير صالح."]


def test_malformed_table_rejected_on_partial_update(eng_client, app):
    """The same row contract applies to PATCH (partial=True): the stored
    table survives a rejected update untouched."""
    from app.ops.models import DailySiteReport
    rid = _record_id(app, DailySiteReport, "DSR-000001")
    with app.app_context():
        seeded = db_get(DailySiteReport, rid).labor_table
    assert seeded and seeded[0]["trade"] == "حدادة"
    r = eng_client.put(f"/ops/daily-reports/{rid}", json={
        "labor_table": [{"trade": "حدادة", "count": "كثير"}]})
    assert r.status_code == 422
    assert r.get_json()["details"] == [
        "الصف 1 في «جدول العمالة»: «count» يجب أن يكون رقماً."]
    with app.app_context():
        assert db_get(DailySiteReport, rid).labor_table == seeded


NON_NUMERIC_SCHEMA_CASES = [
    ("cost-variances", "budgeted_qty", "عشرون",
     "«الكمية المعتمدة» يجب أن يكون رقماً."),
    ("progress-billings", "retention_pct", "ten percent",
     "«نسبة المحجوز (%)» يجب أن يكون رقماً."),
    ("subcontractor-performances", "quality_score", [90],
     "«الجودة» يجب أن يكون رقماً."),
    ("site-inspections", "slump", {"value": 12},
     "«الهبوط» يجب أن يكون رقماً."),
    ("rfis", "delay_days", "غير رقم",
     "«أيام التأخير» يجب أن يكون رقماً."),
    ("material-submittals", "quantity", "كثير",
     "«الكمية» يجب أن يكون رقماً."),
]


@pytest.mark.parametrize("kind,field,value,expected", NON_NUMERIC_SCHEMA_CASES)
def test_non_numeric_schema_number_422_with_arabic_label(
        eng_client, app, kind, field, value, expected):
    from app.ops import models as M
    from app.ops.routes import KIND_MODEL
    model = KIND_MODEL[kind]
    before = _count(app, model)
    payload = {"project_id": _alpha(app), **BASE_PAYLOAD[kind], field: value}
    r = eng_client.post(f"/ops/{kind}", json=payload)
    assert r.status_code == 422, r.get_json()
    body = r.get_json()
    assert body["error"] == "validation failed"
    assert body["details"] == [expected]
    # the field is *not* silently dropped -> no row is created
    assert _count(app, model) == before
    assert issubclass(model, M.OpsRecordMixin)


@pytest.mark.parametrize("bad", ["abc", "12abc", "1.2.3", "مشروع ألف", "  "])
def test_non_numeric_project_id_422_on_create(eng_client, app, bad):
    from app.ops.models import RFI
    before = _count(app, RFI)
    r = eng_client.post("/ops/rfis", json={
        "project_id": bad, "subject": "s", "question": "q"})
    assert r.status_code == 422, r.get_json()
    assert "«المشروع»" in r.get_json()["details"][0]
    assert _count(app, RFI) == before


def test_blank_project_id_reports_required_and_invalid(eng_client, app):
    """A blank project trips both the required check and the int() guard."""
    r = eng_client.post("/ops/rfis", json={
        "project_id": "", "subject": "s", "question": "q"})
    assert r.status_code == 422
    assert r.get_json()["details"] == [
        "«المشروع» حقل مطلوب.",
        "«المشروع» يجب أن يكون رقم مشروع صالح — اختره من القائمة.",
    ]


@pytest.mark.parametrize("method", ["PUT", "PATCH"])
def test_non_numeric_project_id_422_on_update_keeps_row(
        client, app, method):
    from app.ops.models import RFI
    rid = _record_id(app, RFI, "RFI-000001")
    login_as(client, "t_eng")
    r = client.open(f"/ops/rfis/{rid}", method=method,
                    json={"project_id": "مشروع-غير-صالح"})
    assert r.status_code == 422
    assert r.get_json()["details"] == [
        "«المشروع» يجب أن يكون رقم مشروع صالح — اختره من القائمة."]
    with app.app_context():
        rec = db_get(RFI, rid)
        assert rec.project_id == _alpha(app)


def test_ui_form_reports_validation_errors_as_flashes(client, app):
    """The HTML form surfaces the same messages and creates nothing."""
    from app.ops.models import RFI
    before = _count(app, RFI)
    login_as(client, "t_eng")
    r = client.post("/ops/ui/rfis/new", data={
        "project_id": "مشروع-غير-صالح", "subject": "s", "question": "q"},
        follow_redirects=True)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "«المشروع» يجب أن يكون رقم مشروع صالح" in html
    assert _count(app, RFI) == before


# ------------------------------------------- 3. create success (date/form)
def test_create_with_empty_report_date_falls_back_to_today(eng_client, app):
    """An empty date is dropped by the validator -> the column default
    (today) applies, instead of a NULL/500."""
    pid = _alpha(app)
    r = eng_client.post("/ops/rfis", json={
        "project_id": pid, "subject": "بدون تاريخ", "question": "؟",
        "report_date": ""})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["report_date"] == date.today().isoformat()
    assert body["project_id"] == pid
    assert body["status"] == "pending"
    assert body["serial"].startswith("RFI-")
    assert body["signatory"] == ENGINEER_FULL_NAME
    assert body["computed"]["days_open"] == 0


def test_create_form_encoded_body_is_coerced_and_persisted(eng_client, app):
    """A form body (not JSON) goes through the same validator/coercion:
    every value arrives as a string and must be converted server-side."""
    pid = _alpha(app)
    r = eng_client.post("/ops/daily-reports", data={
        "project_id": str(pid), "weather": "مشمس", "temp_c": "31.5",
        "work_hours": "8", "engineers_count": "4", "labor_count": "12",
        "report_date": "2026-03-14"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["project_id"] == pid              # str -> int
    assert body["temp_c"] == 31.5                 # str -> float
    assert body["work_hours"] == 8.0
    assert body["engineers_count"] == 4
    assert body["labor_count"] == 12
    assert body["report_date"] == "2026-03-14"    # str -> date
    assert body["computed"]["manpower_total"] == 16
    assert body["serial"].startswith("DSR-")
    assert body["status"] == "pending"


def test_create_form_encoded_body_is_still_validated(eng_client, app):
    """Form input is not a validation bypass: same 422 contract as JSON."""
    from app.ops.models import RFI
    before = _count(app, RFI)
    r = eng_client.post("/ops/rfis", data={
        "project_id": str(_alpha(app)), "subject": "s", "question": "q",
        "priority": "عاجل", "report_date": "2026-13-45"})
    assert r.status_code == 422
    details = r.get_json()["details"]
    assert "قيمة غير مسموحة في «الأولوية» — المسموح: low، normal، high، critical." \
        in details
    assert "التاريخ غير صالح في «تاريخ التقرير» — الصيغة المطلوبة YYYY-MM-DD." \
        in details
    assert _count(app, RFI) == before


def test_create_form_encoded_rejects_json_only_table_field(eng_client, app):
    """A form cannot express the structured workflow tables; a string in
    that field is rejected rather than stored as-is."""
    from app.ops.models import DailySiteReport
    before = _count(app, DailySiteReport)
    r = eng_client.post("/ops/daily-reports", data={
        "project_id": str(_alpha(app)), "labor_table": "حدادة,8"})
    assert r.status_code == 422
    assert r.get_json()["details"] == [
        "«جدول العمالة» يجب أن يكون قائمة بنود."]
    assert _count(app, DailySiteReport) == before


# ---------------------------------------- 4. submit permission/state gates
def test_submit_by_non_author_non_manager_is_403_and_changes_nothing(
        client, app):
    from app.ops.models import DailySiteReport
    rid = _record_id(app, DailySiteReport, "DSR-000001")
    login_as(client, "t_safety")  # same project, not the author, not a manager
    r = client.post(f"/ops/daily-reports/{rid}/submit")
    assert r.status_code == 403
    assert r.get_json() == {
        "error": "only the author or a manager may submit"}
    assert _status_of(app, DailySiteReport, rid) == "pending"


def test_submit_on_missing_or_cross_tenant_record_is_404(client, app):
    """404 (not 403) for both a missing row and a foreign tenant row, so the
    response is no existence oracle."""
    from app.ops.models import CostVariance, DailySiteReport
    mine = _record_id(app, DailySiteReport, "DSR-000001")
    foreign = _record_id(app, CostVariance, "CVR-000002")  # Beta Hospital
    login_as(client, "t_eng")  # Alpha-only engineer
    _force_status(app, DailySiteReport, mine, "draft")
    r = client.post(f"/ops/daily-reports/{mine}/submit")
    assert r.status_code == 200                       # control: own record
    assert r.get_json()["status"] == "submitted"
    r = client.post("/ops/daily-reports/987654/submit")
    assert r.status_code == 404
    r = client.post(f"/ops/cost-variances/{foreign}/submit")
    assert r.status_code == 404
    with app.app_context():
        assert db_get(CostVariance, foreign).status == "pending"


SUBMIT_MATRIX = [
    # stored status, expected HTTP, expected code in the error, final status
    ("draft", 200, None, "submitted"),
    ("rejected", 200, None, "submitted"),
    ("pending", 422, "submitted", "pending"),
    ("approved", 422, "approved", "approved"),
    ("amended", 422, "amended", "amended"),
]


@pytest.mark.parametrize("status,expected_http,code,final", SUBMIT_MATRIX)
def test_submit_state_machine_codes(eng_client, app, status, expected_http,
                                    code, final):
    """Only draft/rejected may reach submitted; every other state reports
    the *normalized* status in a stable machine code."""
    from app.ops.models import RFI
    rid = _record_id(app, RFI, "RFI-000001")
    _force_status(app, RFI, rid, status)
    r = eng_client.post(f"/ops/rfis/{rid}/submit")
    assert r.status_code == expected_http, r.get_json()
    if code is None:
        body = r.get_json()
        assert body["status"] == final
        assert body["status_norm"] == "submitted"
        assert body["is_locked"] is False
    else:
        assert r.get_json() == {
            "error": f"cannot submit from status '{code}'"}
    assert _status_of(app, RFI, rid) == final


def test_submit_by_platform_manager_on_foreign_record_is_allowed(
        client, app):
    """Managers bypass the author check but never the state machine."""
    from app.ops.models import CostVariance
    foreign = _record_id(app, CostVariance, "CVR-000002")
    login_as(client, "t_admin")
    r = client.post(f"/ops/cost-variances/{foreign}/submit")
    assert r.status_code == 422
    assert r.get_json() == {
        "error": "cannot submit from status 'submitted'"}
    assert _status_of(app, CostVariance, foreign) == "pending"


def test_ui_submit_sets_submitted_and_redirects(client, app):
    from app.ops.models import DailySiteReport
    rid = _record_id(app, DailySiteReport, "DSR-000001")
    _force_status(app, DailySiteReport, rid, "draft")
    login_as(client, "t_eng")
    r = client.post(f"/ops/ui/daily-reports/{rid}/submit")
    assert r.status_code == 302
    assert f"/ops/ui/daily-reports/{rid}" in r.headers["Location"]
    assert _status_of(app, DailySiteReport, rid) == "submitted"


def test_ui_submit_refuses_a_row_already_pending(client, app):
    from app.ops.models import DailySiteReport
    rid = _record_id(app, DailySiteReport, "DSR-000001")
    assert _status_of(app, DailySiteReport, rid) == "pending"
    login_as(client, "t_eng")
    r = client.post(f"/ops/ui/daily-reports/{rid}/submit",
                    follow_redirects=True)
    assert r.status_code == 200
    assert "لا يمكن التقديم" in r.get_data(as_text=True)
    assert _status_of(app, DailySiteReport, rid) == "pending"


def test_ui_approve_requires_platform_manager(client, app):
    """The HTML approve gate aborts 403 and leaves the record untouched."""
    from app.ops.models import DailySiteReport
    rid = _record_id(app, DailySiteReport, "DSR-000001")
    login_as(client, "t_eng")
    r = client.post(f"/ops/ui/daily-reports/{rid}/approve")
    assert r.status_code == 403
    assert _status_of(app, DailySiteReport, rid) == "pending"
    # a manager is admitted and the reviewer identity is stamped
    login_as(client, "t_admin")
    r = client.post(f"/ops/ui/daily-reports/{rid}/approve")
    assert r.status_code == 302
    with app.app_context():
        rec = db_get(DailySiteReport, rid)
        assert rec.status == "approved"
        assert rec.reviewed_by_id is not None
        assert rec.reviewed_at is not None


# ----------------------------------------- 5. pagination + filter clamps
ARCHIVE_CLAMPS = [
    ("", 1, 20),
    ("?page=2", 2, 20),
    ("?page=0", 1, 20),
    ("?page=-4", 1, 20),
    ("?page=not-a-number", 1, 20),
    ("?per_page=1", 1, 1),
    ("?per_page=0", 1, 1),
    ("?per_page=-9", 1, 1),
    ("?per_page=9999", 1, 100),
    ("?per_page=oops", 1, 20),
    ("?page=abc&per_page=xyz", 1, 20),
]


@pytest.mark.parametrize("query,page,per_page", ARCHIVE_CLAMPS)
def test_archive_pagination_is_clamped_to_safe_bounds(
        eng_client, query, page, per_page):
    r = eng_client.get("/ops/api/archive" + query)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["page"] == page
    assert body["per_page"] == per_page
    assert 1 <= body["page"] and 1 <= body["per_page"] <= 100
    assert len(body["results"]) <= body["per_page"]


def test_archive_pagination_slices_consistently(eng_client):
    """The clamped window really slices: totals stay stable, page 1 and the
    last page never overlap, and an out-of-range page is empty (not 500)."""
    full = eng_client.get("/ops/api/archive?per_page=100").get_json()
    total = full["total"]
    assert total > 2
    first = eng_client.get("/ops/api/archive?per_page=1&page=1").get_json()
    second = eng_client.get("/ops/api/archive?per_page=1&page=2").get_json()
    beyond = eng_client.get("/ops/api/archive?per_page=1&page=999").get_json()
    assert first["total"] == second["total"] == beyond["total"] == total
    assert len(first["results"]) == len(second["results"]) == 1
    assert first["results"][0]["serial"] != second["results"][0]["serial"]
    assert beyond["results"] == []
    serials = {row["serial"] for row in full["results"]}
    assert first["results"][0]["serial"] in serials


def test_archive_clamps_before_slicing_not_after(eng_client):
    """per_page=0 is raised to 1 rather than producing an empty page: the
    endpoint stays usable for an abusive value."""
    one = eng_client.get("/ops/api/archive?per_page=0").get_json()
    assert one["per_page"] == 1
    assert len(one["results"]) == 1
    assert one["results"] == eng_client.get(
        "/ops/api/archive?per_page=1").get_json()["results"]


def test_archive_non_numeric_project_id_yields_no_rows(eng_client, app):
    """A junk project id must be filtered away (200 + 0 rows), never raise
    ValueError into a 500 or silently ignore the filter."""
    for junk in ("abc", "1.5", "-", "مشروع"):
        r = eng_client.get(f"/ops/api/archive?project_id={junk}")
        assert r.status_code == 200, junk
        body = r.get_json()
        assert body["total"] == 0, junk
        assert body["results"] == []
    # control: the real id still returns the tenant's rows
    ok = eng_client.get(f"/ops/api/archive?project_id={_alpha(app)}")
    assert ok.get_json()["total"] > 0


def test_archive_unknown_type_falls_back_to_all_modules(eng_client):
    """An unregistered `type` must not silently return an empty archive."""
    everything = eng_client.get("/ops/api/archive?per_page=100").get_json()
    fallback = eng_client.get(f"/ops/api/archive?type={UNKNOWN}").get_json()
    assert fallback["total"] == everything["total"]
    one = eng_client.get("/ops/api/archive?type=cost-variances").get_json()
    assert one["total"] == 1
    assert one["results"][0]["type"] == "cost-variances"
    assert one["results"][0]["project"] == "Alpha Tower"


def test_listing_non_numeric_project_id_returns_empty_page(eng_client):
    """listing() guards the same int() cast with db.false() — 200 + no rows,
    and the unfiltered listing is unaffected afterwards."""
    r = eng_client.get(f"/ops/rfis?project_id={UNKNOWN}")
    assert r.status_code == 200
    assert r.get_json()["results"] == []
    again = eng_client.get("/ops/rfis")
    assert again.status_code == 200
    assert [row["serial"] for row in again.get_json()["results"]] \
        == ["RFI-000001"]


def test_listing_ignores_unknown_status_but_honours_valid_one(eng_client):
    """An unknown status is ignored (no empty-by-accident page); a valid
    status really filters."""
    unknown = eng_client.get("/ops/rfis?status=not-a-status")
    assert unknown.status_code == 200
    assert len(unknown.get_json()["results"]) == 1
    approved = eng_client.get("/ops/rfis?status=approved")
    assert approved.status_code == 200
    assert approved.get_json()["results"] == []
    pending = eng_client.get("/ops/rfis?status=pending")
    assert [row["serial"] for row in pending.get_json()["results"]] \
        == ["RFI-000001"]


def test_listing_date_window_excludes_out_of_range_rows(eng_client):
    """from/to are real filters on report_date (valid ISO dates only)."""
    future = eng_client.get("/ops/rfis?from=2999-01-01")
    assert future.status_code == 200
    assert future.get_json()["results"] == []
    windowed = eng_client.get("/ops/rfis?from=2000-01-01&to=2000-01-02")
    assert windowed.status_code == 200
    assert windowed.get_json()["results"] == []


# ------------------------------------------ 6. comment mismatch 404 rules
#: (route kind, seeded serial) pairs a comment on RFI-000001 is *not*
#: addressable through — same tenant, same project, all real records.
COMMENT_MISMATCH_TARGETS = [
    ("daily-reports", "DSR-000001"),          # right kind, wrong record
    ("material-submittals", "MSR-000001"),    # wrong kind, existing record
    ("cost-variances", "CVR-000001"),
    ("progress-billings", "PBR-000001"),
]


def _model_for(kind):
    from app.ops import models as M
    from app.ops.routes import KIND_MODEL
    return KIND_MODEL[kind]


@pytest.mark.parametrize("kind,serial", COMMENT_MISMATCH_TARGETS)
def test_comment_delete_mismatch_returns_404_and_keeps_the_row(
        eng_client, app, kind, serial):
    """A comment is only addressable through its own (kind, record) pair;
    any other pairing is a plain 404 that deletes nothing."""
    from app.ops.models import OpsRecordComment, RFI
    host = _record_id(app, RFI, "RFI-000001")
    created = eng_client.post(f"/ops/rfis/{host}/comments",
                              json={"body": "ملاحظة مربوطة"})
    assert created.status_code == 201, created.get_json()
    cid = created.get_json()["id"]
    # every target below exists and is inside the tenant, so the 404 can
    # only come from the (record_kind, record_id) pair mismatch
    other = _record_id(app, _model_for(kind), serial)
    assert other != host or kind != "rfis"
    r = eng_client.delete(f"/ops/{kind}/{other}/comments/{cid}")
    assert r.status_code == 404, r.get_json()
    assert r.get_json() == {"error": "not found"}
    with app.app_context():
        assert db_get(OpsRecordComment, cid) is not None
        assert OpsRecordComment.query.count() == 1
    # ...and the comment is still visible on its real thread
    listed = eng_client.get(f"/ops/rfis/{host}/comments").get_json()
    assert [c["id"] for c in listed["comments"]] == [cid]


def test_comment_delete_unknown_id_returns_404(eng_client, app):
    from app.ops.models import RFI
    rid = _record_id(app, RFI, "RFI-000001")
    r = eng_client.delete(f"/ops/rfis/{rid}/comments/123456")
    assert r.status_code == 404
    assert r.get_json() == {"error": "not found"}


def test_comment_create_on_missing_record_404_persists_nothing(
        eng_client, app):
    from app.ops.models import OpsRecordComment
    before = _count(app, OpsRecordComment)
    r = eng_client.post("/ops/rfis/123456/comments", json={"body": "تختفي"})
    assert r.status_code == 404
    assert _count(app, OpsRecordComment) == before


def test_comment_create_then_delete_round_trip_is_scoped(eng_client, app):
    """Control for the mismatch cases: the correct pairing works and the
    mismatch 404s are not blanket failures."""
    from app.ops.models import OpsRecordComment, RFI
    rid = _record_id(app, RFI, "RFI-000001")
    cid = eng_client.post(f"/ops/rfis/{rid}/comments",
                          json={"body": "ملاحظة صالحة"}).get_json()["id"]
    assert cid > 0
    assert [c["id"] for c in eng_client.get(
        f"/ops/rfis/{rid}/comments").get_json()["comments"]] == [cid]
    r = eng_client.delete(f"/ops/rfis/{rid}/comments/{cid}")
    assert r.status_code == 200
    assert r.get_json() == {"deleted": cid}
    with app.app_context():
        assert db_get(OpsRecordComment, cid) is None
