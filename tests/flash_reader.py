"""Reading flash messages back out of a rendered page.

Several test modules need the exact (category, message) pairs a view emitted.
A 200 re-render consumes the queue inside base.html, so the texts have to be
read out of the rendered alert boxes; an unfollowed 302 leaves them in the
session cookie instead.

This was written three times over, once per module, and each copy parsed the
alert by looking for a background colour. When the template moved to a semantic
tone class all three went quiet at once - they stopped matching anything and
the assertions they guarded quietly stopped testing anything. One reader, and
one test that checks it still matches the markup the template renders.
"""
import html
import re

ALERT_RE = re.compile(
    r'<div role="alert" class="([^"]*)"[^>]*>\s*<span>(.*?)</span>', re.S)

#: The tone is named by one class on the alert. It used to be inferred from a
#: background colour, which is also how a colour could have been the only
#: signal in the first place.
TONE_CATEGORIES = (("flash-success", "success"), ("flash-danger", "danger"),
                   ("flash-warning", "warning"), ("flash-info", "info"),
                   ("flash-message", "info"))


def flashes(client, response):
    """The (category, message) pairs this response showed the browser."""
    if response.status_code == 302:
        with client.session_transaction() as session:
            return [tuple(item) for item in session.pop("_flashes", [])]

    emitted = []
    for classes, message in ALERT_RE.findall(response.get_data(as_text=True)):
        for needle, category in TONE_CATEGORIES:
            if needle in classes:
                emitted.append((category,
                                html.unescape(message.strip())))
                break
        else:
            # An alert with no recognised tone would otherwise be dropped,
            # turning a styling regression into silence.
            raise AssertionError(
                "alert carries no known tone class: %r" % classes)
    return emitted
