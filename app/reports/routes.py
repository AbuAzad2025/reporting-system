"""Field-reporting blueprint — two engines side by side.

LEGACY (v1, static):  /reports/new/<daily|weekly|monthly|safety>, view/edit/
                      delete/pdf — hardcoded FIELD_SPECS, Report table.
DYNAMIC (v2, SaaS):   /reports/dyn, /reports/dyn/new/<template_key>,
                      /reports/dyn/<id>, .../edit, .../delete, .../pdf —
                      DB-driven ReportTemplate + DynamicField + ReportSubmission.

Both stamp signatory_name + timestamp (auto-sign & audit trail) and enforce
anti-duplicate constraints.
"""
from datetime import datetime
from flask import (render_template, request, redirect, url_for, flash,
                   Response, abort, jsonify)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

import os
import re
import uuid
from flask import current_app

from app.reports import bp
from app.extensions import db
from app.models import Report, ReportTemplate, ReportSubmission, Project, REPORT_TYPES
from app.ops.isolation import visible_projects, get_linked_project_or_404
from utils.helpers import FIELD_SPECS
from utils.pdf_generator import build_report_pdf
from app.services.pdf_dynamic import build_dynamic_pdf
from app.services.share import get_share_data

# secure upload for dynamic table file cells (mirrors ops secure handling)
ALLOWED_MIME_DYN = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}
MAX_UPLOAD_DYN = 4 * 1024 * 1024


def _safe_filename_dyn(name: str) -> str:
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE).strip("._")
    if not base:
        return ""
    if "." in base:
        stem, _, ext = base.rpartition(".")
        ext = re.sub(r"[^\w]+", "", ext, flags=re.UNICODE)[:10]
        stem = (stem or "file")[:40]
        return f"{stem}.{ext}" if ext else stem
    return base[:40]


def _store_dyn_file(template_key: str, filename: str, buf: bytes) -> str:
    """Store under UPLOAD_FOLDER/reports/<template_key>/ ; return relative key."""
    rel = os.path.join("reports", template_key, f"{uuid.uuid4().hex[:12]}_{filename}")
    rel = rel.replace(os.sep, "/")
    base = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    abs_path = os.path.abspath(os.path.join(base, rel))
    if abs_path != base and not abs_path.startswith(base + os.sep):
        raise ValueError("storage key escapes upload folder")
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as fh:
        fh.write(buf)
    return rel


# ================================================================ LEGACY
def _parse_common(form):
    project_name = form.get("project_name", "").strip()
    location = form.get("location", "").strip()
    contractor = form.get("contractor", "").strip()
    try:
        report_date = datetime.strptime(form.get("report_date", ""), "%Y-%m-%d").date()
    except ValueError:
        report_date = None
    return project_name, location, contractor, report_date


def _collect_legacy(report_type, form):
    return {k: form.get(k, "").strip()
            for k, _l, _kd in FIELD_SPECS.get(report_type, [])}


@bp.route("/new/<report_type>", methods=["GET", "POST"])
@login_required
def new(report_type):
    if report_type not in REPORT_TYPES:
        abort(404)
    specs = FIELD_SPECS[report_type]
    if request.method == "POST":
        project_name, location, contractor, report_date = _parse_common(request.form)
        payload = _collect_legacy(report_type, request.form)
        ctx = dict(mode="new", report_type=report_type,
                   type_ar=REPORT_TYPES[report_type], specs=specs,
                   form_data=request.form)
        if not project_name:
            flash("اسم المشروع حقل مطلوب.", "danger")
            return render_template("reports/form.html", **ctx)
        if report_date is None:
            flash("تاريخ التقرير غير صالح.", "danger")
            return render_template("reports/form.html", **ctx)
        if Report.query.filter_by(project_name=project_name,
                                  report_type=report_type,
                                  report_date=report_date).first():
            flash(f"يوجد بالفعل {REPORT_TYPES[report_type]} لنفس المشروع "
                  f"({project_name}) بتاريخ {report_date}. لا يمكن تكراره.", "danger")
            return render_template("reports/form.html", **ctx)
        r = Report(report_type=report_type, project_name=project_name,
                   location=location, contractor=contractor,
                   report_date=report_date, data=payload,
                   signatory_name=current_user.full_name, user_id=current_user.id)
        db.session.add(r)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("تم رفض الحفظ: تقرير مكرر لنفس المشروع والنوع والتاريخ.", "danger")
            return render_template("reports/form.html", **ctx)
        flash("تم حفظ التقرير بنجاح.", "success")
        return redirect(url_for("reports.view", report_id=r.id))
    return render_template("reports/form.html", mode="new",
                           report_type=report_type,
                           type_ar=REPORT_TYPES[report_type], specs=specs,
                           form_data={})


