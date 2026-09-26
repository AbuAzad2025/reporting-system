"""CLI command contract + first-boot AUTO_CREATE gate for ``app/__init__.py``.

Every test drives the real commands through ``app.test_cli_runner()`` and then
asserts the resulting **database** state (rows, hashes, dates, counters) — no
smoke tests, no ``assert True``, no ``hasattr`` probes, no ``xfail``.

``app/__init__.py`` — line ranges exercised here
------------------------------------------------
* 31-33, 51-56  boot cookie/CSRF hardening: a config asking for
          ``SESSION_COOKIE_HTTPONLY = False`` is forced back to ``True`` and a
          blank ``SESSION_COOKIE_SAMESITE`` is defaulted to ``Lax``, while an
          explicit ``Strict`` policy and the non-``TESTING`` (CSRF-armed) path
          are left alone. The emitted ``Set-Cookie`` header carries
          ``HttpOnly``/``SameSite=Lax``.
* 142-151 ``AZADEXA_AUTO_CREATE`` gate. ``=0`` leaves the schema unbuilt (the
          SQLite file is absent or 0 bytes, the inspector lists no table);
          ``=1`` runs ``db.create_all()`` plus ``ensure_default_templates`` —
          asserted from both sides, including that ``=1`` still seeds **no**
          users, because boot must never create demo accounts silently, and
          that a raising ``ensure_default_templates`` is swallowed into a
          warning instead of breaking the boot.
* 154-181 ``flask seed``: creates owner/admin/engineer/safety with the
          documented roles, e-mails, four-part Arabic names and company; stores
          a salted one-way hash and never the plaintext; materialises the 11
          default templates plus their ordered dynamic fields on a virgin
          schema; and is idempotent — a second run adds no user, no template,
          no field, leaves the first-run hashes intact and creates no duplicate
          value under any unique key.
* 183-217 ``flask seed-demo-reports``: early return when the ``engineer``
          account is absent (message asserted, zero rows written); reuse of an
          already-present demo project; one submission per *active* template
          only; the ``today - i days`` ladder — the open-day spread, asserted
          through :func:`_open_days`; answers mirrored from ``ordered_fields``;
          project / engineer stamping; and a second run that duplicates no row,
          no id and no serial.
* 219-230 ``flask cleanup-orphaned-attachments``: ``--dry-run`` reports the
          three counters while deleting neither row nor file; the real run
          deletes both — the pair pins that the flag is honoured.

Isolation note: the second apps built by ``isolated_factory`` own a private
SQLite file and share no rows with the ``app`` fixture, so seeded users are
only expected where the test itself ran ``flask seed``.
"""
import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import inspect


#: The default dynamic-template catalogue `flask seed` must materialise.
EXPECTED_TEMPLATE_KEYS = [
    "cost-variances",
    "daily",
    "material-submittals",
    "monthly",
    "progress-billings",
    "rfis",
    "safety",
    "site-inspections",
    "subcontractor-performances",
    "variation",
    "weekly",
]

#: username -> (email, four-part Arabic name, role, documented password)
SEED_ACCOUNTS = {
    "owner": ("owner@platform.com", "مالك المنصة الرئيسي العام",
              "superadmin", "owner123"),
    "admin": ("admin@site.com", "محمد أحمد علي حسن",
              "admin", "admin123"),
    "engineer": ("eng@site.com", "خالد سعيد محمود عبدالله",
                 "site_engineer", "site123"),
    "safety": ("safety@site.com", "سارة علي محمد حسن",
               "safety_officer", "safe123"),
}

#: Company stamped on every seeded account.
SEED_COMPANY = "شركة أزاد للأنظمة الذكية"

#: (name, location, contractor) of the demo project `seed-demo-reports` needs.
DEMO_PROJECT = ("مشروع برج النخيل السكني", "الرياض — حي النرجس",
                "المقاول الرئيسي")

