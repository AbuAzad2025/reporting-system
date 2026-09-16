from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        ident = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(
            (User.username == ident) | (User.email == ident)).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            flash(f"مرحباً {user.full_name} 👋", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("main.dashboard"))
        flash("بيانات الدخول غير صحيحة. تحقق من اسم المستخدم وكلمة المرور.", "danger")
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        role = "admin" if request.form.get("role") == "admin" else "user"

        errors = []
        if len(full_name.split()) < 4:
            errors.append("يرجى إدخال الاسم الرباعي الكامل (أربعة مقاطع على الأقل).")
        if len(username) < 3:
            errors.append("اسم المستخدم يجب أن يكون 3 أحرف على الأقل.")
        if "@" not in email:
            errors.append("البريد الإلكتروني غير صالح.")
        if len(password) < 6:
            errors.append("كلمة المرور يجب أن تكون 6 أحرف على الأقل.")
        if password != confirm:
            errors.append("تأكيد كلمة المرور غير متطابق.")
        if User.query.filter_by(username=username).first():
            errors.append("اسم المستخدم مسجل مسبقاً.")
        if User.query.filter_by(email=email).first():
            errors.append("البريد الإلكتروني مسجل مسبقاً.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            # First ever user becomes admin automatically
            if User.query.count() == 0:
                role = "admin"
            user = User(username=username, email=email, full_name=full_name,
                        role=role, phone=request.form.get("phone", "").strip(),
                        company=request.form.get("company", "").strip())
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("تم إنشاء الحساب بنجاح. سجل الدخول الآن.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("تم تسجيل الخروج بنجاح.", "info")
    return redirect(url_for("auth.login"))
