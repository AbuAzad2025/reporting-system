"""Final targeted hits for remaining backup.py lines."""

def test_json_default_date_final(app):
    from app.services.backup import _json_default
    from datetime import date
    assert _json_default(date(2026, 1, 1)) == "2026-01-01"

def test_query_all_no_project(app):
    with app.app_context():
        from app.services.backup import _query_all
        from app.models import User
        assert _query_all(User, project_id=1) == []

def test_attachment_filter(app):
    with app.app_context():
        from app.services.backup import _collect_attachments
        assert isinstance(_collect_attachments(project_id=1), list)

def test_project_scope_build(app):
    with app.app_context():
        from app.services.backup import build_backup
        assert len(build_backup(project_id=1)) > 100

def test_restore_rows_remap(app):
    with app.app_context():
        from app.services.backup import _restore_rows
        id_map = {"users": {1: 10}, "projects": {2: 20}}
        from app.ops.models import ProjectMember
        _restore_rows(ProjectMember,
                      [{"id": 1, "user_id": 1, "project_id": 2, "role_in_project":"m"}],
                      id_map, "project_members")

def test_filename_project(app):
    from app.services.backup import backup_filename
    assert "project-99" in backup_filename(99)

def test_size(app):
    from app.services.backup import backup_size
    assert backup_size(b"x") == 1

def test_validate_bad(app):
    from app.services.backup import validate_backup
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("metadata.json", b"bad")
    assert not validate_backup(buf.getvalue())["ok"]
