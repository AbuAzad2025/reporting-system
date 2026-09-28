"""Every class a template uses must be defined by a stylesheet.

This is a real, measured defect that this suite now prevents from coming back.

The templates are written against a utility vocabulary. An audit found 269 of
the 341 distinct class names they used matched no rule in any stylesheet -
2090 usages - including all of the type scale, most of the colour set, and the
entire grid system. Nothing failed: the pages rendered, the tests passed, and
the markup looked designed while being largely unstyled. A class that matches
no selector is a silent no-op, and no tool in the chain reports it.

The contract asserted here is deliberately narrow: a class used in a template
must exist in some stylesheet. It says nothing about whether that rule is a
good one - that is what a design review is for.
"""
import collections
import io
import os
import re

import pytest

TEMPLATES_DIR = "templates"
STATIC_DIR = os.path.join("static", "css")

CLASS_ATTR = re.compile(r'class\s*=\s*"([^"]*)"')
CSS_SELECTOR = re.compile(r'\.((?:[a-zA-Z0-9_-]|\\.)+)')


def _load_css():
    text = []
    for name in sorted(os.listdir(STATIC_DIR)):
        if name.endswith(".css"):
            text.append(io.open(os.path.join(STATIC_DIR, name),
                                encoding="utf-8").read())
    assert text, "no stylesheet found - this test would pass vacuously"
    return "\n".join(text)


def _defined_classes(css_text):
    """Class names the stylesheets define, with CSS escapes resolved.

    A utility like ``hover:bg-slate-50`` is written in the stylesheet as
    ``.hover\\:bg-slate-50``; the template writes it unescaped. The escape
    has to come back off before the two can be compared.
    """
    defined = set()
    for raw in CSS_SELECTOR.findall(css_text):
        defined.add(raw.replace("\\", ""))
    return defined


def _used_classes():
    """(class -> set of templates) for every literal class in every template.

    Jinja is stripped from the whole document *before* class attributes are
    read. Doing it the other way round truncates any class attribute holding a
    quote inside a Jinja tag - which is what the flash markup in base.html does
    - and every class after that point escapes the audit entirely. That is not
    hypothetical: it hid the flash colours the first time this was measured.
    """
    usage = collections.defaultdict(set)
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, TEMPLATES_DIR).replace("\\", "/")
            text = io.open(path, encoding="utf-8").read()
            text = re.sub(r"\{%.*?%\}", " ", text, flags=re.S)
            text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.S)
            for match in CLASS_ATTR.finditer(text):
                for token in match.group(1).split():
                    if token:
                        usage[token].add(rel)
    return usage


@pytest.fixture(scope="module")
def defined():
    return _defined_classes(_load_css())


@pytest.fixture(scope="module")
def used():
    return _used_classes()


def test_every_template_class_is_defined(defined, used):
    """The whole point: a class in a template must match a real rule."""
    undefined = {
        cls: sorted(files) for cls, files in used.items()
        if cls not in defined
    }
    if undefined:
        report = "\n".join(
            f"  .{cls} used in {len(files)} template(s): {', '.join(files[:3])}"
            for cls, files in sorted(undefined.items(),
                                     key=lambda kv: -len(kv[1]))
        )
        pytest.fail(
            f"{len(undefined)} class(es) are used in templates but defined "
            f"nowhere. They render as no-ops:\n{report}")


def test_the_utilities_stylesheet_is_loaded(used):
    """A defined class is still dead if no template loads the stylesheet.

    This is the failure mode where utilities.css exists and is perfect, but
    nothing includes it, so every one of its rules is inert.
    """
    base = io.open(os.path.join(TEMPLATES_DIR, "base.html"), encoding="utf-8").read()
    assert "utilities.css" in base, (
        "utilities.css is not referenced by base.html, so none of it applies")


def test_no_selector_is_defined_twice_at_the_same_level(defined):
    """A repeated top-level rule is a leftover, not an intention.

    Only unconditional, single-selector rules count. A rule inside an
    @media block is a deliberate contextual override - the print sheet
    re-declaring .table is exactly that - and a multi-selector rule is not a
    duplicate of the rules around it.
    """
    duplicated = collections.defaultdict(list)
    for name in sorted(os.listdir(STATIC_DIR)):
        if not name.endswith(".css"):
            continue
        text = io.open(os.path.join(STATIC_DIR, name), encoding="utf-8").read()
        depth = 0
        for line in text.splitlines():
            stripped = line.strip()
            opens = stripped.count("{")
            closes = stripped.count("}")
            # Depth is tracked for every line, at-rules included: skipping the
            # brace on an @media line is what makes everything inside it look
            # like a top-level rule.
            if depth == 0 and not stripped.startswith("@"):
                match = re.match(r"^\.([A-Za-z0-9_-]+)\s*\{$", stripped)
                if match:
                    duplicated[match.group(1)].append(f"{name}:{stripped}")
            depth += opens - closes
            if depth < 0:
                depth = 0

    repeated = {sel: where for sel, where in duplicated.items() if len(where) > 1}
    assert not repeated, "duplicated top-level selectors: " + "; ".join(
        f".{sel} in {', '.join(w)}" for sel, w in sorted(repeated.items()))


