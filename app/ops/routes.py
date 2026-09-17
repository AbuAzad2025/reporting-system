"""Azadexa ops controllers — JSON-first secure CRUD per module.

Security posture on EVERY route:
  * @login_required + active-account check (fail-closed).
  * Tenant scoping via app/ops/isolation.py — cross-tenant access returns 404
    (no IDOR enumeration oracle); role-denied actions return 403.
  * Strict input validation (required/enum/numeric-range/date) — 422 on abuse.
  * Approval transitions restricted to platform-manager roles; every decision
    stamps reviewer identity + timestamp (legal audit trail).
  * Serials unique per module with DB constraint + insert retry.
"""
from datetime import datetime
from flask import Response, current_app, jsonify, request, send_file
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
import os
import re
import uuid

from app.ops import bp
from app.extensions import db
from app.models import Project
from app.ops import models as M
from app.ops.models import Attachment
from app.ops.isolation import (is_platform_manager, scope_to_tenant,
                               get_object_or_404_tenant, tenant_create_guard,
                               roles_required_json)
from app.utils.decorators import permission_required, any_permission_required

KIND_MODEL = {
    "site-inspections": M.SiteInspection,
    "material-submittals": M.MaterialSubmittal,
    "rfis": M.RFI,
    "cost-variances": M.CostVariance,
    "progress-billings": M.ProgressBilling,
    "subcontractor-performances": M.SubcontractorPerformance,
    "daily-reports": M.DailySiteReport,
    "variation-orders": M.VariationOrder,
    "safety-reports": M.SafetyReport,
}

#: validation schema per kind
SCHEMAS = {
    "site-inspections": {
        "required": ["project_id", "test_category", "test_type"],
        "enums": {"test_category": list(M.TEST_CATEGORIES),
                  "verdict": ["pass", "fail", "pending"]},
        "numbers": {"result_value": (None, None),
                    "acceptance_min": (None, None),
                    "acceptance_max": (None, None),
                    "slump": (0, None), "attachments": (0, None)},
        "dates": ["report_date"],
    },
    "material-submittals": {
        "required": ["project_id", "material_name"],
        "enums": {"consultant_action": list(M.CONSULTANT_ACTIONS)},
        "numbers": {"quantity": (0, None)},
        "dates": ["report_date", "resubmit_due"],
    },
    "rfis": {
        "required": ["project_id", "subject", "question"],
        "enums": {"ball_in_court": list(M.BALL_IN_COURT),
                  "priority": ["low", "normal", "high", "critical"],
                  "cost_impact": ["none", "pending", "confirmed"]},
        "numbers": {"delay_days": (0, None)},
        "dates": ["report_date", "reply_due", "date_replied"],
    },
    "cost-variances": {
        "required": ["project_id", "boq_item"],
        "enums": {},
        "numbers": {"budgeted_qty": (0, None), "budgeted_rate": (0, None),
                    "actual_qty": (0, None), "actual_rate": (0, None),
                    "reestimated_qty": (0, None),
                    "reestimated_rate": (0, None),
                    "schedule_impact_days": (0, None)},
        "dates": ["report_date"],
    },
    "progress-billings": {
        "required": ["project_id", "work_item"],
        "enums": {},
        "numbers": {"qty_completed": (0, None), "rate": (0, None),
                    "retention_pct": (0, 100),
                    "previously_certified": (0, None),
                    "progress_pct": (0, 100)},
        "dates": ["report_date", "period_from", "period_to"],
    },
    "subcontractor-performances": {
        "required": ["project_id", "subcontractor"],
        "enums": {"recommendation": list(M.SUB_RECOMMENDATIONS)},
        "numbers": {"quality_score": (0, 100), "schedule_score": (0, 100),
                    "safety_score": (0, 100), "compliance_score": (0, 100),
                    "recommended_payment": (0, None),
                    "delay_days": (0, None), "penalty": (0, None),
                    "incidents": (0, None)},
        "dates": ["report_date"],
    },
    "daily-reports": {
        "required": ["project_id"],
        "enums": {"weather": list(M.WEATHER)},
        "numbers": {"temp_c": (-10, 55), "work_hours": (0, 24),
                    "engineers_count": (0, None),
                    "technicians_count": (0, None),
                    "labor_count": (0, None),
                    "day_progress_pct": (0, 100)},
        "dates": ["report_date"],
    },
    "variation-orders": {
        "required": ["project_id", "title"],
        "enums": {"category": list(M.VO_CATEGORIES),
                  "recommendation": list(M.VO_RECOMMENDATIONS)},
        "numbers": {"cost_impact": (None, None),
                    "time_impact_days": (None, None),
                    "attachments": (0, None)},
        "dates": ["report_date"],
    },
    "safety-reports": {
        "required": ["project_id", "area"],
        "enums": {"inspection_type": list(M.SAFETY_INSPECTION_TYPES),
                  "risk_level": list(M.RISK_LEVELS),
                  "responsible": list(M.SAFETY_RESPONSIBLE)},
        "numbers": {"incidents_count": (0, None),
                    "lost_time_injuries": (0, None),
                    "toolbox_talks": (0, None),
                    "ppe_compliance": (0, 100)},
        "dates": ["report_date", "target_date", "closure_date"],
    },
}

