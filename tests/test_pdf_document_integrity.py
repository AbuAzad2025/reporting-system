"""Content-level integrity tests for app/ops/pdf.py (build_ops_pdf).

These assert what the *drawn* document says, not just that a PDF came back:
the raw page streams are ASCII85+Flate decoded (see tests/pdf_tools) and the
Latin/numeric runs are matched exactly. Arabic arrives as reshaped
presentation forms in subset fonts, so it is deliberately never asserted on --
where a branch is Arabic-only (computed verdicts) the tests assert that the
branches *differ* instead of what they spell.

Deliberately not asserted (known unrelated defects):
* the hardcoded ``SIR-`` footer prefix in utils/pdf_generator._footer -- the
  numeric part and the identity-table serial are checked instead;
* the ops attachment *gallery* route, which is never populated.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from flask import has_app_context

from app.ops.pdf import build_ops_pdf
from tests.pdf_tools import PdfDocument

# ------------------------------------------------------------------ records
#: A fully populated cost-variance row. The five computed money figures are
#: supplied as values (the production ``CostVariance`` properties are pure
#: arithmetic over these same inputs: 100 x 300.5, 110 x 310.25, ...).
COST_VARIANCE = {
    "id": 42, "serial": "CVR-000042", "status": "draft",
    "status_ar": "AR-draft", "report_date": date(2026, 3, 4),
    "signatory_name": "John Doe", "review_notes": "checked on site",
    "boq_item": "Ready-mix concrete C30", "boq_ref": "BOQ-2.14",
    "unit": "m3", "currency": "SAR",
    "budgeted_qty": 100, "budgeted_rate": 300.5,
    "actual_qty": 110, "actual_rate": 310.25,
    "reestimated_qty": 120, "reestimated_rate": 330.75,
    "reason": "price escalation", "corrective_action": "negotiate rate",
    "vo_ref": "VO-000009", "schedule_impact_days": 6,
    "budgeted_total": 100 * 300.5,
    "actual_total": 110 * 310.25,
    "variance": 110 * 310.25 - 100 * 300.5,
    "variance_pct": (110 * 310.25 - 100 * 300.5) / (100 * 300.5) * 100.0,
    "reestimated_total": 120 * 330.75,
}

#: A fully populated site-inspection row (22 detail fields, 1 computed row).
SITE_INSPECTION = {
    "id": 11, "serial": "SIR-000011", "status": "approved",
    "status_ar": "AR-approved", "report_date": date(2026, 3, 4),
    "signatory_name": "Sara Engineer", "review_notes": "accepted",
    "test_category": "concrete", "test_type": "cube 7d",
    "element": "Column C-3", "axes": "C-D/3-4", "location_detail": "Level 3",
    "spec_reference": "Spec 5.2", "standard_code": "ASTM C39",
    "concrete_class": "C30/37", "slump": 175.0,
    "cube_ids": "CUBE-01,CUBE-02", "result_value": 28.0,
    "result_unit": "MPa", "acceptance_min": 25.0, "acceptance_max": 35.5,
    "verdict": "pass", "lab_name": "Riyadh Central Lab",
    "pour_permit_ref": "PP-114", "witness": "Consultant Rep",
    "follow_up": "none", "attachments": 3, "notes": "all good",
    "computed_pass": True,
}

#: Every page of a cost-variance document carries the brand footer, so the
#: em-dash baseline is 3 (contract header) + 3 x pages (footer line).
FOOTER_DASHES_PER_PAGE = 3
HEADER_DASHES = 3
COST_VARIANCE_PAGES = 2


class _ExplodingFirst(SimpleNamespace):
    """Cost-variance row whose first computed property raises."""

    @property
    def budgeted_total(self):
        raise RuntimeError("budgeted_total exploded")


class _ExplodingLast(SimpleNamespace):
    """Cost-variance row whose last computed property raises."""

    @property
    def reestimated_total(self):
        raise RuntimeError("reestimated_total exploded")


def _record(template, **overrides):
    return SimpleNamespace(**dict(template, **overrides))


def _render(kind, record, **options):
    """Render one document and return a parsed :class:`PdfDocument`."""
    settings = {"project_name": "Alpha Tower",
                "reviewer_name": "Jane Reviewer",
                "generated_at": "2026-03-04 10:00"}
    settings.update(options)
    return PdfDocument(build_ops_pdf(kind, record, **settings))


def _runs(document):
    """Latin/numeric runs of a document, as a set for exact matching."""
    return set(document.latin_text.split("\n"))


def _all_runs(document):
    """Every drawn run, including the Arabic and placeholder-only cells."""
    return document.text_runs


def _placeholder_cells(document):
    """Standalone em-dash cells -- the "no value supplied" placeholder."""
    return document.text_runs.count("—")


def _dash_count(document):
    return document.text.count("\u2014")


# ---------------------------------------------------------------- watermark
def test_draft_watermark_is_drawn_on_every_page():
    document = _render("cost-variances", _record(COST_VARIANCE))
    assert document.problems == ()
    assert document.page_count == COST_VARIANCE_PAGES
    # one watermark per page: the page callback is registered for both the
    # first and the later pages, so a 2-page draft is marked twice
    assert document.latin_text.count("DRAFT") == COST_VARIANCE_PAGES
    for number in range(1, COST_VARIANCE_PAGES + 1):
        assert "DRAFT" in document.page_text(number)


@pytest.mark.parametrize("status", ["approved", "submitted", "pending",
                                    "rejected", "amended"])
def test_watermark_is_absent_for_every_non_draft_status(status):
    document = _render("cost-variances",
                       _record(COST_VARIANCE, status=status))
    assert document.problems == ()
    assert document.page_count == COST_VARIANCE_PAGES
    assert "DRAFT" not in document.latin_text
    # the rest of the document is unaffected by the missing watermark
    assert "CVR-000042" in _runs(document)
    assert "Ready-mix concrete C30" in _runs(document)


# ------------------------------------------------------------------- money
def test_cost_variance_computed_money_rows_are_formatted_exactly():
    document = _render("cost-variances", _record(COST_VARIANCE))
    runs = _runs(document)
    assert document.problems == ()
    assert document.page_count == COST_VARIANCE_PAGES
    # thousands separator + exactly two decimals, per computed row
    assert "30,050.00" in runs          # budgeted 100 x 300.5
    assert "34,127.50" in runs          # actual 110 x 310.25
    assert "4,077.50" in runs           # variance actual - budgeted
    assert "39,690.00" in runs          # re-estimated 120 x 330.75
    assert "13.57 %" in runs            # variance ratio, 2dp + percent sign
    # unseparated / unrounded renderings must not appear as their own cell
    assert "30050.00" not in runs
    assert "34127.5" not in runs
    assert "13.569" not in runs


def test_cost_variance_input_quantities_and_rates_are_formatted_exactly():
    document = _render("cost-variances", _record(COST_VARIANCE))
    runs = _runs(document)
    assert document.problems == ()
    # whole floats collapse to grouped integers, fractions get 2 decimals
    assert "100" in runs and "110" in runs and "120" in runs
    assert "300.50" in runs and "310.25" in runs and "330.75" in runs
    assert "6" in runs                 # schedule_impact_days, plain int
    assert "300.5" not in runs
    assert "300.500" not in runs
    # raw (unformatted) rates are the model's own inputs, not the cell text
    assert "SAR" in runs and "m3" in runs and "BOQ-2.14" in runs


def test_site_inspection_measurements_are_formatted_exactly():
    document = _render("site-inspections", _record(SITE_INSPECTION))
    runs = _runs(document)
    assert document.problems == ()
    assert document.page_count == COST_VARIANCE_PAGES
    assert "28" in runs                # result_value 28.0 -> grouped integer
    assert "25" in runs                # acceptance_min 25.0
    assert "35.50" in runs             # acceptance_max 35.5 -> 2 decimals
    assert "175" in runs               # slump 175.0
    assert "3" in runs                 # attachment count
    assert "28.00" not in runs
    assert "35.5" not in runs
    assert "175.0" not in runs
    # engineering identifiers survive the subset font verbatim
    for token in ("ASTM C39", "C30/37", "CUBE-01,CUBE-02", "MPa",
                  "Riyadh Central Lab", "PP-114", "Consultant Rep",
                  "Column C-3", "C-D/3-4"):
        assert token in runs, token


def test_cost_variance_missing_reestimate_renders_an_em_dash():
    populated = _render("cost-variances", _record(COST_VARIANCE))
    blank = _render("cost-variances",
                    _record(COST_VARIANCE, reestimated_total=None))
    assert blank.problems == ()
    assert blank.page_count == populated.page_count
    assert "39,690.00" in _runs(populated)
    # reestimated_total is the one computed row that has a None branch, and
    # it costs exactly one extra em dash on the page
    assert "39,690.00" not in _runs(blank)
    assert _dash_count(blank) == _dash_count(populated) + 1
    # the other four computed rows are untouched by the None branch
    for money in ("30,050.00", "34,127.50", "4,077.50", "13.57 %"):
        assert money in _runs(blank), money


def test_site_inspection_computed_verdict_separates_all_three_branches():
    # the renderer branches on computed_pass only; the model derives it from
    # the acceptance window. All three outcomes are Arabic-only strings, so
    # the assertion is that the three renders differ, not what they spell.
    measured = dict(SITE_INSPECTION, result_value=28.5)
    documents = {
        "pass": _render("site-inspections",
                        _record(measured, computed_pass=True)),
        "fail": _render("site-inspections",
                        _record(measured, computed_pass=False)),
        "unmeasurable": _render("site-inspections",
                                _record(SITE_INSPECTION, result_value=None,
                                        computed_pass=None)),
    }
    for name, document in documents.items():
        assert document.problems == (), name
        assert document.page_count == COST_VARIANCE_PAGES, name
    texts = {document.text for document in documents.values()}
    assert len(texts) == 3, "computed verdict branches render identically"
    # pass/fail keep the measurement; unmeasurable falls back to the em dash
    assert "28.50" in _runs(documents["pass"])
    assert "28.50" in _runs(documents["fail"])
    assert "28.50" not in _runs(documents["unmeasurable"])
    assert _dash_count(documents["unmeasurable"]) == \
        _dash_count(documents["pass"]) + 1


# ---------------------------------------------------------------- computed
def test_computed_summary_degrades_to_em_dash_when_a_property_raises():
    healthy = _render("cost-variances", _record(COST_VARIANCE))
    broken = _render("cost-variances", _ExplodingFirst(**COST_VARIANCE))
    assert broken.problems == ()
    assert broken.page_count == healthy.page_count
    for money in ("30,050.00", "34,127.50", "4,077.50", "13.57 %",
                  "39,690.00"):
        assert money in _runs(healthy), money
        assert money not in _runs(broken), money
    # the whole summary table falls back to the em dash -- five rows, not one
    assert _dash_count(broken) == _dash_count(healthy) + 5


def test_late_computed_failure_degrades_the_entire_summary():
    healthy = _render("cost-variances", _record(COST_VARIANCE))
    broken = _render("cost-variances", _ExplodingLast(**COST_VARIANCE))
    assert broken.problems == ()
    assert broken.page_count == healthy.page_count
    # the None guard on reestimated_total does not protect the earlier rows:
    # one raising property takes the whole computed block down with it
    for money in ("30,050.00", "34,127.50", "4,077.50", "39,690.00"):
        assert money not in _runs(broken), money
    assert _dash_count(broken) == _dash_count(healthy) + 5
    # details and authentication blocks still render normally
    assert "Ready-mix concrete C30" in _runs(broken)
    assert "John Doe" in _runs(broken)


# ------------------------------------------------------------ module guard
@pytest.mark.parametrize("kind", ["not-a-module", "", None,
                                  "Cost-Variances", "cost_variances",
                                  "rfis "])
def test_unknown_module_raises_value_error(kind):
    record = _record(COST_VARIANCE)
    with pytest.raises(ValueError) as excinfo:
        build_ops_pdf(kind, record)
    assert "unknown ops module" in str(excinfo.value)
    assert str(kind) in str(excinfo.value)


# -------------------------------------------------------------- structure
def test_rendered_document_is_structurally_valid():
    document = _render("cost-variances", _record(COST_VARIANCE))
    assert document.data.startswith(b"%PDF-")
    assert document.problems == ()
    assert document.is_valid
    # xref offsets, trailer /Root -> /Catalog, /Count and every page stream
    # are cross-checked by PdfDocument.problems; the page tree must be real
    assert document.page_count == COST_VARIANCE_PAGES
    assert len(document.content_streams) == COST_VARIANCE_PAGES
    assert all(stream.startswith(b"1 0 0 1") for stream in
               document.content_streams)
    # identity, not just a header: /Info title is derived from serial + kind
    assert document.metadata["Title"] == "CVR-000042-cost-variances"
    assert "reportlab" in document.metadata["Producer"].lower()


def test_page_count_matches_the_footer_page_numbers():
    document = _render("cost-variances", _record(COST_VARIANCE))
    assert document.page_count == COST_VARIANCE_PAGES
    for number in range(1, COST_VARIANCE_PAGES + 1):
        assert "Page %d" % number in _runs(document)
        # every page repeats the branded footer and the numeric serial part
        assert "Generated securely via Azadexa Cloud Platform" in \
            document.page_text(number)
        assert "000042" in document.page_text(number)
    assert "Page %d" % (COST_VARIANCE_PAGES + 1) not in _runs(document)


def test_footer_carries_the_real_module_prefix_not_a_hardcoded_one():
    records = {
        "site-inspections": _record(SITE_INSPECTION, serial="SIR-000777"),
        "cost-variances": _record(COST_VARIANCE, serial="CVR-000778"),
    }
    expected = {
        "site-inspections": "SIR-000777",
        "cost-variances": "CVR-000778",
    }
    for kind, record in records.items():
        document = _render(kind, record)
        assert document.problems == (), kind
        text = document.latin_text
        assert expected[kind] in text, kind
        for other in ("SIR-", "CVR-", "RFI-", "VOR-", "MSR-", "PBR-",
                      "SPR-", "DSR-", "HSR-"):
            if other in expected[kind]:
                continue
            assert other + "00077" not in text, (kind, other)


def test_identity_signature_and_contract_parties_are_drawn():
    document = _render(
        "cost-variances", _record(COST_VARIANCE),
        project_name="Alpha Tower", project_owner="Owner Est",
        consultant="Consultant Est", contractor="Contractor Est")
    runs = _runs(document)
    assert document.problems == ()
    assert "CVR-000042" in runs          # serial in the identity grid
    assert "Alpha Tower" in runs         # project name
    assert "2026-03-04" in runs          # report date
    assert "Owner Est" in runs
    assert "Consultant Est" in runs
    assert "Contractor Est" in runs
    assert "John Doe" in runs            # quad-name signatory
    assert "Jane Reviewer" in runs       # reviewer
    assert "checked on site" in runs     # review notes
    assert "2026-03-04 10:00" in runs    # issue stamp
    # the three contract parties filled the header placeholders, which are
    # the only standalone em-dash cells: the footer em dashes are part of
    # longer runs and survive either way
    default = _render("cost-variances", _record(COST_VARIANCE))
    assert _placeholder_cells(default) == HEADER_DASHES
    assert _placeholder_cells(document) == 0
    assert _dash_count(document) == \
        FOOTER_DASHES_PER_PAGE * COST_VARIANCE_PAGES
    assert _dash_count(default) == _dash_count(document) + HEADER_DASHES


def test_reviewer_is_replaced_while_the_record_is_pending():
    document = _render("cost-variances",
                       _record(COST_VARIANCE, status="pending"))
    runs = _runs(document)
    assert document.problems == ()
    assert "Jane Reviewer" not in runs
    assert "John Doe" in runs            # author still signs
    assert "2026-03-04 10:00" in runs


# ------------------------------------------------------- attachments (DB)
class _EmptyEvidenceQuery:
    """Stand-in chain for ``Attachment.query...all()`` with no rows."""

    def order_by(self, *_args):
        return self

    def all(self):
        return []


class _NoAttachments:
    """Stand-in for the Attachment model: a reachable but empty evidence DB."""

    query = _EmptyEvidenceQuery()


def test_build_without_app_context_omits_the_evidence_appendix(monkeypatch):
    # No fixtures at all: pytest-flask only pushes a context for tests that
    # request ``app``, so the evidence query genuinely has no app context.
    assert not has_app_context()
    record = _record(SITE_INSPECTION)
    contextless = _render("site-inspections", record)
    assert contextless.problems == ()
    assert contextless.page_count == COST_VARIANCE_PAGES
    assert "SIR-000011" in _runs(contextless)
    assert "Riyadh Central Lab" in _runs(contextless)
    # reference render: database reachable, zero attachments
    monkeypatch.setattr("app.ops.models.Attachment", _NoAttachments)
    empty = _render("site-inspections", record)
    # byte-identical output proves no appendix block was appended when the
    # query is unavailable
    assert contextless.text == empty.text
    assert contextless.page_count == empty.page_count
    assert "image/png" not in contextless.latin_text
    assert "cube-scan-a.pdf" not in contextless.latin_text


def test_second_attachment_appears_in_the_evidence_appendix(app):
    from datetime import datetime
    from app.extensions import db
    from app.ops.models import Attachment, SiteInspection
    with app.app_context():
        row = SiteInspection.query.filter_by(serial="SIR-000001").one()
        record_id, project_id, uploader = row.id, row.project_id, row.user_id
        db.session.add_all([
            Attachment(record_kind="site-inspections", record_id=record_id,
                       project_id=project_id, filename="cube-scan-a.pdf",
                       storage_key="evidence/scan-a.pdf",
                       mime_type="application/pdf", byte_size=2048,
                       uploaded_by=uploader,
                       created_at=datetime(2026, 3, 4, 9, 0)),
            Attachment(record_kind="site-inspections", record_id=record_id,
                       project_id=project_id, filename="cube-scan-b.pdf",
                       storage_key="evidence/scan-b.pdf",
                       mime_type="image/png", byte_size=4096,
                       uploaded_by=uploader,
                       created_at=datetime(2026, 3, 4, 11, 0)),
        ])
        db.session.commit()
        document = _render("site-inspections",
                           _record(SITE_INSPECTION, id=record_id))
        # same record, different id: no evidence rows, hence no appendix
        without = _render("site-inspections",
                          _record(SITE_INSPECTION, id=record_id + 1000))
    runs = _runs(document)
    assert document.problems == ()
    # both rows are listed, not just the newest one
    assert "cube-scan-a.pdf" in runs
    assert "cube-scan-b.pdf" in runs
    assert "application/pdf" in runs
    assert "image/png" in runs
    assert "2026-03-04 09:00" in runs and "2026-03-04 11:00" in runs
    # newest first: the appendix is ordered by created_at descending
    assert document.latin_text.index("cube-scan-b.pdf") < \
        document.latin_text.index("cube-scan-a.pdf")
    # the appendix appends a section title plus one row per attachment
    # (3 cells each) and leaves the rest of the document untouched
    assert len(document.text_runs) - len(without.text_runs) == 2 * 3 + 1
    assert "Riyadh Central Lab" in runs
    assert "application/pdf" not in _runs(without)
