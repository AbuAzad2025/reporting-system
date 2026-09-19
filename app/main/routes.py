"""Main blueprint — landing, dashboard (dynamic template selector),
central archive (legacy + dynamic), profile, platform-owner user admin.
"""
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm.attributes import flag_modified
import os

from app.main import bp
from app.extensions import db
from app.models import User, Report, ReportTemplate, ReportSubmission, ROLES, Project
from app.utils.decorators import roles_required, permission_required


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    templates = ReportTemplate.query.filter_by(is_active=True).order_by(
        ReportTemplate.id).all()
    # per-template counts visible to this user
    counts, total = {}, 0
    for t in templates:
        q = ReportSubmission.query.filter_by(template_id=t.id)
        if not current_user.is_admin:
            q = q.filter_by(user_id=current_user.id)
        c = q.count()
        counts[t.key] = c
        total += c
    # legacy reports (v1 static flow) still counted
    legacy_q = Report.query if current_user.is_admin else \
        Report.query.filter_by(user_id=current_user.id)
    legacy_total = legacy_q.count()
    recent_dyn = (ReportSubmission.query if current_user.is_admin
                  else ReportSubmission.query.filter_by(user_id=current_user.id)
                  ).order_by(ReportSubmission.created_at.desc()).limit(5).all()
    recent_legacy = legacy_q.order_by(Report.created_at.desc()).limit(5).all()
    return render_template("dashboard.html", templates=templates, counts=counts,
                           total=total, legacy_total=legacy_total,
                           recent_dyn=recent_dyn, recent_legacy=recent_legacy)


