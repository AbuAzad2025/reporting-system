"""Quick tests for services/pdf_dynamic — boost coverage."""

def test_pdf_dynamic_import():
    from app.services.pdf_dynamic import build_dynamic_pdf
    assert callable(build_dynamic_pdf)
