"""Platform-owner blueprint — template builder, field manager, projects,
user administration, system-wide analytics.

Gates: templates/fields/projects/analytics -> admin+superadmin.
Users suspend/delete -> superadmin only for delete; admin can suspend.
"""
import logging
from datetime import date, timedelta
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from app.admin import bp
from app.extensions import db
from app.models import (User, Project, ReportTemplate, DynamicField,
                        ReportSubmission, Report, ROLES, FIELD_TYPES,
                        TenantBranding, TenantTemplateOverride)
from app.utils.decorators import (template_manager_required, roles_required,
                                  permission_required)
from app.ops.isolation import roles_required_json
from app.services.default_templates import ensure_default_templates

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- dashboard
@bp.route("/")
@login_required
@template_manager_required
def dashboard():
    stats = {
        "users": User.query.count(),
        "projects": Project.query.count(),
        "templates": ReportTemplate.query.count(),
        "submissions": ReportSubmission.query.count(),
        "legacy": Report.query.count(),
    }
    # submissions per day (last 14 days)
    since = date.today() - timedelta(days=13)
    rows = (db.session.query(ReportSubmission.report_date,
                             func.count(ReportSubmission.id))
            .filter(ReportSubmission.created_at >= since.strftime("%Y-%m-%d"))
            .group_by(ReportSubmission.report_date)
            .order_by(ReportSubmission.report_date).all())
    chart = [{"d": str(d), "c": c} for d, c in rows]
    per_template = (db.session.query(ReportTemplate.name_ar,
                                     func.count(ReportSubmission.id))
                    .outerjoin(ReportSubmission)
                    .group_by(ReportTemplate.id).all())
    return render_template("admin/dashboard.html", stats=stats, chart=chart,
                           per_template=per_template)


# ---------------------------------------------------------------- templates
@bp.route("/templates")
@login_required
@template_manager_required
def templates():
    tpl_list = ReportTemplate.query.order_by(ReportTemplate.id).all()
    # ---- branding customization (per-tenant / per-project identity)
    # Admin may edit company names, logos and custom header/footer per project.
    tpl_branding = None
    if tpl_list:
        tpl_branding = (db.session.query(TenantBranding)
                        .filter_by(project_id=tpl_list[0].id, is_active=True).first())
    return render_template("admin/templates.html", templates=tpl_list,
                           tpl_branding=tpl_branding)


@bp.route("/templates/new", methods=["GET", "POST"])
@login_required
@template_manager_required
def template_new():
    if request.method == "POST":
        key = request.form.get("key", "").strip().lower().replace(" ", "_")
        name_ar = request.form.get("name_ar", "").strip()
        if not key or not name_ar:
            flash("المفتاح اللاتيني والاسم العربي حقلان مطلوبان.", "danger")
            return render_template("admin/template_form.html", tpl=None)
        if ReportTemplate.query.filter_by(key=key).first():
            flash("يوجد قالب بنفس المفتاح مسبقاً.", "danger")
            return render_template("admin/template_form.html", tpl=None)
        tpl = ReportTemplate(
            key=key, name_ar=name_ar,
            name_en=request.form.get("name_en", "").strip(),
            description=request.form.get("description", "").strip(),
            icon=request.form.get("icon", "📋").strip() or "📋",
            gradient=request.form.get("gradient", "from-sky-500 to-blue-700"),
            is_active=bool(request.form.get("is_active")),
            created_by_id=current_user.id)
        db.session.add(tpl)
        db.session.commit()
        flash(f"تم إنشاء القالب «{name_ar}». أضف الحقول الآن.", "success")
        return redirect(url_for("admin.fields", template_id=tpl.id))
    return render_template("admin/template_form.html", tpl=None)


