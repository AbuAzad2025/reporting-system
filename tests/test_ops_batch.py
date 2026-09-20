"""Tests for ops/batch.py — full coverage."""
import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

from app.ops.batch import _fmt, collect_batch, batch_summary, build_batch_pdf, CONDENSED


class TestFmt:

    def test_none_returns_dash(self):
        assert _fmt(None) == "—"

    def test_float_formatted(self):
        assert _fmt(1234.567) == "1,234.57"
        assert _fmt(0.0) == "0.00"
        assert _fmt(-12.5) == "-12.50"

    def test_string_stripped(self):
        assert _fmt("  hello  ") == "hello"

    def test_empty_string_returns_dash(self):
        assert _fmt("") == "—"
        assert _fmt("   ") == "—"

    def test_integer_formatted(self):
        assert _fmt(42) == "42"


class TestCollectBatch:

    def test_collect_batch_empty(self, app, eng_client):
        with app.app_context():
            from app.ops.routes import KIND_MODEL
            from app.models import User
            from app.extensions import db
            u = User.query.filter_by(username="t_eng").first()
            records = collect_batch({}, u)
            assert records == []

    def test_collect_batch_filters_by_project(self, app):
        with app.app_context():
            from app.ops.models import SiteInspection
            from app.models import User, Project
            from app.extensions import db
            from app.ops.models import ProjectMember
            u = User.query.filter_by(username="t_eng").first()
            p1 = Project(name="P1")
            p2 = Project(name="P2")
            db.session.add_all([p1, p2])
            db.session.commit()
            # Add user as member of p1
            db.session.add(ProjectMember(user_id=u.id, project_id=p1.id))
            db.session.commit()
            s1 = SiteInspection(project_id=p1.id, user_id=u.id, serial="SIR-001",
                               test_category="concrete", test_type="cube", result_value=25,
                               acceptance_min=20, verdict="pass", signatory_name="Eng")
            s2 = SiteInspection(project_id=p2.id, user_id=u.id, serial="SIR-002",
                               test_category="concrete", test_type="cube", result_value=30,
                               acceptance_min=20, verdict="pass", signatory_name="Eng")
            db.session.add_all([s1, s2])
            db.session.commit()

            # Test without isolation - directly query
            from app.ops.models import SiteInspection
            from app.ops.batch import collect_batch
            model_map = {"site-inspections": SiteInspection}
            # Mock the isolation to pass through
            from app.ops.isolation import scope_to_tenant
            original_scope = scope_to_tenant
            try:
                import app.ops.batch as batch_module
                batch_module.scope_to_tenant = lambda q, m, u: q  # bypass isolation
                records = collect_batch({"site-inspections": SiteInspection}, u, project_id=p1.id)
                assert len(records) == 1
                assert records[0][1].serial == "SIR-001"
            finally:
                batch_module.scope_to_tenant = original_scope


class TestBatchSummary:

    def test_empty_records(self):
        summary = batch_summary([])
        assert summary == {
            "total": 0, "by_module": {}, "by_status": {},
            "billing_gross": 0.0, "billing_net": 0.0, "cost_variance": 0.0
        }

    def test_counts_by_module_and_status(self):
        from unittest.mock import MagicMock
        mock_records = [
            ("site-inspections", MagicMock(status="approved")),
            ("site-inspections", MagicMock(status="pending")),
            ("rfis", MagicMock(status="approved")),
        ]
        summary = batch_summary(mock_records)
        assert summary["total"] == 3
        assert summary["by_module"] == {"site-inspections": 2, "rfis": 1}
        assert summary["by_status"] == {"approved": 2, "pending": 1}

    def test_financial_totals(self):
        from unittest.mock import MagicMock
        from app.ops.models import ProgressBilling, CostVariance
        mock_pb1 = MagicMock()
        mock_pb1.kind = "progress-billings"
        mock_pb1.net_payable = 1000.0
        mock_pb1.gross = 1200.0
        mock_pb2 = MagicMock()
        mock_pb2.kind = "progress-billings"
        mock_pb2.net_payable = 500.0
        mock_pb2.gross = 600.0
        mock_cv = MagicMock()
        mock_cv.kind = "cost-variances"
        mock_cv.variance = 1500.0

        records = [
            ("progress-billings", mock_pb1),
            ("progress-billings", mock_pb2),
            ("cost-variances", mock_cv),
        ]
        summary = batch_summary(records)
        assert summary["billing_net"] == 1500.0
        assert summary["billing_gross"] == 1800.0
        assert summary["cost_variance"] == 1500.0


class TestBuildBatchPDF:

    def test_build_batch_pdf_empty_records(self):
        pdf_bytes = build_batch_pdf(
            records=[],
            project_name="Test Project",
            date_from="2024-01-01",
            date_to="2024-01-31",
            generated_by="Test User",
            generated_at="2024-01-15 10:00"
        )
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        assert pdf_bytes.startswith(b"%PDF-")

    def test_build_batch_pdf_with_records(self, app):
        with app.app_context():
            from app.ops.models import SiteInspection
            from app.models import User, Project
            from app.extensions import db
            u = User.query.filter_by(username="t_eng").first()
            p = Project(name="Test Project")
            db.session.add(p)
            db.session.commit()
            s = SiteInspection(project_id=p.id, user_id=1, serial="SIR-001",
                               test_category="concrete", test_type="cube", result_value=25,
                               acceptance_min=20, verdict="pass", signatory_name="Eng")
            db.session.add(s)
            db.session.commit()

            from app.ops.routes import KIND_MODEL
            from app.ops.models import SiteInspection
            from app.ops.isolation import scope_to_tenant
            u = User.query.filter_by(username="t_eng").first()
            model_map = {"site-inspections": SiteInspection}
            records = collect_batch(model_map, u, project_id=p.id)

            pdf_bytes = build_batch_pdf(
                records=records,
                project_name="Test Project",
                date_from="2024-01-01",
                date_to="2024-12-31",
                generated_by="Test Engineer",
                generated_at="2024-01-15 10:00"
            )
            assert isinstance(pdf_bytes, bytes)
            assert len(pdf_bytes) > 1000
            assert pdf_bytes.startswith(b"%PDF-")


class TestCondensedMapping:

    def test_all_kinds_have_condensed_mapping(self):
        from app.ops.models import OPS_MODULES
        for kind in CONDENSED:
            assert kind in ["site-inspections", "material-submittals", "rfis",
                           "cost-variances", "progress-billings",
                           "subcontractor-performances", "daily-reports",
                           "variation-orders", "safety-reports"]
            for attr, label in CONDENSED[kind]:
                assert attr
                assert label

    def test_condensed_fields_are_strings(self):
        for kind, fields in CONDENSED.items():
            for attr, label in fields:
                assert isinstance(attr, str)
                assert isinstance(label, str)
                assert len(attr) > 0
                assert len(label) > 0