#: mass-assignment guard — never client-settable
PROTECTED = {"id", "serial", "status", "signatory_name", "user_id",
             "reviewed_by_id", "reviewed_at", "created_at", "updated_at"}

#: structured workflow tables: kind -> table -> [(key, type, required, rule)]
#: type ∈ text/number/enum; rule = allowed tuple (enum) or (lo, hi) (number).
TABLE_SPECS = {
    "daily-reports": {
        "labor_table": [("trade", "text", True, None),
                        ("count", "number", True, (0, None))],
        "equipment_table": [("eq_type", "text", True, None),
                            ("qty", "number", True, (0, None)),
                            ("hours", "number", False, (0, 24)),
                            ("status", "enum", False,
                             list(M.EQUIPMENT_STATUS))],
        "work_fronts": [("area", "text", True, None),
                        ("activity", "text", False, None),
                        ("progress_pct", "number", False, (0, 100))],
    },
}


def _validate_table(table: str, spec: list, raw, errors: list):
    """Validate one list-of-dicts workflow table. Returns cleaned list."""
    if not isinstance(raw, list):
        errors.append(f"الحقل {table} يجب أن يكون قائمة.")
        return None
    if len(raw) > M.MAX_TABLE_ROWS:
        errors.append(f"الحقل {table} يتجاوز الحد ({M.MAX_TABLE_ROWS} صفاً).")
        return None
    cleaned_rows = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            errors.append(f"الصف {i + 1} في {table} غير صالح.")
            return None
        cleaned_row = {}
        for key, typ, required, rule in spec:
            val = row.get(key)
            if val in ("", None):
                if required:
                    errors.append(f"الصف {i + 1} في {table}: {key} مطلوب.")
                    return None
                continue
            if typ == "text":
                if not isinstance(val, str):
                    errors.append(f"الصف {i + 1} في {table}: {key} نصي.")
                    return None
                cleaned_row[key] = val.strip()[:200]
            elif typ == "number":
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    errors.append(f"الصف {i + 1} في {table}: {key} رقمي.")
                    return None
                lo, hi = rule
                if (lo is not None and v < lo) or (hi is not None and v > hi):
                    errors.append(f"الصف {i + 1} في {table}: {key} خارج النطاق.")
                    return None
                cleaned_row[key] = v
            elif typ == "enum":
                if str(val).strip() not in rule:
                    errors.append(f"الصف {i + 1} في {table}: {key} غير صالح.")
                    return None
                cleaned_row[key] = str(val).strip()
        cleaned_rows.append(cleaned_row)
    return cleaned_rows


def _payload():
    if request.is_json:
        return dict(request.get_json(silent=True) or {})
    return dict(request.form or {})


def _parse_date(raw, field, errors):
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if raw in ("", None):
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"التاريخ غير صالح في حقل {field} (YYYY-MM-DD).")
        return None


