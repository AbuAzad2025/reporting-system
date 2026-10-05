"""Computed totals refuse to guess, and saying "unknown" never crashes a caller.

Three properties on the daily site report sum a breakdown table: the headcount,
the plant-hours, and the mean progress across work fronts. Each used to skip a
cell it could not parse and total the rest.

That is wrong in two directions, and both are silent:

    a malformed headcount      under-reports the total
    a malformed progress value  inflates the mean, because dropping a row from
                               an average biases it upwards

They now return None for "not computable" and the caller prints a dash. A blank
cell is still treated as unfilled rather than bad - that is the common case and
was never the problem.
"""
import pytest

from app.admin.routes import _add_unless_unknown
from app.extensions import db
from app.ops.models import DailySiteReport


def _dsr(**kwargs):
    """An unsaved daily report with the fields the totals read."""
    defaults = dict(
        project_id=kwargs.pop("project_id", 1), user_id=1,
        report_date=kwargs.pop("report_date", "2026-04-01"),
        serial=kwargs.pop("serial", "DSR-CMP-0001"), status="draft",
        signatory_name="Comparator",
        weather="", work_hours=8, engineers_count=1, technicians_count=1,
        labor_count=1)
    defaults.update(kwargs)
    return DailySiteReport(**defaults)


# ------------------------------------------------------------- the totals


def test_labor_sums_the_trades():
    r = _dsr(labor_table=[{"trade": "نجار", "count": 4},
                          {"trade": "حداد", "count": 6}])
    assert r.labor_table_total == 10


def test_equipment_hours_is_qty_times_hours():
    r = _dsr(equipment_table=[{"eq": "لودر", "qty": 1, "hours": 8},
                              {"eq": "خلاطة", "qty": 2, "hours": 4}])
    assert r.equipment_hours_total == 16.0


def test_fronts_average_is_the_mean():
    r = _dsr(work_fronts=[{"front": "a", "progress_pct": 40},
                          {"front": "b", "progress_pct": 50}])
    assert r.fronts_avg_pct == 45.0


def test_empty_tables_are_zero_not_an_error():
    r = _dsr(labor_table=None, equipment_table=None, work_fronts=None)
    assert r.labor_table_total == 0
    assert r.equipment_hours_total == 0.0
    assert r.fronts_avg_pct is None


# ----------------------------------------------- unusable values refuse


@pytest.mark.parametrize("bad", ["abc", "12abc", {}, [1, 2], "1,5x"])
def test_a_malformed_count_makes_the_total_unknown(bad):
    r = _dsr(labor_table=[{"trade": "نجار", "count": 4},
                          {"trade": "حداد", "count": bad}])
    assert r.labor_table_total is None, (
        "a total that quietly omits a row is under-reporting, and the reader "
        "has no way to know")


def test_a_malformed_qty_makes_plant_hours_unknown():
    r = _dsr(equipment_table=[{"eq": "لودر", "qty": "one", "hours": 8}])
    assert r.equipment_hours_total is None


def test_a_malformed_progress_makes_the_mean_unknown():
    """The mean is the case that mattered: dropping the row inflates it."""
    r = _dsr(work_fronts=[{"front": "a", "progress_pct": 10},
                          {"front": "b", "progress_pct": "n/a"},
                          {"front": "c", "progress_pct": 90}])
    assert r.fronts_avg_pct is None, (
        "averaging the two rows that parsed gives 50, which is not the mean of "
        "this table and looks entirely plausible")


def test_a_malformed_multiplier_makes_plant_hours_unknown():
    r = _dsr(equipment_table=[{"eq": "لودر", "qty": 2, "hours": "eight"}])
    assert r.equipment_hours_total is None


# --------------------------------------------------- blank is not malformed


@pytest.mark.parametrize("blank", [None, ""])
def test_a_blank_cell_is_unfilled_not_unusable(blank):
    """The common case, and it was never the problem."""
    r = _dsr(labor_table=[{"trade": "نجار", "count": 4},
                          {"trade": "حداد", "count": blank}])
    assert r.labor_table_total == 4


def test_numeric_strings_still_work():
    """Form posts arrive as strings; they are numbers."""
    r = _dsr(labor_table=[{"trade": "نجار", "count": "7"}],
             equipment_table=[{"eq": "لودر", "qty": "3", "hours": "2.5"}],
             work_fronts=[{"front": "a", "progress_pct": "33.3"}])
    assert r.labor_table_total == 7
    assert r.equipment_hours_total == 7.5
    assert r.fronts_avg_pct == 33.3


def test_a_non_dict_row_is_ignored_not_fatal():
    r = _dsr(labor_table=["junk", None, {"trade": "نجار", "count": 5}])
    assert r.labor_table_total == 5


# ---------------------------------------------------- the caller must cope


def test_adding_a_none_total_does_not_raise():
    """The bug this change would have shipped.

    Returning None is only correct if every caller copes, and the dashboard
    summed these with `+=`, which raises TypeError on None - so the honest
    value turned one bad cell into a 500 on the analytics page.
    """
    assert _add_unless_unknown(0, None) is None
    assert _add_unless_unknown(None, 5) is None
    assert _add_unless_unknown(None, None) is None


def test_adding_ordinary_figures_is_still_a_sum():
    assert _add_unless_unknown(0, 4) == 4
    assert _add_unless_unknown(4, 6) == 10
    assert _add_unless_unknown(1.5, 2.25) == pytest.approx(3.75)


def test_uncertainty_is_sticky():
    """Once unknown, adding more reports cannot make it known again."""
    total = 0
    for value in (4, None, 6):
        total = _add_unless_unknown(total, value)
    assert total is None