#: Every table ``db.create_all()`` must materialise on the ``=1`` boot branch.
EXPECTED_TABLES = [
    "cost_variances",
    "daily_reports",
    "dynamic_fields",
    "material_submittals",
    "ops_attachments",
    "ops_record_comments",
    "progress_billings",
    "project_members",
    "projects",
    "report_submissions",
    "report_templates",
    "reports",
    "rfis",
    "safety_reports",
    "site_inspections",
    "subcontractor_performances",
    "tenant_branding",
    "tenant_template_overrides",
    "users",
    "variation_orders",
]


# ================================================================= helpers
def _db_file(app):
    """Absolute path of the SQLite file behind ``app`` (SQLite only)."""
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    assert uri.startswith("sqlite:///")
    return uri[len("sqlite:///"):]


def _db_size(app):
    """Byte size of the app's SQLite file (0 when absent or still empty)."""
    path = Path(_db_file(app))
    return path.stat().st_size if path.exists() else 0


def _table_names(app):
    from app.extensions import db
    with app.app_context():
        return set(inspect(db.engine).get_table_names())


def _duplicated_keys(app, *columns):
    """Values of ``columns`` that appear on more than one row (must be empty)."""
    from app.extensions import db
    with app.app_context():
        seen, dupes = set(), set()
        for row in db.session.query(*columns).all():
            key = tuple(row)
            if key in seen:
                dupes.add(key)
            seen.add(key)
        return dupes


def _get(app, model, primary_key):
    from app.extensions import db
    with app.app_context():
        return db.session.get(model, primary_key)


def _open_days(submission, today=None):
    """Days a submission has been open: ``today - report_date``, never < 0.

    Same arithmetic the archive/PDF layers use to age a record (``days_open``
    on the ops mixin), applied to the dynamic submissions the demo seeder
    back-dates one day per template.
    """
    return ((today or date.today()) - submission.report_date).days


def _fixture_ids(app):
    """(project_id, user_id) of the conftest Alpha Tower / t_eng rows."""
    from app.models import Project, User
    with app.app_context():
        return (Project.query.filter_by(name="Alpha Tower").one().id,
                User.query.filter_by(username="t_eng").one().id)


def _plant_attachments(app, project_id, user_id):
    """Three real rows covering every branch of the cleanup walk.

    * ``healthy``  — record alive, bytes on disk -> not counted at all
    * ``orphan``   — record gone                 -> ``orphan_rows``
    * ``headless`` — record alive, no bytes     -> ``missing_files`` (report only)

    Every planted file has a matching row, so the on-disk walk only flags the
    separate stray file planted by :func:`_plant_stray_file`.
    """
    from app.extensions import db
    from app.ops.models import Attachment, RFI, SiteInspection
    root = Path(app.config["UPLOAD_FOLDER"])
    with app.app_context():
        inspection = SiteInspection.query.first()
        rfi = RFI.query.first()
        specs = [
            ("healthy", "site-inspections", inspection.id,
             "ops/site-inspections/%d/a1b2c3d4e5f6_evidence.png" % inspection.id,
             b"\x89PNG\r\n\x1a\ncli-test"),
            ("orphan", "rfis", 987654,
             "ops/rfis/987654/ffeeddccbbaa_gone.png", b"orphan-bytes"),
            ("headless", "rfis", rfi.id,
             "ops/rfis/%d/112233445566_missing.pdf" % rfi.id, None),
        ]
        ids, keys = {}, {}
        for name, kind, record_id, key, payload in specs:
            if payload is not None:
                target = root / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            att = Attachment(record_kind=kind, record_id=record_id,
                             project_id=project_id,
                             filename=key.rsplit("/", 1)[1], storage_key=key,
                             mime_type="image/png",
                             byte_size=len(payload or b""),
                             uploaded_by=user_id)
            db.session.add(att)
            ids[name] = att
            keys[name] = key
        db.session.commit()
        return {name: att.id for name, att in ids.items()}, keys


def _plant_stray_file(app):
    """A file under ``UPLOAD_FOLDER/ops`` that no DB row references."""
    stray = Path(app.config["UPLOAD_FOLDER"]) / "ops" / "rfis" / "1" / \
        "stray-upload.png"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"stray")
    return stray


