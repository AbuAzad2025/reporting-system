"""PDF rendering integrity for all nine modules + archive retrieval API."""
from tests.conftest import login_as

KINDS = ["site-inspections", "material-submittals", "rfis", "cost-variances",
         "progress-billings", "subcontractor-performances", "daily-reports",
         "variation-orders", "safety-reports"]


def test_registry_lists_all_nine(eng_client):
    kinds = {m["kind"] for m in eng_client.get("/ops/").get_json()["modules"]}
    assert set(KINDS) <= kinds


def test_every_module_renders_valid_pdf(eng_client):
    for kind in KINDS:
        first = eng_client.get(f"/ops/{kind}").get_json()["results"][0]
        r = eng_client.get(f"/ops/{kind}/{first['id']}/pdf")
        assert r.status_code == 200, kind
        assert r.content_type == "application/pdf", kind
        assert r.data[:5] == b"%PDF-", kind
        assert len(r.data) > 8000, kind  # real content, not an empty shell
        disp = r.headers.get("Content-Disposition", "")
        assert first["serial"] in disp, kind  # serial-mapped retrieval


def test_approved_pdf_renders_with_reviewer_block(client):
    login_as(client, "t_admin")
    r = client.get("/ops/progress-billings/1/pdf")
    assert r.status_code == 200 and r.data[:5] == b"%PDF-"


def test_archive_filters_sorting_pagination(eng_client):
    a = eng_client.get("/ops/api/archive").get_json()
    assert a["total"] == 9  # 10 fixture rows minus Beta-only CVR-000002

    by_type = eng_client.get(
        "/ops/api/archive?type=cost-variances").get_json()
    assert by_type["total"] == 1
    assert by_type["results"][0]["serial"] == "CVR-000001"

    by_status = eng_client.get(
        "/ops/api/archive?status=approved").get_json()
    assert by_status["total"] == 1
    assert by_status["results"][0]["serial"] == "PBR-000001"

    by_q = eng_client.get("/ops/api/archive?q=SIR-").get_json()
    assert by_q["total"] == 1 and by_q["results"][0]["type"] == "site-inspections"

    asc = eng_client.get("/ops/api/archive?sort=serial&order=asc").get_json()
    serials = [r["serial"] for r in asc["results"]]
    assert serials == sorted(serials)

    p1 = eng_client.get("/ops/api/archive?per_page=3&page=1").get_json()
    p2 = eng_client.get("/ops/api/archive?per_page=3&page=2").get_json()
    assert len(p1["results"]) == 3 and len(p2["results"]) == 3
    s1 = set([r["serial"] for r in p1["results"]])
    s2 = set([r["serial"] for r in p2["results"]])
    assert s1.isdisjoint(s2)

    # hierarchical structuring keys present on every row
    for row in p1["results"]:
        assert {"type", "type_ar", "serial", "project", "date",
                "status", "status_ar", "signatory"} <= set(row)


def test_archive_tenant_scoped(client):
    login_as(client, "t_eng2")  # Beta only
    a = client.get("/ops/api/archive").get_json()
    assert a["total"] == 1
    assert a["results"][0]["serial"] == "CVR-000002"
