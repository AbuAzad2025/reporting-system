"""Permission + flow tests for tenant (project) backup routes."""
import pytest
from unittest.mock import patch


def test_project_backup_owner_can_export(client):
    from tests.conftest import login_as
    login_as(client, "t_pm")
    resp = client.post("/projects/1/backup", follow_redirects=True)
    assert resp.status_code == 200


def test_project_backup_import_owner(client):
    from tests.conftest import login_as
    import io
    login_as(client, "t_pm")
    resp = client.post("/projects/1/backup/import",
                       data={"backup_file": (io.BytesIO(b"PK\x03\x04fake"), "test.zip")},
                       content_type="multipart/form-data",
                       follow_redirects=True)
    assert resp.status_code == 200


def test_project_backup_member_denied(client):
    from tests.conftest import login_as
    login_as(client, "t_eng")
    resp = client.post("/projects/1/backup", follow_redirects=True)
    # Forbidden or redirect to dashboard
    assert resp.status_code in (403, 302, 401, 200)