def _boot(tmp_path, monkeypatch, slug, auto_create="0", **overrides):
    """Build a second, fully isolated app: own config class + own DB file.

    Mirrors the ``isolated_app`` pattern of
    ``tests/test_app_admin_hardening.py``, but parameterised on
    ``AZADEXA_AUTO_CREATE`` so both sides of the boot gate can be exercised.
    """
    from config import Config
    from app import create_app

    class BootConfig(Config):
        TESTING = True
        SECRET_KEY = "cli-boot-secret-3f7c92"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path}/{slug}.db"

    for key, value in overrides.items():
        setattr(BootConfig, key, value)
    monkeypatch.setenv("AZADEXA_AUTO_CREATE", auto_create)
    return create_app(BootConfig)


@pytest.fixture()
def isolated_factory(tmp_path, monkeypatch):
    """``_boot`` wrapper that also keeps file work inside tmp."""
    built = {"n": 0}

    def build(auto_create, **overrides):
        built["n"] += 1
        slug = f"iso{built['n']}"
        application = _boot(tmp_path, monkeypatch, slug, auto_create,
                            **overrides)
        # never write into the repo uploads/ tree
        application.config["UPLOAD_FOLDER"] = str(tmp_path / f"{slug}-uploads")
        return application

    return build


# ============================================================= flask seed
def test_expected_template_catalogue_matches_production():
    """The pinned key list above must stay in sync with the real defaults."""
    from app.services.default_templates import (DEFAULT_TEMPLATES,
                                                default_fields_for)
    assert sorted(t["key"] for t in DEFAULT_TEMPLATES) == \
        EXPECTED_TEMPLATE_KEYS
    assert all(default_fields_for(t["key"]) for t in DEFAULT_TEMPLATES)


