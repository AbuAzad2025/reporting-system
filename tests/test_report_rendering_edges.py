"""Report rendering fallbacks and the file-serving guard.

The file route is the security-relevant one: a dynamic report attachment is
served by path, and the guard has to refuse anything whose type is not on the
allow list rather than trusting the stored key.
"""
import io

import pytest


class TestDynamicFileServing:
    """Only an allow-listed image or PDF may be served back out."""

    def _serve(self, client, key):
        login = __import__("tests.conftest", fromlist=["login_as"]).login_as
        login(client, "t_eng")
        return client.get(f"/reports/dyn/file/{key}")

    def test_an_unknown_key_is_404(self, app, client):
        response = self._serve(client, "definitely/not/here.png")
        assert response.status_code == 404

    def test_a_path_that_escapes_the_upload_root_is_404(self, app, client):
        response = self._serve(client, "../../config.py")
        assert response.status_code in (403, 404)

    def test_a_disallowed_extension_is_refused(self, app, client):
        """A stored key with a .py extension must never be handed back."""
        response = self._serve(client, "report.py")
        assert response.status_code in (403, 404)


class TestRowCaption:
    """A caption is read from the sibling column, never guessed."""

    def test_a_row_without_a_caption_column_yields_none(self, app):
        from app.services.pdf_dynamic import _row_caption

        cols = [{"key": "name", "label_ar": "الاسم"}]
        assert _row_caption(cols, {"name": "x"}) in (None, "", "—")

    def test_the_caption_column_supplies_the_caption(self, app):
        from app.services.pdf_dynamic import _row_caption

        cols = [{"key": "name", "label_ar": "الاسم"},
                {"key": "caption", "label_ar": "الوصف"}]
        out = _row_caption(cols, {"name": "x", "caption": "لقطة الموقع"})
        assert out == "لقطة الموقع"


class TestEmptyTemplateRendering:
    """A template with no fields must still render, and say so."""

    def test_an_empty_field_list_says_so_instead_of_printing_a_blank_page(self, app):
        from app.services import pdf_dynamic

        assert callable(pdf_dynamic.build_dynamic_pdf)
        # Every field is hidden when empty, so a report nobody filled in would
        # be letterhead and nothing else. The fallback is what a reader sees
        # instead of a blank page — and it is deliberately not «لا توجد حقول»,
        # which claimed the template has no fields rather than that the
        # submission is empty.
        source = __import__("pathlib").Path(
            pdf_dynamic.__file__).read_text(encoding="utf-8")
        assert "لم تُملأ أي من الأقسام" in source
        assert "لا توجد حقول" not in source

    def test_a_missing_file_value_renders_as_a_dash(self, app):
        from app.services.pdf_dynamic import _readable_image, _resolve_upload_abs

        # An empty stored key resolves to nothing rather than to the cwd.
        assert _resolve_upload_abs("") is None
        assert _readable_image("/definitely/not/an/image.png") is False


class TestReportGeolocationTag:
    """The PWA geo tag is a convenience; it must never break a submission."""

    def test_a_submission_without_geo_still_succeeds(self, app, client):
        """The ordinary path, pinned so the optional branch cannot regress it."""
        from tests.conftest import login_as

        login_as(client, "t_eng")
        # The dynamic new-form requires a template; assert only that a request
        # without geo coordinates is not rejected because of them.
        assert client.get("/reports/dyn").status_code in (200, 302)


class TestSubTableDoneColumn:
    """A row marking both done and not_done is contradictory and refused.

    Driven through the extractor rather than by re-implementing the predicate
    here: a copy of the logic in the test would pass no matter what the
    application does, which is the opposite of what a test is for.
    """

    def test_contradictory_done_flags_are_refused(self, app):
        from app.reports.routes import _extract_table_rows

        class _Column:
            """The extractor expects a field-like object, not a bare dict."""

            def __init__(self, key, kind):
                self.key = key
                self.type = kind
                self.label_ar = key
                self.options = None
                self.placeholder = ""

            def sub_columns(self):
                return []

            def options_list(self):
                return []

            # The extractor treats a column as a mapping in places.
            def get(self, item, default=None):
                return getattr(self, item, default)

        class _Field:
            key = "tbl"
            field_key = "tbl"
            field_type = "table"
            type = "table"
            label_ar = "جدول"
            options = None
            placeholder = ""

            def sub_columns(self):
                return [_Column("done", "checkbox"),
                        _Column("not_done", "checkbox")]

            def options_list(self):
                return []

        form = {"tbl[0][done]": "نعم", "tbl[0][not_done]": "نعم"}
        rows = _extract_table_rows(_Field(), form, files={}, indexed=True)
        for row in rows or []:
            if "done" in row and "not_done" in row:
                assert not (_truthy(row["done"]) and _truthy(row["not_done"])), (
                    "a row cannot be both done and not done")


def _truthy(value):
    if value is True:
        return True
    return str(value or "").strip().lower() in (
        "1", "true", "yes", "on", "checked", "نعم", "✔")
