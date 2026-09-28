"""Branches the JSON and upload surfaces leave open, driven at real endpoints.

Every test here calls an actual route and asserts what the caller receives: a
status code, a body, or a row. The purpose is to cover behaviour a user or an
operator can actually hit, and to be explicit about which paths are left
uncovered and why - a defensive handler that only fires when the
application's own code is broken is not the same thing as a feature.
"""
import io

import pytest

from tests.conftest import login_as

#: The nine operations modules the ops blueprint serves, taken from the app
#: rather than from a list that could drift: "daily-site-reports" is not one of
#: them, and asking its meta endpoint yields an error rather than a schema.
FULL_MODULES = sorted(
    __import__("app.ops.routes", fromlist=["KIND_MODEL"]).KIND_MODEL)

#: Modules that declare at least one controlled vocabulary.
ENUM_MODULES = ["rfis", "site-inspections", "variation-orders"]


def _rfi_id(client):
    body = client.get("/ops/rfis").get_json() or {}
    rows = body.get("results") or []
    assert rows, "the fixture must provide at least one RFI"
    return rows[0]["id"]


def _png(size=64):
    return b"\x89PNG\r\n\x1a\n" + b"0" * size


class TestJsonCreateRejectsBadInput:
    """The JSON API answers 422 with a reason; it never 500s."""

    def test_an_invalid_date_is_reported(self, app, client):
        login_as(client, "t_eng")
        response = client.post("/ops/rfis", json={
            "project_id": 1, "subject": "سؤال", "question": "لماذا؟",
            "report_date": "20-06-2026",
        })
        assert response.status_code == 422, response.get_data(as_text=True)[:200]
        assert "error" in (response.get_json() or {})

    def test_a_missing_required_field_is_reported(self, app, client):
        """project_id, subject and question are all required for an RFI."""
        login_as(client, "t_eng")
        response = client.post("/ops/rfis", json={"question": "بلا عنوان"})
        assert response.status_code == 422
        assert "error" in (response.get_json() or {})

    def test_a_blank_project_id_is_refused_not_guessed(self, app, client):
        """A blank project must not be silently attached to some default.

        The 422 body names the offending fields, so the caller can say which
        one is missing rather than a bare "validation failed".
        """
        login_as(client, "t_eng")
        response = client.post("/ops/rfis", json={
            "subject": "بلا مشروع", "question": "س", "project_id": "",
        })
        assert response.status_code == 422
        body = response.get_json() or {}
        details = " ".join(body.get("details") or [])
        assert "المشروع" in details, (
            f"the 422 must name the missing field, got {body!r}")

    def test_a_non_numeric_project_id_is_refused(self, app, client):
        login_as(client, "t_eng")
        response = client.post("/ops/rfis", json={
            "subject": "س", "question": "س", "project_id": "not-a-number",
        })
        assert response.status_code == 422
        assert "error" in (response.get_json() or {})

    def test_a_valid_payload_is_accepted(self, app, client):
        """The control: the guard must not refuse good input."""
        login_as(client, "t_eng")
        response = client.post("/ops/rfis", json={
            "project_id": 1, "subject": "سؤال سليم", "question": "ما التفسير؟",
        })
        assert response.status_code in (200, 201), response.get_data(as_text=True)[:200]
        assert "id" in (response.get_json() or {})


class TestUnknownKindIsRefused:
    def test_getting_an_unknown_kind_is_404(self, app, client):
        login_as(client, "t_eng")
        assert client.get("/ops/not-a-module/1").status_code == 404

    def test_docx_for_an_unknown_kind_is_404(self, app, client):
        login_as(client, "t_eng")
        assert client.get("/ops/not-a-module/1/docx").status_code == 404


class TestUploadGuards:
    """Both size guards, on the route that actually enforces them."""

    def test_an_oversized_attachment_is_refused_with_413(self, app, client):
        login_as(client, "t_eng")
        rid = _rfi_id(client)
        oversized = _png() + b"0" * (5 * 1024 * 1024)
        response = client.post(f"/ops/rfis/{rid}/attachments", data={
            "file": (io.BytesIO(oversized), "big.png"),
        }, content_type="multipart/form-data")
        assert response.status_code == 413, response.get_data(as_text=True)[:200]

    def test_content_that_disagrees_with_its_type_is_refused(self, app, client):
        login_as(client, "t_eng")
        rid = _rfi_id(client)
        response = client.post(f"/ops/rfis/{rid}/attachments", data={
            "file": (io.BytesIO(b"#!/bin/sh\nrm -rf /"), "evil.png"),
        }, content_type="multipart/form-data")
        assert response.status_code in (400, 415, 422)
        assert response.status_code != 500

    def test_a_real_image_is_accepted(self, app, client):
        """The guard must not be so strict that a valid upload is refused."""
        login_as(client, "t_eng")
        rid = _rfi_id(client)
        response = client.post(f"/ops/rfis/{rid}/attachments", data={
            "file": (io.BytesIO(_png()), "photo.png"),
        }, content_type="multipart/form-data")
        assert response.status_code in (200, 201, 302), \
            response.get_data(as_text=True)[:200]