def validate_input(kind: str, data: dict, partial: bool = False):
    """Returns (cleaned, errors). partial=True for updates (all optional)."""
    schema = SCHEMAS[kind]
    errors, cleaned = [], {}
    if not partial:
        for f in schema["required"]:
            if data.get(f) in ("", None):
                errors.append(f"الحقل {f} مطلوب.")
    for f, allowed in schema["enums"].items():
        if f in data and data[f] not in ("", None):
            if str(data[f]).strip() not in allowed:
                errors.append(f"قيمة غير صالحة للحقل {f}.")
            else:
                cleaned[f] = str(data[f]).strip()
    for f, (lo, hi) in schema["numbers"].items():
        if f in data and data[f] not in ("", None):
            try:
                v = float(data[f])
            except (TypeError, ValueError):
                errors.append(f"الحقل {f} يجب أن يكون رقماً.")
                continue
            if lo is not None and v < lo:
                errors.append(f"الحقل {f} يجب أن يكون ≥ {lo}.")
                continue
            if hi is not None and v > hi:
                errors.append(f"الحقل {f} يجب أن يكون ≤ {hi}.")
                continue
            cleaned[f] = v
    for f in schema["dates"]:
        if f in data and data[f] not in ("", None):
            v = _parse_date(data[f], f, errors)
            if v is not None:
                cleaned[f] = v
    # structured workflow tables (DSR labor/equipment/staging)
    for table, spec in TABLE_SPECS.get(kind, {}).items():
        if table in data and data[table] not in ("", None):
            rows = _validate_table(table, spec, data[table], errors)
            if rows is not None:
                cleaned[table] = rows
    # free text passthrough (mass-assignment guarded)
    model_cols = {c.key for c in KIND_MODEL[kind].__table__.columns}
    table_keys = set(TABLE_SPECS.get(kind, {}))
    for k, v in data.items():
        if k in PROTECTED or k in cleaned or k in table_keys \
                or k in schema["enums"] \
                or k in schema["numbers"] or k in schema["dates"]:
            continue
        if k == "project_id":
            try:
                cleaned[k] = int(v)
            except (TypeError, ValueError):
                errors.append("الحقل project_id يجب أن يكون رقم مشروع صالح.")
            continue
        if k in model_cols and isinstance(v, str):
            cleaned[k] = v.strip()
    return cleaned, errors


def _serialize(kind, record):
    from app.ops.versioning import (normalize, is_locked, TRANSITIONS,
                                    WORKFLOW_AR)
    d = record.to_dict()
    _m, _p, name_ar, name_en = M.OPS_MODULES[kind]
    d["module"] = kind
    d["module_ar"] = name_ar
    d["signatory"] = record.signatory_name  # alias: matches archive rows
    d["status_norm"] = normalize(record.status)
    d["status_ar"] = WORKFLOW_AR.get(normalize(record.status),
                                     record.status_ar)
    d["is_locked"] = is_locked(record)
    d["allowed_transitions"] = list(TRANSITIONS.get(normalize(record.status),
                                                    ()))
    project = db.session.get(Project, record.project_id)
    d["project_name"] = project.name if project else ""
    # computed summaries for financial/engineering modules
    if kind == "cost-variances":
        d["computed"] = {"budgeted_total": record.budgeted_total,
                         "actual_total": record.actual_total,
                         "variance": record.variance,
                         "variance_pct": round(record.variance_pct, 2),
                         "reestimated_total": record.reestimated_total}
    elif kind == "progress-billings":
        d["computed"] = {"gross": record.gross, "retention": record.retention,
                         "net_payable": record.net_payable,
                         "cumulative": record.cumulative}
    elif kind == "subcontractor-performances":
        d["computed"] = {"overall": record.overall, "grade": record.grade}
    elif kind == "site-inspections":
        d["computed"] = {"auto_pass": record.computed_pass}
    elif kind == "rfis":
        d["computed"] = {"days_open": record.days_open}
    elif kind == "daily-reports":
        d["computed"] = {"manpower_total": record.manpower_total,
                         "labor_table_total": record.labor_table_total,
                         "equipment_hours_total":
                             record.equipment_hours_total,
                         "fronts_avg_pct": record.fronts_avg_pct}
    elif kind == "variation-orders":
        d["computed"] = {"impact_signed": record.impact_signed}
    elif kind == "safety-reports":
        d["computed"] = {"is_closed": record.is_closed}
    return d


def _resolve_kind(kind):
    if kind not in KIND_MODEL:
        return None, (jsonify({"error": "unknown module"}), 404)
    return KIND_MODEL[kind], None


# ---------------------------------------------------------------- registry
@bp.route("/", methods=["GET"])
@login_required
@permission_required("view_reports")
def registry():
    return jsonify({"modules": [
        {"kind": k, "prefix": p, "name_ar": a, "name_en": e}
        for k, (_m, p, a, e) in M.OPS_MODULES.items()]})


@bp.route("/<kind>/meta", methods=["GET"])
@login_required
@permission_required("view_reports")
def meta(kind):
    model, err = _resolve_kind(kind)
    if err:
        return err
    _m, prefix, name_ar, name_en = M.OPS_MODULES[kind]
    return jsonify({"kind": kind, "prefix": prefix, "name_ar": name_ar,
                    "name_en": name_en, "schema": SCHEMAS[kind],
                    "statuses": list(M.STATUSES)})