@bp.route("/archive")
@login_required
def archive():
    """Filterable, sortable, paginated history across BOTH engines.

    Query params (all optional, backward compatible):
      src: dyn | legacy (default dyn)
      q, from, to, tpl, type: filters (as before)
      project: project_id — filter by project
      sort: date | project | type (default date)
      order: desc | asc (default desc)
      page: >=1 (default 1) · per_page: 1..100 (default 20)
    """
    from app.models import REPORT_TYPES
    src = request.args.get("src", "dyn")  # dyn | legacy
    search = request.args.get("q", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    tpl_key = request.args.get("tpl", "").strip()
    rtype = request.args.get("type", "").strip()
    sort = request.args.get("sort", "date").strip()
    if sort not in ("date", "project", "type"):
        sort = "date"
    order = request.args.get("order", "desc").strip().lower()
    if order not in ("desc", "asc"):
        order = "desc"
    project_id = request.args.get("project", "").strip()
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    except (TypeError, ValueError):
        per_page = 20

    # Project filter → resolve id to name (dyn/legacy store project_name).
    project_name_filter, project_obj = "", None
    if project_id.isdigit():
        project_obj = db.session.get(Project, int(project_id))
        if project_obj:
            project_name_filter = project_obj.name

    # Projects visible to this user for the filter dropdown.
    if current_user.is_admin:
        projects = Project.query.order_by(Project.name).all()
    else:
        from app.ops.models import ProjectMember
        member_ids = db.session.query(ProjectMember.project_id).filter_by(
            user_id=current_user.id).all()
        ids = [r[0] for r in member_ids]
        projects = Project.query.filter(
            Project.id.in_(ids)).order_by(Project.name).all() if ids else []

    submissions, reports = [], []
    total, total_pages = 0, 1
    templates = ReportTemplate.query.filter_by(is_active=True).all()

    def _apply_common(q, model):
        if search:
            like = f"%{search}%"
            q = q.filter(or_(model.project_name.ilike(like),
                             model.location.ilike(like),
                             model.signatory_name.ilike(like)))
        if date_from:
            q = q.filter(model.report_date >= date_from)
        if date_to:
            q = q.filter(model.report_date <= date_to)
        if project_name_filter:
            q = q.filter_by(project_name=project_name_filter)
        return q

    def _apply_sort(q, model):
        cols = {
            "date": (model.report_date, model.created_at, model.id),
            "project": (model.project_name, model.report_date, model.id),
            "type": None,
        }
        if sort == "type":
            if model is Report:
                type_col = model.report_type
            else:
                return q.order_by(model.report_date.desc(),
                                  model.created_at.desc(), model.id.desc())
            keys = [type_col, model.report_date, model.id]
        else:
            keys = list(cols[sort])
        if order == "asc":
            return q.order_by(*[c.asc() for c in keys])
        return q.order_by(*[c.desc() for c in keys])

    if src == "legacy":
        q = Report.query if current_user.is_admin else \
            Report.query.filter_by(user_id=current_user.id)
        if rtype:
            q = q.filter_by(report_type=rtype)
        q = _apply_sort(_apply_common(q, Report), Report)
        total = q.count()
        total_pages = max((total + per_page - 1) // per_page, 1)
        page = min(page, total_pages)
        reports = q.offset((page - 1) * per_page).limit(per_page).all()
    else:
        q = ReportSubmission.query if current_user.is_admin else \
            ReportSubmission.query.filter_by(user_id=current_user.id)
        if tpl_key:
            tpl = ReportTemplate.query.filter_by(key=tpl_key).first()
            q = q.filter_by(template_id=tpl.id) if tpl else q.filter(False)
        q = _apply_sort(_apply_common(q, ReportSubmission), ReportSubmission)
        total = q.count()
        total_pages = max((total + per_page - 1) // per_page, 1)
        page = min(page, total_pages)
        submissions = q.offset((page - 1) * per_page).limit(per_page).all()

    return render_template("archive.html", src=src, submissions=submissions,
                           reports=reports, templates=templates,
                           types=REPORT_TYPES, f_q=search, f_from=date_from,
                           f_to=date_to, f_tpl=tpl_key, f_type=rtype,
                           f_sort=sort, f_order=order, f_project=project_id,
                           projects=projects, total=total, page=page,
                           per_page=per_page, total_pages=total_pages)


# Allowed avatar MIME types and max size (2 MB)
ALLOWED_AVATAR_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024


def _save_avatar(file_storage) -> str:
    """Save uploaded avatar to uploads/avatars/ and return storage key."""
    if not file_storage or file_storage.filename == "":
        return ""
    filename = os.path.basename(file_storage.filename)
    mime = (file_storage.mimetype or "").lower()
    if mime not in ALLOWED_AVATAR_MIME:
        raise ValueError("نوع الملف غير مدعوم (JPG, PNG, GIF, WebP فقط).")
    content = file_storage.read()
    if len(content) > MAX_AVATAR_SIZE:
        raise ValueError("حجم الصورة يتجاوز 2 ميغابايت.")
    # Generate unique storage key
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    import time
    storage_key = f"avatars/{current_user.id}_{int(time.time())}{ext}"
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
    avatar_dir = os.path.join(upload_dir, "avatars")
    os.makedirs(avatar_dir, exist_ok=True)
    dest = os.path.join(avatar_dir, os.path.basename(storage_key))
    with open(dest, "wb") as f:
        f.write(content)
    return storage_key


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if len(full_name.split()) < 4:
            flash("الاسم الرباعي يجب أن يتكون من أربعة مقاطع على الأقل.", "danger")
        else:
            current_user.full_name = full_name
            current_user.phone = request.form.get("phone", "").strip()
            current_user.company = request.form.get("company", "").strip()
            current_user.job_title = request.form.get("job_title", "").strip()
            current_user.department = request.form.get("department", "").strip()
            current_user.certification = request.form.get("certification", "").strip()
            # Notification preferences
            prefs = current_user.notification_prefs or {}
            prefs["email"] = bool(request.form.get("notify_email"))
            prefs["sms"] = bool(request.form.get("notify_sms"))
            prefs["push"] = bool(request.form.get("notify_push"))
            prefs["in_app"] = bool(request.form.get("notify_in_app"))
            current_user.notification_prefs = prefs
            flag_modified(current_user, "notification_prefs")

            # Avatar upload
            if "avatar" in request.files:
                avatar_file = request.files["avatar"]
                if avatar_file and avatar_file.filename:
                    try:
                        storage_key = _save_avatar(avatar_file)
                        if storage_key:
                            current_user.avatar = storage_key
                    except ValueError as e:
                        flash(str(e), "danger")
                        return render_template("profile.html")

            new_pw = request.form.get("new_password", "").strip()
            if new_pw:
                if len(new_pw) < 6:
                    flash("كلمة المرور الجديدة قصيرة (6 أحرف على الأقل).", "danger")
                    return render_template("profile.html")
                current_user.set_password(new_pw)
            db.session.commit()
            flash("تم تحديث الملف الشخصي بنجاح.", "success")
            return redirect(url_for("main.profile"))
    return render_template("profile.html")


@bp.route("/profile/avatar/remove", methods=["POST"])
@login_required
def remove_avatar():
    """Remove user's avatar."""
    if current_user.avatar:
        # Delete file from filesystem
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
        file_path = os.path.join(upload_dir, current_user.avatar)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass  # Ignore filesystem errors
        current_user.avatar = ""
        db.session.commit()
        flash("تم حذف الصورة الشخصية.", "success")
    else:
        flash("لا توجد صورة لحذفها.", "warning")
    return redirect(url_for("main.profile"))


# ---- platform-owner user management (also mirrored under /admin/users)
@bp.route("/admin/users")
@login_required
@roles_required("admin", "superadmin")
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users, ROLES=ROLES)


@bp.route("/admin/users/<int:user_id>/toggle-role", methods=["POST"])
@login_required
@roles_required("admin", "superadmin")
def toggle_role(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("لا يمكنك تغيير دور حسابك الخاص.", "warning")
    else:
        # Cycle through roles:
        # site_engineer -> safety_officer -> procurement_officer -> qa_qc_inspector
        # -> senior_consultant -> project_manager -> project_director -> admin -> superadmin
        # -> site_engineer
        role_order = ["site_engineer", "safety_officer", "procurement_officer",
                      "qa_qc_inspector", "senior_consultant", "project_manager",
                      "project_director", "admin", "superadmin"]
        try:
            idx = role_order.index(user.role)
            user.role = role_order[(idx + 1) % len(role_order)]
        except ValueError:
            user.role = "site_engineer"
        db.session.commit()
        flash(f"تم تحديث دور {user.full_name} إلى ({user.role_ar}).", "success")
    return redirect(url_for("main.users"))


# ---------------------------------------------------------------- self-service projects
# Domain rule: a real-world project is created ONCE by its project manager
# (manage_projects); everyone else joins by invitation with role permissions.
@bp.route("/projects", methods=["GET"])
@login_required
@permission_required("create_reports")
def projects():
    """My projects: tenant-scoped list (creation lives in project_create)."""
    from app.ops.isolation import (visible_projects, is_platform_manager,
                                   membership_role)
    plist = visible_projects(current_user, active_only=False)
    roles = {p.id: (membership_role(current_user, p.id) or "member")
             for p in plist}
    return render_template(
        "projects.html", projects=plist, roles=roles,
        is_manager=is_platform_manager(current_user),
        can_create=current_user.has_perm("manage_projects"))


@bp.route("/projects", methods=["POST"])
@login_required
@permission_required("manage_projects")
def project_create():
    """Create a project (project manager and above); creator becomes owner."""
    from app.ops.models import ProjectMember
    name = request.form.get("name", "").strip()
    if not name:
        flash("اسم المشروع مطلوب.", "danger")
    elif Project.query.filter_by(name=name).first():
        flash("يوجد مشروع بنفس الاسم.", "danger")
    else:
        p = Project(
            name=name, location=request.form.get("location", "").strip(),
            contractor=request.form.get("contractor", "").strip(),
            client=request.form.get("client", "").strip())
        db.session.add(p)
        db.session.flush()
        db.session.add(ProjectMember(
            user_id=current_user.id, project_id=p.id,
            role_in_project="owner"))
        db.session.commit()
        flash(f"تم إنشاء المشروع «{name}» — ادعُ فريقك قبل التقارير.",
              "success")
        return redirect(url_for("main.project_detail", project_id=p.id))
    return redirect(url_for("main.projects"))


@bp.route("/projects/<int:project_id>")
@login_required
@permission_required("view_reports")
def project_detail(project_id):
    """Project card + member roster (tenant-scoped, 404 outside scope)."""
    from app.ops.isolation import (get_linked_project_or_404,
                                   is_platform_manager, membership_role)
    from app.ops.models import ProjectMember
    project = get_linked_project_or_404(current_user, project_id)
    my_role = membership_role(current_user, project.id)
    members = (db.session.query(User, ProjectMember)
               .join(ProjectMember, ProjectMember.user_id == User.id)
               .filter(ProjectMember.project_id == project.id)
               .order_by(User.full_name).all())
    can_manage = is_platform_manager(current_user) or my_role == "owner"
    directory = []
    if can_manage:
        # invite UX: active-user directory (username + name) for the
        # invite box; visible to project managers only, not plain members.
        directory = User.query.filter_by(is_active=True).order_by(
            User.full_name).all()
    return render_template("project_detail.html", project=project,
                           members=members, my_role=my_role,
                           can_manage=can_manage, directory=directory)


@bp.route("/projects/<int:project_id>/members", methods=["POST"])
@login_required
def project_member_add(project_id):
    """Owner (or platform manager) invites a member by username."""
    from app.ops.isolation import (get_linked_project_or_404,
                                   is_platform_manager, membership_role)
    from app.ops.models import ProjectMember
    project = get_linked_project_or_404(current_user, project_id)
    my_role = membership_role(current_user, project.id)
    if not (is_platform_manager(current_user) or my_role == "owner"):
        flash("إدارة الأعضاء مقصورة على مالك المشروع.", "danger")
        return redirect(url_for("main.project_detail",
                                project_id=project.id))
    username = request.form.get("username", "").strip()
    u = User.query.filter_by(username=username).first() if username else None
    if u is None or not u.is_active:
        flash("المستخدم غير موجود أو موقوف.", "danger")
    elif ProjectMember.query.filter_by(
            user_id=u.id, project_id=project.id).first():
        flash("هذا المستخدم عضو بالفعل.", "warning")
    else:
        db.session.add(ProjectMember(user_id=u.id, project_id=project.id,
                                     role_in_project="member"))
        db.session.commit()
        flash(f"تمت إضافة {u.full_name} إلى المشروع.", "success")
    return redirect(url_for("main.project_detail", project_id=project.id))


@bp.route("/projects/<int:project_id>/members/<int:user_id>/remove",
          methods=["POST"])
@login_required
def project_member_remove(project_id, user_id):
    """Owner (or platform manager) removes a member; self-removal barred."""
    from app.ops.isolation import (get_linked_project_or_404,
                                   is_platform_manager, membership_role)
    from app.ops.models import ProjectMember
    project = get_linked_project_or_404(current_user, project_id)
    my_role = membership_role(current_user, project.id)
    if not (is_platform_manager(current_user) or my_role == "owner"):
        flash("إدارة الأعضاء مقصورة على مالك المشروع.", "danger")
        return redirect(url_for("main.project_detail",
                                project_id=project.id))
    if user_id == current_user.id:
        flash("لا يمكنك إزالة نفسك من المشروع.", "warning")
    else:
        row = ProjectMember.query.filter_by(
            user_id=user_id, project_id=project.id).first()
        if row is None:
            flash("العضوية غير موجودة.", "warning")
        else:
            db.session.delete(row)
            db.session.commit()
            flash("تمت إزالة العضو.", "info")
    return redirect(url_for("main.project_detail", project_id=project.id))


# ---------------------------------------------------------------- project backup
@bp.route("/projects/<int:project_id>/backup", methods=["POST"])
@login_required
def project_backup(project_id):
    """Project owner/manager exports project data as downloadable ZIP."""
    from app.services.backup import build_backup, backup_filename
    from app.services.storage import upload as storage_upload
    from app.ops.isolation import get_linked_project_or_404, membership_role, is_platform_manager
    project = get_linked_project_or_404(current_user, project_id)
    my_role = membership_role(current_user, project.id)
    can_manage = is_platform_manager(current_user) or my_role == "owner"
    if not can_manage:
        flash("إدارة النسخ الاحتياطي مقصورة على مالك المشروع.", "danger")
        return redirect(url_for("main.project_detail", project_id=project_id))
    data = build_backup(project_id)
    filename = backup_filename(project_id)
    try:
        storage_upload(data, filename)
    except Exception as exc:
        flash(f"فشل حفظ النسخة الاحتياطية: {exc}", "danger")
        return redirect(url_for("main.project_detail", project_id=project_id))
    flash(f"تم إنشاء نسخة احتياطية للمشروع «{project.name}».", "success")
    return redirect(url_for("main.project_detail", project_id=project_id))


@bp.route("/projects/<int:project_id>/backup/import", methods=["POST"])
@login_required
def project_backup_import(project_id):
    """Project owner/manager restores project data from uploaded backup."""
    from app.services.backup import restore_backup, validate_backup
    from app.ops.isolation import get_linked_project_or_404, membership_role, is_platform_manager
    project = get_linked_project_or_404(current_user, project_id)
    my_role = membership_role(current_user, project.id)
    can_manage = is_platform_manager(current_user) or my_role == "owner"
    if not can_manage:
        flash("إدارة النسخ الاحتياطي مقصورة على مالك المشروع.", "danger")
        return redirect(url_for("main.project_detail", project_id=project_id))
    if "backup_file" not in request.files:
        flash("لم يتم اختيار ملف نسخة احتياطية.", "danger")
        return redirect(url_for("main.project_detail", project_id=project_id))
    file = request.files["backup_file"]
    if file.filename == "":
        flash("لم يتم اختيار ملف نسخة احتياطية.", "danger")
        return redirect(url_for("main.project_detail", project_id=project_id))
    data = file.read()
    validation = validate_backup(data)
    if not validation["ok"]:
        flash(f"الملف غير صالح: {validation['error']}", "danger")
        return redirect(url_for("main.project_detail", project_id=project_id))
    try:
        counts = restore_backup(data, project_id=project_id, replace=True)
    except Exception as exc:
        flash(f"فشل الاستعادة: {exc}", "danger")
        return redirect(url_for("main.project_detail", project_id=project_id))
    summary = ", ".join(f"{k}: {v}" for k, v in counts.items())
    flash(f"تم استعادة المشروع «{project.name}» — {summary}", "success")
    return redirect(url_for("main.project_detail", project_id=project_id))
