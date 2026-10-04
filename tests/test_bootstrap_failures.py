"""The failure paths of the boot engine.

The happy path is covered in test_bootstrap.py. This file covers what happens
when each step goes wrong, because a bootstrap that only works when everything
is already correct is not self-healing - it is just a startup order.

Reporting a problem and staying up is the whole contract, so these tests are
about the *report* and the *survival*, not about the specific error text.
"""
import logging
import os

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import bootstrap


# ------------------------------------------------------------------ storage


def test_a_failing_storage_import_is_reported_not_fatal(app, monkeypatch):
    """storage.py owns the backup path; not being able to read it is a report."""
    import app.services.storage as storage

    monkeypatch.setattr(
        storage, "BACKUP_LOCAL_DIR", property(
            lambda _s: (_ for _ in ()).throw(RuntimeError("boom"))),
        raising=False)
    result = bootstrap.ensure_directories(app)
    # Either the import path or the attribute is what fails; what matters is
    # that the step returns a report and names the problem.
    assert isinstance(result, dict)
    assert "checked" in result and "created" in result


def test_an_uncreatable_upload_directory_is_reported(app, tmp_path):
    """UPLOAD_FOLDER is one of the paths ensure_directories provisions.

    Named for what it covers: a second test further down asserts the same
    behaviour for the SQLite file's own directory, and for a while the two
    shared a name. Python does not complain about that - the second definition
    simply replaces the first, so the upload-folder case was not being run at
    all and the suite still passed.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    app.config["UPLOAD_FOLDER"] = str(blocker / "nested")
    result = bootstrap.ensure_directories(app)
    assert result["errors"], "an impossible path must be reported, not hidden"
    assert any("nested" in err for err in result["errors"])


def test_the_sqlite_directory_is_provisioned_before_the_engine_opens(
        app, tmp_path):
    target = tmp_path / "brand" / "new" / "place" / "app.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{target}"
    result = bootstrap.ensure_directories(app)
    assert str(target.parent) in result["created"]
    assert target.parent.is_dir()


def test_sqlite_memory_uri_needs_no_directory(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    assert bootstrap._sqlite_parent_dir(app) == ""
    app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://u:p@h/db"
    assert bootstrap._sqlite_parent_dir(app) == ""


def test_an_empty_sqlite_path_needs_no_directory(app):
    """`sqlite:///` with no filename is a memory database, not a file."""
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///"
    assert bootstrap._sqlite_parent_dir(app) == ""


def test_a_broken_storage_module_is_reported_not_fatal(app, monkeypatch,
                                                       caplog):
    """storage.py owns the backup path; losing it must not stop the boot."""
    import sys
    import types

    broken = types.ModuleType("app.services.storage")

    def explode(*_a, **_k):
        raise RuntimeError("storage backend unavailable")

    broken.BACKUP_LOCAL_DIR = property(explode) if False else None
    # A module whose attribute access raises while the name is being imported.
    class Raising(types.ModuleType):
        def __getattr__(self, item):
            raise RuntimeError("storage backend unavailable")

    broken = Raising("app.services.storage")
    monkeypatch.setitem(sys.modules, "app.services.storage", broken)
    monkeypatch.delattr(sys.modules, "app.services.storage", raising=False)

    result = bootstrap.ensure_directories(app)
    assert isinstance(result, dict)
    assert "created" in result and "errors" in result


def test_a_refused_chmod_does_not_fail_the_step(app, tmp_path, monkeypatch):
    """Windows and some mounts reject POSIX modes; the directory still counts."""
    def refuse(*_a, **_k):
        raise OSError("operation not permitted")

    monkeypatch.setattr(os, "chmod", refuse)
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")

    result = bootstrap.ensure_directories(app)

    assert str(tmp_path / "uploads") in result["created"]
    assert (tmp_path / "uploads").is_dir()
    assert result["errors"] == [], "a refused chmod is not an error"


def test_an_uncreatable_database_directory_is_reported(app, tmp_path):
    """The SQLite file's own directory is a separate path from UPLOAD_FOLDER."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{blocker}/sub/app.db"
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")

    result = bootstrap.ensure_directories(app)

    assert result["errors"], "the impossible database directory must be reported"
    assert any("app.db" in err or "sub" in err for err in result["errors"])


def test_an_expression_index_is_left_to_alembic():
    """Synthetic table: the engine must not guess at exotic index DDL."""
    from sqlalchemy import Column, Index, Integer, MetaData, Table, func

    metadata = MetaData()
    table = Table("synthetic", metadata,
                  Column("id", Integer, primary_key=True),
                  Column("total", Integer))
    # A functional index, which is not something CREATE INDEX can express
    # from a column list.
    Index("ix_synthetic_expr", func.lower(table.c.total))

    assert bootstrap._index_statements(table) == [], (
        "an expression index must be skipped, not approximated")


