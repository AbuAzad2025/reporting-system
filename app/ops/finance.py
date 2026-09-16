"""Pure financial/engineering calculations for the ops modules.

Kept free of Flask/SQLAlchemy so they are trivially unit-testable and the
model properties delegate here (single source of truth).
"""
from __future__ import annotations


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def variance_metrics(b_qty, b_rate, a_qty, a_rate,
                     r_qty=None, r_rate=None) -> dict:
    """Cost variance core: budgeted vs actual vs re-estimate."""
    budgeted = _f(b_qty) * _f(b_rate)
    actual = _f(a_qty) * _f(a_rate)
    variance = actual - budgeted
    variance_pct = (variance / budgeted * 100.0) if budgeted else 0.0
    reestimated = None
    if r_qty is not None and r_rate is not None:
        try:
            reestimated = float(r_qty) * float(r_rate)
        except (TypeError, ValueError):
            reestimated = None
    return {"budgeted_total": round(budgeted, 2),
            "actual_total": round(actual, 2),
            "variance": round(variance, 2),
            "variance_pct": round(variance_pct, 2),
            "reestimated_total": round(reestimated, 2)
            if reestimated is not None else None}


def billing_metrics(qty, rate, retention_pct=10.0, previously=0.0) -> dict:
    """IPC core: gross − retention = net payable; cumulative cash flow."""
    gross = _f(qty) * _f(rate)
    retention = gross * _f(retention_pct) / 100.0
    net = gross - retention
    cumulative = _f(previously) + net
    return {"gross": round(gross, 2), "retention": round(retention, 2),
            "net_payable": round(net, 2),
            "cumulative": round(cumulative, 2)}


#: weights must sum to 1.0 — quality-led, safety-weighted
PERF_WEIGHTS = {"quality": 0.35, "schedule": 0.25,
                "safety": 0.25, "compliance": 0.15}


def performance_overall(quality, schedule, safety, compliance) -> float:
    overall = (_f(quality) * PERF_WEIGHTS["quality"]
               + _f(schedule) * PERF_WEIGHTS["schedule"]
               + _f(safety) * PERF_WEIGHTS["safety"]
               + _f(compliance) * PERF_WEIGHTS["compliance"])
    return round(max(0.0, min(100.0, overall)), 2)


def performance_grade(overall) -> str:
    overall = _f(overall)
    if overall >= 85:
        return "A"
    if overall >= 70:
        return "B"
    if overall >= 50:
        return "C"
    return "D"


def manpower_total(engineers, technicians, labor) -> int:
    """Daily diary headcount: tier sum (negative inputs clamp to zero)."""
    return int(max(0, _f(engineers)) + max(0, _f(technicians))
               + max(0, _f(labor)))


def signed_amount(value) -> str:
    """Signed variation-order impact, e.g. +12,500.00 / −3,200.00 / 0.00."""
    v = _f(value)
    if v > 0:
        return f"+{v:,.2f}"
    if v < 0:
        return f"\u2212{abs(v):,.2f}"
    return "0.00"
