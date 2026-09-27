"""Zero-touch bootstrap: schema, first platform admin, reference data, storage.

Everything here runs automatically from the application factory, so a fresh
deployment needs no manual command before it can serve traffic. Each step is
independent, idempotent, and individually guarded: a failure is logged and the
remaining steps still run, because a half-provisioned application that boots
and reports the problem is far easier to recover than one that will not start.

Two deliberate design points:

* **No default password is ever created.** The existing code refused to seed
  users on boot, and it was right to: an account named ``superadmin`` with a
  guessable password is a backdoor, not a convenience. When no administrator
  exists, one is created either from ``AZADEXA_SUPERADMIN_PASSWORD`` or with a
  cryptographically random password that is printed exactly once. An existing
  administrator is never modified.

* **Schema changes still belong to Alembic.** ``create_all`` fills in missing
  tables and indexes, which is what a fresh or partially-provisioned database
  needs. It does not and cannot alter existing columns; that remains
  ``flask db migrate`` / ``flask db upgrade``.

Diagnostics are written to the application log and to
``app.extensions["azadexa_bootstrap"]``. They are deliberately not exposed on
an HTTP endpoint: /healthz has a fixed one-key contract, and bootstrap details
are not something an unauthenticated caller should be able to read.
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db

#: Directories the application writes into at runtime, relative to the project
#: root. Backup storage is deliberately absent: app/services/storage.py owns
#: that path, and duplicating the rule here is how a second, unused directory
#: appears next to the real one.
STORAGE_DIR_NAMES = ("instance", "uploads")

#: Mode for provisioned directories: owner+group may traverse and write, others
#: nothing. Best effort - Windows and some network filesystems ignore it.
DIR_MODE = 0o770


def _log(app):
    return app.logger


def _sqlite_parent_dir(app) -> str:
    """Directory that must exist before a file-backed SQLite database opens."""
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    prefix = "sqlite:///"
    if not uri.startswith(prefix) or uri.endswith(":memory:"):
        return ""
    path = uri[len(prefix):]
    if not path or path == ":memory:":
        return ""
    return os.path.dirname(os.path.abspath(path))


# ---------------------------------------------------------------- storage


def ensure_directories(app) -> dict[str, Any]:
    """Create the writable directories the app needs, if they are missing."""
    from config import BASE_DIR

    result: dict[str, Any] = {"checked": [], "created": [], "errors": []}
    log = _log(app)

    targets = [os.path.join(BASE_DIR, name) for name in STORAGE_DIR_NAMES]
    upload_folder = app.config.get("UPLOAD_FOLDER")
    if upload_folder:
        targets.append(str(upload_folder))

    # storage.py owns the backup path; reuse it rather than duplicating the rule.
    try:
        from app.services.storage import BACKUP_LOCAL_DIR

        if BACKUP_LOCAL_DIR:
            targets.append(str(BACKUP_LOCAL_DIR))
    except Exception as exc:  # storage import must never block boot
        result["errors"].append(f"backup dir unavailable: {exc}")

    seen: set[str] = set()
    for path in targets:
        resolved = os.path.abspath(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        result["checked"].append(resolved)
        try:
            if os.path.isdir(resolved):
                continue
            os.makedirs(resolved, exist_ok=True)
            try:
                os.chmod(resolved, DIR_MODE)
            except (OSError, NotImplementedError):
                # Windows and some mounts do not support POSIX modes.
                pass
            result["created"].append(resolved)
            log.info("bootstrap: created storage directory %s", resolved)
        except OSError as exc:
            result["errors"].append(f"{resolved}: {exc}")
            log.error("bootstrap: could not create %s (%s)", resolved, exc)

    # A SQLite file cannot be created unless its directory already exists, and
    # "unable to open database file" is an opaque way to learn that on first
    # boot. PostgreSQL needs no directory, and :memory: has no path at all.
    sqlite_dir = _sqlite_parent_dir(app)
    if sqlite_dir:
        seen.add(os.path.abspath(sqlite_dir))
        try:
            if not os.path.isdir(sqlite_dir):
                os.makedirs(sqlite_dir, exist_ok=True)
                result["created"].append(sqlite_dir)
                log.info("bootstrap: created database directory %s", sqlite_dir)
        except OSError as exc:
            result["errors"].append(f"{sqlite_dir}: {exc}")
            log.error("bootstrap: could not create database directory %s (%s)",
                      sqlite_dir, exc)

    if not result["errors"]:
        log.info("bootstrap: storage ready (%d directories, %d newly created)",
                 len(result["checked"]), len(result["created"]))
    return result


# ---------------------------------------------------------------- schema


def _index_statements(table) -> list[tuple[str, str]]:
    """(name, CREATE statement) for the plain column indexes of a table.

    Anything exotic - expression indexes, partial indexes - is skipped rather
    than approximated, because emitting the wrong DDL is worse than leaving a
    declared index for Alembic to create.
    """
    from sqlalchemy import Column

    statements = []
    for index in table.indexes:
        if not all(isinstance(expr, Column) for expr in index.expressions):
            continue
        columns = ", ".join(f'"{expr.name}"' for expr in index.expressions)
        statements.append((
            index.name,
            f'CREATE INDEX IF NOT EXISTS "{index.name}" '
            f'ON "{table.name}" ({columns})',
        ))
    return statements


def _stamp_alembic_head(app, log) -> bool:
    """Record Alembic head when this run created the tables from the models.

    Returns True when a stamp was written. Any failure is reported by the
    caller through the log; stamping is a convenience, never a blocker.
    """
    try:
        from flask import current_app
        from alembic import command as alembic_command
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory

        directory = current_app.extensions["migrate"].directory
        config = AlembicConfig(os.path.join(directory, "alembic.ini"))
        config.set_main_option("script_location", directory)
        config.set_main_option("sqlalchemy.url",
                               str(current_app.config["SQLALCHEMY_DATABASE_URI"]))
        # `alembic.command.heads` prints and returns None; the revision list
        # comes from the script directory.
        heads = ScriptDirectory.from_config(config).get_heads()
        if not heads:
            log.info("bootstrap: no Alembic revisions to stamp")
            return False

        # Loading migrations/env.py runs logging.config.fileConfig(), which
        # clears the root logger's handlers and resets its level to whatever
        # alembic.ini says. Doing that to a running application is not this
        # function's decision to make, so the root logger is put back exactly
        # as it was found.
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        try:
            alembic_command.stamp(config, "heads")
        finally:
            root.handlers[:] = saved_handlers
            root.setLevel(saved_level)

        log.warning(
            "bootstrap: schema was created from the models, so Alembic history "
            "was stamped at head (%s). Use `flask db migrate` to author the "
            "matching revision.", ", ".join(heads))
        return True
    except Exception as exc:
        log.warning("bootstrap: could not stamp Alembic head (%s). Run "
                    "`flask db stamp head` before the first `flask db upgrade`, "
                    "or the upgrade will collide with the existing tables.",
                    exc)
        return False


def _diagnose_database_error(exc: Exception, log) -> str:
    """Turn a driver error into one actionable sentence.

    The three-argument form matters: PostgreSQL's "database does not exist"
    (SQLSTATE 3D000) and "server unreachable" look identical in a stack trace
    but need completely different fixes, and neither is guessable from
    "OperationalError". Creating a database is a privileged action, so this
    reports the exact statement rather than performing it behind the
    operator's back.
    """
    code = getattr(exc, "pgcode", None) or ""
    original = str(getattr(exc, "orig", exc)).splitlines()[0]

    if code == "3D000":
        message = ("the database does not exist on that server. Create it "
                   "first, then restart: CREATE DATABASE azadexa;")
        log.error("bootstrap: %s (driver said: %s)", message, original)
        return message
    if "does not exist" in original.lower() and "database" in original.lower():
        message = ("the database does not exist on that server. Create it, "
                   "then restart.")
        log.error("bootstrap: %s (driver said: %s)", message, original)
        return message
    if "Connection refused" in original or "could not connect" in original.lower():
        message = ("the database server is not reachable. Check that "
                   "PostgreSQL is running and that DATABASE_URL is correct.")
        log.error("bootstrap: %s (driver said: %s)", message, original)
        return message
    if "authentication failed" in original.lower() or "password" in original.lower():
        message = ("the database rejected the credentials. Check the "
                   "user/password in DATABASE_URL.")
        log.error("bootstrap: %s (driver said: %s)", message, original)
        return message
    return original


def ensure_schema(app) -> dict[str, Any]:
    """Create missing tables and missing declared indexes."""
    log = _log(app)
    result: dict[str, Any] = {
        "dialect": None, "missing_tables": [], "created_tables": [],
        "failed_tables": [], "created_indexes": [], "skipped_indexes": [],
        "alembic_stamped": False, "errors": [],
    }

    try:
        engine = db.engine
    except Exception as exc:
        result["errors"].append(f"no database engine: {exc}")
        log.error("bootstrap: no database engine available (%s)", exc)
        return result

    result["dialect"] = engine.dialect.name

    try:
        inspector = inspect(engine)
        present = set(inspector.get_table_names())
        declared = [t.name for t in db.metadata.sorted_tables]
        result["missing_tables"] = [name for name in declared
                                    if name not in present]

        if result["missing_tables"]:
            log.warning("bootstrap: %d table(s) missing, creating: %s",
                        len(result["missing_tables"]),
                        ", ".join(result["missing_tables"]))
            db.create_all()
            present = set(inspect(engine).get_table_names())
            result["created_tables"] = [name for name in result["missing_tables"]
                                        if name in present]
            result["failed_tables"] = [name for name in result["missing_tables"]
                                       if name not in present]
            for name in result["failed_tables"]:
                result["errors"].append(f"table {name} still missing after create_all")
                log.error("bootstrap: table %s could not be created", name)

            # Tables built from the models, with no Alembic history, would make
            # a later `flask db upgrade` try to create them all again and fail
            # on "already exists". Because this step is what created them, the
            # database is at head by construction, so recording head is a
            # statement of fact rather than a guess. Stamping is only done in
            # that case: an existing database with an empty history is left
            # alone, because that one really is a decision for an operator.
            result["alembic_stamped"] = _stamp_alembic_head(app, log)
        else:
            log.info("bootstrap: schema complete (%d tables)", len(present))

        # Declared indexes on tables that already existed may be absent if a
        # column gained index=True without a migration ever being applied.
        if engine.dialect.name in ("mysql", "mariadb"):
            log.info("bootstrap: skipping index check on %s (no IF NOT EXISTS)",
                     engine.dialect.name)
        else:
            for table in db.metadata.sorted_tables:
                if table.name not in present:
                    continue
                existing = {idx["name"]
                            for idx in inspector.get_indexes(table.name)}
                for name, ddl in _index_statements(table):
                    if name in existing:
                        continue
                    try:
                        db.session.execute(text(ddl))
                        result["created_indexes"].append(f"{table.name}.{name}")
                    except SQLAlchemyError as exc:
                        result["skipped_indexes"].append(f"{table.name}.{name}")
                        log.warning("bootstrap: could not create index %s.%s (%s)",
                                    table.name, name, exc)
            if result["created_indexes"]:
                db.session.commit()
                log.warning("bootstrap: created %d missing index(es): %s",
                            len(result["created_indexes"]),
                            ", ".join(result["created_indexes"]))
    except Exception as exc:
        db.session.rollback()
        result["errors"].append(_diagnose_database_error(exc, log))
        log.error("bootstrap: schema check failed (%s)", exc)

    return result


# ---------------------------------------------------------------- first admin


def _weak_password(password: str) -> bool:
    return len(password) < 12 or password.lower() in {
        "admin", "admin123", "password", "password123", "12345678",
        "changeme", "superadmin",
    }


def ensure_platform_admin(app) -> dict[str, Any]:
    """Guarantee exactly one usable platform administrator exists.

    Never touches an account that is already there, and never invents a
    password: a random one is generated and shown once if the operator did not
    supply one.
    """
    log = _log(app)
    result: dict[str, Any] = {"created": False, "username": None, "errors": []}

    try:
        from app.models import User

        existing = User.query.filter(
            User.role == "superadmin", User.is_active.is_(True)).first()
        if existing is not None:
            result["username"] = existing.username
            log.info("bootstrap: platform admin present (%s), nothing to do",
                     existing.username)
            return result

        username = (os.environ.get("AZADEXA_SUPERADMIN_USERNAME")
                    or "").strip() or "superadmin"
        email = (os.environ.get("AZADEXA_SUPERADMIN_EMAIL")
                 or "").strip() or f"{username}@localhost.invalid"
        full_name = (os.environ.get("AZADEXA_SUPERADMIN_NAME")
                     or "").strip() or "مدير النظام الافتراضي"
        company = (os.environ.get("AZADEXA_SUPERADMIN_COMPANY")
                   or "").strip() or app.config.get("COMPANY_NAME_EN", "")

        supplied = os.environ.get("AZADEXA_SUPERADMIN_PASSWORD") or ""
        generated = False
        if supplied:
            if _weak_password(supplied):
                log.warning(
                    "bootstrap: AZADEXA_SUPERADMIN_PASSWORD is weak; use at "
                    "least 12 unpredictable characters")
        else:
            supplied = secrets.token_urlsafe(24)
            generated = True

        user = User(username=username, email=email, full_name=full_name,
                    role="superadmin", company=company)
        user.set_password(supplied)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            # Another worker provisioned it first, or the username/email is
            # already taken. Either way the invariant now holds.
            db.session.rollback()
            result["username"] = username
            log.info("bootstrap: platform admin already present "
                     "(concurrent boot or duplicate identity)")
            return result

        result["created"] = True
        result["username"] = username
        if generated:
            log.warning(
                "bootstrap: created superadmin %r with a generated one-time "
                "password. Sign in and change it now - this is the only time "
                "it is shown: %s", username, supplied)
        else:
            log.warning("bootstrap: created superadmin %r using "
                        "AZADEXA_SUPERADMIN_PASSWORD", username)
    except Exception as exc:
        db.session.rollback()
        result["errors"].append(str(exc))
        log.error("bootstrap: platform admin check failed (%s)", exc)

    return result


# ---------------------------------------------------------------- reference data


def ensure_reference_data(app, admin_id=None) -> dict[str, Any]:
    """Seed the system templates and their fields if they are missing."""
    log = _log(app)
    result: dict[str, Any] = {"ok": False, "errors": []}
    try:
        from app.models import ReportTemplate, DynamicField
        from app.services.default_templates import ensure_default_templates

        ensure_default_templates(db, ReportTemplate, DynamicField,
                                 admin_id=admin_id)
        db.session.commit()
        result["ok"] = True
        result["templates"] = ReportTemplate.query.count()
        result["fields"] = DynamicField.query.count()
        log.info("bootstrap: reference data ready (%d templates, %d fields)",
                 result["templates"], result["fields"])
    except Exception as exc:
        db.session.rollback()
        result["errors"].append(str(exc))
        log.warning("bootstrap: reference data seed skipped (%s)", exc)
    return result


# ---------------------------------------------------------------- entry point


def _run_step(name: str, app, func, *args) -> dict[str, Any]:
    """Run one bootstrap step, converting any escape into a reported error.

    Each step guards its own internals, but a guard can itself fail (a bad
    monkeypatch, an unexpected driver error in cleanup). The requirement is
    that the server always starts, so the call site is guarded too.
    """
    try:
        return func(app, *args)
    except Exception as exc:
        _log(app).error("bootstrap: step %s failed (%s)", name, exc)
        try:
            db.session.rollback()
        except Exception as rollback_exc:
            # Nothing useful is left to do: the connection is already gone. It
            # is still worth recording, because a session that cannot be
            # rolled back will also fail the first real request.
            _log(app).error("bootstrap: rollback after step %s failed too (%s)",
                            name, rollback_exc)
        return {"errors": [f"{name}: {exc}"]}


def ensure_ready(app) -> dict[str, Any]:
    """Run every bootstrap step. Never raises: the app must still boot."""
    log = _log(app)
    report: dict[str, Any] = {"ran": True, "steps": {}}

    if app.config.get("TESTING"):
        report["ran"] = False
        report["reason"] = "TESTING"
        return report
    if os.environ.get("AZADEXA_AUTO_CREATE", "1") != "1":
        report["ran"] = False
        report["reason"] = "AZADEXA_AUTO_CREATE=0"
        log.info("bootstrap: disabled by AZADEXA_AUTO_CREATE=0")
        return report

    with app.app_context():
        report["steps"]["storage"] = _run_step("storage", app,
                                               ensure_directories)
        report["steps"]["schema"] = _run_step("schema", app, ensure_schema)
        report["steps"]["admin"] = _run_step("admin", app,
                                             ensure_platform_admin)
        report["steps"]["reference_data"] = _run_step(
            "reference_data", app, ensure_reference_data)

    problems = [name for name, step in report["steps"].items()
                if step.get("errors")]
    report["healthy"] = not problems
    if problems:
        log.error("bootstrap: finished with problems in: %s",
                  ", ".join(problems))
    else:
        log.info("bootstrap: complete and healthy")
    return report