class TestListDateRangeFilter:
    """A range that is supplied must actually narrow the result set."""

    def _query(self, client, **params):
        login_as(client, "t_eng")
        body = client.get("/ops/rfis", query_string=params).get_json() or {}
        return body.get("results") or []

    def test_a_wide_range_keeps_everything(self, app, client):
        everything = self._query(client)
        assert everything, "the fixture must provide rows"
        wide = self._query(client, **{"from": "2000-01-01",
                                      "to": "2099-12-31"})
        assert len(wide) == len(everything)

    def test_a_future_lower_bound_excludes_the_rows(self, app, client):
        rows = self._query(client, **{"from": "2099-01-01"})
        assert rows == [], "a from= in the future must return nothing"

    def test_a_reversed_range_returns_nothing(self, app, client):
        rows = self._query(client, **{"from": "2099-01-01",
                                      "to": "2000-01-01"})
        assert rows == []

    def test_an_unparseable_bound_is_reported(self, app, client):
        login_as(client, "t_eng")
        response = client.get("/ops/rfis", query_string={"from": "20-06-2026"})
        assert response.status_code in (400, 422)


class TestModuleMetaContract:
    """Every module must publish a schema the form can actually render."""

    @pytest.mark.parametrize("kind", FULL_MODULES)
    def test_each_module_publishes_its_identity(self, app, client, kind):
        login_as(client, "t_eng")
        response = client.get(f"/ops/{kind}/meta")
        assert response.status_code == 200, kind
        body = response.get_json() or {}
        for key in ("kind", "prefix", "schema"):
            assert key in body, f"{kind} meta is missing {key!r}"
        assert body["prefix"], f"{kind} has no serial prefix"

    @pytest.mark.parametrize("kind", ENUM_MODULES)
    def test_every_enum_field_has_values(self, app, client, kind):
        """A dropdown built from an empty value list renders an empty box."""
        login_as(client, "t_eng")
        schema = (client.get(f"/ops/{kind}/meta").get_json() or {})["schema"]
        enums = schema.get("enums") or {}
        assert enums, f"{kind} declares no controlled vocabulary at all"
        for field, values in enums.items():
            assert values, f"{kind}.{field} is an enum with no values"

    @pytest.mark.parametrize("kind", ENUM_MODULES)
    def test_enum_values_are_stable_strings(self, app, client, kind):
        """Stored values are keys; a non-string would not round-trip."""
        login_as(client, "t_eng")
        schema = (client.get(f"/ops/{kind}/meta").get_json() or {})["schema"]
        for field, values in (schema.get("enums") or {}).items():
            for value in values:
                assert isinstance(value, str), f"{kind}.{field} has {value!r}"

    def test_a_module_that_requires_nothing_says_so_explicitly(
            self, app, client):
        """A module with no required list must publish an empty one, not None.

        The form iterates the list; a missing key would make it fail silently
        for that module only.
        """
        login_as(client, "t_eng")
        for kind in FULL_MODULES:
            schema = (client.get(f"/ops/{kind}/meta").get_json() or {})["schema"]
            assert "required" in schema, f"{kind} schema has no 'required' key"
            assert isinstance(schema["required"], list)


class TestTenantFallbackDoesNotLeak:
    """If the tenant query cannot run, a field user must still get nothing."""

    def test_a_non_manager_gets_no_projects_from_the_fallback(self, app,
                                                              monkeypatch):
        from app.models import User
        from app.ops import routes as ops_routes

        with app.app_context():
            engineer = User.query.filter_by(username="t_eng").one()

            def explode(*_a, **_k):
                raise RuntimeError("tenant query unavailable")

            monkeypatch.setattr(ops_routes, "visible_projects", explode)
            rows = ops_routes._ui_projects(engineer)
            assert rows == [], (
                "a failed tenant query must not hand a field user every project")

    def test_a_platform_manager_still_sees_them(self, app, monkeypatch):
        from app.models import User
        from app.ops import routes as ops_routes

        with app.app_context():
            owner = User.query.filter_by(username="t_owner").one()

            def explode(*_a, **_k):
                raise RuntimeError("tenant query unavailable")

            monkeypatch.setattr(ops_routes, "visible_projects", explode)
            rows = ops_routes._ui_projects(owner)
            assert len(rows) >= 1, "a manager must keep working on the fallback"
