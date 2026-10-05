"""Money is computed exactly, and rounded the way money rounds.

Every figure in app/ops/finance.py is money or a ratio of money. They were
computed in binary float, where 0.1 + 0.2 is 0.30000000000000004, so the error
accumulated across a bill of quantities and a re-estimate could differ from the
measurement certificate by a cent nobody can explain.

Two things that were wrong in a way only a test would show:

* rounding. round() is banker's rounding - round(0.125, 2) is 0.12 because the
  digit before the half is even. A measurement certificate says 0.13.
* the float-to-Decimal conversion. Decimal(0.1) inherits the float's error;
  Decimal(str(0.1)) is exact. Reading a form post as a string is therefore not
  a stylistic choice, it is the only correct conversion.
"""
import pytest

from app.ops.finance import (_d, billing_metrics, evm_metrics,
                             manpower_total, performance_grade,
                             performance_overall, signed_amount,
                             variance_metrics)


# ---------------------------------------------------- the float error, named


def test_a_half_cent_line_rounds_up_where_float_rounds_down():
    """The change, on one line of a bill of quantities.

    Three units at 0.145 is 0.435. In binary float that product is stored as
    0.43499999999999994, so round() returns 0.43 - a half cent lost on a line
    that is exactly half a cent. Across a hundred such lines that is five
    shekels the contractor did not get paid for, and the PDF disagrees with the
    measurement certificate.

    Decimal holds 0.435 exactly and ROUND_HALF_UP returns 0.44, which is what a
    certificate shows.
    """
    assert 3 * 0.145 == 0.43499999999999994
    assert round(3 * 0.145, 2) == 0.43, "float loses the half cent"

    assert billing_metrics(3, "0.145")["gross"] == 0.44
    assert billing_metrics(3, "1.005")["gross"] == 3.02
    assert billing_metrics(1, "1.005")["gross"] == 1.01


def test_a_hundred_such_lines_were_short_by_five_shekels():
    line, lines = 0.435, 100
    was = sum(round(3 * 0.145, 2) for _ in range(lines))
    now = sum(billing_metrics(3, "0.145")["gross"] for _ in range(lines))
    assert was == 43.0
    assert now == pytest.approx(44.0, abs=0.005)


def test_the_float_error_is_real_and_is_what_this_module_avoided():
    """If this ever stops being true the justification is gone - check it."""
    assert 0.1 + 0.2 != 0.3


def test_decimal_conversion_reads_the_string_not_the_float():
    assert _d(0.1) == _d("0.1")
    assert str(_d(0.1)) == "0.1", "the float's error was carried in"
    assert str(_d(1.005)) == "1.005"


# --------------------------------------------------------- rounding is HALF_UP


@pytest.mark.parametrize("raw,expected", [
    ("0.125", 0.13),   # banker's rounding would give 0.12
    ("2.345", 2.35),
    ("2.355", 2.36),   # banker's rounding would give 2.36 too, but 0.125 is the case
    ("0.005", 0.01),
])
def test_half_cent_rounds_up_not_to_even(raw, expected):
    got = billing_metrics(1, raw)["gross"]
    assert got == expected


def test_banker_rounding_is_genuinely_different():
    """Documents the behaviour being replaced, so a revert is visible."""
    assert round(0.125, 2) == 0.12
    assert billing_metrics(1, "0.125")["gross"] == 0.13


# ---------------------------------------------------------------- the totals


def test_variance_basics_unchanged_in_shape():
    m = variance_metrics(10, 100, 12, 100)
    assert m["budgeted_total"] == 1000.0
    assert m["actual_total"] == 1200.0
    assert m["variance"] == 200.0
    assert m["variance_pct"] == 20.0
    assert m["reestimated_total"] is None


def test_variance_handles_a_missing_re_estimate():
    assert variance_metrics(1, 1, 2, 1, r_qty=None, r_rate=None)[
        "reestimated_total"] is None
    assert variance_metrics(1, 1, 2, 1, r_qty=5, r_rate=5)[
        "reestimated_total"] == 25.0


