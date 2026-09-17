"""Immutable audit trail: versioning + a tiny explicit state machine.

Statuses: draft -> submitted (-> pending-review) -> approved (locked).
Rejected rows return to draft; approving an amendment supersedes the prior
approved version (marked amended, never deleted or overwritten).

Locked (approved) rows are read-only: PUT auto-spawns a linked amendment
draft (version+1) instead of mutating history; DELETE on locked rows is 423.
Legacy 'pending' rows are treated as 'submitted' everywhere.
"""
from datetime import datetime

DRAFT = "draft"
SUBMITTED = "submitted"
APPROVED = "approved"
REJECTED = "rejected"
AMENDED = "amended"
PENDING_LEGACY = "pending"  # historic alias of SUBMITTED

WORKFLOW_AR = {
    DRAFT: "مسودة",
    SUBMITTED: "قيد المراجعة",
    PENDING_LEGACY: "قيد المراجعة",
    APPROVED: "معتمد / مغلق",
    REJECTED: "مرفوض",
    AMENDED: "معدّل (نسخة تاريخية)",
}

#: allowed transitions (normalized statuses)
TRANSITIONS = {
    DRAFT: (SUBMITTED,),
    SUBMITTED: (APPROVED, REJECTED, DRAFT),
    APPROVED: (),
    REJECTED: (DRAFT, SUBMITTED),
    AMENDED: (),
}


def normalize(status: str) -> str:
    """Map legacy 'pending' onto the canonical machine."""
    return SUBMITTED if status == PENDING_LEGACY else (status or DRAFT)


def can_transition(fr: str, to: str) -> bool:
    return normalize(to) in TRANSITIONS.get(normalize(fr), ())


def is_locked(record) -> bool:
    return normalize(record.status) == APPROVED


def is_historical(record) -> bool:
    return normalize(record.status) == AMENDED


def spawn_amendment(model, record, author, updates: dict):
    """Create version N+1 draft linked to `record`; never touches history.

    The new row copies every data column, bumps version, chains
    root/supersedes, snapshots the amending author's quad-name, and applies
    `updates` (already validated + tenant-checked by the caller).

    `author` may be a User object or a raw user id (int); ints are resolved
    to the corresponding user for the signatory snapshot.
    """
    from app.extensions import db
    from app.ops.models import next_serial, OPS_MODULES

    if isinstance(author, int):
        from app.models import User
        _u = db.session.get(User, author)
        if _u is None:
            raise ValueError(f"unknown author user_id={author}")
        author = _u

    prefix = next((p for (_m, p, _a, _e) in OPS_MODULES.values()
                   if _m == model.__name__), "OPS")
    skip = {"id", "serial", "status", "version", "root_id", "supersedes_id",
            "reviewed_by_id", "reviewed_at", "review_notes",
            "created_at", "updated_at", "signatory_name", "user_id"}
    data = {c.key: getattr(record, c.key)
            for c in record.__table__.columns if c.key not in skip}
    data.update(updates)
    for attempt in range(5):
        amendment = model(
            project_id=data.pop("project_id", record.project_id),
            user_id=author.id, signatory_name=author.full_name,
            status=DRAFT, version=(record.version or 1) + 1,
            root_id=record.root_id or record.id,
            supersedes_id=record.id, **data)
        amendment.serial = next_serial(prefix, model, offset=attempt)
        db.session.add(amendment)
        try:
            db.session.commit()
            return amendment
        except Exception:
            db.session.rollback()
    raise RuntimeError("could not allocate amendment serial")


def apply_decision(record, decision: str, reviewer, notes: str = ""):
    """Manager approve/reject with reviewer stamp. Returns error str|None.

    Atomic: both the decision and the prior-version retirement happen in
    a single transaction — either both succeed or both fail.
    """
    from app.extensions import db
    if normalize(record.status) not in (SUBMITTED, PENDING_LEGACY):
        return (f"requires status 'submitted', current is "
                f"'{normalize(record.status)}'")
    if decision in ("approve", "approved", "accept", "معتمد"):
        record.status = APPROVED
    elif decision in ("reject", "rejected", "مرفوض"):
        record.status = REJECTED
    else:
        return "decision must be approve or reject"
    record.reviewed_by_id = reviewer.id
    record.reviewed_at = datetime.utcnow()
    record.review_notes = (notes or "").strip()[:2000]
    # an approved amendment retires the version it supersedes (trail kept)
    if record.status == APPROVED and record.supersedes_id:
        prior = db.session.get(type(record), record.supersedes_id)
        if prior is not None and normalize(prior.status) == APPROVED:
            prior.status = AMENDED
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return "database error during decision — transaction rolled back"
    return None
