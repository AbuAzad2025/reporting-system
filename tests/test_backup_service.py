"""Tests for backup serialization service — pytest + app fixture."""
import pytest


def test_backup_filename():
    from app.services.backup import backup_filename
    n = backup_filename()
    assert n.startswith("azadexa-full-backup-")
    assert n.endswith(".zip")


def test_validate_backup_bad_zip():
    from app.services.backup import validate_backup
    res = validate_backup(b"not a zip")
    assert not res["ok"]


def test_build_and_restore(app):
    with app.app_context():
        from app.services.backup import build_backup, restore_backup, validate_backup
        data = build_backup()
        v = validate_backup(data)
        assert v["ok"], f"Validation failed: {v.get('error')}"
        counts = restore_backup(data, project_id=None, replace=False)
        assert isinstance(counts, dict)
