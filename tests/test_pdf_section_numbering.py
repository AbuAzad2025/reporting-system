"""The printed section number comes from the document order, not the label.

Field labels carry their numbers typed into the string - "8.4 أ. التلوث
الهوائي" - so the numbering is only as good as the last person who added a
section, and it drifts the moment one is inserted in the middle. `section_heading`
strips the typed number and applies the position instead.

The interesting cases are the Arabic sub-item designators, because the letter
range that recognises them also covers every letter in every ordinary Arabic
word. Without a lookahead the first character of the first word gets eaten:
"8.3 سجل النفايات" printed as "جل النفايات", a misspelled heading that still
looks like a heading.
"""
import pytest

from app.services.pdf_dynamic import section_heading


@pytest.mark.parametrize("label,expected", [
    # a plain number and a full stop
    ("1. حالة الطقس وجودة الهواء", "7. حالة الطقس وجودة الهواء"),
    ("4. تقدم الأشغال والتنفيذ", "7. تقدم الأشغال والتنفيذ"),
    # a dotted number, as the ESHS items use
    ("8.3 سجل النفايات اليومية", "7. سجل النفايات اليومية"),
    ("8.10 الصور التوثيقية مع التعليقات", "7. الصور التوثيقية مع التعليقات"),
    # a letter sub-designator, standing alone
    ("8.4 أ. التلوث الهوائي والغبار والضوضاء", "7. التلوث الهوائي والغبار والضوضاء"),
    ("8.4 و/ز. الأراضي ومصادر الرزق", "7. و/ز. الأراضي ومصادر الرزق"),
    # no typed number at all
    ("المواد الموردة للموقع", "7. المواد الموردة للموقع"),
    ("إجراءات إدارة النفايات (8.3)", "7. إجراءات إدارة النفايات (8.3)"),
])
def test_the_typed_number_is_replaced_by_the_position(label, expected):
    assert section_heading(label, 7) == expected


@pytest.mark.parametrize("word", [
    "سجل", "جدول", "أعمال", "تنفيذ", "وصف", "utum", "mal",
])
def test_the_first_letter_of_a_word_is_never_eaten(word):
    """The regression this whole helper exists beside.

    Every one of these begins with an Arabic letter in the sub-designator range,
    and none of them is a sub-designator. Losing the first letter produces a
    misspelling, not an error, so nothing downstream would catch it.
    """
    out = section_heading("8.3 " + word + " تفصيلية", 7)
    assert word in out, f"{word!r} lost its first letter: {out!r}"
    assert out.startswith("7. ")


def test_the_number_is_the_position_not_the_label():
    """Two sections with the same typed number must print different numbers.

    This is the drift the helper removes: both said "8.4" in the field manager,
    and the document could not show both as 8.4.
    """
    a = section_heading("8.4 أ. التلوث الهوائي", 3)
    b = section_heading("8.4 ب. المرافق العامة", 4)
    assert a.startswith("3.")
    assert b.startswith("4.")


def test_an_empty_label_still_yields_a_number():
    assert section_heading("", 12).startswith("12.")
    assert section_heading(None, 12).startswith("12.")
