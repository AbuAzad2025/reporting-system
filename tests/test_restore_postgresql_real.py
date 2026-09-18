"""Real production restore with PostgreSQL DB (correct, not mock)."""
import os
os.environ["TEST_DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/azadexa_test"


def test_restore_real_postgresql(app):
    """Full restore cycle on real PostgreSQL database."""
    from app.extensions import db
    from app.services.backup import build_backup, restore_backup
    from app.models import User, Project
    from app.ops.models import ProjectMember
    with app.app_context():
        db.drop_all()
        db.create_all()
        # Seed minimal clean data
        u = User(username="pg_real", email="pg@t.com", full_name="PG Real",
                 role="admin")
        u.set_password("pw")
        db.session.add(u)
        db.session.flush()
        p = Project(name="PGReal", location="PG", contractor="PG")
        db.session.add(p)
        db.session.flush()
        db.session.add(ProjectMember(user_id=u.id, project_id=p.id))
        db.session.commit()
        # Build archive
        data = build_backup()
        # Clear for restore
        db.session.query(ProjectMember).delete()
        db.session.query(Project).delete()
        db.session.query(User).delete()
        db.session.commit()
        # Restore
        counts = restore_backup(data, project_id=None, replace=False)
        assert isinstance(counts, dict)
        assert counts.get("users", 0) >= 1
        assert counts.get("projects", 0) >= 1
