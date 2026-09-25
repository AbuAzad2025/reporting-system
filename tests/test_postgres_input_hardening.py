"""PostgreSQL-parity input hardening for the ops surface.

SQLite silently tolerates comparing a DATE column against a raw string or
binding a string into a FLOAT column; PostgreSQL raises
``InvalidDatetimeFormat`` / ``DataError`` and turns the request into a 500.
These tests pin the validation that keeps both backends on the same contract,
and prove the real column types/values in the database afterwards.
"""
from datetime import date

import pytest

from tests.conftest import login_as

BAD_DATES = ["garbage", "2026-13-45", "2026/01/01", "01-01-2026",
             "2026-1-1x", "20260101", "2026-01-01T00:00:00", "..",
             "2026-02-30"]


def _alpha(app):
    from app.models import Project
    with app.app_context():
        return Project.query.filter_by(name="Alpha Tower").one().id


def _site_inspection_payload(app, **over):
    payload = {"project_id": _alpha(app), "test_category": "concrete",
               "test_type": "cube 7d", "slump": 175}
    payload.update(over)
    return payload


class TestDateFilterValidation:

    @pytest.mark.parametrize("value", BAD_DATES)
    def test_listing_rejects_malformed_from(self, app, client, value):
        login_as(client, "t_eng")
        r = client.get(f"/ops/site-inspections?from={value}")
        assert r.status_code == 422, value
        assert r.get_json()["error"] == "validation failed"
        assert "YYYY-MM-DD" in r.get_json()["details"][0]

    @pytest.mark.parametrize("value", BAD_DATES)
    def test_listing_rejects_malformed_to(self, app, client, value):
        login_as(client, "t_eng")
        r = client.get(f"/ops/site-inspections?to={value}")
        assert r.status_code == 422, value

    @pytest.mark.parametrize("value", BAD_DATES)
    def test_archive_rejects_malformed_range(self, app, client, value):
        login_as(client, "t_eng")
        r = client.get(f"/ops/api/archive?from={value}")
        assert r.status_code == 422, value
        assert r.get_json()["total"] if "total" in r.get_json() else True

    def test_valid_range_still_filters_by_real_date(self, app, client):
        login_as(client, "t_eng")
        today = date.today().isoformat()
        r = client.get(f"/ops/site-inspections?from={today}")
        assert r.status_code == 200
        assert len(r.get_json()["results"]) == 1
        assert r.get_json()["results"][0]["serial"] == "SIR-000001"

    def test_out_of_range_window_returns_empty_not_error(self, app, client):
        login_as(client, "t_eng")
        r = client.get("/ops/site-inspections?from=2999-01-01&to=2999-12-31")
        assert r.status_code == 200
        assert r.get_json()["results"] == []

    def test_inverted_range_is_empty_not_an_error(self, app, client):
        login_as(client, "t_eng")
        r = client.get("/ops/site-inspections?from=2026-12-31&to=2026-01-01")
        assert r.status_code == 200
        assert r.get_json()["results"] == []

    @pytest.mark.parametrize("field", ["from", "to"])
    def test_batch_export_rejects_malformed_dates(self, app, client, field):
        login_as(client, "t_admin")
        r = client.post("/ops/batch-export",
                        json={field: "2026-13-45", "types": ["rfis"]})
        assert r.status_code == 422, field
        assert "YYYY-MM-DD" in r.get_json()["details"][0]

    @pytest.mark.parametrize("field", ["from", "to"])
    def test_batch_export_rejects_non_string_dates(self, app, client, field):
        login_as(client, "t_admin")
        r = client.post("/ops/batch-export",
                        json={field: 20260901, "types": ["rfis"]})
        assert r.status_code == 422, field
        assert r.get_json()["error"] == "validation failed"

    def test_batch_export_accepts_a_valid_range(self, app, client):
        login_as(client, "t_admin")
        r = client.post("/ops/batch-export", json={
            "from": "2000-01-01", "to": "2999-12-31",
            "types": ["rfis"]})
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"