@bp.route("/<int:report_id>")
@login_required
def view(report_id):
    r = Report.query.get_or_404(report_id)
    if not current_user.is_admin and r.user_id != current_user.id:
        abort(403)
    return render_template("reports/view.html", report=r,
                           specs=FIELD_SPECS.get(r.report_type, []))


@bp.route("/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def edit(report_id):
    r = Report.query.get_or_404(report_id)
    if not current_user.is_admin and r.user_id != current_user.id:
        abort(403)
    specs = FIELD_SPECS.get(r.report_type, [])
    if request.method == "POST":
        project_name, location, contractor, report_date = _parse_common(request.form)
        payload = _collect_legacy(r.report_type, request.form)
        if not project_name or report_date is None:
            flash("تحقق من اسم المشروع والتاريخ.", "danger")
        elif Report.query.filter(Report.id != r.id,
                                 Report.project_name == project_name,
                                 Report.report_type == r.report_type,
                                 Report.report_date == report_date).first():
            flash("يوجد تقرير آخر بنفس المشروع والنوع والتاريخ.", "danger")
        else:
            r.project_name, r.location, r.contractor, r.report_date, r.data = \
                project_name, location, contractor, report_date, payload
            try:
                db.session.commit()
                flash("تم تحديث التقرير بنجاح.", "success")
                return redirect(url_for("reports.view", report_id=r.id))
            except IntegrityError:
                db.session.rollback()
                flash("تعذر الحفظ بسبب قيد عدم التكرار.", "danger")
    prefill = {"project_name": r.project_name, "location": r.location,
               "contractor": r.contractor, "report_date": str(r.report_date),
               **(r.data or {})}
    return render_template("reports/form.html", mode="edit", report=r,
                           report_type=r.report_type,
                           type_ar=REPORT_TYPES[r.report_type], specs=specs,
                           form_data=prefill)


@bp.route("/<int:report_id>/delete", methods=["POST"])
@login_required
def delete(report_id):
    r = Report.query.get_or_404(report_id)
    if not current_user.is_admin and r.user_id != current_user.id:
        abort(403)
    db.session.delete(r)
    db.session.commit()
    flash("تم حذف التقرير.", "info")
    return redirect(url_for("main.archive", src="legacy"))


@bp.route("/<int:report_id>/pdf")
@login_required
def pdf(report_id):
    r = Report.query.get_or_404(report_id)
    if not current_user.is_admin and r.user_id != current_user.id:
        abort(403)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    data = build_report_pdf(r, author_name=r.signatory_name, generated_at=stamp)
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"inline; filename=report-{r.id}.pdf"})


# ================================================================ DYNAMIC
def _visible_submission(sub_id: int) -> ReportSubmission:
    s = ReportSubmission.query.get_or_404(sub_id)
    if not current_user.is_admin and s.user_id != current_user.id:
        abort(403)
    return s


