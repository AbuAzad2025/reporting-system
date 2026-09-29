"""The shared flash reader has to keep matching the template.

Every flash assertion in the suite goes through this module. When base.html
moved from a pile of utility classes to one semantic tone class, three separate
copies of this reader stopped matching anything - and no test failed, because a
regex that matches nothing simply produces no messages.

So: the reader is read against the markup the template actually renders.
"""
import re

import flash_reader

TEMPLATE = "templates/base.html"


def _rendered_alert_markup():
    """The alert element as base.html writes it, with the tone filled in."""
    base = open(TEMPLATE, encoding="utf-8").read()
    match = re.search(r'<div role="alert" class="([^"]*)"[^>]*>', base)
    assert match, ("no role=alert element found in %s; if the markup moved, "
                   "this file needs to know" % TEMPLATE)
    return match.group(0)


def test_the_reader_matches_the_element_the_template_writes():
    markup = _rendered_alert_markup()
    assert "flash-msg" in markup
    assert "{{ cat }}" in markup, (
        "the alert no longer interpolates its tone; the reader cannot be "
        "checked against it")
    rendered = markup.replace("{{ cat }}", "danger")
    assert flash_reader.ALERT_RE.search(rendered + "<span>رسالة</span></div>")


def test_every_tone_the_reader_knows_is_produced_by_the_template():
    base = open(TEMPLATE, encoding="utf-8").read()
    css = ""
    for name in ("custom.css", "utilities.css", "layout.css"):
        try:
            css += open("static/css/" + name, encoding="utf-8").read()
        except OSError:
            pass
    for needle, _category in flash_reader.TONE_CATEGORIES:
        assert "{%s" % needle.split("-", 1)[1] or needle in base, needle
        assert "." + needle in css, (
            "%s is used by the flash reader but no stylesheet defines it, so "
            "those messages would be unstyled" % needle)


def test_an_alert_with_no_known_tone_is_an_error_not_silence():
    """A styling change must not make the reader quietly drop messages."""
    class Response:
        status_code = 200

        def get_data(self, **_kwargs):
            return ('<div role="alert" class="flash-msg flash-unknown">'
                    '<span>رسالة</span></div>')

    class Client:
        def session_transaction(self):
            raise AssertionError("should not be reached for a 200")

    try:
        flash_reader.flashes(Client(), Response())
    except AssertionError as exc:
        assert "no known tone" in str(exc)
    else:
        raise AssertionError(
            "an alert with an unrecognised tone was dropped silently")


def test_a_redirect_reads_the_session_queue():
    class Response:
        status_code = 302

        def get_data(self, **_kwargs):
            raise AssertionError("should not read the body of a redirect")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def pop(self, key, *_default):
            assert key == "_flashes"
            return [("success", "تم الحفظ")]

    class Client:
        def session_transaction(self):
            return Session()

    assert flash_reader.flashes(Client(), Response()) == [("success", "تم الحفظ")]
