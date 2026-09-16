from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_

from extensions import db
from models import User, Report, REPORT_TYPES
from utils.helpers import admin_required

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    # Template selector cards + quick stats
    if current_user.is_admin:
        base = Report.query
    else:
        base = Report.query.filter_by(user_id=current_user.id)
    total = base.count()
    counts = {k: base.filter_by(report_type=k).count() for k in REPORT_TYPES}
    recent = base.order_by(Report.created_at.desc()).limit(5).all()
    return render_template("dashboard.html", types=REPORT_TYPES,
                           total=total, counts=counts, recent=recent)


@bp.route("/archive")
@login_required
def archive():
    q = Report.query if current_user.is_admin else Report.query.filter_by(
        user_id=current_user.id)
    rtype = request.args.get("type", "").strip()
    search = request.args.get("q", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()

    if rtype in REPORT_TYPES:
        q = q.filter_by(report_type=rtype)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Report.project_name.ilike(like),
                         Report.location.ilike(like),
                         Report.signatory_name.ilike(like)))
    if date_from:
        q = q.filter(Report.report_date >= date_from)
    if date_to:
        q = q.filter(Report.report_date <= date_to)

    reports = q.order_by(Report.report_date.desc(),
                         Report.created_at.desc()).limit(300).all()
    return render_template("archive.html", reports=reports, types=REPORT_TYPES,
                           f_type=rtype, f_q=search,
                           f_from=date_from, f_to=date_to)


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


@bp.route("/admin/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users)


@bp.route("/admin/users/<int:user_id>/toggle-role", methods=["POST"])
@login_required
@admin_required
def toggle_role(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("لا يمكنك تغيير دور حسابك الخاص.", "warning")
    else:
        user.role = "user" if user.is_admin else "admin"
        db.session.commit()
        flash(f"تم تحديث دور {user.full_name} إلى ({user.role_ar}).", "success")
    return redirect(url_for("main.users"))