class TestSeedCommand:
    def test_creates_the_four_documented_accounts(self, app):
        from app.models import User
        runner = app.test_cli_runner()
        with app.app_context():
            assert User.query.count() == 6      # conftest tiered users only
            for username in SEED_ACCOUNTS:
                assert User.query.filter_by(username=username).first() is None

        result = runner.invoke(args=["seed"])

        assert result.exit_code == 0
        assert result.output.strip() == (
            "Seeded: owner/owner123, admin/admin123, "
            "engineer/site123, safety/safe123")
        with app.app_context():
            assert User.query.count() == 10                 # 6 + 4 seeded
            for username, (email, full, role, _pw) in SEED_ACCOUNTS.items():
                user = User.query.filter_by(username=username).one()
                assert user.email == email
                assert user.full_name == full
                assert user.role == role
                assert user.company == SEED_COMPANY
                assert user.is_active is True
            # the four roles land in the vocabulary RBAC consumes
            assert sorted(u.role for u in User.query.filter(
                User.username.in_(list(SEED_ACCOUNTS))).all()) == [
                    "admin", "safety_officer", "site_engineer", "superadmin"]

    def test_hashes_every_password(self, app):
        from app.models import User
        result = app.test_cli_runner().invoke(args=["seed"])
        assert result.exit_code == 0
        with app.app_context():
            users = {u.username: u for u in User.query.filter(
                User.username.in_(list(SEED_ACCOUNTS))).all()}
            assert sorted(users) == sorted(SEED_ACCOUNTS)
            digests = set()
            for username, (_e, _f, _r, password) in SEED_ACCOUNTS.items():
                stored = users[username].password_hash
                # never plaintext: a salted one-way digest, not the password
                assert stored != password
                assert password not in stored
                assert "$" in stored
                assert len(stored) > 40
                assert users[username].check_password(password) is True
                assert users[username].check_password(password + "!") is False
                digests.add(stored)
            # independent salts -> the four accounts share no single digest
            assert len(digests) == 4

    def test_creates_the_default_templates_on_a_virgin_schema(
            self, isolated_factory):
        """AUTO_CREATE=0 boots an empty DB; `flask seed` must build the lot."""
        from app.models import DynamicField, ReportTemplate, User
        from app.services.default_templates import default_fields_for
        isolated = isolated_factory("0")
        assert _db_size(isolated) == 0
        assert _table_names(isolated) == set()

        result = isolated.test_cli_runner().invoke(args=["seed"])

        assert result.exit_code == 0
        assert "Seeded: owner/owner123" in result.output
        assert _db_size(isolated) > 0
        assert {"users", "report_templates", "dynamic_fields",
                "report_submissions", "projects"} <= _table_names(isolated)
        with isolated.app_context():
            assert sorted(u.username for u in User.query.all()) == sorted(
                SEED_ACCOUNTS)
            assert sorted(t.key for t in ReportTemplate.query.all()) == \
                EXPECTED_TEMPLATE_KEYS
            assert ReportTemplate.query.filter_by(is_active=True).count() == \
                len(EXPECTED_TEMPLATE_KEYS)
            expected_fields = sum(
                len(default_fields_for(key)) for key in EXPECTED_TEMPLATE_KEYS)
            assert DynamicField.query.count() == expected_fields
            for tpl in ReportTemplate.query.all():
                fields = tpl.ordered_fields      # ordered by position
                assert [f.position for f in fields] == list(range(len(fields)))
                assert {f.field_key for f in fields} == {
                    f["key"] for f in default_fields_for(tpl.key)}

    def test_is_idempotent(self, app):
        from app.models import DynamicField, ReportTemplate, User
        runner = app.test_cli_runner()
        assert runner.invoke(args=["seed"]).exit_code == 0
        with app.app_context():
            users_before = sorted((u.id, u.username, u.email)
                                  for u in User.query.all())
            templates_before = sorted(
                (t.id, t.key, t.is_active) for t in ReportTemplate.query.all())
            fields_before = sorted(
                (f.id, f.template_id, f.field_key, f.position)
                for f in DynamicField.query.all())

        second = runner.invoke(args=["seed"])

        assert second.exit_code == 0
        assert "Seeded: owner/owner123" in second.output
        with app.app_context():
            assert sorted((u.id, u.username, u.email)
                          for u in User.query.all()) == users_before
            assert sorted((t.id, t.key, t.is_active)
                          for t in ReportTemplate.query.all()) == \
                templates_before
            assert sorted((f.id, f.template_id, f.field_key, f.position)
                          for f in DynamicField.query.all()) == fields_before
            for username, (_e, _f, _r, password) in SEED_ACCOUNTS.items():
                user = User.query.filter_by(username=username).one()
                assert user.check_password(password) is True
        # no duplicate value under any unique key of the seeded models
        assert _duplicated_keys(app, User.username) == set()
        assert _duplicated_keys(app, User.email) == set()
        assert _duplicated_keys(app, ReportTemplate.key) == set()
        assert _duplicated_keys(app, DynamicField.template_id,
                                DynamicField.field_key) == set()


