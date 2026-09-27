"""Primary-key lookups that end in a 404.

flask_sqlalchemy offers ``Model.query.get_or_404(pk)``, but it reaches the row
through the legacy ``Query.get()`` that SQLAlchemy 2.0 flags with a
``LegacyAPIWarning`` on every single call. The warning is noise about a
supported API, and it cannot be silenced without hiding real legacy usage, so
the lookup is done through ``Session.get()`` instead — same row, same 404
contract, no deprecated API involved.
"""
from __future__ import annotations

from flask import abort

from app.extensions import db


def get_or_404(model, ident, description: str | None = None):
    """Return the row with this primary key, or abort with 404.

    Mirrors ``flask_sqlalchemy.Query.get_or_404`` exactly, including the
    optional ``description`` forwarded to ``abort``.
    """
    obj = db.session.get(model, ident)
    if obj is None:
        abort(404, description=description)
    return obj
