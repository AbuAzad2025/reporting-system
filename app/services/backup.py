"""
Backup/Restore Service for Azadexa Cloud.

Core serialization/deserialization of all application data into a portable
ZIP archive format. Platform-level backup exports the entire database schema
data; project-level backup exports only one tenant (project) scope.

Format:
    backup-platform-<timestamp>.zip
    backup-project-<project_id>-<timestamp>.zip

Structure:
    metadata.json
    users.json
    projects.json
    project_members.json
    report_templates.json
    dynamic_fields.json
    report_submissions.json
    legacy_reports.json
    ops_records/
        site_inspections.json
        material_submittals.json
        rfis.json
        cost_variances.json
        progress_billings.json
        subcontractor_performances.json
        daily_site_reports.json
        variation_orders.json
        safety_reports.json
    attachments/
        <relative_path_to_file>
"""
import io
import json
import zipfile
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.extensions import db
from app.models import (Project, Report, ReportSubmission, ReportTemplate,
                        DynamicField, User)
from app.ops.models import Attachment, ProjectMember
from app.ops.models import (SiteInspection, MaterialSubmittal, RFI,
                            CostVariance, ProgressBilling,
                            SubcontractorPerformance, DailySiteReport,
                            VariationOrder, SafetyReport)


OPS_MODELS = {
    "site_inspections": SiteInspection,
    "material_submittals": MaterialSubmittal,
    "rfis": RFI,
    "cost_variances": CostVariance,
    "progress_billings": ProgressBilling,
    "subcontractor_performances": SubcontractorPerformance,
    "daily_site_reports": DailySiteReport,
    "variation_orders": VariationOrder,
    "safety_reports": SafetyReport,
}

BACKUP_VERSION = "1.0"


def _json_default(value: Any) -> str:
    """JSON serializer for non-serializable values (dates/datetimes)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _model_to_dict(model: Any) -> Dict[str, Any]:
    """Convert a SQLAlchemy model instance to a JSON-serializable dict."""
    data = {}
    for col in model.__table__.columns:
        value = getattr(model, col.name)
        if isinstance(value, (datetime, date)):
            data[col.name] = value.isoformat()
        else:
            data[col.name] = value
    return data


def _dict_to_model(model_cls: Any, data: Dict[str, Any]) -> Any:
    """Create a model instance from a dict (skip id to avoid conflicts)."""
    payload = {k: v for k, v in data.items() if k != "id"}
    return model_cls(**payload)


def _query_all(model_cls: Any,
               project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Serialize all rows of a model, optionally scoped to a project."""
    query = model_cls.query
    if project_id is not None:
        if hasattr(model_cls, "project_id"):
            query = query.filter_by(project_id=project_id)
        elif hasattr(model_cls, "project"):
            query = query.filter(model_cls.project.has(id=project_id))
        else:
            return []
    return [_model_to_dict(row) for row in query.all()]


def _write_json(buf: io.BytesIO, archive: zipfile.ZipFile,
                name: str, data: Any) -> None:
    """Write a JSON file into the ZIP archive."""
    payload = json.dumps(data, ensure_ascii=False, default=_json_default,
                         indent=2).encode("utf-8")
    archive.writestr(name, payload)


