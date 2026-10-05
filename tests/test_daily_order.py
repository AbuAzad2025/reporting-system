"""The daily template runs in the approved order, and its labels carry no numbers.

The form used to open with "8.1 وصف أنشطة البناء" while the printed report
numbered from document position and opened with item 1 - the same list held in
two places, disagreeing. The order is now written out explicitly and the
numbers are gone from the labels, so there is one source of truth.

Stripping the number is the fiddly part, because the sub-designator is Arabic
and the Arabic letter range covers every letter in every Arabic word. An
unbounded class eats whole words; a single-character class with no lookahead
eats the first letter. What survives is: one or two letters, an optional
tatweel, optionally two joined by a slash, and only when standing alone.
"""
import re

import pytest

from app.services.default_templates import (_strip_leading_number,
                                            default_fields_for)

APPROVED_ORDER = [
    "report_period_label", "shift_name",
    "weather_esha", "equipment_esha", "staff_esha", "work_progress_esha",
    "mockup_approval_esha", "materials_esha", "next_day_esha", "meetings_esha",
    "eshs_desc_81", "eshs_location_82", "waste_daily_esha", "waste_mgmt_esha",
    "eshs_air_esha", "eshs_utilities_esha", "eshs_ohs_esha",
    "eshs_workcond_esha", "eshs_community_esha", "eshs_land_heritage_esha",
    "eshs_biodiversity_esha", "announcements_esha", "incidents_esha",
    "cap_esha", "stakeholder_activities_esha", "complaints_esha",
    "safety_team_esha", "photos_esha", "ncr_esha", "signatures_esha",
    "attach_attendance", "attach_complaints", "attach_scaffolding",
]


def _keys(template_key):
    return [f["key"] for f in default_fields_for(template_key)]


def test_the_daily_template_runs_in_the_approved_order():
    assert _keys("daily") == APPROVED_ORDER


def test_no_section_is_lost_or_duplicated():
    keys = _keys("daily")
    assert len(keys) == len(set(keys)), "a section appears twice"
    from app.services.default_templates import DAILY_TABLES
    defined = {k for k, _lb, _cols in DAILY_TABLES}
    assert defined <= set(keys), (
        f"tables defined but not ordered: {sorted(defined - set(keys))}")


def test_the_extras_sit_beside_the_section_they_belong_to():
    """Kept, not dropped - and not swept to the end either."""
    keys = _keys("daily")
    assert keys.index("mockup_approval_esha") == \
        keys.index("work_progress_esha") + 1, \
        "mockup approval certifies the progress section, so it follows it"
    assert keys.index("cap_esha") == keys.index("incidents_esha") + 1, \
        "a corrective action plan answers an incident, so it follows it"
    assert keys.index("ncr_esha") < keys.index("signatures_esha"), \
        "a non-conformance has to be closed before the report is signed"
    for key in ("attach_attendance", "attach_complaints",
                "attach_scaffolding"):
        assert key in keys, f"{key} was dropped"


def test_no_daily_label_starts_with_a_number():
    """The form and the document must not carry two different numbers."""
    for f in default_fields_for("daily"):
        assert not re.match(r"^\s*\d", f["label_ar"]), (
            f"{f['key']} still opens with a number: {f['label_ar']!r}")


# ------------------------------------------------------- the strip itself


@pytest.mark.parametrize("raw,expected", [
    ("1. حالة الطقس وجودة الهواء", "حالة الطقس وجودة الهواء"),
    ("8.10 الصور التوثيقية", "الصور التوثيقية"),
    ("8.4 أ. التلوث الهوائي", "التلوث الهوائي"),
    ("8.4 هـ. صحة وسلامة المجتمع", "صحة وسلامة المجتمع"),
    ("8.4 و/ز. الأراضي ومصادر الرزق", "الأراضي ومصادر الرزق"),
    ("4.ب اعتماد العينات", "اعتماد العينات"),
    ("المواد الموردة للموقع", "المواد الموردة للموقع"),
])
def test_the_number_goes_and_the_words_stay(raw, expected):
    assert _strip_leading_number(raw) == expected


@pytest.mark.parametrize("word", [
    "سجل", "جدول", "أعمال", "تنفيذ", "وصف", "المواد", "تنظيف", "الجودة",
    "utum", "mal", "hard",
])
def test_no_word_loses_its_first_letter(word):
    """The failure this regex is most likely to have.

    Two separate versions of it existed: one matched the first letter of any
    word ("سجل" -> "جل"), the next matched the whole word ("المواد" ->
    "الموردة"). Neither raised anything - the heading simply came out wrong.
    """
    assert _strip_leading_number(word) == word
    assert _strip_leading_number("8.3 " + word) == word


def test_an_empty_label_does_not_raise():
    assert _strip_leading_number("") == ""
    assert _strip_leading_number(None) == ""


# --------------------------------------------- the order is not optional


def test_an_order_that_names_an_undefined_table_raises():
    """A key added to the order with no definition must not vanish.

    The failure this guards is silence: a section named in the order but not
    defined would simply be absent from the form, and a section defined but not
    ordered would drop off the end. Both produce a shorter form and no error.
    """
    import app.services.default_templates as dt

    original = dt.DAILY_TABLES
    try:
        dt.DAILY_TABLES = list(original) + [
            ("ghost_section", "قسم غير معرّف", [])]
        with pytest.raises(KeyError, match="ghost_section"):
            default_fields_for("daily")
    finally:
        dt.DAILY_TABLES = original


def test_a_table_missing_from_the_order_raises():
    import app.services.default_templates as dt

    original = dt.DAILY_TABLES
    try:
        dt.DAILY_TABLES = list(original) + [
            ("orphan_section", "قسم ينساه الترتيب", [])]
        with pytest.raises(KeyError, match="orphan_section"):
            default_fields_for("daily")
    finally:
        dt.DAILY_TABLES = original


def test_the_other_templates_keep_their_order():
    """Only the daily template is written out; the rest are unchanged."""
    for key in ("weekly", "safety", "monthly"):
        keys = _keys(key)
        assert keys, f"{key} lost every field"
        assert len(keys) == len(set(keys))