# ---------------------------------------------------------------- CRUD
@bp.route("/<kind>", methods=["GET"])
@login_required
@permission_required("view_reports")
def listing(kind):
    model, err = _resolve_kind(kind)
    if err:
        return err
    q = scope_to_tenant(model.query, model, current_user)
    project_id = request.args.get("project_id")
    if project_id:
        q = q.filter_by(project_id=int(project_id)) \
            if str(project_id).isdigit() else q.filter(db.false())
    status = request.args.get("status")
    if status in M.STATUSES:
        q = q.filter_by(status=status)
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    if date_from:
        q = q.filter(model.report_date >= date_from)
    if date_to:
        q = q.filter(model.report_date <= date_to)
    q = q.order_by(model.report_date.desc(), model.id.desc()).limit(500)
    return jsonify({"results": [_serialize(kind, r) for r in q.all()]})


@bp.route("/<kind>", methods=["POST"])
@login_required
@permission_required("create_reports")
def create(kind):
    model, err = _resolve_kind(kind)
    if err:
        return err
    data = _payload()
    cleaned, errors = validate_input(kind, data)
    if errors:
        return jsonify({"error": "validation failed", "details": errors}), 422
    project = tenant_create_guard(current_user, cleaned.get("project_id"))
    cleaned.pop("project_id", None)  # set explicitly below (no dup kwargs)
    record = model(project_id=project.id, user_id=current_user.id,
                   signatory_name=current_user.full_name, **cleaned)
    _m, prefix, _a, _e = M.OPS_MODULES[kind]
    committed = False
    for attempt in range(5):  # serial race retry under UNIQUE constraint
        record.serial = M.next_serial(prefix, model, offset=attempt)
        db.session.add(record)
        try:
            db.session.commit()
            committed = True
            break
        except IntegrityError:
            db.session.rollback()
    if not committed:
        return jsonify({"error": "could not allocate serial"}), 409
    return jsonify(_serialize(kind, record)), 201


@bp.route("/<kind>/<int:obj_id>", methods=["GET"])
@login_required
@permission_required("view_reports")
def detail(kind, obj_id):
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    return jsonify(_serialize(kind, record))


@bp.route("/<kind>/<int:obj_id>", methods=["PUT", "PATCH"])
@login_required
@any_permission_required("edit_own_reports", "edit_all_reports")
def update(kind, obj_id):
    from app.ops.versioning import (is_locked, is_historical, spawn_amendment)
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    if record.user_id != current_user.id and not is_platform_manager(current_user):
        return jsonify({"error": "only the author or a manager may edit"}), 403
    cleaned, errors = validate_input(kind, _payload(), partial=True)
    if errors:
        return jsonify({"error": "validation failed", "details": errors}), 422
    if "project_id" in cleaned and int(cleaned["project_id"]) != record.project_id:
        tenant_create_guard(current_user, cleaned["project_id"])  # 404 if out of scope
    if is_historical(record):
        return jsonify({"error": "historical version is read-only; amend the "
                                 "latest version instead"}), 423
    if is_locked(record):
        # immutable trail: edits spawn a linked amendment draft, history kept
        amendment = spawn_amendment(model, record, current_user, cleaned)
        body = _serialize(kind, amendment)
        body["amended_from"] = record.serial
        return jsonify(body), 201
    for k, v in cleaned.items():
        setattr(record, k, v)
    db.session.commit()
    return jsonify(_serialize(kind, record))


@bp.route("/<kind>/<int:obj_id>", methods=["DELETE"])
@login_required
@any_permission_required("delete_own_reports", "delete_all_reports")
def remove(kind, obj_id):
    from app.ops.versioning import is_locked, is_historical
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    if record.user_id != current_user.id and not is_platform_manager(current_user):
        return jsonify({"error": "only the author or a manager may delete"}), 403
    if is_locked(record) or is_historical(record):
        return jsonify({"error": "locked/historical versions cannot be "
                                 "deleted (legal audit trail)"}), 423
    serial = record.serial
    delete_record_attachments(kind, record.id)  # rows + bytes, same txn
    delete_record_comments(kind, record.id)  # feedback threads go with it
    db.session.delete(record)
    db.session.commit()
    return jsonify({"deleted": serial})


