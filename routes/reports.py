"""Report CRUD + PDF export with anti-duplicate validation."""
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, Response, abort)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Report, REPORT_TYPES
from utils.helpers import FIELD_SPECS
from utils.pdf_generator import build_report_pdf

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _parse_common(form):
    project_name = form.get("project_name", "").strip()
    location = form.get("location", "").strip()
    contractor = form.get("contractor", "").strip()
    date_raw = form.get("report_date", "").strip()
    try:
        report_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
    except ValueError:
        report_date = None
    return project_name, location, contractor, report_date


def _collect_payload(report_type, form):
    payload = {}
    for key, _label, _kind in FIELD_SPECS.get(report_type, []):
        payload[key] = form.get(key, "").strip()
    return payload


@bp.route("/new/<report_type>", methods=["GET", "POST"])
@login_required
def new(report_type):
    if report_type not in REPORT_TYPES:
        abort(404)
    specs = FIELD_SPECS[report_type]

    if request.method == "POST":
        project_name, location, contractor, report_date = _parse_common(request.form)
        payload = _collect_payload(report_type, request.form)

        if not project_name:
            flash("اسم المشروع حقل مطلوب.", "danger")
            return render_template("reports/form.html", mode="new",
                                   report_type=report_type,
                                   type_ar=REPORT_TYPES[report_type],
                                   specs=specs, form_data=request.form)
        if report_date is None:
            flash("تاريخ التقرير غير صالح.", "danger")
            return render_template("reports/form.html", mode="new",
                                   report_type=report_type,
                                   type_ar=REPORT_TYPES[report_type],
                                   specs=specs, form_data=request.form)

        # ---- Anti-duplicate constraint (friendly check before DB hit)
        dup = Report.query.filter_by(
            project_name=project_name, report_type=report_type,
            report_date=report_date).first()
        if dup:
            flash(f"يوجد بالفعل {REPORT_TYPES[report_type]} لنفس المشروع "
                  f"({project_name}) بتاريخ {report_date}. لا يمكن تكراره.",
                  "danger")
            return render_template("reports/form.html", mode="new",
                                   report_type=report_type,
                                   type_ar=REPORT_TYPES[report_type],
                                   specs=specs, form_data=request.form)

        report = Report(report_type=report_type, project_name=project_name,
                        location=location, contractor=contractor,
                        report_date=report_date, data=payload,
                        signatory_name=current_user.full_name,
                        user_id=current_user.id)
        db.session.add(report)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("تم رفض الحفظ: تقرير مكرر لنفس المشروع والنوع والتاريخ.", "danger")
            return render_template("reports/form.html", mode="new",
                                   report_type=report_type,
                                   type_ar=REPORT_TYPES[report_type],
                                   specs=specs, form_data=request.form)
        flash("تم حفظ التقرير بنجاح.", "success")
        return redirect(url_for("reports.view", report_id=report.id))

    return render_template("reports/form.html", mode="new",
                           report_type=report_type,
                           type_ar=REPORT_TYPES[report_type],
                           specs=specs, form_data={})


@bp.route("/<int:report_id>")
@login_required
def view(report_id):
    report = Report.query.get_or_404(report_id)
    if not current_user.is_admin and report.user_id != current_user.id:
        abort(403)
    specs = FIELD_SPECS.get(report.report_type, [])
    return render_template("reports/view.html", report=report, specs=specs)


@bp.route("/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def edit(report_id):
    report = Report.query.get_or_404(report_id)
    if not current_user.is_admin and report.user_id != current_user.id:
        abort(403)
    specs = FIELD_SPECS.get(report.report_type, [])

    if request.method == "POST":
        project_name, location, contractor, report_date = _parse_common(request.form)
        payload = _collect_payload(report.report_type, request.form)
        if not project_name or report_date is None:
            flash("تحقق من اسم المشروع والتاريخ.", "danger")
        else:
            # duplicate check excluding self
            dup = Report.query.filter(
                Report.id != report.id,
                Report.project_name == project_name,
                Report.report_type == report.report_type,
                Report.report_date == report_date).first()
            if dup:
                flash("يوجد تقرير آخر بنفس المشروع والنوع والتاريخ.", "danger")
            else:
                report.project_name = project_name
                report.location = location
                report.contractor = contractor
                report.report_date = report_date
                report.data = payload
                try:
                    db.session.commit()
                    flash("تم تحديث التقرير بنجاح.", "success")
                    return redirect(url_for("reports.view", report_id=report.id))
                except IntegrityError:
                    db.session.rollback()
                    flash("تعذر الحفظ بسبب قيد عدم التكرار.", "danger")

    # prefill dict for template
    prefill = {"project_name": report.project_name, "location": report.location,
               "contractor": report.contractor,
               "report_date": str(report.report_date),
               **(report.data or {})}
    return render_template("reports/form.html", mode="edit", report=report,
                           report_type=report.report_type,
                           type_ar=REPORT_TYPES[report.report_type],
                           specs=specs, form_data=prefill)


@bp.route("/<int:report_id>/delete", methods=["POST"])
@login_required
def delete(report_id):
    report = Report.query.get_or_404(report_id)
    if not current_user.is_admin and report.user_id != current_user.id:
        abort(403)
    db.session.delete(report)
    db.session.commit()
    flash("تم حذف التقرير.", "info")
    return redirect(url_for("main.archive"))


@bp.route("/<int:report_id>/pdf")
@login_required
def pdf(report_id):
    report = Report.query.get_or_404(report_id)
    if not current_user.is_admin and report.user_id != current_user.id:
        abort(403)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf_bytes = build_report_pdf(report,
                                 author_name=report.signatory_name,
                                 generated_at=stamp)
    filename = f"{report.report_type}-{report.project_name}-{report.report_date}.pdf"
    # ASCII-safe fallback filename for old browsers
    safe = f"report-{report.id}.pdf"
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={safe}"})
