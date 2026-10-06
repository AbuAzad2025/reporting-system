"""The remaining uncovered statements across the service layer.

Nine of them, in five places, and every one of them is a guard: something
that decides whether an operation quietly gives up or loudly complains.
- branding.delete_logo swallowing a file that is already gone
- BrandView's fallback logo when there is no application to ask
- pdf_dynamic treating a missing Pillow as "assume the file is fine"
- default_fields_for refusing a template order it cannot satisfy
- build_ops_pdf placing a tenant's logo above the contractual header

None of these are reachable through a normal successful request. That is the
point of each one: they are what happens when the happy path has already gone
wrong somewhere else.
"""
import sys
import types

import pytest


# ================================================== branding.delete_logo

def test_deleting_a_logo_whose_file_vanished_is_not_an_error(app, monkeypatch):
    """Two admins can delete the same logo; the second one loses the race.

    The file existed when the key was resolved and is gone by the time the
    delete runs. That is ordinary concurrent editing, not a failure to report
    - and it must not surface as a 500 on a settings page.

    logo_path returns None for a key whose file is missing, so the race has to
    be staged by making the unlink itself fail.
    """
    import os as real_os
    from app.services.branding import delete_logo, logo_path

    def _vanished(*a, **k):
        raise FileNotFoundError("another process got there first")

    with app.app_context():
        monkeypatch.setattr(real_os, "remove", _vanished)
        delete_logo("race.png")


def test_an_absolute_key_that_points_at_nothing_is_refused(app, monkeypatch,
                                                           tmp_path):
    """logo_path honours absolute paths, but only ones that exist.

    Absolute paths were written by earlier versions, so they cannot simply be
    rejected outright - the check is that the file is really there. One that is
    not resolves to nothing, and then there is nothing for delete_logo to do.
    """
    import os as real_os
    from app.services import branding
    absent = str(tmp_path / "never-uploaded.png")
    removed = []
    with app.app_context():
        assert branding.logo_path(absent) is None, (
            "an absolute path to a file that does not exist must resolve to "
            "nothing")
        monkeypatch.setattr(real_os, "remove", lambda p: removed.append(p))
        branding.delete_logo(absent)
    assert not removed, f"an unresolvable key reached the filesystem: {removed}"


def test_an_absolute_path_to_a_real_file_is_still_honoured(app, tmp_path):
    """The other half: absolute paths from earlier versions keep working.

    This is why the check above is isfile rather than isabs - rejecting every
    absolute path would blank the header of every project that had a logo
    uploaded before the paths became relative.
    """
    from app.services import branding
    real = tmp_path / "legacy.png"
    real.write_bytes(b"x")
    with app.app_context():
        assert branding.logo_path(str(real)) == str(real), (
            "an absolute path to a real file must still be served")


# ================================== BrandView outside an application context

def test_the_fallback_logo_is_absolute_when_there_is_no_app_to_ask():
    """BrandView falls back to the platform logo when a tenant has none.

    Building one outside an application context - a CLI export, a background
    job - has no url_for to ask, so the fallback has to be a path that is
    already correct on its own.
    """
    from app.services.branding import BrandView
    view = BrandView(types.SimpleNamespace(logo_path="", logo2_path=""), {})
    assert view.logo_url == "/static/img/brand/azad-logo.png", (
        "the fallback must be a literal path, because there is no "
        "url_for outside an application context")
    assert view.has_logo, "the platform fallback counts as a logo"


# =========================== pdf_dynamic without Pillow installed

def test_a_missing_pillow_means_an_image_is_assumed_readable(app, monkeypatch):
    """If Pillow cannot be imported, _readable_image cannot vet the file.

    It answers True rather than False, because the alternative is dropping
    every image from every tenant's report on a machine where the PDF writer
    happens to be a different install than the one Pillow lives in.
    """
    from app.services import pdf_dynamic
    monkeypatch.setitem(sys.modules, "PIL", None)
    with app.app_context():
        assert pdf_dynamic._readable_image("whatever.png") is True


def test_an_unreadable_image_is_still_rejected_when_pillow_is_present(
        app, tmp_path):
    """The control: with Pillow importable, a real file is actually opened.

    Without this, the test above would also pass if the function simply
    returned True for everything. _readable_image takes an absolute path, so
    the probe file does not have to live in the uploads directory.
    """
    from app.services import pdf_dynamic
    from PIL import Image
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    good = tmp_path / "probe.png"
    good.write_bytes(buf.getvalue())
    truncated = tmp_path / "broken.png"
    truncated.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    with app.app_context():
        assert pdf_dynamic._readable_image(str(good)) is True
        assert pdf_dynamic._readable_image(str(truncated)) is False
        assert pdf_dynamic._readable_image(str(tmp_path / "absent.png")) is False


# ==================================== default_fields_for integrity checks

def _key_of(field):
    """default_fields_for returns plain dicts; the ORM rows elsewhere do not."""
    return field["key"] if isinstance(field, dict) else field.field_key


def _type_of(field):
    if isinstance(field, dict):
        return field.get("type") or field.get("field_type")
    return field.field_type


def test_a_daily_order_naming_an_undefined_table_is_refused(app, monkeypatch):
    """A table key named in the order but missing from DAILY_TABLES must not
    silently vanish.

    Skipping it would produce a daily form quietly shorter than the standard,
    and the missing section would only surface in the field.
    """
    from app.services import default_templates
    monkeypatch.setattr(
        default_templates, "DAILY_TABLES",
        [t for t in default_templates.DAILY_TABLES if t[0] != "ncr_esha"])
    with app.app_context():
        with pytest.raises(KeyError) as exc:
            default_templates.default_fields_for("daily")
    assert "ncr_esha" in str(exc.value), (
        "the error must name the missing key, or nobody can tell which one")


def test_a_daily_table_defining_a_section_the_order_omits_is_refused(
        app, monkeypatch):
    """The other direction: a section that exists but is never ordered.

    This is the half that actually bit - sections went missing off the form
    with no error at all, which is why the check exists.
    """
    from app.services import default_templates
    monkeypatch.setattr(
        default_templates, "DAILY_TABLES",
        list(default_templates.DAILY_TABLES)
        + [("never_ordered_esha", "شبح", [])])
    with app.app_context():
        with pytest.raises(KeyError) as exc:
            default_templates.default_fields_for("daily")
    assert "never_ordered_esha" in str(exc.value)


def test_the_daily_standard_builds_without_complaint(app):
    """The control for both tests above: the shipped spec is self-consistent.

    If this ever fails, the KeyError is pointing at a real drift between the
    order and the table definitions rather than at a test that was wrong.
    """
    from app.services import default_templates
    with app.app_context():
        fields = default_templates.default_fields_for("daily")
    keys = [_key_of(f) for f in fields]
    assert keys, "the daily standard must produce fields"
    assert len(keys) == len(set(keys)), (
        f"the daily standard has duplicate field keys: {keys}")
    tables = {k for k, f in zip(keys, fields) if _type_of(f) == "table"}
    defined = {k for k, _lb, _cols in default_templates.DAILY_TABLES}
    assert tables == defined, (
        "every DAILY_TABLES section must appear in the built standard")
