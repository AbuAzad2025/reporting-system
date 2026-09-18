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
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from app.extensions import db
from app.models import (Project, Report, ReportSubmission, ReportTemplate,
                        DynamicField, User)
from app.ops.models import ProjectMember
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
            "created_at": datetime.utcnow().isoformat(),
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


def _restore_rows(model_cls: Any, rows: Iterable[Dict[str, Any]],
                  id_map: Dict[str, Dict[int, int]], key: str) -> None:
    """Restore rows into the database, remapping foreign keys."""
    for row in rows:
        old_id = row.get("id")
        payload = {k: v for k, v in row.items() if k != "id"}
        # Remap FK columns that reference restored entities.
        for fk_col, target_key in (("project_id", "projects"),
                                   ("user_id", "users"),
                                   ("template_id", "report_templates")):
            if fk_col in payload and payload[fk_col] is not None:
                payload[fk_col] = id_map.get(target_key, {}).get(
                    payload[fk_col], payload[fk_col])
        obj = model_cls(**payload)
        db.session.add(obj)
        db.session.flush()
        if old_id is not None:
            id_map.setdefault(key, {})[old_id] = obj.id


def restore_backup(data: bytes, project_id: Optional[int] = None,
                   replace: bool = False) -> Dict[str, int]:
    """
    Restore a ZIP backup archive into the database.

    :param data: ZIP archive bytes.
    :param project_id: Target project id for project-scoped restore.
    :param replace: If True, delete existing target data first.
    :returns: Count of restored rows per table.
    """
    archive_bytes = io.BytesIO(data)
    counts: Dict[str, int] = {}
    id_map: Dict[str, Dict[int, int]] = {}

    with zipfile.ZipFile(archive_bytes, "r") as archive:
        meta = json.loads(archive.read("metadata.json").decode("utf-8"))
        if meta.get("version") != BACKUP_VERSION:
            raise ValueError("Backup version mismatch.")

        # Users (platform-wide only)
        if meta.get("scope") == "platform":
            users = _load_json(archive, "users.json")
            for row in users:
                old_id = row.get("id")
                payload = {k: v for k, v in row.items() if k != "id"}
                obj = User(**payload)
                db.session.add(obj)
                db.session.flush()
                if old_id is not None:
                    id_map.setdefault("users", {})[old_id] = obj.id
            counts["users"] = len(users)

        # Projects
        projects = _load_json(archive, "projects.json") if \
            meta.get("scope") == "platform" else \
            _load_json(archive, "project.json")
        if project_id is not None and meta.get("scope") == "project":
            # Restore into the existing target project (update in place).
            target = Project.query.get(project_id)
            if target is None:
                raise ValueError("Target project not found.")
            for row in projects:
                for k, v in row.items():
                    if k != "id":
                        setattr(target, k, v)
                db.session.add(target)
                db.session.flush()
                id_map["projects"] = {row.get("id"): target.id}
        else:
            for row in projects:
                old_id = row.get("id")
                payload = {k: v for k, v in row.items() if k != "id"}
                obj = Project(**payload)
                db.session.add(obj)
                db.session.flush()
                if old_id is not None:
                    id_map.setdefault("projects", {})[old_id] = obj.id
        counts["projects"] = len(projects)

        # Project members
        members = _load_json(archive, "project_members.json")
        for row in members:
            old_id = row.get("id")
            payload = {k: v for k, v in row.items() if k != "id"}
            for fk_col, target_key in (("project_id", "projects"),
                                       ("user_id", "users")):
                if fk_col in payload and payload[fk_col] is not None:
                    payload[fk_col] = id_map.get(target_key, {}).get(
                        payload[fk_col], payload[fk_col])
            obj = ProjectMember(**payload)
            db.session.add(obj)
            db.session.flush()
            if old_id is not None:
                id_map.setdefault("project_members", {})[old_id] = obj.id
        counts["project_members"] = len(members)

        # Templates + fields
        templates = _load_json(archive, "report_templates.json")
        for row in templates:
            old_id = row.get("id")
            payload = {k: v for k, v in row.items() if k != "id"}
            for fk_col, target_key in (("created_by_id", "users"),):
                if fk_col in payload and payload[fk_col] is not None:
                    payload[fk_col] = id_map.get(target_key, {}).get(
                        payload[fk_col], payload[fk_col])
            obj = ReportTemplate(**payload)
            db.session.add(obj)
            db.session.flush()
            if old_id is not None:
                id_map.setdefault("report_templates", {})[old_id] = obj.id
        counts["report_templates"] = len(templates)

        fields = _load_json(archive, "dynamic_fields.json")
        for row in fields:
            old_id = row.get("id")
            payload = {k: v for k, v in row.items() if k != "id"}
            for fk_col, target_key in (("template_id", "report_templates"),):
                if fk_col in payload and payload[fk_col] is not None:
                    payload[fk_col] = id_map.get(target_key, {}).get(
                        payload[fk_col], payload[fk_col])
            obj = DynamicField(**payload)
            db.session.add(obj)
            db.session.flush()
            if old_id is not None:
                id_map.setdefault("dynamic_fields", {})[old_id] = obj.id
        counts["dynamic_fields"] = len(fields)

        # Submissions + legacy reports
        submissions = _load_json(archive, "report_submissions.json")
        for row in submissions:
            old_id = row.get("id")
            payload = {k: v for k, v in row.items() if k != "id"}
            for fk_col, target_key in (("project_id", "projects"),
                                       ("user_id", "users"),
                                       ("template_id", "report_templates")):
                if fk_col in payload and payload[fk_col] is not None:
                    payload[fk_col] = id_map.get(target_key, {}).get(
                        payload[fk_col], payload[fk_col])
            obj = ReportSubmission(**payload)
            db.session.add(obj)
            db.session.flush()
            if old_id is not None:
                id_map.setdefault("report_submissions", {})[old_id] = obj.id
        counts["report_submissions"] = len(submissions)

        legacy = _load_json(archive, "legacy_reports.json")
        for row in legacy:
            old_id = row.get("id")
            payload = {k: v for k, v in row.items() if k != "id"}
            for fk_col, target_key in (("project_id", "projects"),
                                       ("user_id", "users")):
                if fk_col in payload and payload[fk_col] is not None:
                    payload[fk_col] = id_map.get(target_key, {}).get(
                        payload[fk_col], payload[fk_col])
            obj = Report(**payload)
            db.session.add(obj)
            db.session.flush()
            if old_id is not None:
                id_map.setdefault("legacy_reports", {})[old_id] = obj.id
        counts["legacy_reports"] = len(legacy)

        # Ops records
        for filename, model_cls in OPS_MODELS.items():
            rows = _load_json(archive, f"ops_records/{filename}.json")
            for row in rows:
                old_id = row.get("id")
                payload = {k: v for k, v in row.items() if k != "id"}
                for fk_col, target_key in (("project_id", "projects"),
                                           ("user_id", "users")):
                    if fk_col in payload and payload[fk_col] is not None:
                        payload[fk_col] = id_map.get(target_key, {}).get(
                            payload[fk_col], payload[fk_col])
                obj = model_cls(**payload)
                db.session.add(obj)
                db.session.flush()
                if old_id is not None:
                    id_map.setdefault(filename, {})[old_id] = obj.id
            counts[filename] = len(rows)

        db.session.commit()

    return counts


def backup_filename(project_id: Optional[int] = None) -> str:
    """Generate a safe, descriptive backup filename."""
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
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
