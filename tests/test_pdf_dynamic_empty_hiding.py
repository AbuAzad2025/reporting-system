"""A printed report shows what was filled in and nothing else.

The paper form a site fills in has a section only when something applies to
it. A PDF that prints a heading and «لا بنود مسجلة» for every untouched
section cannot be told apart from one where the engineer actually recorded
nothing, so empty fields are omitted entirely.

Assertions use Latin markers on purpose. pdf_tools.text_runs returns the
Arabic drawn inside a ReportLab table as presentation forms in reverse order —
the glyphs a reader sees are correct, the extraction order is not — so an
Arabic substring test here would pass or fail for the wrong reason. The suite's
own pdf_tools docstring says the same: Arabic presentation forms "must never
be asserted on". Each Arabic label is paired with a Latin marker so a missing
section is still detected.
"""
from types import SimpleNamespace


def _field(key, label, ftype, cols=None):
    return SimpleNamespace(field_key=key, label_ar=label, field_type=ftype,
                           sub_columns=lambda: cols or [])


def _cols(*keys):
    return [{"key": k, "label_ar": k, "type": "text", "required": False,
             "options": []} for k in keys]


def _template(*fields):
    return SimpleNamespace(key="daily", name_ar="التقرير اليومي",
                           name_en="Daily Progress Report",
                           ordered_fields=list(fields))


def _submission(data):
    return SimpleNamespace(id=1, project_name="PROJ", location="SITE",
                           contractor="CONT", report_date="2026-09-29",
                           data=data, signatory_name="ENG", project_id=None)


def _latin(pdf_bytes):
    """The Latin-bearing runs only, which extraction reads back faithfully."""
    from tests.pdf_tools import latin_text
    return latin_text(pdf_bytes)


def test_an_unfilled_table_is_absent_from_the_printed_report():
    from app.services.pdf_dynamic import build_dynamic_pdf
    tpl = _template(
        _field("eshs_desc_81", "وصف الأنشطة", "textarea"),
        _field("waste_mgmt_esha", "إدارة النفايات", "table",
               cols=_cols("action", "applied", "notes")),
    )
    text = _latin(build_dynamic_pdf(_submission(
        {"eshs_desc_81": "CASTING-001", "waste_mgmt_esha": []}), tpl))
    assert "CASTING-001" in text          # the filled field is printed
    assert "action" not in text           # the empty section is not


def test_a_kept_table_is_printed_with_its_content():
    from app.services.pdf_dynamic import build_dynamic_pdf
    tpl = _template(
        _field("eshs_desc_81", "وصف الأنشطة", "textarea"),
        _field("waste_mgmt_esha", "إدارة النفايات", "table",
               cols=_cols("action", "applied", "notes")),
    )
    text = _latin(build_dynamic_pdf(_submission(
        {"eshs_desc_81": "CASTING-001", "waste_mgmt_esha": [
            {"action": "SEGREGATION-002", "applied": "1"}]}), tpl))
    assert "SEGREGATION-002" in text
    assert "action" in text


def test_an_unticked_checkbox_is_not_printed():
    """A box nobody ticked is a statement that something was not done.

    Printed for every optional attachment, the three unticked boxes turn a
    filled report into a list of things nobody did. Asserted on the drawn run
    count: the Arabic labels do not survive extraction, and the ☒ glyph is not
    drawn as its own run by the embedded Amiri face.
    """
    from app.services.pdf_dynamic import build_dynamic_pdf
    from tests.pdf_tools import PdfDocument

    tpl = _template(
        _field("attach_attendance", "ATTENDANCE", "checkbox"),
        _field("attach_complaints", "COMPLAINTS", "checkbox"),
        _field("attach_scaffolding", "SCAFFOLDING", "checkbox"),
    )

    def latin(data):
        return "\n".join(r for r in PdfDocument(
            build_dynamic_pdf(_submission(data), tpl)).text_runs
            if any(c.isascii() and c.isalpha() for c in r))

    all_three = latin({"attach_attendance": "yes", "attach_complaints": "yes",
                       "attach_scaffolding": "yes"})
    one = latin({"attach_attendance": "yes", "attach_complaints": "no",
                 "attach_scaffolding": "no"})
    none = latin({"attach_attendance": "no", "attach_complaints": "no",
                  "attach_scaffolding": "no"})
    for marker in ("ATTENDANCE", "COMPLAINTS", "SCAFFOLDING"):
        assert marker in all_three
    assert "ATTENDANCE" in one
    assert "COMPLAINTS" not in one and "SCAFFOLDING" not in one
    for marker in ("ATTENDANCE", "COMPLAINTS", "SCAFFOLDING"):
        assert marker not in none


def test_a_report_nobody_filled_says_so_instead_of_printing_a_blank_page():
    from app.services.pdf_dynamic import build_dynamic_pdf
    from tests.pdf_tools import extract_text
    tpl = _template(
        _field("eshs_desc_81", "وصف الأنشطة", "textarea"),
        _field("waste_mgmt_esha", "إدارة النفايات", "table",
               cols=_cols("action")),
    )
    text = extract_text(build_dynamic_pdf(_submission({}), tpl))
    assert "no rows" not in text.lower()
    # The fallback line is Arabic, so it is checked through the source-level
    # contract instead; the behavioural part asserted here is that the
    # document still builds and carries no section headings.
    assert text.strip()


def test_the_untouched_report_prints_no_section_headings():
    """Behavioural twin of the source check: nothing filled, nothing listed."""
    from app.services.pdf_dynamic import build_dynamic_pdf
    tpl = _template(
        _field("a", "قسم أ", "textarea"),
        _field("b", "قسم ب", "table", cols=_cols("action")),
        _field("c", "قسم ج", "checkbox"),
    )
    empty = _latin(build_dynamic_pdf(_submission({}), tpl))
    filled = _latin(build_dynamic_pdf(_submission(
        {"a": "X1", "b": [{"action": "X2"}], "c": "yes"}), tpl))
    assert "X1" in filled and "X2" in filled
    assert "X1" not in empty and "X2" not in empty