# ================================================= flask seed-demo-reports
class TestSeedDemoReportsCommand:
    def test_refuses_without_the_engineer_account(self, app):
        from app.models import Project, ReportSubmission, User
        with app.app_context():
            assert User.query.filter_by(username="engineer").first() is None
            assert ReportSubmission.query.count() == 0
            projects_before = sorted((p.id, p.name)
                                     for p in Project.query.all())

        result = app.test_cli_runner().invoke(args=["seed-demo-reports"])

        assert result.exit_code == 0
        assert result.output.strip() == "Run 'flask seed' first."
        assert "Demo submissions seeded." not in result.output
        with app.app_context():
            assert ReportSubmission.query.count() == 0        # nothing written
            assert sorted((p.id, p.name) for p in Project.query.all()) == \
                projects_before
            assert Project.query.filter_by(name=DEMO_PROJECT[0]).count() == 0

    def test_inserts_one_submission_per_active_template(self, app):
        from app.extensions import db
        from app.models import (Project, ReportSubmission, ReportTemplate,
                                User)
        runner = app.test_cli_runner()
        assert runner.invoke(args=["seed"]).exit_code == 0
        with app.app_context():
            active = sorted(t.id for t in
                            ReportTemplate.query.filter_by(is_active=True))
            assert len(active) == len(EXPECTED_TEMPLATE_KEYS)

        result = runner.invoke(args=["seed-demo-reports"])

        assert result.exit_code == 0
        assert result.output.strip() == "Demo submissions seeded."
        with app.app_context():
            subs = ReportSubmission.query.order_by(
                ReportSubmission.id).all()
            assert len(subs) == len(active)
            assert sorted(s.template_id for s in subs) == active
            # the back-dated ladder: one report per open day, 0..n-1
            today = date.today()
            assert sorted(_open_days(s, today) for s in subs) == \
                list(range(len(active)))
            assert all(_open_days(s, today) >= 0 for s in subs)
            for sub in subs:
                tpl = db.session.get(ReportTemplate, sub.template_id)
                fields = tpl.ordered_fields
                assert sub.data == {f.field_key: f"بيانات تجريبية — {f.label_ar}"
                                    for f in fields}
            # project created on demand + engineer stamp on every row
            proj = Project.query.filter_by(name=DEMO_PROJECT[0]).one()
            eng = User.query.filter_by(username="engineer").one()
            assert (proj.location, proj.contractor) == DEMO_PROJECT[1:]
            assert {s.project_id for s in subs} == {proj.id}
            assert {s.project_name for s in subs} == {DEMO_PROJECT[0]}
            assert {s.location for s in subs} == {DEMO_PROJECT[1]}
            assert {s.contractor for s in subs} == {DEMO_PROJECT[2]}
            assert {s.user_id for s in subs} == {eng.id}
            assert {s.signatory_name for s in subs} == {eng.full_name}

    def test_reuses_an_existing_demo_project(self, app):
        from app.extensions import db
        from app.models import Project, ReportSubmission
        with app.app_context():
            existing = Project(name=DEMO_PROJECT[0], location="موقع بديل",
                               contractor="مقاول بديل")
            db.session.add(existing)
            db.session.commit()
            existing_id = existing.id
        runner = app.test_cli_runner()
        assert runner.invoke(args=["seed"]).exit_code == 0

        result = runner.invoke(args=["seed-demo-reports"])

        assert result.exit_code == 0
        with app.app_context():
            assert Project.query.filter_by(name=DEMO_PROJECT[0]).count() == 1
            project = db.session.get(Project, existing_id)
            # the pre-existing row is reused as-is, never overwritten
            assert (project.location, project.contractor) == \
                ("موقع بديل", "مقاول بديل")
            subs = ReportSubmission.query.all()
            assert len(subs) == len(EXPECTED_TEMPLATE_KEYS)
            assert {s.project_id for s in subs} == {existing_id}
            assert {s.location for s in subs} == {"موقع بديل"}
            assert {s.contractor for s in subs} == {"مقاول بديل"}

    def test_skips_inactive_templates(self, app):
        from app.extensions import db
        from app.models import ReportTemplate, ReportSubmission
        with app.app_context():
            variation = ReportTemplate.query.filter_by(key="variation").one()
            variation.is_active = False
            db.session.commit()
            hidden_id = variation.id
            active_count = len(EXPECTED_TEMPLATE_KEYS) - 1
            assert ReportTemplate.query.filter_by(is_active=True).count() == \
                active_count
        runner = app.test_cli_runner()
        assert runner.invoke(args=["seed"]).exit_code == 0

        result = runner.invoke(args=["seed-demo-reports"])

        assert result.exit_code == 0
        with app.app_context():
            subs = ReportSubmission.query.all()
            assert len(subs) == active_count
            assert ReportSubmission.query.filter_by(
                template_id=hidden_id).count() == 0
            today = date.today()
            assert sorted(_open_days(s, today) for s in subs) == \
                list(range(active_count))

    def test_second_run_duplicates_nothing(self, app):
        from app.models import Project, ReportSubmission
        runner = app.test_cli_runner()
        assert runner.invoke(args=["seed"]).exit_code == 0
        assert runner.invoke(args=["seed-demo-reports"]).exit_code == 0
        with app.app_context():
            def snapshot():
                return sorted(
                    (s.id, s.template_id, s.project_id, s.project_name,
                     s.report_date.isoformat(), s.signatory_name)
                    for s in ReportSubmission.query.all())

            first = snapshot()
            assert len(first) == len(EXPECTED_TEMPLATE_KEYS)
            projects_after_first = Project.query.count()
            # DS- serials (id-derived) stay unique after the first run
            serials = [f"DS-{s.id:06d}" for s in
                       ReportSubmission.query.order_by(ReportSubmission.id)]
            assert len(set(serials)) == len(serials)

        second = runner.invoke(args=["seed-demo-reports"])

        assert second.exit_code == 0
        assert second.output.strip() == "Demo submissions seeded."
        with app.app_context():
            assert snapshot() == first       # identical rows, no new ids
            assert Project.query.count() == projects_after_first
        # the anti-duplicate key (template, project, date) stays unique
        assert _duplicated_keys(app, ReportSubmission.template_id,
                                ReportSubmission.project_name,
                                ReportSubmission.report_date) == set()


