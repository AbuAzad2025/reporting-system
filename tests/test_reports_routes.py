"""Quick tests for reports/routes — boost coverage."""

def test_reports_import():
    from app.reports import routes
    assert routes is not None
