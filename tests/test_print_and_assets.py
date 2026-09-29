"""Print output: a report is a document, not a screenshot of an application.

The print layer used to consist of two @media print blocks in two stylesheets
that contradicted each other - one set the body background from the *theme*
variables, so a user in dark mode printed dark ink on a grey page. Both styled
`.table` and `.report-section`, classes no template uses, so the real table and
card styles got no print treatment at all, while both hid every `<nav>` and
`<footer>` by element name, which would also hide a `<nav>` inside report data.
"""
import io
import os
import re

import pytest

STATIC_DIR = os.path.join("static", "css")


def _all_css():
    return "\n".join(
        io.open(os.path.join(STATIC_DIR, name), encoding="utf-8").read()
        for name in sorted(os.listdir(STATIC_DIR)) if name.endswith(".css"))


def _print_blocks(css):
    """Every @media print body, as a list of strings."""
    blocks = []
    for match in re.finditer(r"@media\s+print\s*\{", css):
        depth = 1
        index = match.end()
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        blocks.append(css[match.end():index - 1])
    return blocks


@pytest.fixture(scope="module")
def css():
    return _all_css()


@pytest.fixture(scope="module")
def print_blocks(css):
    return _print_blocks(css)


def test_exactly_one_print_layer_exists(print_blocks):
    assert len(print_blocks) == 1, (
        f"{len(print_blocks)} @media print blocks. They are loaded in sequence, "
        "so the last one silently wins for any property they share and the "
        "result depends on stylesheet order rather than on intent.")


def test_printing_never_inherits_the_theme(print_blocks):
    """Dark mode must not decide what comes out of the printer."""
    block = print_blocks[0]
    assert "--slate-" not in block, (
        "the print block references theme variables, so a user in dark mode "
        "prints light text on a dark page")
    assert re.search(r"background:\s*#fff", block)
    assert re.search(r"color:\s*#000", block)


def test_the_page_geometry_is_declared(print_blocks):
    assert "@page" in print_blocks[0], (
        "without @page the browser's default margins apply, which vary by "
        "locale and leave no room for a footer")
    page = re.search(r"@page\s*\{([^}]*)\}", print_blocks[0]).group(1)
    assert re.search(r"size:\s*A4", page)
    assert re.search(r"margin:", page)
    bottom = re.search(r"margin:[^;]*;?", page).group(0)
    assert "bottom" in bottom or page.count("mm") >= 3


def test_the_application_chrome_is_hidden_by_class_not_by_element_name(print_blocks):
    block = print_blocks[0]
    for element in ("nav", "footer", "header"):
        assert not re.search(r"(?m)^\s*%s\s*," % element, block), (
            "hiding <%s> by element name also hides one inside report data"
            % element)
    for required in (".app-header", ".app-nav", ".app-footer", ".flash-stack",
                     "#toast-root"):
        assert required in block, f"{required} is not hidden when printing"


def test_the_print_rules_target_the_classes_templates_actually_use(print_blocks):
    """A print rule for a class nobody renders is decoration."""
    block = print_blocks[0]
    for dead in (".table ", ".report-section", ".card,"):
        assert dead not in block, (
            f"{dead.strip()} is styled for print but no template uses it")
    assert ".data-table" in block
    assert ".surface-card" in block


def test_a_printed_page_carries_its_own_letterhead_and_signatures(print_blocks):
    """Removing the web chrome leaves nothing behind unless something replaces it."""
    block = print_blocks[0]
    assert ".print-only" in block
    assert ".print-letterhead" in block
    assert ".print-signatures" in block
    assert ".print-disclaimer" in block


def test_tables_survive_pagination(print_blocks):
    block = print_blocks[0]
    assert "table-header-group" in block, (
        "column headings do not repeat on page two of a long report")
    assert re.search(r"break-inside:\s*avoid", block)
    assert re.search(r"break-after:\s*avoid", block) or \
        re.search(r"page-break-after:\s*avoid", block)


def test_a_printed_link_does_not_leak_its_url_into_every_row(print_blocks):
    """Appending the href after every link turns data tables into noise."""
    block = print_blocks[0]
    assert "attr(href)" not in block, (
        "every printed link is followed by its URL, which is unreadable in a "
        "table of values and wastes a line of every row")


def test_dark_mode_rules_cannot_leak_into_print(css):
    """The dark theme is scoped to a selector that print must not match."""
    for match in re.finditer(r'\[data-theme="dark"\][^{]*\{', css):
        assert "@media print" not in css[max(0, match.start() - 400):match.start()], (
            "a dark-theme rule sits inside a print block")


#: Words that belong to the platform, not to a tenant's report. A document
#: carrying one of these is a document carrying the vendor's name, which is the
#: thing the branding work was for.
_PLATFORM_WORDS = ("Page ", "DRAFT", "Generated securely", "Generated via")

#: Where a document is composed. Each of these can put English on a page.
_PDF_MODULES = ("utils/pdf_generator.py", "app/ops/pdf.py", "app/ops/batch.py",
                "app/services/pdf_dynamic.py")