# ---------------------------------------------------------------- workflow
@bp.route("/<kind>/<int:obj_id>/submit", methods=["POST"])
@login_required
@any_permission_required("create_reports", "edit_own_reports")
def submit(kind, obj_id):
    """Draft/rejected -> submitted (pending review). Author or manager."""
    from app.ops.versioning import normalize, can_transition
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    if record.user_id != current_user.id and not is_platform_manager(current_user):
        return jsonify({"error": "only the author or a manager may submit"}), 403
    if not can_transition(record.status, "submitted"):
        return jsonify({"error": "cannot submit from status "
                                 f"'{normalize(record.status)}'"}), 422
    record.status = "submitted"
    db.session.commit()
    return jsonify(_serialize(kind, record))


@bp.route("/<kind>/<int:obj_id>/history", methods=["GET"])
@login_required
@permission_required("view_reports")
def history(kind, obj_id):
    """Full amendment chain for one report, oldest version first."""
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    root = record.root_id or record.id
    chain = model.query.filter(
        db.or_(model.id == root, model.root_id == root)).order_by(
        model.version).all()
    # same-project chain
    return jsonify({"root_id": root,
                    "versions": [_serialize(kind, r) for r in chain]})


@bp.route("/<kind>/<int:obj_id>/approve", methods=["POST"])
@login_required
@permission_required("approve_reports")
@roles_required_json("admin", "superadmin", "project_manager")
def approve(kind, obj_id):
    from app.ops.versioning import apply_decision
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    data = _payload()
    err_msg = apply_decision(record,
                             str(data.get("decision", "")).strip().lower(),
                             current_user,
                             str(data.get("notes", "")).strip())
    if err_msg:
        return jsonify({"error": err_msg}), 422
    return jsonify(_serialize(kind, record))


# ---------------------------------------------------------------- PDF
@bp.route("/<kind>/<int:obj_id>/pdf", methods=["GET"])
@login_required
@permission_required("export_pdf")
def pdf(kind, obj_id):
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    from app.ops.pdf import build_ops_pdf
    from app.models import User
    project = db.session.get(Project, record.project_id)
    reviewer = db.session.get(User, record.reviewed_by_id) \
        if record.reviewed_by_id else None
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf_bytes = build_ops_pdf(
        kind, record, project_name=project.name if project else "",
        reviewer_name=reviewer.full_name if reviewer else "",
        generated_at=stamp)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"inline; filename={record.serial}.pdf"})


# ---------------------------------------------------------------- batch export
@bp.route("/batch", methods=["GET"])
@login_required
@permission_required("view_analytics")
@roles_required_json("admin", "superadmin", "project_manager")
def batch_form():
    """Minimal UI: pick project + date range (+modules) → PDF download."""
    from app.models import Project as P
    if is_platform_manager(current_user):
        projects = P.query.order_by(P.name).all()
    else:  # pragma: no cover
        projects = []
    from flask import render_template
    return render_template("ops/batch.html", projects=projects,
                           modules=M.OPS_MODULES)


@bp.route("/batch-export", methods=["POST"])
@login_required
@permission_required("view_analytics")
@roles_required_json("admin", "superadmin", "project_manager")
def batch_export():
    """Aggregate a date range into one indexed multi-report PDF."""
    from app.ops.batch import collect_batch, build_batch_pdf
    data = _payload()
    project_id = (data.get("project_id") or "").strip() \
        if isinstance(data.get("project_id"), str) else data.get("project_id")
    try:
        project_id = int(project_id) if project_id not in ("", None) else None
    except (TypeError, ValueError):
        return jsonify({"error": "project_id must be an integer"}), 422
    date_from = (data.get("from") or "").strip() or None
    date_to = (data.get("to") or "").strip() or None
    if request.is_json:
        kinds = data.get("types") or data.get("type")
        if isinstance(kinds, str):
            kinds = [kinds]
    else:  # repeated checkbox keys: getlist keeps them all
        kinds = request.form.getlist("types") or request.form.getlist("type")
    kinds = [k for k in (kinds or []) if k in KIND_MODEL] or None
    if project_id is not None:
        tenant_create_guard(current_user, project_id)  # 404 if out of scope
    records = collect_batch(KIND_MODEL, current_user, project_id,
                            date_from, date_to, kinds)
    project = db.session.get(Project, project_id) if project_id else None
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf_bytes = build_batch_pdf(
        records, project_name=project.name if project else "",
        date_from=date_from or "", date_to=date_to or "",
        generated_by=current_user.full_name, generated_at=stamp)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition":
                             "inline; filename=azadexa-batch.pdf"})


