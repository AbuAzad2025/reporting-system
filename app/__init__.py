"""Flask application factory — the single canonical entry point.

Registers: auth (field + admin login), main (dashboard/archive/profile),
reports (legacy static + dynamic SaaS engine), admin (platform owner).
Initializes: SQLAlchemy, Login, Migrate. Seeds default dynamic templates.
"""
import os
from datetime import date
import click
from flask import Flask

from config import Config, BASE_DIR
from app.extensions import db, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(__name__,
                template_folder=os.path.join(BASE_DIR, "templates"),
                static_folder=os.path.join(BASE_DIR, "static"))
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

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

    # ---- template globals
    from app.models import REPORT_TYPES, ROLES

    @app.context_processor
    def inject_globals():
        cfg = app.config
        return {"REPORT_TYPES": REPORT_TYPES, "ROLES": ROLES,
                "APP_NAME_AR": cfg.get("APP_NAME_AR"),
                "COMPANY_NAME_AR": cfg.get("COMPANY_NAME_AR"),
                "COMPANY_NAME_EN": cfg.get("COMPANY_NAME_EN"),
                "DEVELOPER_AR": cfg.get("DEVELOPER_AR"),
                "CONTACT_EMAIL": cfg.get("CONTACT_EMAIL"),
                "CONTACT_PHONE": cfg.get("CONTACT_PHONE"),
                "today": date.today().isoformat()}

    # ---- first-boot: create tables + seed default dynamic templates
    # Set AZADEXA_AUTO_CREATE=0 to skip (e.g. pure Alembic workflows where
    # autogenerate must diff against an empty database).
    if os.environ.get("AZADEXA_AUTO_CREATE", "1") == "1":
        with app.app_context():
            os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)
            db.create_all()
            try:
                from app.models import ReportTemplate, DynamicField
                from app.services.default_templates import ensure_default_templates
                ensure_default_templates(db, ReportTemplate, DynamicField)
            except Exception as exc:  # never break boot on seed issues
                app.logger.warning("default-template seed skipped: %s", exc)

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