@bp.route("/templates/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
@template_manager_required
def template_edit(template_id):
    tpl = ReportTemplate.query.get_or_404(template_id)
    if request.method == "POST":
        tpl.name_ar = request.form.get("name_ar", "").strip() or tpl.name_ar
        tpl.name_en = request.form.get("name_en", "").strip()
        tpl.description = request.form.get("description", "").strip()
        tpl.icon = request.form.get("icon", "").strip() or tpl.icon
        tpl.gradient = request.form.get("gradient", "").strip() or tpl.gradient
        tpl.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        flash("تم حفظ القالب.", "success")
        return redirect(url_for("admin.templates"))
    return render_template("admin/template_form.html", tpl=tpl)


@bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
@template_manager_required
def template_delete(template_id):
    tpl = ReportTemplate.query.get_or_404(template_id)
    if tpl.is_system:
        flash("لا يمكن حذف قوالب النظام الأساسية (يمكن تعطيلها فقط).", "warning")
        return redirect(url_for("admin.templates"))
    if tpl.submissions.count():
        flash("لا يمكن حذف قالب عليه تقارير مرسلة — عطّله بدلاً من ذلك.", "danger")
        return redirect(url_for("admin.templates"))
    db.session.delete(tpl)
    db.session.commit()
    flash("تم حذف القالب.", "info")
    return redirect(url_for("admin.templates"))


@bp.route("/templates/reset-defaults", methods=["POST"])
@login_required
@template_manager_required
def reset_defaults():
    ensure_default_templates(db, ReportTemplate, DynamicField,
                             admin_id=current_user.id)
    flash("تمت استعادة/استكمال القوالب الافتراضية الخمسة.", "success")
    return redirect(url_for("admin.templates"))


# ---------------------------------------------------------------- fields
def parse_table_columns(raw: str) -> list:
    """Parse one column per line: key | label | type | required | opt1,opt2.

    type ∈ text/number/dropdown/date (anything else → text).
    A 4th segment of «required»/«مطلوب»/«1» marks the column required.
    """
    cols, seen = [], set()
    for line in (raw or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        key = parts[0].lower().replace(" ", "_")
        if key in seen:
            continue
        seen.add(key)
        ctype = parts[2] if len(parts) > 2 else "text"
        if ctype not in ("text", "number", "dropdown", "date"):
            ctype = "text"
        flag = parts[3] if len(parts) > 3 else ""
        opts = [o.strip() for o in (parts[4].replace("،", ",").split(",")
                                    if len(parts) > 4 else [])
                if o.strip()] if ctype == "dropdown" else []
        cols.append({"key": key, "label_ar": parts[1], "type": ctype,
                     "required": flag in ("required", "مطلوب", "1", "yes"),
                     "options": opts})
    return cols[:12]


@bp.route("/templates/<int:template_id>/fields", methods=["GET", "POST"])
@login_required
@template_manager_required
def fields(template_id):
    tpl = ReportTemplate.query.get_or_404(template_id)
    if request.method == "POST":
        field_key = request.form.get("field_key", "").strip().lower().replace(" ", "_")
        label_ar = request.form.get("label_ar", "").strip()
        field_type = request.form.get("field_type", "text").strip()
        raw_opts = request.form.get("options", "")
        options = [o.strip() for o in raw_opts.replace("،", ",").split(",")
                   if o.strip()] if field_type == "dropdown" else []
        if not field_key or not label_ar:
            flash("مفتاح الحقل والتسمية العربية مطلوبان.", "danger")
        elif field_type not in FIELD_TYPES:
            flash("نوع الحقل غير صالح.", "danger")
        elif DynamicField.query.filter_by(template_id=tpl.id,
                                          field_key=field_key).first():
            flash("يوجد حقل بنفس المفتاح في هذا القالب.", "danger")
        else:
            max_pos = db.session.query(func.max(DynamicField.position)).filter_by(
                template_id=tpl.id).scalar() or 0
            from app.services.field_validation import rules_from_form
            sub_fields = parse_table_columns(
                request.form.get("columns", "")) if field_type == "table" else []
            db.session.add(DynamicField(
                template_id=tpl.id, field_key=field_key, label_ar=label_ar,
                field_type=field_type, options=options,
                required=bool(request.form.get("required")),
                rules=rules_from_form(request.form),
                sub_fields=sub_fields,
                position=max_pos + 1,
                placeholder=request.form.get("placeholder", "").strip()))
            db.session.commit()
            flash(f"تمت إضافة الحقل «{label_ar}».", "success")
        return redirect(url_for("admin.fields", template_id=tpl.id))
    field_list = tpl.fields.order_by(DynamicField.position).all()
    return render_template("admin/fields.html", tpl=tpl, fields=field_list,
                           FIELD_TYPES=FIELD_TYPES)


@bp.route("/fields/<int:field_id>/delete", methods=["POST"])
@login_required
@template_manager_required
def field_delete(field_id):
    f = DynamicField.query.get_or_404(field_id)
    tid = f.template_id
    db.session.delete(f)
    db.session.commit()
    flash("تم حذف الحقل.", "info")
    return redirect(url_for("admin.fields", template_id=tid))


@bp.route("/fields/<int:field_id>/move/<direction>", methods=["POST"])
@login_required
@template_manager_required
def field_move(field_id, direction):
    f = DynamicField.query.get_or_404(field_id)
    sibs = DynamicField.query.filter_by(template_id=f.template_id).order_by(
        DynamicField.position).all()
    idx = next((i for i, s in enumerate(sibs) if s.id == f.id), None)
    if idx is not None:
        j = idx - 1 if direction == "up" else idx + 1
        if 0 <= j < len(sibs):
            sibs[idx].position, sibs[j].position = sibs[j].position, sibs[idx].position
            db.session.commit()
    return redirect(url_for("admin.fields", template_id=f.template_id))


@bp.route("/fields/<int:field_id>/columns", methods=["POST"])
@login_required
@template_manager_required
def field_column_add(field_id):
    """Append one column to a table field."""
    f = DynamicField.query.get_or_404(field_id)
    if f.field_type != "table":
        flash("الأعمدة لجداول البنود فقط.", "danger")
        return redirect(url_for("admin.fields", template_id=f.template_id))
    key = request.form.get("col_key", "").strip().lower().replace(" ", "_")
    label = request.form.get("col_label", "").strip()
    ctype = request.form.get("col_type", "text").strip()
    if ctype not in ("text", "number", "dropdown", "date"):
        ctype = "text"
    cols = f.sub_columns()
    if not key or not label:
        flash("مفتاح العمود وتسميته مطلوبان.", "danger")
    elif any(c["key"] == key for c in cols):
        flash("يوجد عمود بنفس المفتاح.", "danger")
    elif len(cols) >= 12:
        flash("الحد الأقصى 12 عموداً.", "danger")
    else:
        raw_opts = request.form.get("col_options", "")
        cols.append({"key": key, "label_ar": label, "type": ctype,
                     "required": bool(request.form.get("col_required")),
                     "options": [o.strip() for o in raw_opts.replace("،", ",")
                                 .split(",") if o.strip()]
                     if ctype == "dropdown" else []})
        f.sub_fields = cols
        db.session.commit()
        flash(f"تمت إضافة العمود «{label}».", "success")
    return redirect(url_for("admin.fields", template_id=f.template_id))


@bp.route("/fields/<int:field_id>/columns/<col_key>/delete", methods=["POST"])
@login_required
@template_manager_required
def field_column_delete(field_id, col_key):
    f = DynamicField.query.get_or_404(field_id)
    kept = [c for c in f.sub_columns() if c["key"] != col_key]
    if len(kept) != len(f.sub_columns()):
        f.sub_fields = kept
        db.session.commit()
        flash("تم حذف العمود.", "info")
    return redirect(url_for("admin.fields", template_id=f.template_id))


# ---------------------------------------------------------------- projects — with professional logo upload
@bp.route("/projects", methods=["GET", "POST"])
@login_required
@template_manager_required
def projects():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("اسم المشروع مطلوب.", "danger")
        elif Project.query.filter_by(name=name).first():
            flash("يوجد مشروع بنفس الاسم.", "danger")
        else:
            # ensure logo columns exist on old DBs (SQLite/Postgres)
            try:
                from sqlalchemy import text as _text
                db.session.execute(_text("ALTER TABLE projects ADD COLUMN logo_path VARCHAR(500) DEFAULT ''"))
                db.session.commit()
            except Exception:
                db.session.rollback()
            try:
                from sqlalchemy import text as _text2
                db.session.execute(_text2("ALTER TABLE projects ADD COLUMN logo2_path VARCHAR(500) DEFAULT ''"))
                db.session.commit()
            except Exception:
                db.session.rollback()
            proj = Project(
                name=name, location=request.form.get("location", "").strip(),
                contractor=request.form.get("contractor", "").strip(),
                client=request.form.get("client", "").strip())
            # handle custom header logos (professional)
            try:
                from app.services.storage import upload_image
                for field_name, attr in [("logo", "logo_path"), ("logo2", "logo2_path")]:
                    f = request.files.get(field_name)
                    if f and f.filename:
                        # validate image type
                        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"
                        if ext not in ("png", "jpg", "jpeg", "webp", "svg"):
                            flash(f"صيغة الشعار {f.filename} غير مدعومة (png/jpg/webp/svg فقط).", "warning")
                            continue
                        data = f.read()
                        if len(data) > 5 * 1024 * 1024:
                            flash("حجم الشعار يجب ألا يتجاوز 5MB.", "warning")
                            continue
                        path = upload_image(name or "project", f.filename, data)
                        setattr(proj, attr, path)
            except Exception as exc:
                # column may not exist on old DB — create it on the fly
                try:
                    from sqlalchemy import text as _text
                    db.session.execute(_text("ALTER TABLE projects ADD COLUMN logo_path VARCHAR(500) DEFAULT ''"))
                    db.session.execute(_text("ALTER TABLE projects ADD COLUMN logo2_path VARCHAR(500) DEFAULT ''"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                log.warning("logo upload skipped: %s", exc)
            db.session.add(proj)
            db.session.commit()
            flash(f"تمت إضافة المشروع «{name}».", "success")
        return redirect(url_for("admin.projects"))
    plist = Project.query.order_by(Project.name).all()
    return render_template("admin/projects.html", projects=plist)


@bp.route("/projects/<int:project_id>/toggle", methods=["POST"])
@login_required
@template_manager_required
def project_toggle(project_id):
    p = Project.query.get_or_404(project_id)
    p.is_active = not p.is_active
    db.session.commit()
    flash(f"تم {'تفعيل' if p.is_active else 'أرشفة'} المشروع «{p.name}».", "success")
    return redirect(url_for("admin.projects"))


# ---------------------------------------------------------------- users
@bp.route("/users")
@login_required
@template_manager_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users, ROLES=ROLES)


@bp.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@template_manager_required
def user_role(user_id):
    u = User.query.get_or_404(user_id)
    new_role = request.form.get("role", "").strip()
    if new_role not in ROLES:
        flash("الدور غير صالح.", "danger")
    elif u.id == current_user.id:
        flash("لا يمكنك تغيير دور حسابك الخاص.", "warning")
    elif new_role == "superadmin" and not current_user.is_superadmin:
        flash("ترقية Superadmin مقصورة على مالك المنصة.", "danger")
    else:
        u.role = new_role
        db.session.commit()
        flash(f"تم تعيين {u.full_name} كـ ({u.role_ar}).", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@login_required
@template_manager_required
def user_suspend(user_id):
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash("لا يمكنك إيقاف حسابك الخاص.", "warning")
    else:
        u.is_active = not u.is_active
        db.session.commit()
        flash(f"تم {'إيقاف' if not u.is_active else 'تفعيل'} حساب {u.full_name}.",
              "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@roles_required("superadmin")
def user_delete(user_id):
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash("لا يمكنك حذف حسابك الخاص.", "warning")
    else:
        db.session.delete(u)
        db.session.commit()
        flash(f"تم حذف حساب {u.full_name}.", "info")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------- backup
@bp.route("/backup", methods=["GET"])
@login_required
@roles_required("superadmin")
def backup_index():
    backups = []
    try:
        from app.services.storage import list_backups
        backups = list_backups()
    except Exception as exc:
        logging.getLogger(__name__).exception("backup list failed")
        flash("تعذر جلب قائمة النسخ الاحتياطية. حدّث الصفحة أو تحقق من إعدادات التخزين.", "danger")
    return render_template("admin/backup.html", backups=backups)


@bp.route("/backup/export", methods=["POST"])
@login_required
@roles_required("superadmin")
def backup_export():
    from app.services.backup import build_backup, backup_filename, validate_backup
    from app.services.storage import upload as storage_upload
    data = build_backup()
    validation = validate_backup(data)
    if not validation["ok"]:
        flash(f"فشل التحقق من النسخة: {validation['error']}", "danger")
        return redirect(url_for("admin.backup_index"))
    filename = backup_filename()
    try:
        storage_upload(data, filename)
    except Exception as exc:
        logging.getLogger(__name__).exception("backup upload failed")
        flash("فشل الرفع إلى التخزين. تحقق من الاتصال وإعدادات التخزين ثم أعد المحاولة.", "danger")
        return redirect(url_for("admin.backup_index"))
    flash(f"تم إنشاء نسخة احتياطية كاملة: {filename}", "success")
    return redirect(url_for("admin.backup_index"))


@bp.route("/backup/import", methods=["POST"])
@login_required
@roles_required("superadmin")
def backup_import():
    from app.services.backup import restore_backup, validate_backup
    if "backup_file" not in request.files:
        flash("لم يتم اختيار ملف نسخة احتياطية.", "danger")
        return redirect(url_for("admin.backup_index"))
    file = request.files["backup_file"]
    if file.filename == "":
        flash("لم يتم اختيار ملف نسخة احتياطية.", "danger")
        return redirect(url_for("admin.backup_index"))
    data = file.read()
    validation = validate_backup(data)
    if not validation["ok"]:
        flash(f"الملف غير صالح: {validation['error']}", "danger")
        return redirect(url_for("admin.backup_index"))
    try:
        counts = restore_backup(data)
    except Exception as exc:
        logging.getLogger(__name__).exception("backup restore failed")
        flash("فشل الاستعادة. تأكد من سلامة الملف وأعد المحاولة.", "danger")
        return redirect(url_for("admin.backup_index"))
    summary = ", ".join(f"{k}: {v}" for k, v in counts.items())
    flash(f"تم استعادة النسخة بنجاح — {summary}", "success")
    return redirect(url_for("admin.backup_index"))


@bp.route("/backup/download/<path:key>", methods=["GET"])
@login_required
@roles_required("superadmin")
def backup_download(key):
    from flask import send_file
    import io
    from app.services.storage import download as storage_download
    try:
        data = storage_download(key)
    except Exception as exc:
        logging.getLogger(__name__).exception("backup download failed")
        flash("تعذر تنزيل النسخة. أعد المحاولة.", "danger")
        return redirect(url_for("admin.backup_index"))
    buf = io.BytesIO(data)
    fname = key.rsplit("/", 1)[-1] if "/" in key else key
    return send_file(buf, as_attachment=True,
                     download_name=fname,
                     mimetype="application/zip")


@bp.route("/backup/delete/<path:key>", methods=["POST"])
@login_required
@roles_required("superadmin")
def backup_delete(key):
    from app.services.storage import delete as storage_delete
    try:
        storage_delete(key)
        flash(f"تم حذف النسخة: {key}", "info")
    except Exception as exc:
        logging.getLogger(__name__).exception("backup delete failed")
        flash("تعذر حذف النسخة. أعد المحاولة.", "danger")
    return redirect(url_for("admin.backup_index"))


# ---------------------------------------------------------------- ops analytics
def _ops_analytics() -> dict:
    """Cross-tenant rollup over all nine ops modules (superadmin only).

    One grouped query per module (project × status) feeds both the
    per-module and per-project views; DSR manpower and open-RFI queues
    are aggregated in Python over the 30-day window.
    """
    from datetime import datetime, timezone
    from app.ops.routes import KIND_MODEL
    from app.ops.models import OPS_MODULES, OpsRecordComment

    by_kind, per_project = {}, {}
    for kind, (_m, prefix, name_ar, _e) in OPS_MODULES.items():
        model = KIND_MODEL[kind]
        rows = (db.session.query(model.project_id, model.status,
                                 func.count(model.id))
                .group_by(model.project_id, model.status).all())
        by_status: dict = {}
        for _pid, status, count in rows:
            by_status[status] = by_status.get(status, 0) + count
            cell = per_project.setdefault(_pid, {"total": 0, "approved": 0,
                                                 "attention": 0})
            cell["total"] += count
            if status == "approved":
                cell["approved"] += count
            if status in ("pending", "submitted"):
                cell["attention"] += count
        by_kind[kind] = {"name_ar": name_ar, "prefix": prefix,
                         "total": sum(by_status.values()),
                         "by_status": by_status}

    projects = []
    for p in Project.query.order_by(Project.name).all():
        cell = per_project.get(p.id, {"total": 0, "approved": 0,
                                      "attention": 0})
        total = cell["total"]
        projects.append({"id": p.id, "name": p.name, "total": total,
                         "approved": cell["approved"],
                         "attention": cell["attention"],
                         "approval_rate": round(cell["approved"] / total * 100, 1)
                         if total else 0.0})

    # DSR manpower, last 30 days (scalar tiers in SQL, tables in Python)
    from app.ops.models import DailySiteReport
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    dsrs = DailySiteReport.query.filter(
        DailySiteReport.report_date >= since.date()).all()
    manpower = {"reports": len(dsrs), "engineers": 0, "technicians": 0,
                "labor": 0, "structured_labor": 0, "plant_hours": 0.0}
    for d in dsrs:
        manpower["engineers"] += d.engineers_count or 0
        manpower["technicians"] += d.technicians_count or 0
        manpower["labor"] += d.labor_count or 0
        manpower["structured_labor"] += d.labor_table_total
        manpower["plant_hours"] += d.equipment_hours_total
    manpower["plant_hours"] = round(manpower["plant_hours"], 2)

    # open RFI queue by ball-in-court
    from app.ops.models import RFI
    rfi_rows = (db.session.query(RFI.ball_in_court, func.count(RFI.id))
                .filter(RFI.status.in_(("pending", "submitted")))
                .group_by(RFI.ball_in_court).all())
    open_rfis = {"total": sum(c for _, c in rfi_rows),
                 "by_court": {k or "—": c for k, c in rfi_rows}}

    comments_30d = OpsRecordComment.query.filter(
        OpsRecordComment.created_at >= since).count()

    return {"by_kind": by_kind, "by_project": projects,
            "dsr_manpower_30d": manpower, "open_rfis": open_rfis,
            "comments_30d": comments_30d,
            "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")}


@bp.route("/api/analytics")
@login_required
@permission_required("view_analytics")
@roles_required_json("superadmin")
def api_analytics():
    """Machine-readable cross-tenant ops rollup (superadmin only)."""
    from flask import jsonify
    return jsonify(_ops_analytics())


@bp.route("/branding/<int:template_id>", methods=["GET", "POST"])
@login_required
@template_manager_required
def branding(template_id):
    """Tenant branding customization for the report identity."""
    tpl = ReportTemplate.query.get_or_404(template_id)
    from app.models import TenantBranding
    brand = (db.session.query(TenantBranding)
             .filter_by(project_id=tpl.id, is_active=True).first())
    # Initialize brand row if missing (idempotent for demo)
    if brand is None:
        brand = TenantBranding(project_id=tpl.id, is_active=True)
        db.session.add(brand)
        db.session.commit()
    if request.method == "POST":
        brand.company_name_ar = request.form.get("company_name_ar", "").strip()
        brand.company_name_en = request.form.get("company_name_en", "").strip()
        brand.logo_path = request.form.get("logo_path", "").strip()
        brand.primary_color = request.form.get("primary_color", "#1e3a5f").strip() or "#1e3a5f"
        brand.secondary_color = request.form.get("secondary_color", "#c9a227").strip() or "#c9a227"
        brand.custom_header_text_ar = request.form.get("custom_header_text_ar", "").strip()
        brand.custom_footer_notes = request.form.get("custom_footer_notes", "").strip()
        brand.disclaimer_text = request.form.get("disclaimer_text", "").strip()
        db.session.commit()
        flash("تم حفظ تخصيص المظهر للمشروع.", "success")
        return redirect(url_for("admin.templates"))
    return render_template("admin/branding.html", tpl=tpl, brand=brand)


@bp.route("/analytics")
@login_required
@permission_required("view_analytics")
@roles_required("superadmin")
def analytics():
    """Superadmin cross-tenant ops analytics dashboard."""
    return render_template("admin/analytics.html", data=_ops_analytics())
