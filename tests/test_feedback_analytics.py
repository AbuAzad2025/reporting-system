"""WORKSTREAM 3: dual-party feedback, DSR workflows, admin analytics."""

from tests.conftest import login_as


def _alpha_pid(client):
    from app.models import Project
    with client.application.app_context():
        return Project.query.filter_by(name="Alpha Tower").first().id


def _make_dsr(client, **over):
    payload = {"project_id": _alpha_pid(client), "weather": "مشمس",
               "works_executed": "صب أعمدة", "engineers_count": 2,
               "technicians_count": 3, "labor_count": 28,
               "day_progress_pct": 3.0}
    payload.update(over)
    r = client.post("/ops/daily-reports", json=payload)
    assert r.status_code == 201, f"create DSR: {r.get_json()}"
    return r.get_json()


TABLES = {
    "labor_table": [{"trade": "حدادة", "count": 12},
                    {"trade": "نجارة", "count": 8}],
    "equipment_table": [{"eq_type": "رافعة برجية", "qty": 1, "hours": 8,
                         "status": "operating"},
                        {"eq_type": "خلاطة", "qty": 2, "hours": 4,
                         "status": "idle"}],
    "work_fronts": [{"area": "الدور الثالث", "activity": "صب أعمدة",
                     "progress_pct": 60},
                    {"area": "القبو", "activity": "عزل",
                     "progress_pct": 30}],
}


# ---- dual-party feedback ---------------------------------------------------

