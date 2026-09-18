"""Real production restore with PostgreSQL DB (correct, not mock)."""
import os
import pytest

try:
    import psycopg2
    _pg_available = True
except Exception:
    _pg_available = False

def _pg_reachable() -> bool:
    try:
        import psycopg2
        c = psycopg2.connect(host='localhost', dbname='postgres', user='postgres',
                             password='postgres', port=5432, connect_timeout=2)
        c.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_reachable(), reason="PostgreSQL not available in CI")
def test_restore_real_postgresql(app):
    """Full restore cycle on real PostgreSQL database."""
    os.environ["TEST_DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/azadexa_test"
    from app.extensions import db
    from app.services.backup import build_backup, restore_backup
    from app.models import User, Project
    from app.ops.models import ProjectMember
    with app.app_context():
        db.drop_all()
        db.create_all()
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
        data = build_backup()
        db.session.query(ProjectMember).delete()
        db.session.query(Project).delete()
        db.session.query(User).delete()
        db.session.commit()
        counts = restore_backup(data, project_id=None, replace=False)
        assert isinstance(counts, dict)
        assert counts.get("users", 0) >= 1
        assert counts.get("projects", 0) >= 1
