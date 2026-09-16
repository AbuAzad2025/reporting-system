from flask import Blueprint

bp = Blueprint("ops", __name__, url_prefix="/ops")

from app.ops import routes  # noqa: F401,E402