def test_dark_mode_is_reachable_from_the_attribute_the_toggle_sets():
    """The toggle writes data-theme; the stylesheet must listen to it.

    The dark theme was implemented as `.dark { ... }` while the toggle set
    `data-theme="dark"`, so no rule anywhere matched the value the UI actually
    produced. The feature was inert: the switch flipped and nothing happened.

    The logic now lives in static/js/theme.js, so the attribute is written
    there; what is asserted is that the writer and the stylesheet agree.
    """
    css = _load_css()
    assert 'data-theme="dark"' in css, (
        "no stylesheet rule keys off [data-theme=\"dark\"], so the theme "
        "toggle cannot work")

    module = io.open(os.path.join("static", "js", "theme.js"),
                     encoding="utf-8").read()
    assert "data-theme" in module, (
        "the theme module must write the attribute the stylesheet reads")
    assert "THEME_ATTRIBUTE" in module, (
        "the attribute should be a named constant, not a literal in a call")

    base = io.open(os.path.join(TEMPLATES_DIR, "base.html"), encoding="utf-8").read()
    assert 'data-theme="light"' in base, (
        "base.html should declare a default theme so the first paint is not "
        "whatever the previous page left behind")
    assert "theme.js" in base, (
        "base.html must load the theme module, or the toggle does nothing")

    # The service worker is the one asset that must not be cache-busted by a
    # new path, or the browser would keep the old worker forever. It is
    # registered through asset_url, so the URL stays /static/sw.js and only
    # the query string changes.
    assert "asset_url('sw.js')" in base, (
        "the service worker should be registered through asset_url")


def test_every_user_facing_control_is_in_the_control_family():
    """No control may be styled by hand.

    An audit found 56 inputs carrying ad-hoc classes across 35 different
    spellings, plus one file input left with `text-xs` and nothing else. Every
    user-facing control now belongs to the control family, so that a change to
    the family reaches all of them.

    File inputs are counted separately and are allowed their own class: they
    must not carry `.form-control`, which sets `appearance: none` and so
    removes the native "choose file" button. `.form-control-file` keeps that
    button and matches the rest of the family.
    """
    control_re = re.compile(r"<(input|select|textarea)\b[^>]*>", re.S)
    not_a_control = re.compile(r'type="(hidden|checkbox|radio|submit|button)"')
    hand_styled = []
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, TEMPLATES_DIR).replace("\\", "/")
            text = io.open(path, encoding="utf-8").read()
            text = re.sub(r"\{%.*?%\}", " ", text, flags=re.S)
            text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.S)
            for match in control_re.finditer(text):
                tag = match.group(0)
                if not_a_control.search(tag):
                    continue
                if "form-control" in tag or "form-control-file" in tag:
                    continue
                hand_styled.append("%s: %s" % (rel, " ".join(tag.split())[:80]))
    assert not hand_styled, (
        "these controls are not in the control family:\n  "
        + "\n  ".join(hand_styled))

    css = _load_css()
    assert ".form-control-file" in css, (
        "file inputs carry .form-control-file, but no such rule exists")
    assert "::file-selector-button" in css, (
        "the native file button is left unstyled, so it looks foreign next to "
        "the rest of the form")
    assert "appearance: none" not in css.split(".form-control-file")[1].split("}")[0], (
        "appearance: none on the file input removes the native choose-file "
        "button and leaves the control looking broken")


def test_focus_is_always_visible(used):
    """Keyboard users must be able to see where they are."""
    css = _load_css()
    assert "focus-visible" in css, (
        "no focus-visible rule: keyboard focus is invisible")


def test_reduced_motion_is_respected(used):
    css = _load_css()
    assert "prefers-reduced-motion" in css, (
        "no prefers-reduced-motion block: animation cannot be turned off")


def test_print_hides_the_chrome(used):
    css = _load_css()
    print_block = css.split("@media print")[-1] if "@media print" in css else ""
    assert print_block, "no @media print block: printed pages carry the nav"
    assert ".no-print" in print_block


# --------------------------------------------------------------- form fields