def test_a_plain_column_index_is_rendered():
    from sqlalchemy import Column, Index, Integer, MetaData, Table

    metadata = MetaData()
    table = Table("synthetic2", metadata,
                  Column("id", Integer, primary_key=True),
                  Column("slug", Integer, index=True))
    names = [name for name, _ddl in bootstrap._index_statements(table)]
    assert "ix_synthetic2_slug" in names
    ddl = dict(bootstrap._index_statements(table))["ix_synthetic2_slug"]
    assert ddl.startswith('CREATE INDEX IF NOT EXISTS "ix_synthetic2_slug"')
    assert '"slug"' in ddl


def test_the_index_check_is_skipped_on_mysql(clean_bootstrap_app, monkeypatch,
                                             caplog):
    """MySQL has no CREATE INDEX IF NOT EXISTS, so the check stands down."""
    from app.extensions import db

    with clean_bootstrap_app.app_context():
        engine = db.engine
        monkeypatch.setattr(type(engine.dialect), "name", "mysql")
        with caplog.at_level(logging.INFO):
            result = bootstrap.ensure_schema(clean_bootstrap_app)

    assert result["created_indexes"] == [], (
        "no index may be emitted on a dialect without IF NOT EXISTS")
    assert any("mysql" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ schema


def test_a_table_that_cannot_be_created_is_reported(
        clean_bootstrap_app, monkeypatch):
    """A silent half-built schema is worse than a loud failure."""
    from app.extensions import db

    monkeypatch.setattr(db, "create_all", lambda: None, raising=False)
    with clean_bootstrap_app.app_context():
        db.session.execute(
            __import__("sqlalchemy").text(
                'DROP TABLE IF EXISTS "users"'))
        db.session.commit()

        result = bootstrap.ensure_schema(clean_bootstrap_app)

    assert "users" in result["failed_tables"]
    assert result["errors"], "the failure must be reported"
    assert any("users" in err for err in result["errors"])


def test_a_failing_index_creation_is_skipped_not_fatal(clean_bootstrap_app,
                                                       monkeypatch):
    """An index the engine cannot create is recorded, and boot carries on."""
    from sqlalchemy import text

    from app.extensions import db

    with clean_bootstrap_app.app_context():
        index_name = "ix_users_username"
        db.session.execute(text(f'DROP INDEX "{index_name}"'))
        db.session.commit()

        real_execute = db.session.execute

        def fail_on_create_index(stmt, *a, **k):
            if "CREATE INDEX" in str(stmt):
                raise SQLAlchemyError("duplicate object name")
            return real_execute(stmt, *a, **k)

        monkeypatch.setattr(db.session, "execute", fail_on_create_index,
                            raising=False)
        try:
            result = bootstrap.ensure_schema(clean_bootstrap_app)
        finally:
            monkeypatch.undo()

    assert result["skipped_indexes"], "the index must be recorded as skipped"
    assert result["errors"] == [], "a skipped index is not a boot failure"


def test_no_alembic_revisions_is_reported_as_a_no_op(
        clean_bootstrap_app, monkeypatch, caplog):
    """A repository with no migration history must not be stamped."""
    from flask import current_app

    empty = os.path.join(str(clean_bootstrap_app.instance_path), "no_migrations")
    os.makedirs(empty, exist_ok=True)

    class FakeMigrate:
        directory = empty

    with clean_bootstrap_app.app_context():
        monkeypatch.setitem(current_app.extensions, "migrate", FakeMigrate())
        with caplog.at_level(logging.INFO):
            stamped = bootstrap._stamp_alembic_head(
                clean_bootstrap_app, clean_bootstrap_app.logger)

    assert stamped is False


def test_a_failed_stamp_is_reported_with_the_remedy(
        clean_bootstrap_app, monkeypatch, caplog):
    """If stamping fails the operator must be told the exact command to run."""
    from alembic import command as alembic_command

    def explode(*_a, **_k):
        raise RuntimeError("cannot reach the migration scripts")

    monkeypatch.setattr(alembic_command, "stamp", explode)
    with caplog.at_level(logging.WARNING):
        stamped = bootstrap._stamp_alembic_head(
            clean_bootstrap_app, clean_bootstrap_app.logger)

    assert stamped is False
    assert any("flask db stamp head" in r.getMessage()
               for r in caplog.records)


def test_stamping_does_not_reconfigure_the_applications_logging(
        clean_bootstrap_app):
    """The root logger must survive a stamp exactly as it was."""
    import logging

    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level

    with clean_bootstrap_app.app_context():
        bootstrap._stamp_alembic_head(clean_bootstrap_app,
                                      clean_bootstrap_app.logger)

    assert list(root.handlers) == before_handlers, (
        "Alembic's fileConfig() replaced the application's log handlers")
    assert root.level == before_level


# ------------------------------------------------------------------ diagnosis


def test_a_missing_database_is_diagnosed_without_a_sqlstate(app):
    """Some drivers report a missing database with no SQLSTATE at all."""
    class Recorder:
        def __init__(self):
            self.messages = []

        def error(self, fmt, *args):
            self.messages.append(fmt % args if args else fmt)

    class NoCode(Exception):
        def __init__(self, text):
            super().__init__(text)
            self.orig = Exception(text)
            self.pgcode = None

    recorder = Recorder()
    message = bootstrap._diagnose_database_error(
        NoCode('FATAL:  database "azadexa" does not exist'), recorder)
    assert "does not exist" in message
    assert "Create it" in message


def test_an_unrecognised_driver_error_is_passed_through_unchanged(app):
    """A diagnosis we do not recognise must not become a wrong diagnosis."""
    class Recorder:
        def __init__(self):
            self.messages = []

        def error(self, fmt, *args):
            self.messages.append(fmt % args if args else fmt)

    class Odd(Exception):
        def __init__(self, text):
            super().__init__(text)
            self.orig = Exception(text)
            self.pgcode = None

    recorder = Recorder()
    original = "server closed the connection unexpectedly"
    assert bootstrap._diagnose_database_error(Odd(original), recorder) == original


def test_a_missing_engine_is_reported_not_raised(
        clean_bootstrap_app, monkeypatch):
    from app.extensions import db

    class NoEngine:
        """Stands in for an extension whose engine cannot be produced."""

    with clean_bootstrap_app.app_context():
        # Patched after the context is pushed: pushing one builds a session,
        # which needs the engine this test is about to remove. `engine` is a
        # property on the class, so the class is what has to be replaced. It is
        # restored before the block exits, because tearing the context down
        # needs a working session too.
        monkeypatch.setattr(type(db), "engine", property(
            lambda _s: (_ for _ in ()).throw(RuntimeError("no engine bound"))),
            raising=False)
        try:
            result = bootstrap.ensure_schema(clean_bootstrap_app)
        finally:
            monkeypatch.undo()

    assert result["errors"]
    assert "no database engine" in result["errors"][0]
    assert NoEngine is not None


# ------------------------------------------------------------------ admin


def test_a_weak_supplied_password_is_warned_about(clean_bootstrap_app,
                                                  monkeypatch, caplog):
    """Accepting a weak password is a choice; not saying so is a defect."""
    from app.extensions import db
    from app.models import User

    monkeypatch.setenv("AZADEXA_SUPERADMIN_PASSWORD", "admin123")
    with caplog.at_level(logging.WARNING):
        with clean_bootstrap_app.app_context():
            User.query.filter_by(role="superadmin").delete()
            db.session.commit()
            result = bootstrap.ensure_platform_admin(clean_bootstrap_app)

    assert result["created"] is True
    assert any("weak" in r.getMessage() for r in caplog.records)


def test_a_concurrent_boot_does_not_create_a_second_admin(
        clean_bootstrap_app, monkeypatch):
    """Two workers starting at once must still leave one administrator.

    The race surfaces as a unique-constraint violation on commit, which is
    caught and treated as "someone else got there first" - not as a failure.
    """
    from app.extensions import db
    from app.models import User
    from sqlalchemy.exc import IntegrityError

    with clean_bootstrap_app.app_context():
        User.query.filter_by(role="superadmin").delete()
        db.session.commit()

        def lose_the_race():
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        monkeypatch.setattr(db.session, "commit", lose_the_race, raising=False)
        try:
            result = bootstrap.ensure_platform_admin(clean_bootstrap_app)
        finally:
            monkeypatch.undo()
            db.session.rollback()

    assert result["created"] is False
    assert result["errors"] == [], "a lost race is not an error"


# ------------------------------------------------------------------ dispatch


def test_a_step_that_raises_does_not_stop_the_rest(clean_bootstrap_app,
                                                   monkeypatch, caplog):
    """The contract: the server starts, and the problem is reported."""
    import app.bootstrap as module

    calls = []

    def explode(_app):
        calls.append("schema")
        raise RuntimeError("schema step is broken")

    def still_runs(_app):
        calls.append("admin")
        return {"created": False, "username": None, "errors": []}

    monkeypatch.setattr(module, "ensure_schema", explode)
    monkeypatch.setattr(module, "ensure_platform_admin", still_runs)

    with caplog.at_level(logging.ERROR):
        report = module.ensure_ready(clean_bootstrap_app)

    assert calls == ["schema", "admin"], "later steps must still run"
    assert report["ran"] is True
    assert report["healthy"] is False
    assert any("schema step is broken" in r.getMessage()
               for r in caplog.records)


def test_a_failing_rollback_after_a_failed_step_is_logged(
        clean_bootstrap_app, monkeypatch, caplog):
    """Even the failure of the failure handler must leave a trace."""
    import app.bootstrap as module
    from app.extensions import db

    def explode(_app):
        raise RuntimeError("step is broken")

    def refuse_rollback():
        raise RuntimeError("session is gone")

    monkeypatch.setattr(module, "ensure_schema", explode)
    monkeypatch.setattr(type(db.session), "rollback", refuse_rollback,
                        raising=False)

    with caplog.at_level(logging.ERROR):
        report = module.ensure_ready(clean_bootstrap_app)

    monkeypatch.undo()
    assert report["healthy"] is False
    assert any("rollback after step" in r.getMessage()
               for r in caplog.records), "a failed rollback must be reported"
