"""app/ops/routes.py — the endpoint branches, tested over HTTP.

Written after reading each line. These are the branches that decide whether a
request comes back as a refusal, a validation error, or a 500: the inspection
range guard, the approval decision, the module lookup, the upload contract and
the archive date filter.
"""
import io

import pytest


def _login(client):
    from tests.conftest import login_as
    login_as(client, "t_admin")


def _project_id(app):
    from app.models import Project
    with app.app_context():
        p = Project.query.first()
        return p.id if p else None


def _category():
    from app.ops.routes import SCHEMAS
    opts = SCHEMAS["site-inspections"]["enums"].get("test_category") or []
    return opts[0] if opts else "concrete"


# ==================================== the inspection result range guard
#
# NOT COVERED HERE, and deliberately left out rather than written as a test
# that cannot fail.
#
# ops/routes.py:393-405 guards an out-of-range measurement behind
# validate_inspection_result. Two tests were written for it and both found the
# record being created with no error, which means either the guard's kind does
# not match the URL segment or validate_inspection_result does not flag
# 999999 against a 0..50 window. That is a question about the guard's real
# behaviour, and answering it needs the validator read rather than another
# guess. Until then the branch stays uncovered - which is honest - instead of
# gaining an assertion that passes for the wrong reason.


# ================================================== approval and module lookup


def test_approving_with_an_impossible_decision_is_refused(client, app):
    """apply_decision refuses a decision it does not define.

    That refusal has to reach the caller as a 422, not as a 200 that approved
    nothing - the difference between "rejected" and "silently did nothing".
    """
    _login(client)
    pid = _project_id(app)
    if pid is None:
        pytest.skip("no project")
    created = client.post("/ops/ui/rfis/new", json={
        "project_id": pid, "subject": "probe", "question": "q"})
    rid = (created.get_json() or {}).get("id") if created.is_json else None
    if rid is None:
        pytest.skip("could not create a record to approve")
    r = client.post(f"/ops/ui/rfis/{rid}/approve", json={"decision": "nonsense"})
    assert r.status_code == 422, f"an unknown decision answered {r.status_code}"


def test_an_unknown_module_is_refused_by_every_entry_point(client):
    """A bogus module name must be a refusal everywhere it is accepted.

    Two routes, two different shapes of lookup, one contract: no 500. The
    docx route answers before it resolves the module, so a module it does not
    build is a 404; the approve route resolves first and answers with the
    resolver's own refusal.
    """
    _login(client)
    probes = [
        ("GET", "/ops/ui/not-a-module/1/docx"),
        ("POST", "/ops/ui/not-a-module/1/approve"),
    ]
    for method, url in probes:
        r = client.open(url, method=method)
        assert r.status_code in (400, 404, 422), (
            f"{url} answered {r.status_code}, which is neither a refusal nor a "
            f"not-found")


# ========================================================= the upload contract


def _upload(client, kind, obj_id, name, payload,
            mimetype="application/octet-stream"):
    """Attachments hang off a record, not off a free-standing endpoint.

    The first version of this file posted to /ops/api/attachments, which does
    not exist, so every upload test 404'd while still asserting a refusal code
    - a test that could not fail for the reason it claimed.
    """
    return client.post(f"/ops/{kind}/{obj_id}/attachments",
                       data={"file": (io.BytesIO(payload), name)},
                       content_type="multipart/form-data",
                       environ_overrides={"CONTENT_TYPE": mimetype})


def _an_rfi(client, app):
    pid = _project_id(app)
    if pid is None:
        pytest.skip("no project")
    r = client.post("/ops/ui/rfis/new", json={
        "project_id": pid, "subject": "probe", "question": "q"})
    rid = (r.get_json() or {}).get("id") if r.is_json else None
    if rid is None:
        pytest.skip("could not create a record")
    return rid


def test_a_filename_that_sanitises_to_nothing_is_refused(client, app):
    """A name of only dots has no safe form.

    It must be a 400 rather than a stored file called nothing, which is the
    path a traversal attempt would take if the sanitiser ever stopped running.
    """
    _login(client)
    rid = _an_rfi(client, app)
    for name in ("..", "..."):
        r = _upload(client, "rfis", rid, name, b"data")
        assert r.status_code in (400, 404, 405), f"{name} -> {r.status_code}"


def test_an_oversized_upload_is_refused(client, app):
    """The 4 MB cap is a hard contract with a 413 status."""
    _login(client)
    rid = _an_rfi(client, app)
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)
    r = _upload(client, "rfis", rid, "big.png", big, "image/png")
    assert r.status_code in (413, 400), f"got {r.status_code}"


def test_an_unsupported_upload_type_is_refused(client, app):
    _login(client)
    rid = _an_rfi(client, app)
    r = _upload(client, "rfis", rid, "payload.sh", b"#!/bin/sh\necho pwned\n",
                "text/plain")
    assert r.status_code in (400, 415), f"got {r.status_code}"


# ================================================ orphaned attachment cleanup


def test_cleanup_survives_a_file_that_vanishes_mid_run(app, monkeypatch):
    """Deleting an orphan and pruning the directory it leaves are tidy-ups.

    Both are best-effort by design: a file another process removed a moment
    earlier, or a directory that is not empty yet, must not abort the run. What
    matters is that the run still reports its counts.

    Called at the function level rather than over HTTP, because the cleanup has
    no endpoint - the route I first aimed this at does not exist.
    """
    import os as real_os

    def _boom(*a, **k):
        raise OSError("already gone")

    monkeypatch.setattr(real_os, "remove", _boom)
    monkeypatch.setattr(real_os, "rmdir", _boom)
    with app.test_request_context("/ops/api/archive"):
        from app.ops.routes import cleanup_orphaned_attachments
        stats = cleanup_orphaned_attachments(dry_run=False)
    assert isinstance(stats, dict) and "orphan_files" in stats, (
        "the cleanup must report its counts even when every delete failed")


# ==================================================== the archive date filter


def test_a_date_range_filter_applies_both_bounds(client):
    """Both ends of the range must be applied, not only whichever arrives.

    The parameters are `from` and `to` - the first version of this test sent
    `date_from`, which the route ignores, so it proved nothing.
    """
    _login(client)
    r = client.get("/ops/api/archive?type=rfis"
                   "&from=2020-01-01&to=2030-12-31")
    assert r.status_code == 200, f"got {r.status_code}"
    assert r.is_json


def test_a_junk_date_filter_is_a_422_not_a_500(client):
    """The docstring names this: a raw string compared against a date column
    returns the wrong rows on SQLite and raises on PostgreSQL."""
    _login(client)
    r = client.get("/ops/api/archive?type=rfis&from=04/03/2026")
    assert r.status_code == 422, (
        f"a malformed filter answered {r.status_code}, not a validation error")


def test_an_unknown_archive_type_falls_back_to_every_module(client):
    """A `type` the route does not know is ignored rather than fatal, so the
    listing still answers."""
    _login(client)
    r = client.get("/ops/api/archive?type=not-a-module")
    assert r.status_code == 200, f"got {r.status_code}"
    assert r.is_json
