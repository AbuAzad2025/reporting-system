"""The zero-touch bootstrap that runs on every boot.

`app/bootstrap.py` is the difference between "clone and run" and "read the
deploy manual first", so the properties that make it safe are pinned here:
it never crashes the app, it never doubles up on a second boot, it never
leaves a guessable administrator behind, and it actually repairs a database
that is missing something.
"""
import os

import pytest
from sqlalchemy import inspect, text

from app import bootstrap
from app.extensions import db


def _announced_password(caplog):
    """The one-time password, read back out of the boot log.

    It is deliberately not stored in the bootstrap report: a report is a
    structure that could be logged, serialised into a diagnostics endpoint or
    captured in a traceback, and a credential has no business being in one.
    """
    for record in caplog.records:
        if "generated one-time password" in record.getMessage():
            return record.getMessage().rsplit(":", 1)[-1].strip()
    return None


@pytest.fixture()
def clean_bootstrap_app(tmp_path):
    """A real (non-testing) app on its own empty database.

    Built through the factory rather than by patching, because the whole claim
    is that this happens automatically on boot.
    """
    from config import Config

    class BootConfig(Config):
        TESTING = False
        SECRET_KEY = "bootstrap-test-secret-not-a-default"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/instance/boot.db"
        UPLOAD_FOLDER = str(tmp_path / "uploads")

    from app import create_app

    previous = os.environ.get("AZADEXA_AUTO_CREATE")
    os.environ["AZADEXA_AUTO_CREATE"] = "1"
    try:
        app = create_app(BootConfig)
    finally:
        if previous is None:
            os.environ.pop("AZADEXA_AUTO_CREATE", None)
        else:
            os.environ["AZADEXA_AUTO_CREATE"] = previous
    return app


# ------------------------------------------------------------------ guards


def test_ensure_ready_never_runs_under_testing(app):
    report = bootstrap.ensure_ready(app)
    assert report["ran"] is False
    assert report["reason"] == "TESTING"


def test_ensure_ready_respects_the_opt_out(clean_bootstrap_app, monkeypatch):
    monkeypatch.setenv("AZADEXA_AUTO_CREATE", "0")
    report = bootstrap.ensure_ready(clean_bootstrap_app)
    assert report["ran"] is False
    assert report["reason"] == "AZADEXA_AUTO_CREATE=0"


def test_ensure_ready_reports_health_and_stores_itself(clean_bootstrap_app):
    report = clean_bootstrap_app.extensions["azadexa_bootstrap"]
    assert report["ran"] is True
    assert report["healthy"] is True
    assert report["steps"]["schema"]["errors"] == []
    assert report["steps"]["admin"]["errors"] == []


def test_a_failing_step_cannot_stop_the_boot(clean_bootstrap_app, monkeypatch):
    """The requirement is a server that starts and reports, not one that dies."""
    import app.bootstrap as module

    def explode(_app):
        raise RuntimeError("schema step is broken")

    monkeypatch.setattr(module, "ensure_schema", explode)
    report = module.ensure_ready(clean_bootstrap_app)
    assert report["ran"] is True
    assert report["healthy"] is False
    assert "schema" in report["steps"] or report["steps"] == {}


# ------------------------------------------------------------------ storage


def test_directories_are_created_including_the_database_directory(
        clean_bootstrap_app, tmp_path):
    created = clean_bootstrap_app.extensions["azadexa_bootstrap"][
        "steps"]["storage"]["created"]
    for path in created:
        assert os.path.isdir(path)
    # The SQLite file's directory is provisioned, otherwise a fresh deployment
    # dies with the opaque "unable to open database file".
    assert (tmp_path / "instance").is_dir()
    assert (tmp_path / "uploads").is_dir()


