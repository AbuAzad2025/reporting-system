"""Real integration test for backup serialization with actual DB/filesystem."""

def test_full_build_validate_restore_cycle(app):
    with app.app_context():
        from app.services.backup import build_backup, validate_backup, restore_backup, backup_filename
        data = build_backup()
        assert isinstance(data, bytes)
        assert len(data) > 100
        v = validate_backup(data)
        assert v["ok"], f"Validation failed: {v.get('error')}"
        counts = restore_backup(data, project_id=None, replace=False)
        assert isinstance(counts, dict)
        for k in ("users", "projects", "templates", "submissions"):
            if k in counts:
                assert isinstance(counts[k], int)


def test_filename_format():
    from app.services.backup import backup_filename
    n = backup_filename()
    assert n.startswith("azadexa-full-backup-")
    assert n.endswith(".zip")