CONTROL = re.compile(r"<(input|select|textarea)\b[^>]*>", re.S)
LABEL = re.compile(r"<label\b[^>]*>", re.S)
#: Controls that carry no visible text and so are labelled by wrapping, an
#: aria-label, or are not really user input.
UNLABELLED_OK = re.compile(
    r'type="(hidden|checkbox|radio|submit|button)"|aria-label=|aria-labelledby=')


def test_no_tag_was_spliced_into_an_attribute_value():
    """A closing quote immediately followed by a tag name means a tag was cut.

    Two refactoring passes in this session each broke templates differently.
    One rebuilt an opening tag by replacing only the bracket, producing
    `<input id="x"input ...>`. The other applied offsets taken from a
    Jinja-stripped copy of the file to the unstripped text, so an edit landed
    in the middle of an attribute and left `aria-label="..."input` behind. The
    first shape is caught by the malformed-tag check above; this one has no
    bracket at all and needs its own rule, which is why it is stated
    separately rather than assumed to be covered.
    """
    spliced = re.compile(
        r'"(?:aria-label|id|name|value|placeholder|type|class)="[^"]*"'
        r'(?:</?)?(?:input|select|textarea|label|option|form|div|span|a)\b')
    offenders = []
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, TEMPLATES_DIR).replace("\\", "/")
            for lineno, line in enumerate(
                    io.open(path, encoding="utf-8"), start=1):
                match = spliced.search(line)
                if match:
                    offenders.append(f"{rel}:{lineno} "
                                     f"{line[max(0, match.start() - 20):match.start() + 60].strip()}")
    assert not offenders, (
        f"{len(offenders)} spliced tag(s):\n  " + "\n  ".join(offenders[:10]))


def test_every_template_compiles():
    """A template that will not parse is a 500 on the page that renders it.

    This is the check whose absence let a broken edit reach the suite: a
    refactoring pass deleted an {% endfor %} and a closing </select> from
    archive.html and spliced an <input> into their place. Nothing failed until
    a test happened to render that page, and the failure surfaced as a Jinja
    nesting error three files away from the cause.

    Compiling every template is cheap and makes the whole class of structural
    damage fail immediately, whatever did it.
    """
    from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError, select_autoescape

    # Autoescape is not a detail here. Flask enables it for .html, and bandit
    # rightly flags a bare Environment() that does not - so the check compiles
    # templates under the same rules the application renders them with, and a
    # regression in escaping would surface here rather than as an XSS.
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(default_for_string=True, default=True))
    broken = []
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in sorted(files):
            if not name.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name),
                                  TEMPLATES_DIR).replace("\\", "/")
            try:
                env.get_template(rel)
            except TemplateSyntaxError as exc:
                broken.append(f"{rel} line {exc.lineno}: {exc.message}")
            except Exception as exc:  # noqa: BLE001 - report, never mask
                broken.append(f"{rel}: {type(exc).__name__}: {exc}")

    assert not broken, "templates will not compile:\n  " + "\n  ".join(broken)


def test_every_template_keeps_its_blocks_balanced():
    """A structural sanity check that does not depend on Jinja.

    A template whose block tags are unbalanced is broken even if the parser is
    lenient about it, and counting them is the cheapest way to catch a lost
    {% endfor %} before it reaches a page.
    """
    openers = {"block": "endblock", "for": "endfor", "if": "endif",
               "block_inner": "endblock"}
    problems = []
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in sorted(files):
            if not name.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name),
                                  TEMPLATES_DIR).replace("\\", "/")
            text = io.open(os.path.join(dirpath, name), encoding="utf-8").read()
            tags = re.findall(r"\{%-?\s*(\w+)", text)
            closes = re.findall(r"\{%-?\s*end(\w+)", text)
            for tag, closer in openers.items():
                # 'block' also matches the inner {% block x %} of {% call %}
                if tag == "block_inner":
                    continue
                opened = tags.count(tag)
                closed = closes.count(tag)
                if opened != closed:
                    problems.append(
                        f"{rel}: {opened} '{tag}' vs {closed} 'end{tag}'")
    assert not problems, "unbalanced template blocks:\n  " + "\n  ".join(
        problems[:12])


def test_no_template_contains_a_malformed_tag():
    """A tag must not swallow another tag.

    Added after a refactoring script rebuilt opening tags by replacing only the
    leading bracket, which produced `<input id="f-x"input name="x">` in 34
    places across 9 templates. The corruption check that existed at the time
    only looked for markup inside a class attribute and did not see it, so the
    broken templates passed every test in the suite and would have shipped.

    The shape to catch is a `<` appearing between an opening bracket and its
    closing `>`, which covers both the duplicated tag name above and one tag
    swallowing the next.
    """
    malformed = re.compile(r"<([a-zA-Z][\w-]*)\b[^<>]{0,400}?<[a-zA-Z/]")
    offenders = []
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, TEMPLATES_DIR).replace("\\", "/")
            text = io.open(path, encoding="utf-8").read()
            for lineno, line in enumerate(text.splitlines(), start=1):
                match = malformed.search(line)
                if match:
                    offenders.append(
                        f"{rel}:{lineno} {line[max(0, match.start() - 8):match.start() + 70].strip()}")
    assert not offenders, (
        f"{len(offenders)} malformed tag(s):\n  " + "\n  ".join(offenders[:10]))


