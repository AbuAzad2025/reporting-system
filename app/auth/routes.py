"""Authentication blueprint — login / registration / logout.

Multi-tier RBAC: registration offers engineer tiers + admin request.
The very first account in the DB becomes superadmin (platform owner).
"""
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user

from app.auth import bp
from app.extensions import db
from app.models import User, ROLES

# Roles a self-registering user may pick (superadmin never self-assignable)
SELF_REGISTER_ROLES = ["site_engineer", "safety_officer", "project_manager", "admin"]


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
            if not user.is_active:
                flash("تم إيقاف هذا الحساب. تواصل مع الإدارة.", "danger")
                return render_template("auth/login.html")
            remember = request.form.get("remember", "off") == "on"
            login_user(user, remember=remember)
            flash(f"مرحباً {user.full_name} 👋", "success")
            return redirect(request.args.get("next") or url_for("main.dashboard"))
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
        role = request.form.get("role", "site_engineer").strip()
        if role not in SELF_REGISTER_ROLES:
            role = "site_engineer"

        errors = []
        if len(full_name.split()) < 4:
            errors.append("يرجى إدخال الاسم الرباعي الكامل (أربعة مقاطع على الأقل).")
        if len(username) < 3:
            errors.append("اسم المستخدم يجب أن يكون 3 أحرف على الأقل.")
        if "@" not in email or "." not in email.split("@")[-1]:
            errors.append("البريد الإلكتروني غير صالح (يجب أن يحتوي على @ واسم نطاق صالح).")
        if len(password) < 8:
            errors.append("كلمة المرور يجب أن تكون 8 أحرف على الأقل (أمان أفضل).")
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
            if User.query.count() == 0:
                role = "superadmin"  # platform owner
            user = User(username=username, email=email, full_name=full_name,
                        role=role, phone=request.form.get("phone", "").strip(),
                        company=request.form.get("company", "").strip())
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("تم إنشاء الحساب بنجاح. سجل الدخول الآن.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html",
                           role_choices=[(k, ROLES[k]) for k in SELF_REGISTER_ROLES])


@bp.route("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
        flash("تم تسجيل الخروج بنجاح.", "info")
    return redirect(url_for("auth.login"))
