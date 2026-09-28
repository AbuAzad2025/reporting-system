"""Service-layer behaviour the suite never exercised.

Two of these are security-relevant rather than cosmetic: a backup archive
whose metadata is malformed or lies about its scope must be rejected before it
is used, and a file whose extension implies a type the guard does not allow
must be refused rather than trusted.
"""
import io
import json
import zipfile

import pytest

from app.services import mime_guard
from app.services import word_export as we


# ------------------------------------------------------------ backup metadata


def _archive(metadata, version="1.0", extra=None):
    payload = json.dumps(metadata).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metadata.json", payload)
        if extra:
            for name, data in extra.items():
                zf.writestr(name, data)
    return buf.getvalue()


class TestValidateBackupRefusesBadMetadata:
    """A restore is destructive; the archive is checked before it is trusted."""

    def test_metadata_must_be_an_object(self):
        from app.services.backup import validate_backup

        result = validate_backup(_archive([1, 2, 3]))
        assert result["ok"] is False
        assert "not an object" in result["error"]

    def test_an_unknown_scope_is_refused(self):
        from app.services.backup import validate_backup

        result = validate_backup(_archive({"version": "1.0", "scope": "galaxy"}))
        assert result["ok"] is False
        assert "Unknown backup scope" in result["error"]

    def test_a_project_scoped_archive_must_name_its_project(self):
        from app.services.backup import validate_backup

        result = validate_backup(_archive({"version": "1.0", "scope": "project"}))
        assert result["ok"] is False
        assert "project_id" in result["error"]

    def test_a_project_scope_with_a_string_id_is_still_refused(self):
        """The id has to be an int; a string would silently bind to nothing."""
        from app.services.backup import validate_backup

        result = validate_backup(
            _archive({"version": "1.0", "scope": "project", "project_id": "7"}))
        assert result["ok"] is False
        assert "project_id" in result["error"]

    def test_a_well_formed_platform_archive_passes(self):
        from app.services.backup import validate_backup

        result = validate_backup(_archive({"version": "1.0", "scope": "platform"}))
        assert result["ok"] is True
        assert result["metadata"]["scope"] == "platform"


# ------------------------------------------------------------------- mime guard


class TestMimeGuardRefusesUnknownTypes:
    def test_an_extension_the_guard_does_not_know_is_refused(self, ):
        # A name whose extension maps to no known type must be rejected, not
        # waved through because the declared header said something plausible.
        assert mime_guard.is_allowed_upload(
            payload=b"#!/bin/sh\nrm -rf /", filename="payload.unknownext",
            declared="image/png") is False

    def test_a_name_with_no_extension_falls_back_to_the_declared_type(self):
        assert mime_guard.is_allowed_upload(
            payload=b"\x89PNG\r\n\x1a\n" + b"0" * 32, filename="noext",
            declared="image/png") is True

    def test_a_name_with_no_extension_cannot_smuggle_a_disallowed_type(self):
        """No extension means the declared type is the only signal there is.

        With nothing to corroborate it, a type outside the allow list has to be
        refused - otherwise a client could drop the extension and declare
        anything it liked.
        """
        assert mime_guard.is_allowed_upload(
            payload=b"<html><script>alert(1)</script></html>",
            filename="payload", declared="text/html") is False
        assert mime_guard.is_allowed_upload(
            payload=b"anything at all", filename="payload",
            declared="application/x-msdownload") is False

    def test_a_known_extension_whose_bytes_disagree_is_refused(self):
        assert mime_guard.is_allowed_upload(
            payload=b"not a png at all", filename="photo.png",
            declared="image/png") is False

    def test_a_payload_matching_its_declared_type_is_accepted(self):
        assert mime_guard.is_allowed_upload(
            payload=b"%PDF-1.4\n" + b"0" * 32, filename="doc.pdf",
            declared="application/pdf") is True


# ------------------------------------------------------------------ word export


class TestWordExportFormatting:
    def test_an_empty_table_renders_nothing(self):
        """No rows must not emit an empty <w:tbl>, which Word renders oddly."""
        assert we._table([]) == ""
        assert we._table(None) == ""

    def test_a_missing_number_renders_as_a_dash_not_a_crash(self):
        assert we._fmt(None) == "—"

    def test_numbers_are_grouped_and_fixed(self):
        assert we._fmt(1234.5) == "1,234.50"
        assert we._fmt(1234.5, digits=0) == "1,234"

    def test_text_is_passed_through(self):
        assert we._fmt("نص عربي") == "نص عربي"
        assert we._fmt(7) == "7.00"

    def test_a_cell_escapes_markup_in_the_data(self):
        """A value containing angle brackets must not become Word markup."""
        out = we._cell("a < b & c")
        assert "&lt;" in out and "&amp;" in out
        assert "<b>" not in out
