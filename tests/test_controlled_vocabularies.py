"""Controlled vocabularies: one source of truth, enforced and displayed.

The ops schemas used to hard-code their enum values while `reference_data`
owned the real vocabularies, so the two drifted: `verdict` refused the
`conditional` outcome the reference table defines, and `discipline` was left as
free text on a field that has five defined options. The schemas now derive
from `reference_data`, and every human-facing surface renders the Arabic label
while storing the stable English key.
"""
import pytest

from app.ops.routes import (ENUM_LABEL_TABLES, SCHEMAS, enum_display,
                            enum_labels, flabel, validate_input)
from app.services.reference_data import get_reference_table
from tests.conftest import login_as

ENUM_FIELDS = [
    ("site-inspections", "test_category"),
    ("site-inspections", "verdict"),
    ("material-submittals", "consultant_action"),
    ("daily-reports", "weather"),
    ("rfis", "ball_in_court"),
    ("rfis", "priority"),
    ("rfis", "cost_impact"),
    ("rfis", "discipline"),
    ("variation-orders", "category"),
    ("variation-orders", "recommendation"),
    ("subcontractor-performances", "recommendation"),
    ("safety-reports", "inspection_type"),
    ("safety-reports", "risk_level"),
    ("safety-reports", "responsible"),
]


class TestSchemaMatchesReferenceData:

    @pytest.mark.parametrize("kind,field", ENUM_FIELDS)
    def test_schema_enum_equals_the_reference_vocabulary(self, kind, field):
        table = get_reference_table(ENUM_LABEL_TABLES[(kind, field)])
        assert list(SCHEMAS[kind]["enums"][field]) == table.keys()

    def test_no_enum_is_hard_coded_anywhere(self):
        """Every enum value must trace back to a reference table."""
        for kind, schema in SCHEMAS.items():
            for field, values in schema["enums"].items():
                key = (kind, field)
                assert key in ENUM_LABEL_TABLES, f"{kind}.{field} unmapped"
                assert list(values) == get_reference_table(
                    ENUM_LABEL_TABLES[key]).keys()

    def test_verdict_accepts_the_conditional_outcome(self):
        assert "conditional" in SCHEMAS["site-inspections"]["enums"]["verdict"]

    def test_rfi_discipline_is_now_a_controlled_field(self):
        assert "discipline" in SCHEMAS["rfis"]["enums"]
        assert len(SCHEMAS["rfis"]["enums"]["discipline"]) == 5


RFI_BASE = {"project_id": "1", "subject": "s", "question": "q"}
SITE_BASE = {"project_id": "1", "test_category": "concrete",
             "test_type": "cube 7d"}


class TestValidationAcceptsTheWholeVocabulary:

    @pytest.mark.parametrize("value", get_reference_table("rfi_discipline").keys())
    def test_every_discipline_is_accepted(self, value):
        cleaned, errors = validate_input("rfis", dict(RFI_BASE,
                                                      discipline=value))
        assert errors == []
        assert cleaned["discipline"] == value

    @pytest.mark.parametrize("value",
                             get_reference_table("test_verdicts").keys())
    def test_every_verdict_is_accepted(self, value):
        cleaned, errors = validate_input("site-inspections",
                                         dict(SITE_BASE, verdict=value))
        assert errors == []
        assert cleaned["verdict"] == value

    @pytest.mark.parametrize("bad", ["civil engineering", "مدني", "CIVIL"])
    def test_values_outside_the_vocabulary_are_refused(self, bad):
        _cleaned, errors = validate_input("rfis", dict(RFI_BASE,
                                                       discipline=bad))
        assert len(errors) == 1
        assert "غير مسموحة" in errors[0]

    def test_blank_discipline_is_simply_absent(self):
        cleaned, errors = validate_input("rfis", dict(RFI_BASE, discipline=""))
        assert errors == []
        assert "discipline" not in cleaned

    def test_refusal_message_lists_arabic_labels(self):
        _cleaned, errors = validate_input("rfis", dict(RFI_BASE,
                                                        discipline="nope"))
        assert "مدني" in errors[0]
        assert "إنشائي" in errors[0]
        assert "nope" not in errors[0]

    def test_discipline_is_trimmed_to_the_stored_key(self):
        cleaned, errors = validate_input("rfis", dict(RFI_BASE,
                                                      discipline="  civil  "))
        assert errors == []
        assert cleaned["discipline"] == "civil"


