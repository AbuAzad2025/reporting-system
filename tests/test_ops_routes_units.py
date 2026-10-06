"""app/ops/routes.py — input handling, tested at the unit level.

Each test here was written after reading the line it covers. These are the
functions that decide whether a malformed date is an omission or an error, and
whether an empty project link is dropped or stored as "" — the two places where
SQLite and PostgreSQL disagree, and where SQLite agreeing is the bug.
"""
import pytest

from app.ops import routes as ops_routes


# ================================================== date parsing and filters


def test_a_whitespace_only_date_is_absent_not_an_error():
    """A lone space is what actually reaches here.

    The route guard skips "" and None before calling this, so the one input
    that gets past it is a value that is neither: " ", which strip() empties. It
    must come back as None with no error, because a blank date is an omission
    the engineer left, not a mistake they made.
    """
    errors = []
    assert ops_routes._parse_date("   ", "some_date", errors) is None
    assert errors == [], "a blank date is an omission, not a mistake"


def test_a_null_or_empty_date_is_absent_too():
    errors = []
    assert ops_routes._parse_date(None, "d", errors) is None
    assert ops_routes._parse_date("", "d", errors) is None
    assert errors == []


def test_a_real_date_is_parsed():
    errors = []
    got = ops_routes._parse_date("2026-03-04", "d", errors)
    assert str(got) == "2026-03-04"
    assert errors == []


def test_a_junk_date_is_reported():
    """Reported, not dropped: the writer has to know the date did not save."""
    errors = []
    assert ops_routes._parse_date("not-a-date", "date_from", errors) is None
    assert errors, "a malformed date must be reported, not silently dropped"


def test_a_numeric_date_argument_is_refused_not_500():
    """A JSON body carries the date as a number.

    Calling .strip() on it raises AttributeError, which turns a bad filter into
    a 500 - and the docstring on _parse_date_arg names exactly this.
    """
    with pytest.raises(ValueError):
        ops_routes._parse_date_arg(20260304, "«من»")


def test_a_blank_date_argument_is_absent():
    assert ops_routes._parse_date_arg(None) is None
    assert ops_routes._parse_date_arg("   ") is None
    assert ops_routes._raw_date_arg(None) is None
    assert ops_routes._raw_date_arg("   ") is None


def test_a_valid_raw_date_argument_passes_through():
    assert ops_routes._raw_date_arg(" 2026-03-04 ") == "2026-03-04"


def test_a_junk_date_argument_raises_rather_than_guessing():
    """A date column compared against a raw string returns the wrong rows on
    SQLite and raises on PostgreSQL. Guessing is not an option."""
    for bad in ("04/03/2026", "yesterday", "2026-13-45"):
        with pytest.raises(ValueError):
            ops_routes._parse_date_arg(bad)


# ========================================================== project naming


def test_a_record_with_no_project_resolves_to_an_empty_name(app):
    """Not every ops row is linked to a project, and serialising one must not
    raise on the way to the listing."""
    with app.test_request_context("/ops/api/archive"):
        assert ops_routes._project_name(None) == ""


def test_a_linked_project_resolves_by_name(app):
    from app.models import Project
    with app.app_context():
        p = Project.query.first()
        if p is None:
            pytest.skip("no project")
        pid, name = p.id, p.name
    with app.test_request_context("/ops/api/archive"):
        assert ops_routes._project_name(pid) == name


# ============================================================= enum labels


def test_every_controlled_vocabulary_has_a_display_table():
    """The invariant that made enum_labels' guard unreachable.

    That function skipped an enum field with no label table. Every enum in
    SCHEMAS has one - which is what this asserts - so the skip could not fire
    and the branch was dead rather than merely untested. Unreachable code is
    not protecting anything, and a test written to execute it would report
    coverage that says nothing. This test is what makes the removal safe: add
    an enum field without a table and it fails.
    """
    from app.ops.routes import SCHEMAS, ENUM_LABEL_TABLES
    missing = [(k, f) for k, s in SCHEMAS.items()
               for f in s.get("enums", {}) if (k, f) not in ENUM_LABEL_TABLES]
    assert not missing, (
        f"enum fields with no Arabic label table: {missing}. enum_labels "
        f"would silently return nothing for these.")


def test_enum_labels_returns_choices():
    labels = ops_routes.enum_labels("rfis")
    assert "discipline" in labels
    assert labels["discipline"], "the vocabularies must resolve to choices"


# ============================================ the project link, unit level


def _a_user(app):
    from app.models import User
    with app.app_context():
        return User.query.first()


def test_a_missing_project_link_is_dropped_not_stored_as_empty(app):
    """An empty project_id would reach the column as "".

    SQLite binds that happily; PostgreSQL raises on the integer column. The two
    engines disagreeing is how a form that works on a laptop fails on the
    server, so the key is dropped rather than stored empty.
    """
    user = _a_user(app)
    if user is None:
        pytest.skip("no user")
    cleaned = ops_routes._apply_project_link(user, {"project_id": "", "x": 1})
    assert "project_id" not in cleaned
    assert cleaned["x"] == 1, "the rest of the payload must survive"

    cleaned = ops_routes._apply_project_link(user, {"x": 1})
    assert "project_id" not in cleaned


def test_a_non_numeric_project_id_is_refused_with_a_clear_message(app):
    """"abc" must not become project 0, and the message must be actionable."""
    user = _a_user(app)
    if user is None:
        pytest.skip("no user")
    with pytest.raises(ValueError) as exc:
        ops_routes._apply_project_link(user, {"project_id": "abc"})
    assert "رقم المشروع" in str(exc.value)
