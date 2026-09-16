"""Backward-compat shim — canonical singletons live in app/extensions.py."""
from app.extensions import db, login_manager, migrate  # noqa: F401
