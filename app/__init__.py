"""Flask application factory — the single canonical entry point.

Registers: auth (field + admin login), main (dashboard/archive/profile),
reports (legacy static + dynamic SaaS engine), admin (platform owner).
Initializes: SQLAlchemy, Login, Migrate. Seeds default dynamic templates.
"""
import os
from datetime import date
import click
from flask import Flask, render_template

from flask_wtf.csrf import CSRFProtect

from config import Config, BASE_DIR
from app.extensions import db, login_manager, migrate

csrf = CSRFProtect()


def _register_asset_cache_busting(app):
    """Give every static URL a version, so a deploy is visible immediately.

    Without it the browser keeps serving the stylesheet it already has, and a
    fix that is committed and merged appears to do nothing until a hard
    refresh. The version is the file's mtime, which is stable for a given
    build and changes exactly when the asset does. It is resolved once per
    process per file, so this costs one stat per asset, not one per request.
    """
    from flask import url_for

    cache: dict[str, str] = {}

    def asset_url(filename: str) -> str:
        version = cache.get(filename)
        if version is None:
            try:
                path = os.path.join(app.static_folder, filename)
                version = str(int(os.path.getmtime(path)))
            except OSError:
                # A missing asset should still produce a URL; the browser will
                # report the 404, which is more useful than a 500 here.
                version = "0"
            cache[filename] = version
        return url_for("static", filename=filename, v=version)

    app.jinja_env.globals["asset_url"] = asset_url
    return asset_url