# ---------------------------------------------------------------- attachments
ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif",
                "image/webp", "application/pdf"}
MAX_UPLOAD_BYTES = 4 * 1024 * 1024

#: sub-directory of UPLOAD_FOLDER holding ops evidence files
ATTACH_DIR = "ops"


def _safe_filename(name: str) -> str:
    """Strip directories / control chars; keep unicode word chars (Arabic OK).

    Returns "" when nothing usable remains (caller must reject with 400).
    """
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE).strip("._")
    if not base:
        return ""
    if "." in base:
        stem, _dot, ext = base.rpartition(".")
        ext = re.sub(r"[^\w]+", "", ext, flags=re.UNICODE)[:10]
        stem = (stem or "file")[:40]
        return f"{stem}.{ext}" if ext else stem
    return base[:40]


def _abs_path(storage_key: str) -> str:
    """Absolute path for a storage key; raises ValueError on traversal."""
    base = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    abs_path = os.path.abspath(os.path.join(base, storage_key))
    if abs_path != base and not abs_path.startswith(base + os.sep):
        raise ValueError("storage key escapes upload folder")
    return abs_path


def _store_file(kind: str, record_id: int, filename: str, buf: bytes) -> str:
    """Persist bytes under UPLOAD_FOLDER/ops/<kind>/<id>/; return key.

    Key layout keeps the DB column (String 120) safe: short prefix +
    12-hex unique token + truncated sanitized filename.
    """
    rel = os.path.join(ATTACH_DIR, kind, str(record_id),
                       f"{uuid.uuid4().hex[:12]}_{filename}")
    storage_key = rel.replace(os.sep, "/")
    abs_path = _abs_path(storage_key)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(buf)
    return storage_key


def _delete_file(storage_key: str) -> bool:
    """Best-effort unlink; never raises (missing file is not an error)."""
    try:
        os.remove(_abs_path(storage_key))
        return True
    except (OSError, ValueError):
        return False


def delete_record_attachments(kind: str, record_id: int) -> int:
    """Delete every attachment row + bytes for one record. Returns count."""
    atts = Attachment.query.filter_by(
        record_kind=kind, record_id=record_id).all()
    for a in atts:
        _delete_file(a.storage_key)
        db.session.delete(a)
    return len(atts)


def delete_record_comments(kind: str, record_id: int) -> int:
    """Delete every feedback comment for one record. Returns count."""
    rows = M.OpsRecordComment.query.filter_by(
        record_kind=kind, record_id=record_id).all()
    for c in rows:
        db.session.delete(c)
    return len(rows)


def cleanup_orphaned_attachments(dry_run: bool = False) -> dict:
    """Remove attachment rows whose record is gone + stray files on disk.

    * orphan_rows: DB rows pointing at a missing (kind, record_id), or an
      unknown kind — rows (and their files) are deleted unless dry_run.
    * missing_files: rows whose bytes are absent from disk (reported only).
    * orphan_files: files under UPLOAD_FOLDER/ops with no DB row — deleted
      unless dry_run. Files outside the ops prefix (e.g. avatars) untouched.
    """
    stats = {"orphan_rows": 0, "missing_files": 0, "orphan_files": 0}
    known_keys = set()
    for att in Attachment.query.all():
        known_keys.add(att.storage_key)
        model = KIND_MODEL.get(att.record_kind)
        target = db.session.get(model, att.record_id) \
            if model is not None else None
        if target is None:
            stats["orphan_rows"] += 1
            if not dry_run:
                _delete_file(att.storage_key)
                db.session.delete(att)
            continue
        try:
            present = os.path.isfile(_abs_path(att.storage_key))
        except ValueError:
            present = False
        if not present:
            stats["missing_files"] += 1
    if not dry_run:
        db.session.commit()

    ops_root = os.path.join(
        os.path.abspath(current_app.config["UPLOAD_FOLDER"]), ATTACH_DIR)
    if os.path.isdir(ops_root):
        for root, _dirs, files in os.walk(ops_root):
            for name in files:
                abs_path = os.path.join(root, name)
                rel = os.path.relpath(
                    abs_path,
                    os.path.abspath(current_app.config["UPLOAD_FOLDER"]))
                key = rel.replace(os.sep, "/")
                if key not in known_keys:
                    stats["orphan_files"] += 1
                    if not dry_run:
                        try:
                            os.remove(abs_path)
                        except OSError:
                            pass
    # prune now-empty record directories (tidy only, best-effort)
    if not dry_run and os.path.isdir(ops_root):
        for root, dirs, files in os.walk(ops_root, topdown=False):
            if not dirs and not files:
                try:
                    os.rmdir(root)
                except OSError:
                    pass
    return stats