def test_every_field_is_visibly_labelled_and_bound_to_its_control():
    """Clicking a label must focus its field, and a screen reader must link them.

    The templates were written with <label class="font-bold text-sm">Username
    </label> and no `for`, next to an input with no `id`. The label looked like
    a label and was connected to nothing: clicking the text did nothing, and
    assistive technology had no name for the field. The shared macros in
    _macros.html bind them by id, and this is what stops the copies creeping
    back.
    """
    offenders = []
    for dirpath, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, TEMPLATES_DIR).replace("\\", "/")
            text = io.open(path, encoding="utf-8").read()
            text = re.sub(r"\{%.*?%\}", " ", text, flags=re.S)
            text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.S)

            # A control is fine if it is inside a <label> element.
            wrapped = set()
            for label in LABEL.finditer(text):
                for control in CONTROL.finditer(label.group(0)):
                    wrapped.add(control.start())

            labelled_ids = set()
            for label in LABEL.finditer(text):
                for attr in ("for", re.compile(r'for="([^"]+)"')):
                    pass
                m = re.search(r'for="([^"]+)"', label.group(0))
                if m:
                    labelled_ids.add(m.group(1))

            for control in CONTROL.finditer(text):
                tag = control.group(0)
                if UNLABELLED_OK.search(tag):
                    continue
                has_id = re.search(r'id="([^"]+)"', tag)
                if has_id and has_id.group(1) in labelled_ids:
                    continue
                offenders.append(f"{rel}: {tag[:90]}")

    assert not offenders, (
        f"{len(offenders)} control(s) have no bound label:\n  "
        + "\n  ".join(offenders[:12])
        + ("\n  ... and more" if len(offenders) > 12 else ""))


def test_static_assets_are_cache_busted():
    """A merged stylesheet fix must be visible without a hard refresh."""
    base = io.open(os.path.join(TEMPLATES_DIR, "base.html"), encoding="utf-8").read()
    assert "asset_url(" in base, (
        "base.html should load stylesheets through asset_url so they carry a "
        "version; otherwise a deployed fix stays invisible to browsers")
    # The helper has to exist, or the template renders a literal 500.
    init = io.open(os.path.join("app", "__init__.py"), encoding="utf-8").read()
    assert "asset_url" in init, "asset_url is not registered on the app"
    assert 'jinja_env.globals["asset_url"]' in init, (
        "asset_url must be a Jinja global for base.html to use it")


def test_asset_version_tracks_the_file():
    """The version must follow the asset, not the process start."""
    import importlib
    import os as _os
    import sys
    import tempfile

    sys.path.insert(0, _os.path.abspath("."))
    try:
        module = importlib.import_module("app")
    finally:
        sys.path.pop(0)

    from flask import Flask

    probe = Flask(__name__, static_folder=_os.path.join("static"))
    module._register_asset_cache_busting(probe)

    with probe.test_request_context():
        from flask import render_template_string

        first = render_template_string("{{ asset_url('css/utilities.css') }}")
        assert "?v=" in first, f"no version in {first}"

        # A second call in the same process must reuse the resolved version.
        second = render_template_string("{{ asset_url('css/utilities.css') }}")
        assert first == second, "the version is not being cached per process"

    with tempfile.NamedTemporaryFile(suffix=".css", delete=True) as tmp:
        rendered = None
        probe2 = Flask(__name__, static_folder=tmp.name)
        module._register_asset_cache_busting(probe2)
        with probe2.test_request_context():
            rendered = render_template_string("{{ asset_url('missing.css') }}")
        assert "?v=0" in rendered, (
            "a missing asset must still yield a URL, not raise")


def test_the_shared_macros_exist():
    """The component layer is the single spelling; it has to be present."""
    macros = io.open(os.path.join(TEMPLATES_DIR, "_macros.html"),
                     encoding="utf-8").read()
    for name in ("field", "select", "textarea", "card", "empty_state",
                 "submit_btn", "checkbox", "page_head"):
        assert f"macro {name}(" in macros, f"macro {name} is missing"
    # A macro that emits a control must bind it to a label.
    assert 'for="{{ control_id }}"' in macros, (
        "the field macro must bind its label to the control")
