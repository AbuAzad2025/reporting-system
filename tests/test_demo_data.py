"""The consolidated demo dataset, and the CLI that exposes it.

This module replaced a 26KB top-level script that sat beside the application
and was run by hand. Two things are pinned here:

* the dataset is complete - all nine operations modules and the demo tenancy
  really are created, so deleting the script lost nothing;
* it is never part of boot. Sample contractual records must not appear in
  whatever project the application is actually used for.
"""
import pytest
from sqlalchemy import inspect

from app import bootstrap
from app.extensions import db


@pytest.fixture()
def demo_app(tmp_path):
    """A booted app on an empty database, ready for demo data."""
    from config import Config

    class DemoConfig(Config):
        TESTING = False
        SECRET_KEY = "demo-dataset-test-secret-not-default"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/instance/demo.db"
        UPLOAD_FOLDER = str(tmp_path / "uploads")

    from app import create_app

    app = create_app(DemoConfig)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def test_the_whole_demo_dataset_runs(demo_app):
    from app.services.demo_data import seed_operational_demo

    with demo_app.app_context():
        report = seed_operational_demo()

    assert sorted(report["users"]) == ["admin", "engineer", "engineer2",
                                       "owner", "safety"]
    assert len(report["projects"]) == 2
    counts = report["ops_counts"]
    assert len(counts) == 9, f"expected all nine ops modules, got {sorted(counts)}"
    for kind, count in counts.items():
        assert count >= 1, f"{kind} was seeded with no records"


def test_demo_data_creates_the_tenancy_it_claims(demo_app):
    from app.models import Project, User
    from app.ops.models import ProjectMember
    from app.services.demo_data import seed_operational_demo

    with demo_app.app_context():
        seed_operational_demo()
        assert Project.query.count() == 2
        assert ProjectMember.query.count() >= 2
        # A second engineer exists precisely to cover cross-tenant isolation.
        assert User.query.filter_by(username="engineer2").one()
        assert User.query.filter_by(username="engineer2").one() is not None


def test_demo_data_is_idempotent(demo_app):
    from app.ops.models import RFI
    from app.services.demo_data import seed_operational_demo

    with demo_app.app_context():
        seed_operational_demo()
        first = RFI.query.count()
        second_run = seed_operational_demo()
        assert RFI.query.count() == first
    assert second_run["ops_counts"]["rfis"] == first


def test_demo_data_survives_a_second_bootstrap(demo_app):
    """The engine and the demo dataset must not fight each other.

    Worth stating plainly: the demo set includes an `owner` account whose role
    is superadmin and whose password is published in the README. That is only
    acceptable because the demo is opt-in - a cold boot must never create it,
    which is what test_boot_alone_never_creates_demo_content pins.
    """
    from app.models import User
    from app.services.demo_data import seed_operational_demo

    with demo_app.app_context():
        seed_operational_demo()
        again = bootstrap.ensure_platform_admin(demo_app)
        assert again["created"] is False, "boot must not act on demo data"

        superadmins = User.query.filter_by(role="superadmin").all()
        # One from the engine, one from the demo set - and no more.
        assert len(superadmins) == 2
        assert sorted(u.username for u in superadmins) == ["owner", "superadmin"]
        # The engine's own account is still not reachable with a known password.
        engine_admin = [u for u in superadmins if u.username == "superadmin"][0]
        for guess in ("", "admin", "admin123", "owner123", "password"):
            assert not engine_admin.check_password(guess)


def test_boot_alone_never_creates_demo_content(demo_app):
    """The single most important property: no fake records from a cold boot."""
    from app.models import Project, ReportSubmission, User
    from app.ops.models import RFI

    with demo_app.app_context():
        assert Project.query.count() == 0
        assert User.query.count() == 1, "only the platform admin"
        assert RFI.query.count() == 0
        assert ReportSubmission.query.count() == 0


def test_the_demo_cli_command_is_registered(demo_app):
    assert "seed-operational-demo" in demo_app.cli.commands
    assert "seed" in demo_app.cli.commands
    assert "seed-demo-reports" in demo_app.cli.commands


def test_the_demo_cli_command_runs_end_to_end(demo_app):
    result = demo_app.test_cli_runner().invoke(args=["seed-operational-demo"])
    assert result.exit_code == 0, result.output
    assert "Demo users" in result.output
    assert "Ops records" in result.output
    with demo_app.app_context():
        from app.models import Project
        assert Project.query.count() == 2


def test_templates_come_from_the_engine_not_the_demo_module(demo_app):
    """One source of truth for reference data.

    The demo module must not seed templates itself; the bootstrap owns them.
    """
    import inspect as pyinspect

    from app.services import demo_data

    source = pyinspect.getsource(demo_data)
    assert "ensure_default_templates(" not in source, (
        "the demo dataset must not seed reference data; the engine owns it")
    with demo_app.app_context():
        from app.models import ReportTemplate
        assert ReportTemplate.query.count() > 0


def test_no_legacy_seed_script_remains():
    """The point of the refactor: one entry point, not two."""
    import os

    for legacy in ("seed.py", "setup.py"):
        assert not os.path.exists(legacy), (
            f"{legacy} still exists; the dataset belongs in app/services")


def test_the_bootstrap_report_exposes_no_credential(demo_app):
    import json

    report = demo_app.extensions["azadexa_bootstrap"]
    assert "generated_password" not in report["steps"]["admin"]
    assert "alembic_stamped" in report["steps"]["schema"]
    # The database is created by the engine on a fresh boot.
    with demo_app.app_context():
        assert len(inspect(db.engine).get_table_names()) > 0
    json.dumps(report, default=str)
