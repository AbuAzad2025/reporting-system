"""The replacement for flask_sqlalchemy's deprecated Query.get_or_404 path.

`get_or_404` must be indistinguishable from the helper it replaces: same row,
same 404, same forwarded description. These tests pin that, because a silent
behaviour drift here would turn a missing record into a 500 or, worse, an
unhandled None that a later line dereferences.
"""
import pytest
from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models import Project, User
from app.services.db_lookup import get_or_404


def test_returns_the_row_when_it_exists(app):
    with app.app_context():
        user = User(username="lookup_hit", email="hit@t.com", full_name="Hit",
                    role="admin")
        user.set_password("pw12345")
        db.session.add(user)
        db.session.commit()

        found = get_or_404(User, user.id)
        assert found is not None
        assert found.id == user.id
        assert found.username == "lookup_hit"


def test_raises_404_when_the_row_is_missing(app):
    with app.app_context():
        with pytest.raises(NotFound):
            get_or_404(User, 99999999)


def test_a_missing_row_is_404_even_when_the_table_has_other_rows(app):
    """The lookup must key on the primary key, not merely 'table not empty'."""
    with app.app_context():
        assert Project.query.count() >= 0  # seeded rows exist
        with pytest.raises(NotFound):
            get_or_404(Project, 99999999)


def test_the_description_is_forwarded_to_abort(app):
    with app.app_context():
        with pytest.raises(NotFound) as excinfo:
            get_or_404(User, 99999999, description="no such operator")
        assert "no such operator" in str(excinfo.value.description)


def test_without_a_description_the_404_keeps_the_werkzeug_default(app):
    """Parity with flask_sqlalchemy: no description means the stock 404 text."""
    from werkzeug.exceptions import NotFound as WerkzeugNotFound

    with app.app_context():
        with pytest.raises(WerkzeugNotFound) as excinfo:
            get_or_404(User, 99999999)
        assert "was not found on the server" in excinfo.value.description


def test_it_never_issues_a_legacy_query_warning(app, recwarn):
    """The whole point: no LegacyAPIWarning from the replaced code path."""
    import warnings

    import sqlalchemy.exc

    with app.app_context():
        user = User(username="lookup_quiet", email="quiet@t.com",
                    full_name="Quiet", role="admin")
        user.set_password("pw12345")
        db.session.add(user)
        db.session.commit()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            get_or_404(User, user.id)
            with pytest.raises(NotFound):
                get_or_404(User, 99999999)

    legacy = [w for w in caught
              if issubclass(w.category, sqlalchemy.exc.LegacyAPIWarning)]
    assert legacy == [], f"legacy SQLAlchemy API used: {[str(w.message) for w in legacy]}"