@bp.route("/<kind>/<int:obj_id>/attachments", methods=["GET"])
@login_required
def attachment_list(kind, obj_id):
    model, err = _resolve_kind(kind)
    if err:
        return err
    get_object_or_404_tenant(model, obj_id, current_user)
    atts = Attachment.query.filter_by(
        record_kind=kind, record_id=obj_id).order_by(
            Attachment.created_at.desc()).all()
    return jsonify({"attachments": [
        {"id": a.id, "filename": a.filename, "mime_type": a.mime_type,
         "byte_size": a.byte_size,
         "created_at": a.created_at.isoformat() if a.created_at else "",
         "storage_key": a.storage_key}
        for a in atts]})


@bp.route("/<kind>/<int:obj_id>/attachments", methods=["POST"])
@login_required
def attachment_upload(kind, obj_id):
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    if "file" not in request.files:
        return jsonify({"error": "no file part"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "empty filename"}), 400
    filename = _safe_filename(file.filename)
    if not filename:
        return jsonify({"error": "invalid filename"}), 400
    mime = (file.mimetype or "application/octet-stream").lower()
    if mime not in ALLOWED_MIME:
        return jsonify({"error": f"unsupported type: {mime}"}), 415
    buf = file.read()
    if len(buf) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "file exceeds 4 MB limit"}), 413
    try:
        storage_key = _store_file(kind, record.id, filename, buf)
    except (OSError, ValueError):
        current_app.logger.exception("attachment write failed")
        return jsonify({"error": "storage failure"}), 500
    att = Attachment(record_kind=kind, record_id=record.id,
                     project_id=record.project_id,
                     filename=filename, storage_key=storage_key,
                     mime_type=mime, byte_size=len(buf),
                     uploaded_by=current_user.id)
    db.session.add(att)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        _delete_file(storage_key)  # no orphan bytes on DB failure
        return jsonify({"error": "could not save attachment"}), 500
    return jsonify({"id": att.id, "filename": att.filename,
                    "storage_key": att.storage_key,
                    "mime_type": att.mime_type,
                    "byte_size": att.byte_size}), 201


@bp.route("/<kind>/<int:obj_id>/attachments/<int:att_id>",
          methods=["DELETE"])
@login_required
def attachment_delete(kind, obj_id, att_id):
    model, err = _resolve_kind(kind)
    if err:
        return err
    get_object_or_404_tenant(model, obj_id, current_user)
    att = db.session.get(Attachment, att_id)
    if att is None or att.record_kind != kind or att.record_id != obj_id:
        return jsonify({"error": "not found"}), 404
    if att.uploaded_by != current_user.id and not is_platform_manager(
            current_user):
        return jsonify({"error": "only author or manager may delete"}), 403
    filename = att.filename
    storage_key = att.storage_key
    db.session.delete(att)
    db.session.commit()
    _delete_file(storage_key)  # best-effort; missing bytes are fine
    return jsonify({"deleted": filename})


@bp.route("/<kind>/<int:obj_id>/attachments/<int:att_id>/download",
          methods=["GET"])
@login_required
def attachment_download(kind, obj_id, att_id):
    """Stream the stored bytes (tenant-scoped, correct MIME)."""
    model, err = _resolve_kind(kind)
    if err:
        return err
    get_object_or_404_tenant(model, obj_id, current_user)
    att = db.session.get(Attachment, att_id)
    if att is None or att.record_kind != kind or att.record_id != obj_id:
        return jsonify({"error": "not found"}), 404
    try:
        abs_path = _abs_path(att.storage_key)
    except ValueError:
        return jsonify({"error": "invalid storage key"}), 500
    if not os.path.isfile(abs_path):
        return jsonify({"error": "file missing from storage"}), 404
    return send_file(abs_path, mimetype=att.mime_type,
                     as_attachment=True, download_name=att.filename)


# ---------------------------------------------------------------- feedback
@bp.route("/<kind>/<int:obj_id>/comments", methods=["GET"])
@login_required
@permission_required("view_reports")
def comment_list(kind, obj_id):
    """Dual-party thread (contractor ↔ consultant), oldest first."""
    model, err = _resolve_kind(kind)
    if err:
        return err
    get_object_or_404_tenant(model, obj_id, current_user)
    rows = M.OpsRecordComment.query.filter_by(
        record_kind=kind, record_id=obj_id).order_by(
            M.OpsRecordComment.created_at.asc(),
            M.OpsRecordComment.id.asc()).limit(200).all()
    return jsonify({"comments": [c.to_dict() for c in rows]})


