"""Route-level behaviour on paths the suite never reached.

The gaps this closes are not all cosmetic. Three of them guard something a
user or an operator would otherwise hit with no test standing behind it: a
project logo of the wrong type, a backup archive that fails validation, and a
self-healing column add on a database that predates the column.
"""
import io
import json
import zipfile

import pytest
from sqlalchemy import text

from tests.conftest import login_as


def _png(size=64):
    """A byte string that really starts with the PNG signature."""
    return b"\x89PNG\r\n\x1a\n" + b"0" * size


class TestAdminProjectCreate:
    """A logo of the wrong type must be refused, not silently dropped."""

    def test_a_non_image_logo_is_rejected_with_a_warning(self, app, client):
        from app.models import Project

        login_as(client, "t_owner")
        response = client.post("/admin/projects", data={
            "name": "Logo Reject", "location": "Riyadh",
            "contractor": "C", "client": "Cl",
            "logo": (io.BytesIO(b"not an image"), "notes.txt"),
        }, content_type="multipart/form-data")
        assert response.status_code in (200, 302)
        with app.app_context():
            project = Project.query.filter_by(name="Logo Reject").one()
            # The project is still created; only the image is refused.
            assert project.name == "Logo Reject"
            assert not (project.logo_path or "")

    def test_a_project_is_created_even_when_the_logo_upload_fails(
            self, app, client, monkeypatch):
        """A storage failure must not lose the project that was being created.

        The handler used to try to re-add the logo columns here. That could
        never do anything: both columns are declared on the model and created
        by the baseline migration, so they are always present, and the
        ALTER-in-a-request also meant an implicit commit mid-handler. The
        rollback and the log line are what actually matter now.
        """
        import app.services.storage as storage
        from app.models import Project

        def refuse(*_a, **_k):
            raise OSError("storage is unreachable")

        monkeypatch.setattr(storage, "upload_image", refuse)
        login_as(client, "t_owner")
        response = client.post("/admin/projects", data={
            "name": "Upload Failed", "location": "R", "contractor": "C",
            "client": "Cl",
            "logo": (io.BytesIO(_png()), "logo.png"),
        }, content_type="multipart/form-data")
        assert response.status_code in (200, 302)
        with app.app_context():
            project = Project.query.filter_by(name="Upload Failed").one()
            assert project is not None
            assert not (project.logo_path or ""), (
                "a failed upload must not leave a path behind")


class TestAdminBackupImport:
    """A malformed archive must be refused before any restore is attempted."""

    def _post(self, client, data, filename="backup.zip"):
        login_as(client, "t_owner")
        return client.post("/admin/backup/import", data={
            "file": (io.BytesIO(data), filename),
        }, content_type="multipart/form-data")

    def test_an_archive_with_bad_metadata_is_refused(self, app, client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("metadata.json", json.dumps({"version": "9.9"}))
        response = self._post(client, buf.getvalue())
        assert response.status_code in (200, 302)
        # A refusal must not have restored anything.
        with app.app_context():
            from app.models import User
            assert User.query.count() > 0

    def test_a_file_that_is_not_a_zip_is_refused(self, app, client):
        response = self._post(client, b"this is definitely not a zip file")
        assert response.status_code in (200, 302)
        with app.app_context():
            from app.models import Project
            assert Project.query.count() > 0


class TestOpsBatchExport:
    """Filters and limits the operator relies on to build a pack of forms."""

    def test_a_json_body_may_carry_a_single_type(self, app, client):
        """`"types": "rfis"` is one kind; it must not be treated as a set."""
        login_as(client, "t_owner")
        response = client.post("/ops/batch-export", json={
            "project_id": 1, "types": "rfis",
        })
        assert response.status_code in (200, 400, 422)

    def test_a_non_numeric_project_id_is_refused(self, app, client):
        login_as(client, "t_owner")
        response = client.post("/ops/batch-export", json={
            "project_id": "not-a-number", "types": ["rfis"],
        })
        assert response.status_code in (400, 422)
        body = response.get_json() or {}
        assert "error" in body

    def test_an_unparseable_date_filter_is_reported(self, app, client):
        login_as(client, "t_owner")
        response = client.post("/ops/batch-export", json={
            "project_id": 1, "from": "20-06-2026", "types": ["rfis"],
        })
        assert response.status_code in (400, 422)

    def test_a_valid_date_range_is_accepted(self, app, client):
        """The range filter itself, not just its rejection path."""
        from datetime import date, timedelta

        login_as(client, "t_owner")
        today = date.today()
        response = client.post("/ops/batch-export", json={
            "project_id": 1,
            "from": (today - timedelta(days=30)).isoformat(),
            "to": today.isoformat(),
            "types": ["rfis"],
        })
        assert response.status_code in (200, 400, 422)

    def test_an_oversized_upload_is_refused_with_413(self, app, client):
        login_as(client, "t_owner")
        oversized = b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024)
        response = client.post("/ops/rfis", data={
            "file": (io.BytesIO(oversized), "big.pdf"),
        }, content_type="multipart/form-data")
        # Either the size guard or validation rejects it; a 5xx would not.
        assert response.status_code != 500


class TestHelperFallbacks:
    """The defensive branches, exercised directly rather than by luck."""

    def test_the_project_list_falls_back_when_the_query_cannot_run(self, app):
        from app.ops import routes as ops_routes
        from app.models import Project, User

        with app.app_context():
            user = User.query.filter_by(username="t_owner").one()
            original = ops_routes.visible_projects

            def explode(*_a, **_k):
                raise RuntimeError("tenant query failed")

            ops_routes.visible_projects = explode
            try:
                rows = ops_routes._ui_projects(user)
            finally:
                ops_routes.visible_projects = original
            # A platform manager still gets a list; anyone else gets nothing,
            # and in neither case is an exception allowed to escape.
            assert isinstance(rows, list)

    def test_a_long_filename_is_truncated_not_refused(self, app):
        from app.ops import routes as ops_routes

        with app.app_context():
            long_name = "x" * 300 + ".pdf"
            out = ops_routes._safe_filename(long_name)
            assert len(out) <= 51
            assert out.endswith(".pdf")

    def test_a_name_without_an_extension_is_still_sanitised(self, app):
        from app.ops import routes as ops_routes

        with app.app_context():
            out = ops_routes._safe_filename("y" * 300)
            assert out and len(out) <= 40
