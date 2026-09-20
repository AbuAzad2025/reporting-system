"""Quick tests for services/pdf_dynamic — target 15% → 80%."""
from unittest.mock import patch, MagicMock
import pytest


def test_pdf_dynamic_import():
    from app.services.pdf_dynamic import build_dynamic_pdf
    assert callable(build_dynamic_pdf)


def test_pdf_dynamic_empty_record():
    from app.services.pdf_dynamic import build_dynamic_pdf
    with patch('app.services.pdf_dynamic.weasyprint.HTML') as MockHTML:
        MockHTML.return_value.write_pdf.return_value = b"PDF"
        result = build_dynamic_pdf("test", {}, "user")
        assert result is not None


def test_pdf_dynamic_with_content():
    from app.services.pdf_dynamic import build_dynamic_pdf
    result = build_dynamic_pdf("test", {"field": "value"})
    assert isinstance(result, str)
    assert "test" in result