@bp.route("/<kind>/<int:obj_id>/comments", methods=["POST"])
@login_required
@any_permission_required("create_reports", "edit_own_reports",
                         "approve_reports")
def comment_create(kind, obj_id):
    """Post feedback on any status (incl. approved — review notes live here)."""
    model, err = _resolve_kind(kind)
    if err:
        return err
    record = get_object_or_404_tenant(model, obj_id, current_user)
    body = str((_payload().get("body") or "")).strip()
    if not body:
        return jsonify({"error": "validation failed",
                        "details": ["نص التعليق مطلوب."]}), 422
    if len(body) > M.MAX_COMMENT_LEN:
        return jsonify({"error": "validation failed",
                        "details": [f"التعليق يتجاوز {M.MAX_COMMENT_LEN} حرف."]}), 422
    cmt = M.OpsRecordComment(
        record_kind=kind, record_id=record.id,
        project_id=record.project_id, author_id=current_user.id,
        author_name=current_user.full_name,
        author_role=getattr(current_user, "role", ""), body=body)
    db.session.add(cmt)
    db.session.commit()
    return jsonify(cmt.to_dict()), 201


@bp.route("/<kind>/<int:obj_id>/comments/<int:cmt_id>", methods=["DELETE"])
@login_required
def comment_delete(kind, obj_id, cmt_id):
    model, err = _resolve_kind(kind)
    if err:
        return err
    get_object_or_404_tenant(model, obj_id, current_user)
    cmt = db.session.get(M.OpsRecordComment, cmt_id)
    if cmt is None or cmt.record_kind != kind or cmt.record_id != obj_id:
        return jsonify({"error": "not found"}), 404
    if cmt.author_id != current_user.id and not is_platform_manager(
            current_user):
        return jsonify({"error": "only author or manager may delete"}), 403
    db.session.delete(cmt)
    db.session.commit()
    return jsonify({"deleted": cmt_id})


# ---------------------------------------------------------------- archive API
@bp.route("/api/archive", methods=["GET"])
@login_required
def archive():
    """Advanced filtering + multi-parameter sorting across all nine modules.

    Params: type, project_id, status, from, to, q, sort(date|serial|status|
    project|type), order(asc|desc), page, per_page(≤100).
    """
    kind_filter = request.args.get("type", "").strip()
    kinds = [kind_filter] if kind_filter in KIND_MODEL else list(KIND_MODEL)
    project_id = request.args.get("project_id", "").strip()
    status = request.args.get("status", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date").strip()
    order = request.args.get("order", "desc").strip().lower()
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    try:
        per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    except ValueError:
        per_page = 20

    rows = []
    for kind in kinds:
        model = KIND_MODEL[kind]
        query = scope_to_tenant(model.query, model, current_user)
        if project_id:
            query = query.filter_by(project_id=int(project_id)) \
                if project_id.isdigit() else query.filter(db.false())
        if status in M.STATUSES:
            query = query.filter_by(status=status)
        if date_from:
            query = query.filter(model.report_date >= date_from)
        if date_to:
            query = query.filter(model.report_date <= date_to)
        if q:
            like = f"%{q}%"
            query = query.filter(model.serial.ilike(like))
        for r in query.all():
            _m, _p, name_ar, _e = M.OPS_MODULES[kind]
            project = db.session.get(Project, r.project_id)
            rows.append({
                "type": kind, "type_ar": name_ar, "id": r.id,
                "serial": r.serial, "project_id": r.project_id,
                "project": project.name if project else "",
                "date": r.report_date.isoformat() if r.report_date else "",
                "status": r.status, "status_ar": r.status_ar,
                "signatory": r.signatory_name})

    reverse = order != "asc"
    sort_key = {"serial": lambda x: x["serial"],
                "status": lambda x: (x["status"], x["date"]),
                "project": lambda x: (x["project"], x["date"]),
                "type": lambda x: (x["type"], x["date"])}.get(
        sort, lambda x: (x["date"], x["serial"]))
    rows.sort(key=sort_key, reverse=reverse)
    total = len(rows)
    start = (page - 1) * per_page
    return jsonify({"total": total, "page": page, "per_page": per_page,
                    "results": rows[start:start + per_page]})
