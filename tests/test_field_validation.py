"""Tests for field_validation.py — full coverage."""
import pytest
from app.services.field_validation import validate_field_value, rules_from_form


class TestValidateFieldValue:

    # --- checkbox ---
    def test_checkbox_returns_none(self):
        assert validate_field_value("checkbox", True, {}) is None
        assert validate_field_value("checkbox", False, {}) is None

    # --- empty values ---
    def test_none_value_returns_none(self):
        assert validate_field_value("text", None, {}) is None
        assert validate_field_value("number", None, {}) is None

    def test_empty_string_returns_none(self):
        assert validate_field_value("text", "", {}) is None
        assert validate_field_value("number", "", {}) is None

    def test_whitespace_only_returns_none(self):
        assert validate_field_value("text", "   ", {}) is None

    # --- options validation ---
    def test_options_allowed_value_passes(self):
        assert validate_field_value("text", "red", {"options": ["red", "blue"]}) is None

    def test_options_rejected_value_fails(self):
        err = validate_field_value("text", "green", {"options": ["red", "blue"]})
        assert err is not None
        assert "غير مسموحة" in err

    def test_options_numeric_values_coerced(self):
        assert validate_field_value("text", 1, {"options": [1, 2]}) is None
        err = validate_field_value("text", 3, {"options": [1, 2]})
        assert err is not None

    # --- number type ---
    def test_number_valid_passes(self):
        assert validate_field_value("number", "42", {}) is None
        assert validate_field_value("number", "3.14", {}) is None
        assert validate_field_value("number", "-5", {}) is None

    def test_number_invalid_fails(self):
        err = validate_field_value("number", "abc", {})
        assert err is not None
        assert "رقماً" in err

    def test_number_min_boundary(self):
        assert validate_field_value("number", "10", {"min": 5}) is None
        err = validate_field_value("number", "4", {"min": 5})
        assert err is not None
        assert "≥ 5" in err

    def test_number_max_boundary(self):
        assert validate_field_value("number", "5", {"max": 10}) is None
        err = validate_field_value("number", "15", {"max": 10})
        assert err is not None
        assert "≤ 10" in err

    def test_number_min_max_combined(self):
        assert validate_field_value("number", "7", {"min": 5, "max": 10}) is None
        err = validate_field_value("number", "3", {"min": 5, "max": 10})
        assert err is not None
        err = validate_field_value("number", "12", {"min": 5, "max": 10})
        assert err is not None

    # --- text/textarea length ---
    def test_text_min_length_passes(self):
        assert validate_field_value("text", "hello", {"min_length": 5}) is None

    def test_text_min_length_fails(self):
        err = validate_field_value("text", "hi", {"min_length": 5})
        assert err is not None
        assert "قصير جداً" in err
        assert "5" in err

    def test_text_max_length_passes(self):
        assert validate_field_value("text", "hi", {"max_length": 5}) is None

    def test_text_max_length_fails(self):
        err = validate_field_value("text", "hello world", {"max_length": 5})
        assert err is not None
        assert "طويل جداً" in err
        assert "5" in err

    def test_text_min_max_combined(self):
        assert validate_field_value("text", "hello", {"min_length": 3, "max_length": 10}) is None
        err = validate_field_value("text", "hi", {"min_length": 3, "max_length": 10})
        assert err is not None
        err = validate_field_value("text", "very long text", {"min_length": 3, "max_length": 10})
        assert err is not None

    # --- pattern ---
    def test_pattern_valid_passes(self):
        assert validate_field_value("text", "abc123", {"pattern": r"^[a-z]+\d+$"}) is None

    def test_pattern_invalid_fails(self):
        err = validate_field_value("text", "ABC123", {"pattern": r"^[a-z]+\d+$"})
        assert err is not None
        assert "لا يطابق" in err

    def test_pattern_invalid_regex_returns_error(self):
        err = validate_field_value("text", "abc", {"pattern": "[invalid"})
        assert err is not None
        assert "غير صالح" in err

    def test_textarea_same_as_text(self):
        assert validate_field_value("textarea", "hello", {"min_length": 5}) is None
        err = validate_field_value("textarea", "hi", {"min_length": 5})
        assert err is not None

    # --- other types (date, dropdown, unknown) ---
    def test_date_type_returns_none(self):
        assert validate_field_value("date", "2024-01-01", {}) is None

    def test_dropdown_type_returns_none(self):
        assert validate_field_value("dropdown", "any", {}) is None

    def test_unknown_type_returns_none(self):
        assert validate_field_value("unknown", "anything", {}) is None


class TestRulesFromForm:

    def test_empty_form_returns_empty_rules(self):
        assert rules_from_form({}) == {}

    def test_min_max_float_casting(self):
        rules = rules_from_form({"rule_min": "5.5", "rule_max": "10.0"})
        assert rules == {"min": 5.5, "max": 10.0}

    def test_min_length_max_length_int_casting(self):
        rules = rules_from_form({"rule_min_length": "3", "rule_max_length": "10"})
        assert rules == {"min_length": 3, "max_length": 10}

    def test_invalid_float_ignored(self):
        rules = rules_from_form({"rule_min": "abc"})
        assert rules == {}

    def test_invalid_int_ignored(self):
        rules = rules_from_form({"rule_min_length": "abc"})
        assert rules == {}

    def test_empty_string_ignored(self):
        rules = rules_from_form({"rule_min": ""})
        assert rules == {}

    def test_valid_pattern_compiled(self):
        rules = rules_from_form({"rule_pattern": "^[a-z]+$"})
        assert rules["pattern"] == "^[a-z]+$"

    def test_invalid_pattern_ignored(self):
        rules = rules_from_form({"rule_pattern": "[invalid"})
        assert "pattern" not in rules

    def test_mixed_valid_invalid(self):
        rules = rules_from_form({
            "rule_min": "1.0",
            "rule_max": "bad",
            "rule_min_length": "2",
            "rule_max_length": "bad2",
            "rule_pattern": "[bad",
        })
        assert rules == {"min": 1.0, "min_length": 2}

    def test_whitespace_handled(self):
        rules = rules_from_form({"rule_min": "  5  "})
        assert rules == {"min": 5.0}
