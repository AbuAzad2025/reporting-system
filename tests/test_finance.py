"""Financial calculation accuracy — pure functions AND model delegation."""
from app.ops.finance import (variance_metrics, evm_metrics, billing_metrics,
                             performance_overall, performance_grade,
                             manpower_total, signed_amount)
from app.ops.models import (CostVariance, ProgressBilling,
                            SubcontractorPerformance, DailySiteReport,
                            VariationOrder, SafetyReport)


def test_variance_basic_math():
    m = variance_metrics(100, 300, 110, 310, 115, 310)
    assert m["budgeted_total"] == 30000.00
    assert m["actual_total"] == 34100.00
    assert m["variance"] == 4100.00
    assert m["variance_pct"] == round(4100 / 30000 * 100, 2)
    assert m["reestimated_total"] == 35650.00


def test_variance_zero_budget_guards_division():
    m = variance_metrics(0, 0, 5, 10)
    assert m["variance"] == 50.00
    assert m["variance_pct"] == 0.0  # no ZeroDivisionError
    assert m["reestimated_total"] is None


def test_variance_invalid_reestimate_is_ignored():
    metrics = variance_metrics(1, 2, 1, 3, "invalid", 4)
    assert metrics["reestimated_total"] is None


def test_evm_bac_forecast_handles_zero_cpi():
    assert evm_metrics(100, 50, 0, 200)["forecast_final_cost"] == 150.0


def test_variance_negative_savings():
    m = variance_metrics(100, 100, 80, 90)
    assert m["variance"] == -2800.00
    assert m["variance_pct"] < 0


def test_billing_retention_and_cashflow():
    m = billing_metrics(10, 1000, 10.0, 5000)
    assert m == {"gross": 10000.00, "retention": 1000.00,
                 "net_payable": 9000.00, "cumulative": 14000.00}


def test_billing_zero_retention():
    m = billing_metrics(4, 250, 0, 0)
    assert m["net_payable"] == 1000.00 and m["retention"] == 0.00


def test_performance_weights_and_grade_bands():
    assert performance_overall(100, 100, 100, 100) == 100.0
    assert performance_overall(0, 0, 0, 0) == 0.0
    # quality-led weighting check: 0.35/0.25/0.25/0.15
    assert performance_overall(100, 0, 0, 0) == 35.0
    assert performance_grade(85) == "A"
    assert performance_grade(84.99) == "B"
    assert performance_grade(70) == "B"
    assert performance_grade(50) == "C"
    assert performance_grade(49.99) == "D"


def test_model_properties_mirror_pure_functions(app):
    with app.app_context():
        cv = CostVariance.query.filter_by(serial="CVR-000001").first()
        pure = variance_metrics(cv.budgeted_qty, cv.budgeted_rate,
                                cv.actual_qty, cv.actual_rate)
        assert cv.budgeted_total == pure["budgeted_total"]
        assert cv.actual_total == pure["actual_total"]
        assert cv.variance == pure["variance"]
        assert round(cv.variance_pct, 2) == pure["variance_pct"]

        pb = ProgressBilling.query.filter_by(serial="PBR-000001").first()
        pure_b = billing_metrics(pb.qty_completed, pb.rate,
                                 pb.retention_pct, pb.previously_certified)
        assert pb.gross == pure_b["gross"]
        assert pb.net_payable == pure_b["net_payable"]
        assert pb.cumulative == pure_b["cumulative"]

        sp = SubcontractorPerformance.query.filter_by(
            serial="SPR-000001").first()
        assert sp.overall == performance_overall(90, 80, 70, 85)
        assert sp.grade == performance_grade(sp.overall) == "B"


def test_manpower_total_tiers_and_clamp():
    assert manpower_total(2, 3, 28) == 33
    assert manpower_total(0, 0, 0) == 0
    assert manpower_total(-2, "x", None) == 0  # garbage clamps to zero


def test_signed_amount_variation_impact():
    assert signed_amount(54850) == "+54,850.00"
    assert signed_amount(-3200) == "−3,200.00"  # U+2212 minus sign
    assert signed_amount(0) == "0.00"


def test_new_module_properties_mirror_pure(app):
    with app.app_context():
        dsr = DailySiteReport.query.filter_by(serial="DSR-000001").first()
        assert dsr.manpower_total == manpower_total(2, 3, 28) == 33

        vor = VariationOrder.query.filter_by(serial="VOR-000001").first()
        assert vor.impact_signed == signed_amount(54850)

        hsr = SafetyReport.query.filter_by(serial="HSR-000001").first()
        assert hsr.is_closed is False  # open hazard, no closure date yet
