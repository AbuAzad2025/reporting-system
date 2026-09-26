"""Performance contract: a listing must not issue one query per row.

`_serialize` used to resolve the project name with `db.session.get` for every
record, so a 500-row listing cost ~501 SELECTs. These tests count the actual
statements SQLAlchemy emits, which is the only way to catch an N+1 that still
returns correct data.
"""
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.conftest import login_as

RECORDS = 40

@pytest.fixture()
def counter(app):
    """Count SELECTs emitted while the test runs.

    The engine is resolved and the listener attached inside an application
    context, so the fixture does not depend on test ordering.
    """
    from app.extensions import db
    stats = {"select": 0}

    def _count(_conn, _cursor, statement, _params, _ctx, _many):
        if statement.lstrip()[:16].upper().startswith("SELECT"):
            stats["select"] += 1

    with app.app_context():
        engine = db.engine
        event.listen(engine, "before_cursor_execute", _count)
        try:
            yield stats
        finally:
            event.remove(engine, "before_cursor_execute", _count)


def _seed(app, count=RECORDS, tag="A"):
    from app.extensions import db
    from app.models import Project, User
    from app.ops.models import RFI
    with app.app_context():
        user = User.query.filter_by(username="t_eng").one()
        project = Project.query.filter_by(name="Alpha Tower").one()
        for index in range(count):
            db.session.add(RFI(
                project_id=project.id, user_id=user.id,
                serial=f"RFI-PERF{tag}-{index:04d}", subject=f"perf {index}",
                question="q?", ball_in_court="consultant",
                priority="normal"))
        db.session.commit()
        return project.id


def test_listing_query_count_is_independent_of_row_count(app, client, counter):
    _seed(app, 5, tag="A")
    login_as(client, "t_eng")
    counter["select"] = 0
    r = client.get("/ops/rfis")
    assert r.status_code == 200
    small = len(r.get_json()["results"])
    assert small >= 5
    small_queries = counter["select"]

    _seed(app, 60, tag="B")
    counter["select"] = 0
    r = client.get("/ops/rfis")
    assert r.status_code == 200
    large = len(r.get_json()["results"])
    large_queries = counter["select"]

    assert large > small
    # A per-row lookup would add ~one query per extra record.
    assert large_queries - small_queries <= 4, (
        f"listing scaled with row count: {small_queries} -> {large_queries} "
        f"for {small} -> {large} rows")


def test_archive_query_count_is_independent_of_row_count(app, client, counter):
    _seed(app, 5, tag="A")
    login_as(client, "t_eng")
    counter["select"] = 0
    first = client.get("/ops/api/archive")
    assert first.status_code == 200
    small = first.get_json()["total"]
    small_queries = counter["select"]

    _seed(app, 60, tag="B")
    counter["select"] = 0
    second = client.get("/ops/api/archive")
    assert second.status_code == 200
    large = second.get_json()["total"]
    large_queries = counter["select"]

    assert large > small
    assert large_queries - small_queries <= 6, (
        f"archive scaled with row count: {small_queries} -> {large_queries}")


def test_project_name_is_still_correct_after_caching(app, client, counter):
    _seed(app, 3)
    login_as(client, "t_eng")
    r = client.get("/ops/rfis")
    assert r.status_code == 200
    names = {row["serial"]: row["project_name"]
             for row in r.get_json()["results"]}
    assert names
    assert set(names.values()) == {"Alpha Tower"}


def test_cache_does_not_leak_across_requests(app, client, counter):
    _seed(app, 2)
    login_as(client, "t_eng")
    first = client.get("/ops/rfis").get_json()["results"]
    assert all(row["project_name"] == "Alpha Tower" for row in first)
    second = client.get("/ops/rfis").get_json()["results"]
    assert all(row["project_name"] == "Alpha Tower" for row in second)
    assert [row["serial"] for row in first] == \
        [row["serial"] for row in second]


def test_orphan_project_id_yields_an_empty_name(app, client, counter):
    from app.extensions import db
    from app.ops.models import RFI
    with app.app_context():
        row = RFI.query.filter_by(serial="RFI-000001").one()
        row.project_id = 987654
        db.session.commit()
    login_as(client, "t_admin")
    r = client.get("/ops/rfis")
    assert r.status_code == 200
    names = {row["serial"]: row["project_name"]
             for row in r.get_json()["results"]}
    assert names.get("RFI-000001") == ""