def _extract_table_rows(field, form):
    """Rebuild line-item rows from flat inputs f_<key>__<idx>__<sub>.

    Accepts a POST form (flat keys) or a plain dict holding lists (prefill).
    Fully-empty rows are dropped; at most 200 rows are kept.
    """
    cols = field.sub_columns()
    if not cols:
        return []
    prefix = f"f_{field.field_key}__"
    by_idx: dict = {}
    if isinstance(form, dict):
        pre = form.get(field.field_key)
        if pre is None:
            pre = form.get(f"f_{field.field_key}")
        if isinstance(pre, list):
            for i, row in enumerate(pre[:200]):
                if isinstance(row, dict):
                    by_idx[i] = {c["key"]: str(row.get(c["key"], "") or "").strip()
                                 for c in cols}
            rows = []
            for i in sorted(by_idx)[:200]:
                row = {c["key"]: by_idx[i].get(c["key"], "") for c in cols}
                if any(v for v in row.values()):
                    rows.append(row)
            return rows
    else:
        keys = form.keys() if hasattr(form, "keys") else form
        for k in keys:
            if not k.startswith(prefix):
                continue
            rest = k[len(prefix):]
            idx, sep, sub = rest.partition("__")
            if not sep or not idx.isdigit():
                continue
            by_idx.setdefault(int(idx), {})[sub] = str(
                form.get(k, "") or "").strip()
    rows = []
    for i in sorted(by_idx)[:200]:
        row = {c["key"]: by_idx[i].get(c["key"], "") for c in cols}
        if any(v for v in row.values()):
            rows.append(row)
    return rows


def _display_table_rows(field, form):
    """Rows for the form template: submitted rows, else one blank row."""
    cols = field.sub_columns()
    rows = _extract_table_rows(field, form)
    if not rows:
        rows = [{c["key"]: "" for c in cols}]
    return rows


def _table_rows_map(template, form):
    return {f.field_key: _display_table_rows(f, form)
            for f in template.ordered_fields if f.field_type == "table"}


def _collect_dynamic(template, form):
    """Validate + collect answers per DynamicField schema + JSON rules."""
    from app.services.field_validation import validate_field_value
    payload, errors = {}, []
    for f in template.ordered_fields:
        if f.field_type == "table":
            cols = f.sub_columns()
            if not cols:
                payload[f.field_key] = []
                continue
            rows = _extract_table_rows(f, form)
            # secure file handling for file-type columns (photos etc.)
            try:
                from flask import request as _req
                _files = getattr(_req, "files", None)
            except Exception:
                _files = None
            if _files is not None:
                for idx, row in enumerate(rows):
                    for c in cols:
                        if c.get("type") != "file":
                            continue
                        file_key = f"f_{f.field_key}__{idx}__{c['key']}"
                        file_obj = _files.get(file_key)
                        if file_obj and getattr(file_obj, "filename", ""):
                            safe = _safe_filename_dyn(file_obj.filename)
                            if not safe:
                                errors.append(f"«{f.label_ar}» — الصف {idx+1}: اسم الملف غير صالح.")
                                continue
                            mime = (getattr(file_obj, "mimetype", "") or "application/octet-stream").lower()
                            if mime not in ALLOWED_MIME_DYN:
                                errors.append(f"«{f.label_ar}» — الصف {idx+1}: نوع الملف غير مدعوم ({mime}).")
                                continue
                            try:
                                file_obj.stream.seek(0)
                            except Exception:
                                pass
                            buf = file_obj.read()
                            if len(buf) > MAX_UPLOAD_DYN:
                                errors.append(f"«{f.label_ar}» — الصف {idx+1}: الملف يتجاوز 4MB.")
                                continue
                            try:
                                storage_key = _store_dyn_file(template.key, safe, buf)
                                row[c["key"]] = storage_key
                            except Exception as exc:
                                errors.append(f"«{f.label_ar}» — الصف {idx+1}: فشل الحفظ.")
            for n, row in enumerate(rows, 1):
                for c in cols:
                    if c.get("type") == "file":
                        # file already validated via MIME/size; keep stored key as-is
                        continue
                    if c["required"] and not row[c["key"]]:
                        errors.append(
                            f"«{f.label_ar}» — الصف {n}: «{c['label_ar']}» مطلوب.")
                        continue
                    rules = {"options": c["options"]} if c["options"] else {}
                    err = validate_field_value(
                        c["type"], row[c["key"]], rules,
                        label=f"«{f.label_ar}» — الصف {n} «{c['label_ar']}»")
                    if err:
                        errors.append(err)
            if f.required and not rows:
                errors.append(f"«{f.label_ar}» يتطلب بنداً واحداً على الأقل.")
            payload[f.field_key] = rows
            continue
        raw = form.get(f"f_{f.field_key}", "").strip()
        if f.field_type == "checkbox":
            raw = "yes" if form.get(f"f_{f.field_key}") else "no"
        if f.required and not raw:
            errors.append(f"الحقل «{f.label_ar}» مطلوب.")
            payload[f.field_key] = raw
            continue
        rules = dict(f.rules or {})
        if f.field_type == "dropdown" and f.options_list():
            rules.setdefault("options", f.options_list())
        err = validate_field_value(f.field_type, raw, rules, label=f"«{f.label_ar}»")
        if err:
            errors.append(err)
        payload[f.field_key] = raw
    return payload, errors


