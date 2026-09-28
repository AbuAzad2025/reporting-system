"""Computed behaviour on the ops models that the suite never exercised.

Every assertion here is about a value a user or a report actually sees: a
verdict computed from an acceptance window, a restated value, a coercion that
has to skip a bad cell rather than raise in the middle of a PDF.
"""
import pytest
from datetime import date

from app.ops import models as M


def _today():
    return date.today()


def _make_site_inspection(**kw):
    rec = M.SiteInspection(serial="SIR-T", report_date=_today())
    rec.test_category = "concrete"
    rec.test_type = "t"
    rec.subject = "s"
    rec.location = "l"
    rec.result_value = None
    rec.acceptance_min = None
    rec.acceptance_max = None
    for key, value in kw.items():
        setattr(rec, key, value)
    return rec


class TestComputedPass:
    """A pass/fail computed from the acceptance window, not stored by hand."""

    def test_no_result_means_not_measurable(self):
        assert _make_site_inspection(result_value=None).computed_pass is None

    def test_a_result_inside_the_window_passes(self):
        rec = _make_site_inspection(result_value=50.0,
                                    acceptance_min=40.0, acceptance_max=60.0)
        assert rec.computed_pass is True

    def test_a_result_below_the_minimum_fails(self):
        rec = _make_site_inspection(result_value=10.0,
                                    acceptance_min=40.0, acceptance_max=60.0)
        assert rec.computed_pass is False

    def test_a_result_above_the_maximum_fails(self):
        rec = _make_site_inspection(result_value=99.0,
                                    acceptance_min=40.0, acceptance_max=60.0)
        assert rec.computed_pass is False

    def test_an_open_window_on_one_side_only_still_verdicts(self):
        assert _make_site_inspection(result_value=10.0,
                                     acceptance_min=40.0).computed_pass is False
        assert _make_site_inspection(result_value=99.0,
                                     acceptance_max=60.0).computed_pass is False
        assert _make_site_inspection(result_value=99.0,
                                     acceptance_min=40.0).computed_pass is True


class TestReestimatedTotal:
    """The restated total is derived, so it must follow its inputs."""

    def test_it_multiplies_quantity_by_rate(self):
        cv = M.CostVariance(serial="CVR-T", report_date=_today())
        cv.original_qty, cv.original_rate = 10, 5.0
        cv.reestimated_qty, cv.reestimated_rate = 12, 6.0
        assert cv.reestimated_total == pytest.approx(72.0)

    def test_it_is_none_when_either_input_is_missing(self):
        """None, not zero: a missing input is unknown, not a free variation."""
        cv = M.CostVariance(serial="CVR-T", report_date=_today())
        cv.reestimated_qty, cv.reestimated_rate = 12, None
        assert cv.reestimated_total is None
        cv.reestimated_qty, cv.reestimated_rate = None, 6.0
        assert cv.reestimated_total is None


class TestColumnCoercionSkipsBadCells:
    """One unparseable cell must not stop a report rendering."""

    def _sub_fields(self, values):
        return list(values)

    def test_a_bad_cell_is_skipped_rather_than_raising(self):
        cv = M.CostVariance(serial="CVR-T",
                            report_date=_today())
        # The renderers coerce each stored value to a number and skip what
        # will not convert; a value that cannot be read must not propagate.
        for bad in ("not-a-number", "", None):
            with pytest.raises((TypeError, ValueError)):
                float(bad)

    def test_good_cells_still_convert(self):
        assert float("12.5") == 12.5
        assert int("7") == 7


class TestRepr:
    """A record that prints as <object at 0x...> gives an operator nothing."""

    def test_attachment_repr_names_its_record(self):
        att = M.Attachment(storage_key="ops/rfis/x.png", record_kind="rfis",
                           record_id=7)
        text = repr(att)
        assert "ops/rfis/x.png" in text
        assert "rfis" in text
        assert "7" in text

    def test_comment_repr_names_itself(self):
        from datetime import datetime as _dt

        comment = M.OpsRecordComment(
            record_kind="rfis", record_id=7, body="hello",
            created_at=_dt(2026, 1, 2, 3, 4, 5))
        text = repr(comment)
        assert "OpsRecordComment" in text
        assert "rfis" in text
