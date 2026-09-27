"""Turn a bandit JSON report into truthful CI output.

Why this exists
---------------
The Security Scan job used to run bandit with `|| true` and then print a
hardcoded notice claiming "no critical vulnerabilities found". That string
was emitted whatever bandit actually found, so the job could not distinguish
a clean scan from a scan that flagged HIGH severity issues. A security job
that cannot fail and cannot tell the truth is worse than no security job,
because it manufactures reassurance.

This script instead reads the real report, prints the real severity counts,
and raises one workflow annotation per finding so the results show up in the
run's Annotations tab next to everything else.

Exit status
-----------
Report-only by default: the script exits 0 so the job keeps its current
non-blocking contract. Set ``BANDIT_FAIL_ON`` to a comma-separated list of
severities to make the job a real gate, e.g. ``BANDIT_FAIL_ON=HIGH``.
"""
from __future__ import annotations

import json
import os
import sys

SEVERITIES = ("HIGH", "MEDIUM", "LOW", "UNDEFINED")


def _escape(value: str) -> str:
    """Escape a value for use inside a GitHub workflow command."""
    out = str(value)
    for char, code in (("%", "%25"), ("\r", "%0D"), ("\n", "%0A")):
        out = out.replace(char, code)
    return out.replace(":", "%3A").replace(",", "%2C")


def _fail_on() -> set:
    raw = os.environ.get("BANDIT_FAIL_ON", "").strip()
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: bandit_summary.py <bandit-report.json>", file=sys.stderr)
        return 2

    # utf-8-sig transparently accepts a report with or without a BOM.
    with open(argv[1], encoding="utf-8-sig") as handle:
        report = json.load(handle)

    totals = report.get("metrics", {}).get("_totals", {})
    counts = {sev: totals.get(f"SEVERITY.{sev}", 0) for sev in SEVERITIES}
    results = report.get("results", [])

    print("bandit severity counts: "
          + ", ".join(f"{sev}={counts[sev]}" for sev in SEVERITIES))
    print(f"bandit findings: {len(results)}")

    for finding in results:
        severity = finding.get("issue_severity", "UNDEFINED")
        path = str(finding.get("filename", "")).replace("\\", "/")
        line = finding.get("line_number", 0)
        test_id = finding.get("test_id", "?")
        text = finding.get("issue_text", "")
        level = "error" if severity == "HIGH" else "warning"
        print(f"  - {severity} {test_id} {path}:{line} {text}")
        print(f"::{level} file={_escape(path)},line={line},"
              f"title={_escape(f'{severity} {test_id}')}::{_escape(text)}")

    blocking = sorted(sev for sev in _fail_on() if counts.get(sev, 0))
    if blocking:
        print(f"BANDIT_FAIL_ON triggered by: {', '.join(blocking)}")
        return 1

    print("bandit gate: report-only (set BANDIT_FAIL_ON to make this blocking)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