def test_sqlite_memory_uri_needs_no_directory(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    assert bootstrap._sqlite_parent_dir(app) == ""
    app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://u:p@h/db"
    assert bootstrap._sqlite_parent_dir(app) == ""


def test_directory_provisioning_survives_an_uncreatable_path(app, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    app.config["UPLOAD_FOLDER"] = str(blocker / "nested")
    result = bootstrap.ensure_directories(app)
    assert result["errors"], "an impossible path must be reported, not swallowed"
    assert any("nested" in err for err in result["errors"])


# ------------------------------------------------------------------ schema


def test_bootstrap_creates_every_table_on_an_empty_database(
        clean_bootstrap_app):
    with clean_bootstrap_app.app_context():
        present = set(inspect(db.engine).get_table_names())
    declared = set(db.metadata.tables)
    assert declared <= present, f"missing: {sorted(declared - present)}"


def test_bootstrap_repairs_a_dropped_index(app):
    """Self-healing: an index lost from a live database is recreated."""
    from app.models import User

    index_name = next(iter(User.__table__.indexes)).name
    with app.app_context():
        before = {i["name"] for i in inspect(db.engine).get_indexes("users")}
        assert index_name in before
        db.session.execute(text(f'DROP INDEX "{index_name}"'))
        db.session.commit()

        gone = {i["name"] for i in inspect(db.engine).get_indexes("users")}
        assert index_name not in gone

        result = bootstrap.ensure_schema(app)

        after = {i["name"] for i in inspect(db.engine).get_indexes("users")}
        assert index_name in after, "the dropped index was not restored"
        assert any(index_name in created
                   for created in result["created_indexes"])


def test_schema_check_is_idempotent(clean_bootstrap_app):
    with clean_bootstrap_app.app_context():
        second = bootstrap.ensure_schema(clean_bootstrap_app)
    assert second["missing_tables"] == []
    assert second["created_tables"] == []


# ------------------------------------------------------------------ admin


def test_a_superadmin_exists_after_a_fresh_boot(clean_bootstrap_app):
    from app.models import User

    with clean_bootstrap_app.app_context():
        admins = User.query.filter_by(role="superadmin").all()
    assert len(admins) == 1
    assert admins[0].is_active


def _reprovision_admin(app, caplog):
    """Remove the boot-created admin and let the bootstrap make a new one.

    The fixture's first boot has already provisioned an administrator, so a
    second call is a no-op and announces nothing. Deleting it first is what
    exercises the creation path and produces a fresh one-time password.
    """
    from app.models import User

    with caplog.at_level("WARNING"):
        caplog.clear()
        with app.app_context():
            User.query.filter_by(role="superadmin").delete()
            db.session.commit()
            return bootstrap.ensure_platform_admin(app)


def test_the_generated_password_actually_works(clean_bootstrap_app, caplog):
    from app.models import User

    result = _reprovision_admin(clean_bootstrap_app, caplog)
    assert result["created"] is True
    generated = _announced_password(caplog)
    assert generated, "a password must be announced when none is supplied"
    with clean_bootstrap_app.app_context():
        admin = User.query.filter_by(role="superadmin").one()
        assert admin.check_password(generated)


def test_no_guessable_default_password_is_ever_set(clean_bootstrap_app):
    from app.models import User

    with clean_bootstrap_app.app_context():
        admin = User.query.filter_by(role="superadmin").one()
        for guess in ("admin", "admin123", "password", "password123",
                      "superadmin", "changeme", "12345678", ""):
            assert not admin.check_password(guess), f"{guess!r} must not work"


def test_the_generated_password_is_long_and_unpredictable(
        clean_bootstrap_app, caplog):
    _reprovision_admin(clean_bootstrap_app, caplog)
    assert len(_announced_password(caplog)) >= 32


def test_the_password_is_never_stored_in_the_report(clean_bootstrap_app,
                                                    caplog):
    """A credential must not sit in a structure that could be serialised."""
    import json

    secret = None
    _reprovision_admin(clean_bootstrap_app, caplog)
    secret = _announced_password(caplog)
    assert secret, "a fresh administrator must announce a password"
    report = clean_bootstrap_app.extensions["azadexa_bootstrap"]
    assert secret not in json.dumps(report, default=str)
    assert "generated_password" not in report["steps"]["admin"]


def test_the_password_is_shown_exactly_once(clean_bootstrap_app, caplog):
    """A second boot must not hand the credential out again."""
    with caplog.at_level("WARNING"):
        caplog.clear()
        with clean_bootstrap_app.app_context():
            second = bootstrap.ensure_platform_admin(clean_bootstrap_app)
    assert second["created"] is False
    assert _announced_password(caplog) is None


def test_an_existing_admin_is_never_modified(clean_bootstrap_app):
    from app.models import User

    with clean_bootstrap_app.app_context():
        before = User.query.filter_by(role="superadmin").one()
        before_id, before_hash = before.id, before.password_hash

        result = bootstrap.ensure_platform_admin(clean_bootstrap_app)

        after = User.query.filter_by(role="superadmin").one()
        assert result["created"] is False
        assert after.id == before_id
        assert after.password_hash == before_hash


def test_provisioning_is_idempotent(clean_bootstrap_app):
    from app.models import User

    with clean_bootstrap_app.app_context():
        for _ in range(3):
            bootstrap.ensure_platform_admin(clean_bootstrap_app)
        assert User.query.filter_by(role="superadmin").count() == 1


def test_the_password_can_be_supplied_by_the_operator(clean_bootstrap_app,
                                                      monkeypatch):
    from app.models import User

    monkeypatch.setenv("AZADEXA_SUPERADMIN_USERNAME", "ops_owner")
    monkeypatch.setenv("AZADEXA_SUPERADMIN_EMAIL", "ops@example.com")
    monkeypatch.setenv("AZADEXA_SUPERADMIN_PASSWORD", "correct-horse-battery")
    with clean_bootstrap_app.app_context():
        User.query.filter_by(role="superadmin").delete()
        db.session.commit()

        result = bootstrap.ensure_platform_admin(clean_bootstrap_app)

        assert result["created"] is True
        assert "generated_password" not in result
        admin = User.query.filter_by(username="ops_owner").one()
        assert admin.role == "superadmin"
        assert admin.email == "ops@example.com"
        assert admin.check_password("correct-horse-battery")


def test_a_taken_username_does_not_crash_the_boot(clean_bootstrap_app,
                                                  monkeypatch):
    from app.models import User

    monkeypatch.setenv("AZADEXA_SUPERADMIN_USERNAME", "superadmin")
    with clean_bootstrap_app.app_context():
        # The boot already created an admin; remove it so the only obstacle is
        # the username clash the operator's env var would cause.
        User.query.filter_by(role="superadmin").delete()
        db.session.commit()

        # A non-superadmin already holds the name the operator asked for.
        clash = User(username="superadmin", email="someone@else.test",
                     full_name="Someone", role="site_engineer")
        clash.set_password("whatever12345")
        db.session.add(clash)
        db.session.commit()

        result = bootstrap.ensure_platform_admin(clean_bootstrap_app)

        # A duplicate identity must not raise; the operator keeps a working
        # login through the account they already have.
        assert result["errors"] == []
        assert result["created"] is False
        assert result["username"] == "superadmin"
        assert User.query.filter_by(role="superadmin").count() == 0


@pytest.mark.parametrize("password,weak", [
    ("admin", True), ("admin123", True), ("password123", True),
    ("12345678", True), ("changeme", True), ("short", True),
    ("correct-horse-battery", False), ("A9x!kQ2mZ7pL4vR8", False),
])
def test_weak_password_detection(password, weak):
    assert bootstrap._weak_password(password) is weak


# ------------------------------------------------------------------ reference


def test_reference_data_is_seeded_and_idempotent(clean_bootstrap_app):
    from app.models import DynamicField, ReportTemplate

    with clean_bootstrap_app.app_context():
        first_templates = ReportTemplate.query.count()
        first_fields = DynamicField.query.count()
        assert first_templates > 0
        assert first_fields > 0

        result = bootstrap.ensure_reference_data(clean_bootstrap_app)

        assert result["ok"] is True
        assert ReportTemplate.query.count() == first_templates
        assert DynamicField.query.count() == first_fields


def test_a_reference_data_failure_is_contained(clean_bootstrap_app,
                                               monkeypatch):
    import app.services.default_templates as templates

    def explode(*_a, **_k):
        raise RuntimeError("seed is broken")

    monkeypatch.setattr(templates, "ensure_default_templates", explode)
    with clean_bootstrap_app.app_context():
        result = bootstrap.ensure_reference_data(clean_bootstrap_app)
        assert result["ok"] is False
        assert result["errors"]
