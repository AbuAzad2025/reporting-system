"""Pure financial/engineering calculations for the ops modules.

Kept free of Flask/SQLAlchemy so they are trivially unit-testable and the
model properties delegate here (single source of truth).

Money is computed in Decimal, not float.

A contract variation is qty x rate, and float is binary: 0.1 + 0.2 is
0.30000000000000004. Across a bill of quantities that error accumulates, and it
accumulates in the direction that makes a re-estimate differ from the figure in
the measurement certificate by a cent nobody can explain. Every figure here is
money or a ratio of money, so it is held as Decimal from the moment it is read
off the form.

Two details that are easy to get wrong and were wrong here:

* ``Decimal(float)`` inherits the float's error, so ``Decimal(str(x))`` is the
  only correct conversion. A caller that has already done float arithmetic
  cannot be rescued, but a form post - which arrives as a string or an int - is
  exact from the start.
* ``round()`` is banker's rounding: round(0.125, 2) is 0.12, because the digit
  before the half is even. Money is not rounded that way. ROUND_HALF_UP gives
  0.13, which is what a measurement certificate shows and what an auditor
  expects. This changes results at exact half-cent boundaries, deliberately.

Floats still leave this module. Every public function returns float or int as
before, so the models, the JSON endpoints and the PDF are unaffected - the
precision is gained inside the calculation and the boundary rounds once, on
purpose, to the precision the report is denominated in.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

#: Report precision. Money to the cent, ratios to three places.
CENT = Decimal("0.01")
RATIO = Decimal("0.001")
ZERO = Decimal("0")


def _d(x, default: str = "0") -> Decimal:
    """Coerce a form value to Decimal without inheriting a float's error."""
    if x is None or x == "":
        return Decimal(default)
    try:
        value = Decimal(str(x).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
    # Decimal("NaN") and Decimal("Infinity") parse successfully but compare
    # false against everything and poison every operation downstream, so they
    # are treated as absent rather than carried into a total.
    if not value.is_finite():
        return Decimal(default)
    return value


def _money(value: Decimal) -> float:
    """Leave the module as a float, rounded the way money rounds."""
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _ratio(value: Decimal) -> float:
    return float(value.quantize(RATIO, rounding=ROUND_HALF_UP))


def variance_metrics(b_qty, b_rate, a_qty, a_rate,
                     r_qty=None, r_rate=None) -> dict:
    """Cost variance core: budgeted vs actual vs re-estimate."""
    budgeted = _d(b_qty) * _d(b_rate)
    actual = _d(a_qty) * _d(a_rate)
    variance = actual - budgeted
    variance_pct = (variance / budgeted * Decimal(100)) if budgeted else ZERO
    reestimated = None
    if r_qty is not None and r_rate is not None:
        try:
            reestimated = Decimal(str(r_qty).strip()) * Decimal(str(r_rate).strip())
        except (InvalidOperation, ValueError, TypeError, ArithmeticError):
            reestimated = None
    return {"budgeted_total": _money(budgeted),
            "actual_total": _money(actual),
            "variance": _money(variance),
            "variance_pct": _money(variance_pct),
            "reestimated_total": _money(reestimated)
            if reestimated is not None else None}


def billing_metrics(qty, rate, retention_pct=10.0, previously=0.0) -> dict:
    """IPC core: gross − retention = net payable; cumulative cash flow."""
    gross = _d(qty) * _d(rate)
    retention = gross * _d(retention_pct) / Decimal(100)
    net = gross - retention
    cumulative = _d(previously) + net
    return {"gross": _money(gross), "retention": _money(retention),
            "net_payable": _money(net),
            "cumulative": _money(cumulative)}


def evm_metrics(planned_value, earned_value, actual_cost,
                budget_at_completion=None) -> dict:
    """Earned Value Management for monthly financial pipeline.

    PV = Planned Value, EV = Earned Value, AC = Actual Cost
    Returns CPI, SPI, CV, SV, forecast_final_cost (EAC).
    """
    pv = _d(planned_value)
    ev = _d(earned_value)
    ac = _d(actual_cost)
    bac = _d(budget_at_completion) if budget_at_completion not in (None, "") \
        else None
    cpi_d = (ev / ac) if ac else ZERO
    spi_d = (ev / pv) if pv else ZERO
    # EAC = AC + (BAC-EV)/CPI  (or BAC/CPI when there is no BAC)
    if bac is not None and bac > ZERO:
        eac = ac + (bac - ev) / cpi_d if cpi_d else ac + (bac - ev)
    else:
        eac = ac / cpi_d if cpi_d else (ac if ac else ZERO)
    return {"pv": _money(pv), "ev": _money(ev), "ac": _money(ac),
            "cpi": _ratio(cpi_d), "spi": _ratio(spi_d),
            "cv": _money(ev - ac), "sv": _money(ev - pv),
            "bac": _money(bac) if bac is not None else None,
            "forecast_final_cost": _money(eac)}


#: weights must sum to 1.0 — quality-led, safety-weighted
PERF_WEIGHTS = {"quality": Decimal("0.35"), "schedule": Decimal("0.25"),
                "safety": Decimal("0.25"), "compliance": Decimal("0.15")}


def performance_overall(quality, schedule, safety, compliance) -> float:
    overall = (_d(quality) * PERF_WEIGHTS["quality"]
               + _d(schedule) * PERF_WEIGHTS["schedule"]
               + _d(safety) * PERF_WEIGHTS["safety"]
               + _d(compliance) * PERF_WEIGHTS["compliance"])
    if overall < ZERO:
        overall = ZERO
    elif overall > Decimal(100):
        overall = Decimal(100)
    return _money(overall)


def performance_grade(overall) -> str:
    value = _d(overall)
    if value >= Decimal(85):
        return "A"
    if value >= Decimal(70):
        return "B"
    if value >= Decimal(50):
        return "C"
    return "D"


def manpower_total(engineers, technicians, labor) -> int:
    """Daily diary headcount: tier sum (negative inputs clamp to zero)."""
    def _nonneg(x) -> Decimal:
        value = _d(x)
        return value if value > ZERO else ZERO

    return int(_nonneg(engineers) + _nonneg(technicians) + _nonneg(labor))


def signed_amount(value) -> str:
    """Signed variation-order impact, e.g. +12,500.00 / −3,200.00 / 0.00."""
    amount = _money(_d(value))
    if amount > 0:
        return f"+{amount:,.2f}"
    if amount < 0:
        return f"\u2212{abs(amount):,.2f}"
    return "0.00"