def test_comment_create_list_round_trip(client):
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    r = client.post(f"/ops/daily-reports/{sid}/comments",
                    json={"body": "تم صب الأعمدة حسب المخطط"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["party"] == "contractor"
    assert body["author_name"] != ""

    r = client.get(f"/ops/daily-reports/{sid}/comments")
    assert r.status_code == 200
    comments = r.get_json()["comments"]
    assert len(comments) == 1
    assert comments[0]["body"] == "تم صب الأعمدة حسب المخطط"


def test_comment_party_consultant(client):
    """Manager/consultant authors land on the supervision side."""
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    login_as(client, "t_admin")
    r = client.post(f"/ops/daily-reports/{sid}/comments",
                    json={"body": "اعتمد مع ملاحظة: اختبار المكعبات"})
    assert r.status_code == 201
    assert r.get_json()["party"] == "consultant"


def test_comment_body_validation(client):
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    assert client.post(f"/ops/daily-reports/{sid}/comments",
                       json={"body": "  "}).status_code == 422
    assert client.post(f"/ops/daily-reports/{sid}/comments",
                       json={"body": "x" * 2001}).status_code == 422
    assert client.post(f"/ops/daily-reports/{sid}/comments",
                       json={}).status_code == 422


def test_comment_cross_tenant_404(client):
    """Beta-only engineer cannot thread on Alpha records (no oracle)."""
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    login_as(client, "t_eng2")
    assert client.post(f"/ops/daily-reports/{sid}/comments",
                       json={"body": "hi"}).status_code == 404
    assert client.get(f"/ops/daily-reports/{sid}/comments").status_code == 404


def test_comment_delete_author_manager_only(client):
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    cid = client.post(f"/ops/daily-reports/{sid}/comments",
                      json={"body": "للحذف"}).get_json()["id"]
    # same-project non-author (safety) → 403
    login_as(client, "t_safety")
    r = client.delete(f"/ops/daily-reports/{sid}/comments/{cid}")
    assert r.status_code == 403
    # manager → 200
    login_as(client, "t_admin")
    r = client.delete(f"/ops/daily-reports/{sid}/comments/{cid}")
    assert r.status_code == 200


def test_comment_on_approved_record_allowed(client):
    """Review notes live on locked records — feedback stays open."""
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    login_as(client, "t_admin")
    client.post(f"/ops/daily-reports/{sid}/approve",
                json={"decision": "approve"})
    r = client.post(f"/ops/daily-reports/{sid}/comments",
                    json={"body": "ملاحظة ما بعد الاعتماد"})
    assert r.status_code == 201, r.get_json()


# ---- DSR structured tables ---------------------------------------------------

def test_dsr_tables_create_and_computed(client):
    login_as(client, "t_eng")
    body = _make_dsr(client, **TABLES)
    comp = body["computed"]
    assert comp["labor_table_total"] == 20
    assert comp["equipment_hours_total"] == 16.0  # 1*8 + 2*4
    assert comp["fronts_avg_pct"] == 45.0
    assert comp["manpower_total"] == 33


def test_dsr_tables_rejected(client):
    login_as(client, "t_eng")
    base = {"project_id": _alpha_pid(client), "weather": "مشمس",
            "works_executed": "x", "engineers_count": 1,
            "technicians_count": 1, "labor_count": 1,
            "day_progress_pct": 1.0}
    # missing required column
    r = client.post("/ops/daily-reports",
                    json=dict(base, labor_table=[{"count": 5}]))
    assert r.status_code == 422
    # negative count
    r = client.post("/ops/daily-reports",
                    json=dict(base, labor_table=[{"trade": "x", "count": -1}]))
    assert r.status_code == 422
    # bad enum status
    r = client.post("/ops/daily-reports", json=dict(
        base, equipment_table=[{"eq_type": "x", "qty": 1,
                                "status": "flying"}]))
    assert r.status_code == 422
    # not a list
    r = client.post("/ops/daily-reports",
                    json=dict(base, work_fronts={"area": "x"}))
    assert r.status_code == 422
    # over the row cap
    r = client.post("/ops/daily-reports", json=dict(
        base, labor_table=[{"trade": f"t{i}", "count": 1}
                           for i in range(31)]))
    assert r.status_code == 422
    # pct out of range
    r = client.post("/ops/daily-reports", json=dict(
        base, work_fronts=[{"area": "x", "progress_pct": 150}]))
    assert r.status_code == 422


def test_dsr_tables_partial_update(client):
    login_as(client, "t_eng")
    sid = _make_dsr(client)["id"]
    r = client.put(f"/ops/daily-reports/{sid}",
                   json={"labor_table": [{"trade": "حدادة", "count": 15}]})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["computed"]["labor_table_total"] == 15


def test_dsr_tables_carried_into_amendment(client):
    """Amendment spawn copies structured tables (immutable trail keeps them)."""
    login_as(client, "t_admin")
    sid = _make_dsr(client, **TABLES)["id"]
    client.post(f"/ops/daily-reports/{sid}/approve",
                json={"decision": "approve"})
    r = client.put(f"/ops/daily-reports/{sid}", json={"weather": "ماطر"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["computed"]["labor_table_total"] == 20
    assert body["computed"]["equipment_hours_total"] == 16.0


# ---- superadmin analytics -----------------------------------------------------

def test_analytics_forbidden_for_engineer_and_admin(client):
    login_as(client, "t_eng")
    assert client.get("/admin/api/analytics").status_code == 403
    login_as(client, "t_admin")
    assert client.get("/admin/api/analytics").status_code == 403
    login_as(client, "t_admin")
    assert client.get("/admin/analytics").status_code in (302, 403)


def test_analytics_unauthenticated_401_json(client):
    r = client.get("/admin/api/analytics")
    assert r.status_code == 401
    assert r.get_json()["error"] == "authentication required"


def test_analytics_superadmin_payload(client):
    login_as(client, "t_owner")
    r = client.get("/admin/api/analytics")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert set(data) >= {"by_kind", "by_project", "dsr_manpower_30d",
                         "open_rfis", "comments_30d", "generated_at"}
    # nine modules present
    assert len(data["by_kind"]) == 9
    assert data["by_kind"]["daily-reports"]["total"] == 1
    # seeded tenant split: Alpha 9 records, Beta 1
    totals = {p["name"]: p["total"] for p in data["by_project"]}
    assert totals == {"Alpha Tower": 9, "Beta Hospital": 1}
    # seeded diary manpower
    mp = data["dsr_manpower_30d"]
    assert mp["reports"] == 1
    assert (mp["engineers"], mp["technicians"], mp["labor"]) == (2, 3, 28)
    # seeded open RFI with the consultant
    assert data["open_rfis"]["total"] == 1
    assert data["open_rfis"]["by_court"] == {"consultant": 1}
    assert data["comments_30d"] == 0


def test_analytics_page_renders(client):
    login_as(client, "t_owner")
    r = client.get("/admin/analytics")
    assert r.status_code == 200
    assert "تحليلات العمليات" in r.get_data(as_text=True)