@bp.route("/dyn")
@login_required
def dyn_list():
    templates = ReportTemplate.query.filter_by(is_active=True).order_by(
        ReportTemplate.id).all()
    return render_template("reports/dyn_list.html", templates=templates)


@bp.route("/dyn/new/<template_key>", methods=["GET", "POST"])
@login_required
def dyn_new(template_key):
    tpl = ReportTemplate.query.filter_by(key=template_key,
                                         is_active=True).first_or_404()
    projects = visible_projects(current_user)
    if request.method == "POST":
        project_name = request.form.get("project_name", "").strip()
        project_id = request.form.get("project_id") or None
        try:
            project_id = int(project_id) if project_id else None
        except ValueError:
            project_id = None
        if project_id:
            # linked project is tenant-checked; its name is authoritative
            project_id = get_linked_project_or_404(
                current_user, project_id).id
            project_name = db.session.get(Project, project_id).name
        location = request.form.get("location", "").strip()
        contractor = request.form.get("contractor", "").strip()
        try:
            report_date = datetime.strptime(
                request.form.get("report_date", ""), "%Y-%m-%d").date()
        except ValueError:
            report_date = None
        payload, errors = _collect_dynamic(tpl, request.form)
        if not project_name:
            errors.insert(0, "اسم المشروع حقل مطلوب.")
        if report_date is None:
            errors.insert(0, "تاريخ التقرير غير صالح.")
        dup = None
        if project_name and report_date:
            dup = ReportSubmission.query.filter_by(
                template_id=tpl.id, project_name=project_name,
                report_date=report_date).first()
            if dup:
                errors.insert(0, f"يوجد بالفعل «{tpl.name_ar}» لنفس المشروع "
                              f"({project_name}) بتاريخ {report_date}.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            s = ReportSubmission(
                template_id=tpl.id,
                project_id=project_id if project_id else None,
                project_name=project_name, location=location,
                contractor=contractor, report_date=report_date, data=payload,
                signatory_name=current_user.full_name, user_id=current_user.id)
            db.session.add(s)
            try:
                db.session.commit()
                flash("تم حفظ التقرير الديناميكي بنجاح.", "success")
                return redirect(url_for("reports.dyn_view", sub_id=s.id))
            except IntegrityError:
                db.session.rollback()
                flash("تم رفض الحفظ: تقرير مكرر (القالب + المشروع + التاريخ).",
                      "danger")
        return render_template("reports/dyn_form.html", mode="new", tpl=tpl,
                               projects=projects, form_data=request.form,
                               table_rows=_table_rows_map(tpl, request.form))
    return render_template("reports/dyn_form.html", mode="new", tpl=tpl,
                           projects=projects, form_data={},
                           table_rows=_table_rows_map(tpl, {}))