class TestFloatColumnValidation:

    @pytest.mark.parametrize("field", ["tolerance_mm", "cube_7d", "cube_28d"])
    @pytest.mark.parametrize("bad", ["غير رقم", "12mm", "1.2.3", "abc"])
    def test_non_numeric_float_column_is_rejected(self, app, client, field,
                                                  bad):
        from app.extensions import db
        from app.ops.models import SiteInspection
        with app.app_context():
            before = SiteInspection.query.count()
        login_as(client, "t_eng")
        r = client.post("/ops/site-inspections",
                        json=_site_inspection_payload(app, **{field: bad}))
        assert r.status_code == 422, (field, bad)
        assert r.get_json()["error"] == "validation failed"
        with app.app_context():
            assert SiteInspection.query.count() == before

    @pytest.mark.parametrize("field", ["tolerance_mm", "cube_7d", "cube_28d"])
    def test_valid_float_is_persisted_as_a_number(self, app, client, field):
        from app.extensions import db
        from app.ops.models import SiteInspection
        login_as(client, "t_eng")
        r = client.post("/ops/site-inspections",
                        json=_site_inspection_payload(app, **{field: "27.5"}))
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        with app.app_context():
            row = SiteInspection.query.filter_by(
                serial=body["serial"]).one()
            stored = getattr(row, field)
            assert stored == pytest.approx(27.5)
            assert isinstance(stored, float)

    def test_negative_cube_strength_is_rejected(self, app, client):
        login_as(client, "t_eng")
        r = client.post("/ops/site-inspections",
                        json=_site_inspection_payload(app, cube_7d="-5"))
        assert r.status_code == 422

    def test_float_column_survives_a_round_trip_update(self, app, client):
        from app.ops.models import SiteInspection
        login_as(client, "t_eng")
        rid = SiteInspection.query.filter_by(
            serial="SIR-000001").one().id
        r = client.put(f"/ops/site-inspections/{rid}",
                       json={"cube_28d": "31.75"})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["cube_28d"] == pytest.approx(31.75)


class TestExistenceOracle:

    def _other_users_report(self, app):
        from app.models import Report, User
        with app.app_context():
            other = User.query.filter_by(username="t_eng2").one()
            report = Report(report_type="daily", project_name="Beta Site",
                            location="", contractor="",
                            report_date=date(2026, 3, 3), data={},
                            signatory_name=other.full_name,
                            user_id=other.id)
            from app.extensions import db
            db.session.add(report)
            db.session.commit()
            return report.id

    def _other_users_submission(self, app):
        from app.extensions import db
        from app.models import ReportSubmission, ReportTemplate, User
        with app.app_context():
            other = User.query.filter_by(username="t_eng2").one()
            tpl = ReportTemplate.query.filter_by(key="daily").one()
            sub = ReportSubmission(
                template_id=tpl.id, project_name="Beta Site",
                location="", contractor="", report_date=date(2026, 3, 4),
                data={}, signatory_name=other.full_name, user_id=other.id)
            db.session.add(sub)
            db.session.commit()
            return sub.id

    @pytest.mark.parametrize("path", [
        "/reports/{id}", "/reports/{id}/edit", "/reports/{id}/pdf",
        "/reports/dyn/{id}", "/reports/dyn/{id}/edit", "/reports/dyn/{id}/pdf",
    ])
    def test_out_of_scope_object_is_404_not_403(self, app, client, path):
        login_as(client, "t_eng")
        is_legacy = "/dyn" not in path
        oid = (self._other_users_report(app) if is_legacy
               else self._other_users_submission(app))
        r = client.get(path.format(id=oid))
        assert r.status_code == 404, path
        assert r.status_code != 403

    def test_missing_object_is_404_too(self, client):
        login_as(client, "t_eng")
        for path in ("/reports/999999", "/reports/dyn/999999",
                     "/reports/999999/pdf", "/reports/dyn/999999/pdf"):
            assert client.get(path).status_code == 404, path

    def test_share_of_a_foreign_report_is_404(self, app, client):
        login_as(client, "t_eng")
        rid = self._other_users_report(app)
        r = client.get(f"/reports/share/legacy/{rid}")
        assert r.status_code == 404

    def test_owner_can_still_reach_their_own_report(self, app, client):
        login_as(client, "t_eng")
        from app.extensions import db
        from app.models import Report, User
        with app.app_context():
            me = User.query.filter_by(username="t_eng").one()
            report = Report(report_type="daily", project_name="Alpha Site",
                            location="", contractor="",
                            report_date=date(2026, 3, 5), data={},
                            signatory_name=me.full_name, user_id=me.id)
            db.session.add(report)
            db.session.commit()
            rid = report.id
        assert client.get(f"/reports/{rid}").status_code == 200
        assert client.get(f"/reports/{rid}/pdf").status_code == 200