def test_variance_of_nothing_is_zero_not_a_division_error():
    m = variance_metrics(0, 0, 0, 0)
    assert m["variance_pct"] == 0.0
    assert m["variance"] == 0.0


def test_billing_retention_and_cumulative():
    m = billing_metrics(100, 10, retention_pct=10, previously=500)
    assert m["gross"] == 1000.0
    assert m["retention"] == 100.0
    assert m["net_payable"] == 900.0
    assert m["cumulative"] == 1400.0


def test_billing_zero_retention():
    m = billing_metrics(10, 5, retention_pct=0)
    assert m["retention"] == 0.0
    assert m["net_payable"] == 50.0


def test_evm_indices_and_forecast():
    m = evm_metrics(100, 80, 90, budget_at_completion=110)
    assert m["pv"] == 100.0 and m["ev"] == 80.0 and m["ac"] == 90.0
    assert m["cpi"] == pytest.approx(0.889, abs=0.001)
    assert m["spi"] == pytest.approx(0.8, abs=0.001)
    assert m["cv"] == -10.0
    assert m["sv"] == -20.0
    assert m["bac"] == 110.0


def test_evm_without_a_budget_at_completion():
    m = evm_metrics(100, 80, 90)
    assert m["bac"] is None
    assert m["forecast_final_cost"] > 0


def test_evm_all_zero_does_not_divide_by_zero():
    m = evm_metrics(0, 0, 0)
    assert m["cpi"] == 0.0 and m["spi"] == 0.0
    assert m["forecast_final_cost"] == 0.0


# ------------------------------------------------------- rubbish in, sane out


@pytest.mark.parametrize("junk", ["", None, "abc", [], {}, float("nan"),
                                  float("inf"), "-"])
def test_unusable_input_is_zero_not_an_exception(junk):
    assert billing_metrics(junk, junk)["gross"] == 0.0
    assert variance_metrics(junk, junk, junk, junk)["budgeted_total"] == 0.0
    assert evm_metrics(junk, junk, junk)["forecast_final_cost"] == 0.0


def test_nan_does_not_poison_a_total():
    """Decimal('NaN') parses, then compares false against everything.

    Carried into a sum it would make every comparison in the report behave
    strangely, so it is treated as absent at the boundary.
    """
    assert billing_metrics(10, 5)["gross"] == 50.0
    assert _d(float("nan")) == 0


# -------------------------------------------------------------- performance


def test_performance_weighted_average_and_clamp():
    assert performance_overall(100, 100, 100, 100) == 100.0
    assert performance_overall(0, 0, 0, 0) == 0.0
    assert performance_overall(200, 200, 200, 200) == 100.0
    assert performance_overall(-5, 50, 50, 50) >= 0.0


def test_grade_thresholds():
    assert performance_grade(85) == "A"
    assert performance_grade(84.99) == "B"
    assert performance_grade(70) == "B"
    assert performance_grade(69.99) == "C"
    assert performance_grade(50) == "C"
    assert performance_grade(49.99) == "D"


def test_grade_of_rubbish_is_D_not_a_crash():
    assert performance_grade(None) == "D"
    assert performance_grade("n/a") == "D"


# ------------------------------------------------------------------ display


def test_manpower_clamps_negatives():
    assert manpower_total(2, 3, 5) == 10
    assert manpower_total(-2, 3, 5) == 8
    assert manpower_total(None, None, None) == 0


def test_signed_amount_formatting():
    assert signed_amount(12500) == "+12,500.00"
    assert signed_amount(-3200) == "\u22123,200.00"
    assert signed_amount(0) == "0.00"
    assert signed_amount("0.005") == "+0.01"


def test_the_public_functions_still_return_plain_numbers():
    """Floats leave the module, so no caller has to learn about Decimal."""
    for value in billing_metrics(1, 1).values():
        assert type(value) is float
    for value in evm_metrics(1, 1, 1).values():
        assert value is None or type(value) is float
    for value in variance_metrics(1, 1, 1, 1).values():
        assert value is None or type(value) is float
    assert type(performance_overall(1, 1, 1, 1)) is float
    assert type(manpower_total(1, 1, 1)) is int