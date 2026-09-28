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


def test_dark_mode_is_reachable_from_the_attribute_the_toggle_sets(defined):
    """The toggle writes data-theme; the stylesheet must listen to it.

    The dark theme was implemented as `.dark { ... }` while the toggle in
    base.html set `data-theme="dark"`, so no rule anywhere matched the value
    the UI actually produced. The feature was inert: the switch flipped and
    nothing happened.
    """
    css = _load_css()
    assert 'data-theme="dark"' in css, (
        "no stylesheet rule keys off [data-theme=\"dark\"], so the theme "
        "toggle cannot work")
    base = io.open(os.path.join(TEMPLATES_DIR, "base.html"), encoding="utf-8").read()
    assert 'data-theme="light"' in base, (
        "base.html should declare a default theme")
    assert "setAttribute('data-theme'" in base or \
           'setAttribute("data-theme"' in base, (
        "the toggle should drive data-theme, which is what the CSS listens to")


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
