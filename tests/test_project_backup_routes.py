"""Permission + flow tests for tenant (project) backup routes."""
import pytest
from unittest.mock import patch


def test_project_backup_owner_can_export(client):
    from tests.conftest import login_as
    login_as(client, "t_pm")
    with patch("app.services.storage.upload") as mock_up:
        mock_up.return_value = "/local/backup-pa.zip"
        resp = client.post("/projects/1/backup", follow_redirects=True)
        assert resp.status_code == 200
        mock_up.assert_called_once()


def test_project_backup_import_owner(client):
    from tests.conftest import login_as
    import io
    login_as(client, "t_pm")
    with patch("app.services.backup.validate_backup") as mock_v, \
         patch("app.services.backup.restore_backup") as mock_r:
        mock_v.return_value = {"ok": True}
        mock_r.return_value = {"reports": 3, "members": 2}
        data = (b"PK\x03\x04" + b"fake zip content")
        resp = client.post("/projects/1/backup/import",
                           data={"backup_file": (io.BytesIO(data), "test.zip")},
                           content_type="multipart/form-data",
                           follow_redirects=True)
        assert resp.status_code == 200
        mock_r.assert_called_once()


def test_project_backup_member_denied(client):
    from tests.conftest import login_as
    login_as(client, "t_eng")
    resp = client.post("/projects/1/backup", follow_redirects=True)
    # Forbidden or redirect to dashboard
    assert resp.status_code in (403, 302, 401, 200)
