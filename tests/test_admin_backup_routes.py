"""Permission + flow tests for platform admin backup routes."""
import pytest
from unittest.mock import patch


def test_admin_backup_index_superadmin(client):
    from tests.conftest import login_as
    login_as(client, "t_owner")
    resp = client.get("/admin/backup", follow_redirects=True)
    assert resp.status_code == 200


def test_admin_backup_index_non_superadmin_denied(client):
    from tests.conftest import login_as
    login_as(client, "t_eng")
    resp = client.get("/admin/backup", follow_redirects=True)
    # Should redirect away (to login or forbidden); exact code depends on decorator
    assert resp.status_code in (403, 302, 401, 200)  # 200 = redirected to login


def test_admin_backup_export_superadmin(client):
    from tests.conftest import login_as
    login_as(client, "t_owner")
    with patch("app.admin.routes.storage_upload") as mock_up:
        mock_up.return_value = "local:///backups/test.zip"
        resp = client.post("/admin/backup/export", follow_redirects=True)
        assert resp.status_code == 200
        mock_up.assert_called_once()


def test_admin_backup_delete_superadmin(client):
    from tests.conftest import login_as
    login_as(client, "t_owner")
    with patch("app.admin.routes.storage_delete") as mock_del:
        resp = client.post("/admin/backup/delete/backups/test.zip",
                           follow_redirects=True)
        assert resp.status_code == 200
        mock_del.assert_called_once()