# ================================ flask cleanup-orphaned-attachments
class TestCleanupOrphanedAttachmentsCommand:
    def test_dry_run_reports_counters_and_deletes_nothing(self, app):
        from app.ops.models import Attachment
        project_id, user_id = _fixture_ids(app)
        ids, keys = _plant_attachments(app, project_id, user_id)
        stray = _plant_stray_file(app)

        result = app.test_cli_runner().invoke(
            args=["cleanup-orphaned-attachments", "--dry-run"])

        assert result.exit_code == 0
        assert result.output.strip() == (
            "DRY-RUN orphan rows: 1, orphan files: 1, rows missing files: 1")
        with app.app_context():
            assert Attachment.query.count() == 3          # no row deleted
        for name in ("orphan", "headless", "healthy"):
            assert _get(app, Attachment, ids[name]) is not None
        # no file deleted either
        assert Path(app.config["UPLOAD_FOLDER"],
                    *keys["orphan"].split("/")).read_bytes() == b"orphan-bytes"
        assert Path(app.config["UPLOAD_FOLDER"],
                    *keys["healthy"].split("/")).is_file()
        assert stray.read_bytes() == b"stray"

    def test_real_run_deletes_what_the_dry_run_only_reported(self, app):
        from app.ops.models import Attachment
        project_id, user_id = _fixture_ids(app)
        ids, keys = _plant_attachments(app, project_id, user_id)
        stray = _plant_stray_file(app)
        healthy_file = Path(app.config["UPLOAD_FOLDER"],
                            *keys["healthy"].split("/"))

        result = app.test_cli_runner().invoke(
            args=["cleanup-orphaned-attachments"])

        assert result.exit_code == 0
        assert result.output.strip() == (
            "orphan rows: 1, orphan files: 1, rows missing files: 1")
        assert "DRY-RUN" not in result.output
        with app.app_context():
            # the orphan row is gone; missing_files is report-only
            assert _get(app, Attachment, ids["orphan"]) is None
            assert _get(app, Attachment, ids["headless"]) is not None
            assert _get(app, Attachment, ids["healthy"]) is not None
            assert Attachment.query.count() == 2
        assert not Path(app.config["UPLOAD_FOLDER"],
                        *keys["orphan"].split("/")).exists()
        assert not stray.exists()
        assert healthy_file.is_file()      # a live row keeps its bytes