class TestDisplayLabels:

    @pytest.mark.parametrize("kind,field", ENUM_FIELDS)
    def test_every_enum_field_has_arabic_labels(self, kind, field):
        labels = enum_labels(kind).get(field)
        assert labels, f"{kind}.{field}"
        for value in SCHEMAS[kind]["enums"][field]:
            assert labels.get(value)
            assert labels[value] != value or not labels[value].isascii()

    def test_labels_cover_exactly_the_allowed_values(self):
        labels = enum_labels("rfis")
        for field in ("ball_in_court", "priority", "cost_impact", "discipline"):
            assert set(labels[field]) == set(SCHEMAS["rfis"]["enums"][field])

    def test_enum_display_falls_back_to_the_raw_value(self):
        assert enum_display("rfis", "discipline", "mep")
        assert enum_display("rfis", "discipline", "not-a-value") == "not-a-value"
        assert enum_display("rfis", "no_such_field", "x") == "x"

    def test_same_field_name_resolves_per_module(self):
        """`recommendation` is a different vocabulary in each module."""
        vo = enum_labels("variation-orders")["recommendation"]
        sub = enum_labels("subcontractor-performances")["recommendation"]
        assert set(vo) != set(sub)
        assert "اعتماد" in vo
        assert "استمرار" in sub
        assert enum_display("variation-orders", "recommendation", "اعتماد") == \
            "اعتماد"
        assert enum_display("subcontractor-performances", "recommendation",
                            "استمرار") == "استمرار"

    @pytest.mark.parametrize("kind,field", ENUM_FIELDS)
    def test_every_enum_field_has_an_arabic_field_label(self, kind, field):
        assert flabel(field), field
        assert any("\u0600" <= ch <= "\u06ff" for ch in flabel(field)), field


class TestFormRendersArabicOptions:

    def _form(self, client, kind):
        login_as(client, "t_admin")
        r = client.get(f"/ops/ui/{kind}/new")
        assert r.status_code == 200
        return r.get_data(as_text=True)

    def test_rfi_discipline_is_a_select_not_free_text(self, app, client):
        import re
        html = self._form(client, "rfis")
        block = re.search(r"<select[^>]*name=\"discipline\".*?</select>", html,
                          re.S)
        assert block, "discipline must render as a controlled select"
        values = re.findall(r"value=\"([^\"]*)\"", block.group(0))
        assert values[0] == ""
        assert values[1:] == list(SCHEMAS["rfis"]["enums"]["discipline"])

    def test_options_show_arabic_but_store_stable_keys(self, app, client):
        import re
        html = self._form(client, "rfis")
        block = re.search(r"<select[^>]*name=\"discipline\".*?</select>", html,
                          re.S)
        body = block.group(0)
        assert ">مدني<" in body
        assert ">معماري<" in body
        assert 'value="civil"' in body
        assert 'value="architectural"' in body

    def test_conditional_verdict_is_offered(self, app, client):
        import re
        html = self._form(client, "site-inspections")
        block = re.search(r"<select[^>]*name=\"verdict\".*?</select>", html,
                          re.S)
        assert block
        assert "conditional" in block.group(0)
        assert ">ناجح مشروط<" in block.group(0)

    def test_raw_english_keys_are_not_shown_as_labels(self, app, client):
        import re
        html = self._form(client, "rfis")
        block = re.search(r"<select[^>]*name=\"ball_in_court\".*?</select>",
                          html, re.S)
        assert block
        body = block.group(0)
        assert ">المقاول<" in body
        assert 'value="contractor"' in body

    def test_hints_list_arabic_values(self, app, client):
        html = self._form(client, "rfis")
        assert "القيم المسموحة:" in html
        assert "معماري" in html
