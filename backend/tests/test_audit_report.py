"""The report of the scheduled audit (`.github/scripts/audit_report.py`, run by `audit.yml`).

The script asks the deployed app a few fixed questions and turns every failed one into a finding
with a stable id; the agent matches findings with existing issues by that id. The script lives
outside `backend/`, so it is loaded by path. The network is replaced by a fake `fetch`.
"""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "audit_report.py"
NOW = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)
GOOD_HEADERS = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'self'",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "strict-transport-security": "max-age=31536000",
}


@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location("audit_report", SCRIPT)
    assert spec is not None and spec.loader is not None, f"no script at {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_app(audit, *, headers=None, health=200, calendar=200, home_ms=50, down=()):
    """A fake network: path -> answer. `down` paths raise FetchError."""
    home_headers = GOOD_HEADERS if headers is None else headers

    def fetch(url: str, timeout: int):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1] if url.count("/") > 2 else "/"
        if path in down:
            raise audit.FetchError("connection refused")
        if path == "/health":
            return audit.Response(health, {}, b'{"status": "ok"}', 10)
        if path == "/api/calendar":
            return audit.Response(calendar, {}, b'{"timezone": "UTC"}', 10)
        if path == "/api/event-types":
            return audit.Response(200, {}, b"[]", 10)
        return audit.Response(200, home_headers, b"<!doctype html><html></html>", home_ms)

    return fetch


def ids(report) -> list[str]:
    return [f.id for f in report.findings]


def test_a_healthy_app_has_no_findings(audit):
    report = audit.collect("https://app.example", fake_app(audit), lambda: NOW)

    assert report.findings == []
    assert all(check.ok for check in report.checks)
    assert report.collected_at == "2026-11-09T06:00:00Z"


def test_each_missing_security_header_is_its_own_finding_with_a_stable_id(audit):
    headers = {"x-content-type-options": "nosniff"}

    report = audit.collect("https://app.example", fake_app(audit, headers=headers))

    assert ids(report) == [
        "security-header-content-security-policy",
        "security-header-referrer-policy",
        "security-header-x-frame-options",
        "security-header-strict-transport-security",
    ]
    assert {f.severity for f in report.findings} == {"low"}


def test_frame_ancestors_in_the_csp_replaces_x_frame_options(audit):
    headers = {**GOOD_HEADERS, "content-security-policy": "frame-ancestors 'none'"}
    del headers["x-frame-options"]

    report = audit.collect("https://app.example", fake_app(audit, headers=headers))

    assert report.findings == []


def test_hsts_is_not_demanded_of_a_plain_http_app(audit):
    headers = {k: v for k, v in GOOD_HEADERS.items() if k != "strict-transport-security"}

    report = audit.collect("http://localhost:8000", fake_app(audit, headers=headers))

    assert report.findings == []


def test_an_endpoint_that_does_not_answer_is_a_high_finding(audit):
    report = audit.collect("https://app.example", fake_app(audit, down=("/health",)))

    finding = next(f for f in report.findings if f.id == "endpoint-down-health")
    assert finding.severity == "high"
    assert "connection refused" in finding.evidence


def test_a_bad_status_is_a_finding_not_a_crash(audit):
    report = audit.collect("https://app.example", fake_app(audit, health=500, calendar=503))

    assert ids(report) == ["endpoint-bad-health", "endpoint-bad-api-calendar"]


def test_a_slow_home_page_is_a_medium_finding(audit):
    report = audit.collect("https://app.example", fake_app(audit, home_ms=audit.SLOW_MS + 1))

    assert ids(report) == ["slow-home"]
    assert report.findings[0].severity == "medium"


def test_the_same_app_state_gives_the_same_finding_ids(audit):
    # The agent's de-duplication relies on this: a re-run must not rename a finding.
    headers = {}
    first = audit.collect("https://app.example", fake_app(audit, headers=headers), lambda: NOW)
    second = audit.collect("https://app.example/", fake_app(audit, headers=headers), lambda: NOW)

    assert ids(first) == ids(second)


@pytest.mark.parametrize("bad", ["", "app.example", "ftp://app.example", "https://"])
def test_a_bad_app_url_is_refused(audit, bad):
    with pytest.raises(ValueError, match="APP_URL"):
        audit.collect(bad, fake_app(audit))


def test_the_report_is_written_as_json_and_markdown(audit, tmp_path):
    report = audit.collect("https://app.example", fake_app(audit, headers={}), lambda: NOW)

    audit.write(report, tmp_path / "out")

    data = json.loads((tmp_path / "out" / "report.json").read_text())
    assert data["app_url"] == "https://app.example"
    assert [f["id"] for f in data["findings"]][0] == "security-header-x-content-type-options"
    markdown = (tmp_path / "out" / "report.md").read_text()
    assert "### `security-header-x-content-type-options` (low)" in markdown


def test_main_refuses_a_bad_url_without_writing_a_report(audit, tmp_path):
    assert audit.main(["--app-url", "nope", "--out", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out").exists()
