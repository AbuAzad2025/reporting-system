"""CRUD integrity: serials, signatory stamp, validation, ownership rules."""
from tests.conftest import login_as


def _alpha(app):
    with app.app_context():
        from app.models import Project
        return Project.query.filter_by(name="Alpha Tower").first().id


def test_create_stamps_serial_signatory_pending(app, eng_client):
    pa = _alpha(app)
    r = eng_client.post("/ops/site-inspections", json={
        "project_id": pa, "test_category": "soil",
        "test_type": "compaction", "result_value": 97,
        "acceptance_min": 95})
    assert r.status_code == 201
    body = r.get_json()
    assert body["serial"].startswith("SIR-")
    assert body["status"] == "pending"
    assert body["signatory"] == "مهندس اختبار تجريبي عام"
    assert body["computed"]["auto_pass"] is True


def test_serials_unique_across_creates(app, eng_client):
    pa = _alpha(app)
    serials = set()
    for i in range(3):
        r = eng_client.post("/ops/material-submittals", json={
            "project_id": pa, "material_name": f"mat-{i}"})
        assert r.status_code == 201
        serials.add(r.get_json()["serial"])
    assert len(serials) == 3


def test_protected_fields_cannot_be_mass_assigned(app, eng_client):
    pa = _alpha(app)
    r = eng_client.post("/ops/rfis", json={
        "project_id": pa, "subject": "s", "question": "q",
        "status": "approved", "serial": "RFI-999999"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "pending"  # not client-settable
    assert body["serial"] != "RFI-999999"


def test_validation_matrix(eng_client, app):
    pa = _alpha(app)
    cases = [
        ("/ops/rfis", {"project_id": pa, "subject": "x"},  # missing question
         422),
        ("/ops/site-inspections",
         {"project_id": pa, "test_category": "wood", "test_type": "t"},
         422),  # bad enum
        ("/ops/cost-variances",
         {"project_id": pa, "boq_item": "b", "actual_qty": -5}, 422),
        ("/ops/progress-billings",
         {"project_id": pa, "work_item": "w", "retention_pct": 150}, 422),
        ("/ops/subcontractor-performances",
         {"project_id": pa, "subcontractor": "s", "quality_score": 101}, 422),
        ("/ops/rfis",
         {"project_id": pa, "subject": "s", "question": "q",
          "report_date": "not-a-date"}, 422),
    ]
    for url, payload, expected in cases:
        r = eng_client.post(url, json=payload)
        assert r.status_code == expected, (url, r.get_json())


def test_author_can_edit_but_not_change_status(app, eng_client):
    r = eng_client.put("/ops/rfis/1", json={"priority": "critical"})
    assert r.status_code == 200
    assert r.get_json()["priority"] == "critical"
    r = eng_client.put("/ops/rfis/1", json={"status": "approved"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "pending"  # protected


def test_non_author_non_manager_cannot_edit_or_delete(client):
    login_as(client, "t_safety")  # same project, not author, not manager
    assert client.put("/ops/rfis/1", json={"priority": "low"}).status_code == 403
    assert client.delete("/ops/rfis/1").status_code == 403


def test_manager_can_edit_and_delete_any(client):
    login_as(client, "t_admin")
    assert client.put("/ops/rfis/1",
                      json={"priority": "low"}).status_code == 200
    r = client.delete("/ops/rfis/1")
    assert r.status_code == 200
    assert r.get_json()["deleted"].startswith("RFI-")


def test_unknown_module_404(eng_client):
    assert eng_client.get("/ops/nope").status_code == 404
    assert eng_client.post("/ops/nope", json={}).status_code == 404


def test_new_modules_create_with_serials(app, eng_client):
    """Daily diary / variation order / safety report end-to-end create."""
    pa = _alpha(app)
    cases = [
        ("/ops/daily-reports", {"project_id": pa, "weather": "مشمس",
                                "works_executed": "صب أعمدة",
                                "engineers_count": 1, "labor_count": 20},
         "DSR-", "manpower_total", 21),
        ("/ops/variation-orders", {"project_id": pa, "title": "بند مستجد",
                                   "category": "أعمال إضافية",
                                   "description": "وصف فني",
                                   "cost_impact": 12000},
         "VOR-", "impact_signed", "+12,000.00"),
        ("/ops/safety-reports", {"project_id": pa, "area": "السقالات",
                                 "hazard": "غياب حزام",
                                 "risk_level": "مرتفع"},
         "HSR-", "is_closed", False),
    ]
    for url, payload, prefix, computed_key, computed_val in cases:
        r = eng_client.post(url, json=payload)
        assert r.status_code == 201, (url, r.get_json())
        body = r.get_json()
        assert body["serial"].startswith(prefix), body
        assert body["computed"][computed_key] == computed_val, body


def test_new_modules_validation_matrix(app, eng_client):
    pa = _alpha(app)
    cases = [
        ("/ops/daily-reports", {"project_id": pa, "weather": "ممطر"}, 422),
        ("/ops/daily-reports",
         {"project_id": pa, "day_progress_pct": 150}, 422),
        ("/ops/variation-orders", {"project_id": pa}, 422),  # missing title
        ("/ops/variation-orders",
         {"project_id": pa, "title": "t", "category": "غير معروف"}, 422),
        ("/ops/safety-reports", {"project_id": pa}, 422),  # missing area
        ("/ops/safety-reports",
         {"project_id": pa, "area": "a", "hazard": "h",
          "ppe_compliance": 150}, 422),
    ]
    for url, payload, expected in cases:
        r = eng_client.post(url, json=payload)
        assert r.status_code == expected, (url, r.get_json())
