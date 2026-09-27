"""Full backup/restore cycle against a real PostgreSQL database.

This test used to set ``os.environ["TEST_DATABASE_URL"]`` inside the test body,
which reads as "run me on PostgreSQL" but did nothing: tests/conftest.py reads
TEST_DATABASE_URL once at import time, so the ``app`` fixture had already bound
the app to its per-test SQLite file. The test would have passed while proving
nothing about PostgreSQL.

It is now explicit. The test refuses to run unless the app really is bound to
PostgreSQL, so it can never pass on SQLite by accident, and CI executes it in
the dedicated `postgres-restore` job where TEST_DATABASE_URL is set before
pytest starts.
"""
import pytest


def _is_postgres(app) -> bool:
    return app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql")


@pytest.fixture()
def pg_app(app):
    if not _is_postgres(app):
        pytest.skip(
            "needs a real PostgreSQL database: run with TEST_DATABASE_URL set, "
            "as the postgres-restore CI job does")
    return app


def test_the_fixture_really_is_postgres(pg_app):
    """Guard against this file silently degrading back to SQLite."""
    with pg_app.app_context():
        from app.extensions import db
        dialect = db.session.get_bind().dialect.name
    assert dialect == "postgresql", (
        f"expected a PostgreSQL engine, got {dialect!r}")


def test_restore_real_postgresql(pg_app):
    """Build a backup, wipe the data, restore it, and verify it came back."""
    from app.extensions import db
    from app.services.backup import build_backup, restore_backup
    from app.models import User, Project
    from app.ops.models import ProjectMember

    with pg_app.app_context():
        # Clean target data without dropping tables (safe for CI PG)
        db.session.query(ProjectMember).delete()
        db.session.query(Project).delete()
        db.session.query(User).delete()
        db.session.commit()

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

        # The rows must actually be back in PostgreSQL, not just counted.
        assert db.session.query(User).filter_by(username="pg_real").one_or_none()
        assert db.session.query(Project).filter_by(name="PGReal").one_or_none()