def test_the_document_title_stays_machine_readable():
    """A non-Latin /Title is written as UTF-16 with a byte-order mark.

    That hides the serial from anything reading the file's metadata and shows
    as mojibake in a viewer. The title was briefly carrying the organisation's
    Arabic name, which did exactly that; the organisation belongs in /Author,
    which is read, not parsed.

    The whole argument is checked, expressions included. A first version only
    looked at the literal parts of the f-string, so ``{brand.company_ar}`` -
    the exact thing being banned - passed it.
    """
    banned = re.compile(r"company_ar|company_en|name_ar|brand|tenant",
                        re.I)
    for path in _PDF_MODULES:
        if not os.path.isfile(path):
            continue
        body = io.open(path, encoding="utf-8").read()
        for match in re.finditer(r"title\s*=\s*f?[\"']([^\"']*)[\"']", body):
            value = match.group(1)
            assert not banned.search(value), (
                "%s: the document title reads %r, which carries a name and so "
                "will be written as UTF-16 with a byte-order mark" % (path, value))
            for part in re.findall(r"\{[^}]*\}|[^{}]+", value):
                if "{" not in part:
                    assert re.match(r"\A[A-Za-z0-9_\-\.:]*\Z", part), (
                        "%s: title contains non-Latin text %r" % (path, part))


def test_no_english_platform_survives_into_a_generated_report():
    """The footers and the draft watermark are written by hand.

    They are the only text in a report that is not Arabic, and each one was
    English by default: "Page 3", "DRAFT", "Generated securely via Azadexa
    Cloud Platform". A tenant's own line overrides the third, but never the
    first two.
    """
    drawn = re.compile(
        r'draw(?:String|CentredString|RightString)\(|watermark\s*=|'
        r'platform_line\s*=|or\s+"[^"]*"\)')

    offenders = []
    for path in _PDF_MODULES:
        if not os.path.isfile(path):
            continue
        for number, line in enumerate(io.open(path, encoding="utf-8"), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not drawn.search(line):
                continue
            for word in _PLATFORM_WORDS:
                if word in line:
                    offenders.append("%s:%d  %s" % (path, number,
                                                     stripped[:70]))
    assert not offenders, (
        "English left on the page of an Arabic report:\n  "
        + "\n  ".join(offenders))


def test_the_page_number_and_watermark_are_arabic():
    generator = io.open("utils/pdf_generator.py", encoding="utf-8").read()
    assert "صفحة" in generator, (
        "the page number has to be in the language of the document")
    ops = io.open("app/ops/pdf.py", encoding="utf-8").read()
    assert "WORKFLOW_AR" in ops, (
        "the watermark should come from the status map that already exists, "
        "not from a hand-written word")
    assert '"DRAFT"' not in ops, "an English watermark is still on the page"


#: Latin values that are identifiers rather than prose: field keys a
#: template asks the administrator to key a column by, and a pagination
#: fragment. A reader never sees these as prose.
_TECHNICAL = {"key", "manpower", "equipment", "materials", "visitors",
              "variation", "daily", "weekly", "monthly", "safety"}


def test_no_english_reaches_the_templates():
    """A line-by-line scan of every literal the reader can see.

    Jinja expressions, digits and technical field keys are excluded: they are
    identifiers, not prose. The two things this found were alt="Avatar", in
    two templates.
    """
    text_node = re.compile(r">([^<>{}]+)<")
    attribute = re.compile(r'\b(placeholder|title|alt|aria-label)="([^"]*)"')
    seen = set()
    for dirpath, _dirs, files in os.walk("templates"):
        for name in files:
            if not name.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), "templates")
            body = io.open(os.path.join(dirpath, name),
                           encoding="utf-8").read()
            candidates = [m.group(1).strip() for m in text_node.finditer(body)]
            candidates += [m.group(2).strip() for m in attribute.finditer(body)]
            for value in candidates:
                if not value or not re.search(r"[A-Za-z]{2,}", value):
                    continue
                if re.search(r"[؀-ۿ]", value):
                    continue
                if "{{" in value or "{%" in value:
                    continue
                if value in _TECHNICAL:
                    continue
                if "=" in value or "&" in value:
                    continue
                if not re.fullmatch(r"[A-Za-z0-9 \.\-_/#%\?=&:,\+]+", value):
                    continue
                seen.add((rel, value))
    assert not seen, ("Latin text a reader can see: %s"
                      % ", ".join("%s: %r" % pair for pair in sorted(seen)))


def test_the_manifest_declares_the_icon_sizes_the_files_actually_have():
    """A manifest that lies about its icons fails install validation."""
    import json
    import struct
    manifest = json.load(io.open("static/manifest.json", encoding="utf-8"))
    assert manifest["icons"], "the manifest declares no icons"
    for icon in manifest["icons"]:
        rel = icon["src"].replace("/static/", "").lstrip("/")
        path = os.path.join("static", rel.replace("/", os.sep))
        assert os.path.isfile(path), f"manifest references a missing file: {icon['src']}"
        with open(path, "rb") as fh:
            header = fh.read(24)
        width, height = struct.unpack(">II", header[16:24])
        assert icon["sizes"] == f"{width}x{height}", (
            f"{icon['src']} is {width}x{height} but the manifest claims "
            f"{icon['sizes']}")


def test_the_service_worker_does_not_cache_authenticated_pages():
    """A cached dashboard outlives logout and is served to the next person."""
    sw = io.open("static/sw.js", encoding="utf-8").read()
    assert "request.mode === 'navigate'" in sw, (
        "navigations are not excluded from the cache")

    handler = sw[sw.index("request.mode === 'navigate'"):]
    handler = handler[:handler.index("if (!isStaticAsset")]
    assert "fetch(request)" in handler, "a navigation does not go to the network"
    assert "caches.match" not in handler and "caches.put" not in handler, (
        "a navigation is answered from, or written to, the cache")

    assert "azadexa-static-v2" in sw, (
        "the cache name is not versioned, so stale entries survive upgrades")


def test_the_service_worker_only_caches_static_assets(sw_text=None):
    sw = sw_text or io.open("static/sw.js", encoding="utf-8").read()
    assert "/static/" in sw
    assert "if (!isStaticAsset(url)) return;" in sw