def create_app(config_class=Config):
    app = Flask(__name__,
                template_folder=os.path.join(BASE_DIR, "templates"),
                static_folder=os.path.join(BASE_DIR, "static"))
    app.config.from_object(config_class)
    _register_asset_cache_busting(app)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    # testing: disable CSRF for pytest without token (production remains protected)
    if app.config.get("TESTING"):
        app.config["WTF_CSRF_ENABLED"] = False

    # NOTE (professional posture): no silent user seeding on boot.
    # Demo accounts are created explicitly via `flask seed` only.

    # ---- production trust guards (no new dependencies)
    _secret = str(app.config.get("SECRET_KEY") or "")
    _is_prod = (
        os.environ.get("FLASK_ENV") == "production"
        or os.environ.get("USE_CLOUD_DB") == "1"
        or any(os.environ.get(m) for m in (
            "RENDER", "RAILWAY_ENVIRONMENT", "HEROKU_APP_NAME", "DYNO"))
    )
    if (_is_prod and not app.config.get("TESTING")
            and _secret in ("dev-secret-change-in-production", "", "pytest-secret")):
        app.logger.error(
            "Refusing boot: SECRET_KEY must be set in production "
            "(default dev secret detected).")
        raise RuntimeError("SECRET_KEY must be set in production.")
    if app.config.get("SESSION_COOKIE_HTTPONLY") is not True:
        app.config["SESSION_COOKIE_HTTPONLY"] = True
    if not app.config.get("SESSION_COOKIE_SAMESITE"):
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if _is_prod:
        app.config["SESSION_COOKIE_SECURE"] = True

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    # Fail-closed API posture: unauthenticated /ops/* (and other JSON
    # callers) get a machine-readable 401 instead of a 302 login redirect,
    # so @permission_required / @roles_required_json semantics hold even
    # when @login_required fires first in the decorator stack.
    from flask import jsonify, request
    from app.utils.decorators import JSON_API_PREFIXES

    @login_manager.unauthorized_handler
    def _unauthorized():
        if request.path.startswith(JSON_API_PREFIXES) or request.is_json:
            return jsonify({"error": "authentication required"}), 401
        from flask import flash, redirect, url_for
        flash(login_manager.login_message, login_manager.login_message_category)
        return redirect(url_for(login_manager.login_view))

    # The shared macros are available in every template. Importing them per
    # template meant a page using page_head() without the import raised
    # UndefinedError only when that page was rendered, and nothing failed at
    # build time.
    macros = app.jinja_env.get_template("_macros.html")
    app.jinja_env.globals.update(macros.module.__dict__)

    # The daily report's must-not-be-missing sections. Exposed as a Jinja
    # global so every render of the form can mark them without each route
    # having to thread the list through its render_template call.
    from app.services.report_completeness import CRITICAL_FIELDS
    app.jinja_env.globals["critical_fields"] = CRITICAL_FIELDS

    # ---- blueprints (spec layout: auth / admin / reports + main)
    from app.auth import bp as auth_bp
    from app.main import bp as main_bp
    from app.reports import bp as reports_bp
    from app.admin import bp as admin_bp
    from app.ops import bp as ops_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(ops_bp)

    # ---- professional error pages + health check
    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    @app.errorhandler(403)
    def _forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def _not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _server_error(_e):
        return render_template("errors/500.html"), 500

    # ---- template globals
    from app.models import REPORT_TYPES, ROLES
    from flask_login import current_user

    @app.context_processor
    def inject_globals():
        cfg = app.config
        from app.services.branding import resolve_brand
        brand = resolve_brand(current_user)
        return {"REPORT_TYPES": REPORT_TYPES, "ROLES": ROLES,
                "APP_NAME_AR": cfg.get("APP_NAME_AR"),
                "COMPANY_NAME_AR": brand.company_ar,
                "COMPANY_NAME_EN": brand.company_en,
                "DEVELOPER_AR": cfg.get("DEVELOPER_AR"),
                "CONTACT_EMAIL": cfg.get("CONTACT_EMAIL"),
                "CONTACT_PHONE": cfg.get("CONTACT_PHONE"),
                "today": date.today().isoformat(),
                "current_brand": brand}

    # ---- zero-touch bootstrap (schema, first admin, reference data, storage)
    # Runs automatically on every boot, so a fresh deployment serves traffic
    # without a manual command first. Idempotent, and individually guarded: a
    # failing step is logged and the rest still run. Disable with
    # AZADEXA_AUTO_CREATE=0 (pure Alembic workflows where autogenerate must
    # diff against an empty database), and it never runs under TESTING.
    #
    # Note on users: no demo accounts with weak passwords are seeded here. The
    # only account created is a platform administrator, and only when none
    # exists, using AZADEXA_SUPERADMIN_PASSWORD or a generated one-time random
    # password. `flask seed` remains the explicit way to create demo users.
    from app.bootstrap import ensure_ready

    app.extensions["azadexa_bootstrap"] = ensure_ready(app)

    # ---- CLI helpers
    @app.cli.command("seed")
    def seed():
        """Seed demo accounts (superadmin/admin/engineer/safety)."""
        from app.models import User
        with app.app_context():
            db.create_all()
            defaults = [
                ("owner", "owner@platform.com", "مالك المنصة الرئيسي العام",
                 "superadmin", "owner123"),
                ("admin", "admin@site.com", "محمد أحمد علي حسن",
                 "admin", "admin123"),
                ("engineer", "eng@site.com", "خالد سعيد محمود عبدالله",
                 "site_engineer", "site123"),
                ("safety", "safety@site.com", "سارة علي محمد حسن",
                 "safety_officer", "safe123"),
            ]
            for uname, email, full, role, pw in defaults:
                if not User.query.filter_by(username=uname).first():
                    u = User(username=uname, email=email, full_name=full,
                             role=role, company="شركة أزاد للأنظمة الذكية")
                    u.set_password(pw)
                    db.session.add(u)
            db.session.commit()
            from app.models import ReportTemplate, DynamicField
            from app.services.default_templates import ensure_default_templates
            ensure_default_templates(db, ReportTemplate, DynamicField)
            print("Seeded: owner/owner123, admin/admin123, "
                  "engineer/site123, safety/safe123")

    @app.cli.command("seed-operational-demo")
    def seed_operational_demo_cmd():
        """Seed the full Arabic demonstration dataset.

        This is the former top-level ``seed.py``, now reachable through the
        application instead of beside it. It creates the demo users, two demo
        projects, tenant memberships, template submissions and sample records
        across all nine operations modules. It is never run automatically:
        sample contractual records have no business appearing in a real
        project's database on boot.

        Idempotent - safe to run more than once.
        """
        from app.services.demo_data import seed_operational_demo

        with app.app_context():
            report = seed_operational_demo()
        print("Demo users    :", ", ".join(report["users"]))
        print("Demo projects :", ", ".join(report["projects"]))
        print("Ops records   :")
        for kind, count in sorted(report["ops_counts"].items()):
            print(f"    {kind:28s} {count}")

    @app.cli.command("seed-demo-reports")
    def seed_demo_reports():
        """Insert one sample dynamic submission per default template."""
        from datetime import timedelta
        from app.models import (User, ReportTemplate, Project,
                                ReportSubmission)
        with app.app_context():
            eng = User.query.filter_by(username="engineer").first()
            if not eng:
                print("Run 'flask seed' first.")
                return
            proj = Project.query.filter_by(name="مشروع برج النخيل السكني").first()
            if not proj:
                proj = Project(name="مشروع برج النخيل السكني",
                               location="الرياض — حي النرجس",
                               contractor="المقاول الرئيسي")
                db.session.add(proj)
                db.session.flush()
            for i, tpl in enumerate(
                    ReportTemplate.query.filter_by(is_active=True).all()):
                exists = ReportSubmission.query.filter_by(
                    template_id=tpl.id, project_name=proj.name,
                    report_date=date.today() - timedelta(days=i)).first()
                if not exists:
                    data = {f.field_key: f"بيانات تجريبية — {f.label_ar}"
                            for f in tpl.ordered_fields}
                    db.session.add(ReportSubmission(
                        template_id=tpl.id, project_id=proj.id,
                        project_name=proj.name, location=proj.location,
                        contractor=proj.contractor,
                        report_date=date.today() - timedelta(days=i),
                        data=data, signatory_name=eng.full_name,
                        user_id=eng.id))
            db.session.commit()
            print("Demo submissions seeded.")

    @app.cli.command("cleanup-orphaned-attachments")
    @click.option("--dry-run", is_flag=True, default=False,
                  help="Report only; delete nothing.")
    def cleanup_orphaned_attachments_cmd(dry_run):
        """Delete attachment rows/files orphaned by record removal."""
        from app.ops.routes import cleanup_orphaned_attachments
        with app.app_context():
            stats = cleanup_orphaned_attachments(dry_run=dry_run)
        mode = "DRY-RUN " if dry_run else ""
        print(f"{mode}orphan rows: {stats['orphan_rows']}, "
              f"orphan files: {stats['orphan_files']}, "
              f"rows missing files: {stats['missing_files']}")

    return app