@bp.route("/dyn/<int:sub_id>")
@login_required
def dyn_view(sub_id):
    s = _visible_submission(sub_id)
    return render_template("reports/dyn_view.html", s=s, tpl=s.template)


@bp.route("/dyn/<int:sub_id>/edit", methods=["GET", "POST"])
@login_required
def dyn_edit(sub_id):
    s = _visible_submission(sub_id)
    tpl = s.template
    projects = visible_projects(current_user)
    if request.method == "POST":
        project_name = request.form.get("project_name", "").strip()
        link_id = request.form.get("project_id") or None
        if link_id:
            # linked project is tenant-checked; its name is authoritative
            linked = get_linked_project_or_404(current_user, link_id)
            project_name = linked.name
        try:
            report_date = datetime.strptime(
                request.form.get("report_date", ""), "%Y-%m-%d").date()
        except ValueError:
            report_date = None
        payload, errors = _collect_dynamic(tpl, request.form)
        if not project_name or report_date is None:
            errors.insert(0, "تحقق من اسم المشروع والتاريخ.")
        elif ReportSubmission.query.filter(
                ReportSubmission.id != s.id,
                ReportSubmission.template_id == tpl.id,
                ReportSubmission.project_name == project_name,
                ReportSubmission.report_date == report_date).first():
            errors.insert(0, "يوجد تقرير آخر بنفس القالب والمشروع والتاريخ.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            s.project_name = project_name
            s.location = request.form.get("location", "").strip()
            s.contractor = request.form.get("contractor", "").strip()
            s.report_date = report_date
            s.data = payload
            s.project_id = int(link_id) if link_id else None
            db.session.commit()
            flash("تم تحديث التقرير بنجاح.", "success")
            return redirect(url_for("reports.dyn_view", sub_id=s.id))
        return render_template("reports/dyn_form.html", mode="edit", tpl=tpl,
                               s=s, projects=projects, form_data=request.form,
                               table_rows=_table_rows_map(tpl, request.form))
    prefill = {"project_name": s.project_name, "location": s.location,
               "contractor": s.contractor, "report_date": str(s.report_date),
               "project_id": s.project_id,
               **{f"f_{k}": v for k, v in (s.data or {}).items()}}
    return render_template("reports/dyn_form.html", mode="edit", tpl=tpl, s=s,
                           projects=projects, form_data=prefill,
                           table_rows=_table_rows_map(tpl, prefill))


@bp.route("/dyn/<int:sub_id>/delete", methods=["POST"])
@login_required
def dyn_delete(sub_id):
    s = _visible_submission(sub_id)
    db.session.delete(s)
    db.session.commit()
    flash("تم حذف التقرير.", "info")
    return redirect(url_for("main.archive", src="dyn"))


@bp.route("/dyn/<int:sub_id>/pdf")
@login_required
def dyn_pdf(sub_id):
    s = _visible_submission(sub_id)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    data = build_dynamic_pdf(s, s.template, generated_at=stamp)
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"inline; filename=submission-{s.id}.pdf"})


# ================================================================ SHARE
@bp.route("/share/<report_type>/<int:report_id>")
@login_required
def share_report(report_type, report_id):
    """Return share metadata (URLs) for a report."""
    if report_type == "legacy":
        report = Report.query.get_or_404(report_id)
        if not current_user.is_admin and report.user_id != current_user.id:
            abort(403)
        data = get_share_data(report, "legacy")
    elif report_type == "dynamic":
        from app.reports.routes import _visible_submission
        s = _visible_submission(report_id)
        data = get_share_data(s, "dynamic")
    else:
        abort(404)
    return jsonify(data)