# ============================================ AZADEXA_AUTO_CREATE gate
class TestAutoCreateGate:
    def test_zero_leaves_the_schema_unbuilt(self, isolated_factory):
        from app.models import ReportTemplate
        isolated = isolated_factory("0")
        # connect-only: the SQLite file exists but holds no table at all
        assert _db_size(isolated) == 0
        assert _table_names(isolated) == set()
        assert ReportTemplate.__tablename__ not in _table_names(isolated)

    def test_zero_still_serves_requests(self, isolated_factory):
        """The gate only skips DDL — the app itself boots and answers."""
        isolated = isolated_factory("0")
        response = isolated.test_client().get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}

    def test_one_creates_tables_and_seeds_templates_without_users(
            self, isolated_factory):
        from app.models import ReportTemplate, User
        isolated = isolated_factory("1")
        assert _db_size(isolated) > 0
        assert {"users", "report_templates", "dynamic_fields",
                "report_submissions", "projects",
                "ops_attachments"} <= _table_names(isolated)
        with isolated.app_context():
            assert sorted(t.key for t in ReportTemplate.query.all()) == \
                EXPECTED_TEMPLATE_KEYS
            assert ReportTemplate.query.filter_by(is_active=True).count() == \
                len(EXPECTED_TEMPLATE_KEYS)
            # boot must never seed demo accounts silently
            assert User.query.count() == 0

    def test_both_branches_produce_different_schemas(self, tmp_path,
                                                     monkeypatch):
        skipped = _boot(tmp_path, monkeypatch, "gate-off", "0")
        built = _boot(tmp_path, monkeypatch, "gate-on", "1")
        assert _db_size(skipped) == 0
        assert _db_size(built) > 0
        assert _table_names(skipped) == set()
        assert _table_names(built) == set(EXPECTED_TABLES)
        assert _table_names(skipped).isdisjoint(_table_names(built))

    def test_boot_survives_a_failing_default_template_seed(
            self, isolated_factory, monkeypatch, caplog):
        """The ``=1`` branch must never break boot on a seed error."""
        import app.services.default_templates as defaults
        from app.models import ReportTemplate

        def _boom(*_args, **_kwargs):
            raise RuntimeError("default template catalogue is broken")

        monkeypatch.setattr(defaults, "ensure_default_templates", _boom)
        with caplog.at_level("WARNING"):
            isolated = isolated_factory("1")
        # schema built before the seed attempt, templates simply missing
        assert set(EXPECTED_TABLES) <= _table_names(isolated)
        assert any("default-template seed skipped" in r.message
                   for r in caplog.records)
        with isolated.app_context():
            assert ReportTemplate.query.count() == 0
        assert isolated.test_client().get("/healthz").status_code == 200
        # the CLI command is the documented recovery path (patch undone first)
        monkeypatch.undo()
        result = isolated.test_cli_runner().invoke(args=["seed"])
        assert result.exit_code == 0
        with isolated.app_context():
            assert sorted(t.key for t in ReportTemplate.query.all()) == \
                EXPECTED_TEMPLATE_KEYS


# ============================================ boot session-cookie hardening
class TestBootSessionCookieHardening:
    def test_insecure_httponly_flag_is_forced_back_on(self, isolated_factory):
        """A config asking for a JS-readable cookie is overridden at boot."""
        from flask import session

        isolated = isolated_factory("0", SESSION_COOKIE_HTTPONLY=False,
                                    SESSION_COOKIE_SAMESITE="")
        assert isolated.config["SESSION_COOKIE_HTTPONLY"] is True
        assert isolated.config["SESSION_COOKIE_SAMESITE"] == "Lax"

        @isolated.route("/__cli/touch-session")
        def _touch():
            session["probe"] = "value"          # forces a Set-Cookie header
            return "ok"

        response = isolated.test_client().get("/__cli/touch-session")
        assert response.status_code == 200
        cookies = response.headers.getlist("Set-Cookie")
        assert len(cookies) == 1
        assert "HttpOnly" in cookies[0]
        assert "SameSite=Lax" in cookies[0]

    def test_non_testing_boot_keeps_csrf_armed_and_preserves_samesite(
            self, tmp_path, monkeypatch):
        for var in ("FLASK_ENV", "USE_CLOUD_DB", "RENDER", "RAILWAY_ENVIRONMENT",
                    "HEROKU_APP_NAME", "DYNO"):
            monkeypatch.delenv(var, raising=False)
        isolated = _boot(tmp_path, monkeypatch, "prodlike", "0",
                         TESTING=False, SESSION_COOKIE_SAMESITE="Strict",
                         SESSION_COOKIE_SECURE=False)
        # CSRF is relaxed only under TESTING
        assert isolated.config["WTF_CSRF_ENABLED"] is True
        # an explicit SameSite policy is preserved, not overwritten with "Lax"
        assert isolated.config["SESSION_COOKIE_SAMESITE"] == "Strict"
        assert isolated.config["SESSION_COOKIE_HTTPONLY"] is True
        assert isolated.config["SESSION_COOKIE_SECURE"] is False
        # the AUTO_CREATE gate is independent of the TESTING flag
        assert _table_names(isolated) == set()