def _collect_attachments(project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Collect attachment metadata (paths) for the archive."""
    from app.ops.models import Attachment
    query = Attachment.query
    if project_id is not None:
        query = query.filter_by(project_id=project_id)
    return [_model_to_dict(row) for row in query.order_by(Attachment.id).all()]


def build_backup(project_id: Optional[int] = None) -> bytes:
    """
    Build a ZIP backup archive.

    :param project_id: None = platform-wide backup; int = project-scoped backup.
    :returns: ZIP archive bytes.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        scope = "platform" if project_id is None else "project"
        meta = {
            "version": BACKUP_VERSION,
            "scope": scope,
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "generator": "Azadexa Cloud Backup Service",
        }
        _write_json(buf, archive, "metadata.json", meta)

        if scope == "platform":
            _write_json(buf, archive, "users.json", _query_all(User))
            _write_json(buf, archive, "projects.json", _query_all(Project))
            _write_json(buf, archive, "project_members.json",
                        _query_all(ProjectMember))
            _write_json(buf, archive, "report_templates.json",
                        _query_all(ReportTemplate))
            _write_json(buf, archive, "dynamic_fields.json",
                        _query_all(DynamicField))
            _write_json(buf, archive, "report_submissions.json",
                        _query_all(ReportSubmission))
            _write_json(buf, archive, "legacy_reports.json",
                        _query_all(Report))
            for filename, model_cls in OPS_MODELS.items():
                _write_json(buf, archive, f"ops_records/{filename}.json",
                            _query_all(model_cls))
        else:
            _write_json(buf, archive, "project.json",
                        _query_all(Project, project_id))
            _write_json(buf, archive, "project_members.json",
                        _query_all(ProjectMember, project_id))
            _write_json(buf, archive, "report_templates.json",
                        _query_all(ReportTemplate))
            _write_json(buf, archive, "dynamic_fields.json",
                        _query_all(DynamicField))
            _write_json(buf, archive, "report_submissions.json",
                        _query_all(ReportSubmission, project_id))
            _write_json(buf, archive, "legacy_reports.json",
                        _query_all(Report, project_id))
            for filename, model_cls in OPS_MODELS.items():
                _write_json(buf, archive, f"ops_records/{filename}.json",
                            _query_all(model_cls, project_id))

        # Attachment metadata (files are stored separately in the archive)
        _write_json(buf, archive, "attachments.json",
                    _collect_attachments(project_id))

    return buf.getvalue()


def _load_json(archive: zipfile.ZipFile, name: str) -> List[Dict[str, Any]]:
    """Load a JSON list from the archive."""
    try:
        payload = archive.read(name)
    except KeyError:
        return []
    return json.loads(payload.decode("utf-8"))


_FK_MAP = (("project_id", "projects"),
           ("user_id", "users"),
           ("template_id", "report_templates"),
           ("created_by_id", "users"),
           ("reviewed_by_id", "users"),
           ("uploaded_by", "users"))


def _parse_date(value: Any) -> Optional[date]:
    """Coerce an ISO date/datetime string back into a ``date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Coerce an ISO datetime string back into a naive ``datetime``."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            day = _parse_date(raw)
            return datetime(day.year, day.month, day.day) if day else None
        return parsed.replace(tzinfo=None)
    return None


def _coerce_row(model_cls: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Restore column values to the Python types the DB driver expects.

    JSON round-trips turn DATE/DATETIME columns into strings, which both
    SQLite and PostgreSQL reject on bind, so an export could never be
    re-imported without this coercion.
    """
    from sqlalchemy import Date as SADate, DateTime as SADateTime
    out: Dict[str, Any] = {}
    for col in model_cls.__table__.columns:
        if col.name not in payload:
            continue
        value = payload[col.name]
        if isinstance(col.type, SADateTime):
            value = _parse_datetime(value)
        elif isinstance(col.type, SADate):
            value = _parse_date(value)
        out[col.name] = value
    return out


def _remap_fks(payload: Dict[str, Any],
               id_map: Dict[str, Dict[int, int]]) -> Dict[str, Any]:
    """Point foreign keys at the ids the restore actually produced."""
    out = dict(payload)
    for fk_col, target_key in _FK_MAP:
        if out.get(fk_col) is not None:
            out[fk_col] = id_map.get(target_key, {}).get(
                out[fk_col], out[fk_col])
    return out


def _scoped_rows(rows: Iterable[Dict[str, Any]], project_id: Optional[int],
                 project_name: str = "") -> List[Dict[str, Any]]:
    """Keep only rows that belong to the target project (tenant isolation).

    Ops records and submissions carry ``project_id``; legacy reports are only
    linked by ``project_name``.
    """
    if project_id is None:
        return list(rows)
    kept = []
    for row in rows:
        if "project_id" in row:
            value = row.get("project_id")
            if value is not None and str(value) == str(project_id):
                kept.append(row)
        elif "project_name" in row:
            if project_name and row.get("project_name") == project_name:
                kept.append(row)
        else:
            kept.append(row)
    return kept


_NATURAL_KEYS = {
    ProjectMember: ("project_id", "user_id"),
    Attachment: ("record_kind", "record_id", "storage_key"),
}


def _insert_row(model_cls: Any, row: Dict[str, Any],
                id_map: Dict[str, Dict[int, int]], key: str) -> Optional[int]:
    """Insert one archived row, skipping rows already present (idempotent)."""
    old_id = row.get("id")
    columns = {c.name for c in model_cls.__table__.columns}
    payload_in = {k: v for k, v in row.items() if k in columns and k != "id"}
    existing = None
    if "serial" in columns and row.get("serial"):
        existing = model_cls.query.filter_by(serial=row["serial"]).first()
    else:
        natural = _NATURAL_KEYS.get(model_cls)
        if natural and all(row.get(f) is not None for f in natural):
            existing = model_cls.query.filter_by(
                **{f: row[f] for f in natural}).first()
    if existing is not None:
        if old_id is not None:
            id_map.setdefault(key, {})[old_id] = existing.id
        return existing.id
    payload = _coerce_row(model_cls, _remap_fks(payload_in, id_map))
    obj = model_cls(**payload)
    db.session.add(obj)
    db.session.flush()
    if old_id is not None:
        id_map.setdefault(key, {})[old_id] = obj.id
    return obj.id


def _restore_shared(model_cls: Any, rows: List[Dict[str, Any]],
                    match_fields: tuple, id_map: Dict[str, Dict[int, int]],
                    key: str) -> int:
    """Restore rows of a shared table by natural key instead of blind insert.

    Templates and dynamic fields are platform-wide, so a project-scoped
    archive re-inserting them would violate the unique key; map onto the
    existing rows instead.
    """
    for row in rows:
        old_id = row.get("id")
        payload = _remap_fks({k: v for k, v in row.items() if k != "id"},
                             id_map)
        criteria = {f: payload.get(f) for f in match_fields}
        obj = model_cls.query.filter_by(**criteria).first()
        if obj is None:
            obj = model_cls(**_coerce_row(model_cls, payload))
            db.session.add(obj)
            db.session.flush()
        if old_id is not None:
            id_map.setdefault(key, {})[old_id] = obj.id
    return len(rows)


def _purge_project(project_id: int, project_name: str = "") -> None:
    """Delete every tenant-owned row of a project (children first)."""
    Attachment.query.filter_by(project_id=project_id).delete(
        synchronize_session=False)
    for model_cls in OPS_MODELS.values():
        model_cls.query.filter_by(project_id=project_id).delete(
            synchronize_session=False)
    ReportSubmission.query.filter_by(project_id=project_id).delete(
        synchronize_session=False)
    if project_name:
        Report.query.filter_by(project_name=project_name).delete(
            synchronize_session=False)
    ProjectMember.query.filter_by(project_id=project_id).delete(
        synchronize_session=False)
    db.session.flush()


def restore_backup(data: bytes, project_id: Optional[int] = None,
                   replace: bool = False) -> Dict[str, int]:
    """Restore a ZIP backup archive into the database.

    Atomic: the whole restore runs in one transaction, and any failure rolls
    the session back and re-raises, so a bad archive can never leave the
    database half-written or the session unusable.
    """
    counts: Dict[str, int] = {}
    id_map: Dict[str, Dict[int, int]] = {}
    archive_bytes = io.BytesIO(data)
    try:
        with zipfile.ZipFile(archive_bytes, "r") as archive:
            meta = json.loads(archive.read("metadata.json").decode("utf-8"))
            if meta.get("version") != BACKUP_VERSION:
                raise ValueError("Backup version mismatch.")
            scope = meta.get("scope")
            target_name = ""
            if scope == "project" and project_id is None:
                raise ValueError(
                    "Project-scoped archive requires a target project.")
            if scope == "platform" and project_id is not None:
                raise ValueError(
                    "Platform archive cannot be restored into a project.")

            if scope == "platform":
                users = _load_json(archive, "users.json")
                counts["users"] = _restore_shared(
                    User, users, ("username",), id_map, "users")
                projects = _load_json(archive, "projects.json")
                counts["projects"] = _restore_shared(
                    Project, projects, ("name",), id_map, "projects")
            else:
                target = db.session.get(Project, project_id)
                if target is None:
                    raise ValueError("Target project not found.")
                project_rows = _load_json(archive, "project.json")
                for row in project_rows:
                    for k, v in row.items():
                        if k != "id":
                            setattr(target, k, _coerce_row(Project, {k: v})[k])
                db.session.flush()
                counts["projects"] = len(project_rows)
                id_map["projects"] = {row.get("id"): target.id
                                      for row in project_rows}
                target_name = target.name
                if replace:
                    _purge_project(project_id, target_name)

            members = _scoped_rows(_load_json(archive, "project_members.json"),
                                   project_id)
            counts["project_members"] = len(members)
            for row in members:
                _insert_row(ProjectMember, row, id_map, "project_members")

            templates = _load_json(archive, "report_templates.json")
            counts["report_templates"] = _restore_shared(
                ReportTemplate, templates, ("key",), id_map, "report_templates")

            fields = _load_json(archive, "dynamic_fields.json")
            counts["dynamic_fields"] = _restore_shared(
                DynamicField, fields, ("template_id", "field_key"), id_map,
                "dynamic_fields")

            submissions = _scoped_rows(
                _load_json(archive, "report_submissions.json"), project_id)
            counts["report_submissions"] = len(submissions)
            for row in submissions:
                _insert_row(ReportSubmission, row, id_map,
                            "report_submissions")

            legacy = _scoped_rows(_load_json(archive, "legacy_reports.json"),
                                  project_id, target_name)
            counts["legacy_reports"] = len(legacy)
            for row in legacy:
                _insert_row(Report, row, id_map, "legacy_reports")

            for filename, model_cls in OPS_MODELS.items():
                rows = _scoped_rows(
                    _load_json(archive, f"ops_records/{filename}.json"),
                    project_id)
                for row in rows:
                    _insert_row(model_cls, row, id_map, filename)
                counts[filename] = len(rows)

            attachments = _scoped_rows(
                _load_json(archive, "attachments.json"), project_id)
            restored = 0
            for row in attachments:
                kind = str(row.get("record_kind", "")).replace("-", "_")
                record_id = id_map.get(kind, {}).get(row.get("record_id"))
                if record_id is None:
                    continue
                row = dict(row, record_id=record_id)
                _insert_row(Attachment, row, id_map, "attachments")
                restored += 1
            counts["attachments"] = restored

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return counts


def backup_filename(project_id: Optional[int] = None) -> str:
    """Generate a safe, descriptive backup filename."""
    stamp = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%d-%H%M%S")
    if project_id is None:
        return f"azadexa-platform-{stamp}.zip"
    return f"azadexa-project-{project_id}-{stamp}.zip"


def backup_size(data: bytes) -> int:
    """Return archive size in bytes."""
    return len(data)


def validate_backup(data: bytes) -> Dict[str, Any]:
    """Validate archive integrity and return metadata."""
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"Corrupt archive member: {bad}")
            meta = json.loads(archive.read("metadata.json").decode("utf-8"))
        return {"ok": True, "metadata": meta, "size": len(data)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "size": len(data)}


def export_to_stream(project_id: Optional[int] = None) -> io.BytesIO:
    """Alias for build_backup returning a BytesIO stream."""
    return io.BytesIO(build_backup(project_id))


def import_from_file(path: str, project_id: Optional[int] = None,
                     replace: bool = False) -> Dict[str, int]:
    """Restore a backup from a local file path."""
    with open(path, "rb") as fh:
        return restore_backup(fh.read(), project_id=project_id, replace=replace)


def export_to_file(path: str, project_id: Optional[int] = None) -> str:
    """Write a backup archive to a local file path."""
    data = build_backup(project_id)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


__all__ = [
    "BACKUP_VERSION",
    "build_backup",
    "restore_backup",
    "backup_filename",
    "backup_size",
    "validate_backup",
    "export_to_stream",
    "export_to_file",
    "import_from_file",
]
