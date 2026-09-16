"""Backward-compat shim — canonical models live in app/models.py."""
from app.models import *  # noqa: F401,F403
from app.models import (User, Report, ReportTemplate, DynamicField,
                        ReportSubmission, Project, REPORT_TYPES,
                        REPORT_TYPE_KEYS, ROLES, FIELD_TYPES)  # noqa: F401
from app.extensions import login_manager as _lm  # noqa: F401
import app.models as _m  # noqa: F401

load_user = _m.load_user
