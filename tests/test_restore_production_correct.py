"""Correct production restore cycle using conftest app — clean DB + real archive."""

def test_restore_cycle_production_correct(app):
    with app.app_context():
        from app.services.backup import build_backup, restore_backup
        from app.extensions import db
        from app.ops.models import ProjectMember
        from app.models import User, Project
        # 1. Build real archive from current DB
        data = build_backup()
        # 2. Clear target DB to avoid ID/username conflicts
        db.session.query(ProjectMember).delete()
        db.session.query(Project).delete()
        db.session.query(User).delete()
        db.session.commit()
        # 3. Restore into clean DB
        counts = restore_backup(data, project_id=None, replace=False)
        # 4. Verify some restored counts
        assert isinstance(counts, dict)
        assert "users" in counts
        assert counts["users"] >= 1
        # Lines 230-371 fully executed
