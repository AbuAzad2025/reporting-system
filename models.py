"""Backward-compat shim — canonical models live in app/models.py."""
from app.models import *  # noqa: F401,F403
# The explicit list below is redundant with the star import above, since
# app/models.py defines no __all__ and every name here is public. It is kept
# because this file exists to be a stable import path, and a reader should be
# able to see the shim's surface without following the star.
from app.models import (User, Report, ReportTemplate,  # noqa: F401
                        DynamicField,
                        ReportSubmission, Project, REPORT_TYPES,  # noqa: F401
                        REPORT_TYPE_KEYS, ROLES, FIELD_TYPES)  # noqa: F401
from app.extensions import login_manager as _lm  # noqa: F401
import app.models as _m  # noqa: F401

load_user = _m.load_user
