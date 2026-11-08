"""Collects the audit report of the running app (audit.yml), before the agent is called.

The script asks the deployed app (`APP_URL`) a few fixed questions: do `/health`, `/` and the public
API answer, how fast, and does the app send the basic security headers. Every failed question is a
finding with a STABLE id (`security-header-x-content-type-options`, `endpoint-down-health`, ...):
the agent recognises a finding that already has an issue by this id, not by wording.

Output: `report.json` (data) and `report.md` (the same for a human) in the output directory. They
are uploaded as a workflow artifact and are never committed (`audit-report/` is git-ignored).
The script always exits 0 once the report is written: an app that is down is a finding, not a
crash of the audit. Only a bad `APP_URL` is an error.
Tests: backend/tests/test_audit_report.py. Only the standard library is used.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# The free Render plan sleeps after 15 minutes of silence and the first request takes about a
# minute (README, "Деплой на Render"): the warm-up gets a long timeout, the measured ones do not.
WARMUP_TIMEOUT = 120
REQUEST_TIMEOUT = 20
SLOW_MS = 3000

# header -> (finding id suffix, why it matters). Checked on `/`, the page a visitor opens.
SECURITY_HEADERS = {
    "x-content-type-options": "must be `nosniff`: the browser must not guess the type of a response",
    "content-security-policy": "limits where scripts and frames may come from",
    "referrer-policy": "controls how much of the address is leaked to other sites",
    "x-frame-options": "forbids showing the booking page inside someone else's frame (clickjacking)",
    "strict-transport-security": "pins the browser to https (checked only for an https app)",
}


@dataclass
class Response:
    status: int
    headers: dict[str, str]  # names in lower case
    body: bytes
    elapsed_ms: int


class FetchError(Exception):
    """The request got no HTTP answer at all (DNS, connection, timeout)."""


Fetch = Callable[[str, int], Response]


@dataclass
class Check:
    id: str
    ok: bool
    detail: str
    elapsed_ms: int | None = None


@dataclass
class Finding:
    id: str
    severity: str  # high | medium | low
    title: str
    evidence: str


@dataclass
class Report:
    app_url: str
    collected_at: str
    checks: list[Check] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def http_fetch(url: str, timeout: int) -> Response:
    request = urllib.request.Request(
        url, headers={"User-Agent": "call-calendar-audit/1"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as raw:
            status, headers, body = raw.status, raw.headers, raw.read(1_000_000)
    except (
        urllib.error.HTTPError
    ) as error:  # 4xx / 5xx are answers, not failures to connect
        status, headers, body = error.code, error.headers, error.read(1_000_000)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FetchError(str(getattr(error, "reason", error))) from error
    elapsed = int((time.monotonic() - started) * 1000)
    return Response(status, {k.lower(): v for k, v in headers.items()}, body, elapsed)


def normalize_url(raw: str) -> str:
    url = (raw or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"APP_URL must be an http(s) address, got {raw!r}")
    return url


def _json(body: bytes):
    try:
        return json.loads(body)
    except ValueError:
        return None


def collect(
    app_url: str, fetch: Fetch = http_fetch, now: Callable[[], datetime] | None = None
):
    """Ask the app the fixed questions and return the report."""
    base = normalize_url(app_url)
    clock = now or (lambda: datetime.now(UTC))
    report = Report(app_url=base, collected_at=clock().strftime("%Y-%m-%dT%H:%M:%SZ"))

    def get(path: str, timeout: int = REQUEST_TIMEOUT) -> Response | str:
        try:
            return fetch(base + path, timeout)
        except FetchError as error:
            return str(error)

    def down(check_id: str, path: str, reason: str) -> None:
        report.checks.append(
            Check(check_id, False, f"GET {path}: no answer ({reason})")
        )
        report.findings.append(
            Finding(
                f"endpoint-down-{check_id}",
                "high",
                f"{path} does not answer",
                f"GET {base}{path}: {reason}",
            )
        )

    # Warm-up: the sleeping free plan answers the first request slowly. Not measured, not judged.
    get("/health", WARMUP_TIMEOUT)

    # 1. /health
    health = get("/health")
    if isinstance(health, str):
        down("health", "/health", health)
    else:
        payload = _json(health.body)
        ok = (
            health.status == 200
            and isinstance(payload, dict)
            and payload.get("status") == "ok"
        )
        detail = f"GET /health: {health.status}"
        report.checks.append(Check("health", ok, detail, health.elapsed_ms))
        if not ok:
            report.findings.append(
                Finding(
                    "endpoint-bad-health",
                    "high",
                    "/health does not report `ok`",
                    f"GET {base}/health: status {health.status}, body {health.body[:200]!r}",
                )
            )

    # 2. The public API: what a guest's browser needs to show the booking page.
    for check_id, path in (
        ("api-calendar", "/api/calendar"),
        ("api-event-types", "/api/event-types"),
    ):
        response = get(path)
        if isinstance(response, str):
            down(check_id, path, response)
            continue
        ok = response.status == 200 and _json(response.body) is not None
        report.checks.append(
            Check(check_id, ok, f"GET {path}: {response.status}", response.elapsed_ms)
        )
        if not ok:
            report.findings.append(
                Finding(
                    f"endpoint-bad-{check_id}",
                    "high",
                    f"{path} does not return JSON with 200",
                    f"GET {base}{path}: status {response.status}, body {response.body[:200]!r}",
                )
            )

    # 3. The page itself, its speed and its headers.
    home = get("/")
    if isinstance(home, str):
        down("home", "/", home)
    else:
        ok = home.status == 200 and b"<html" in home.body.lower()
        report.checks.append(
            Check("home", ok, f"GET /: {home.status}", home.elapsed_ms)
        )
        if not ok:
            report.findings.append(
                Finding(
                    "endpoint-bad-home",
                    "high",
                    "/ does not return the page",
                    f"GET {base}/: status {home.status}",
                )
            )
        if home.elapsed_ms > SLOW_MS:
            report.findings.append(
                Finding(
                    "slow-home",
                    "medium",
                    f"/ takes longer than {SLOW_MS} ms on a warm app",
                    f"GET {base}/ took {home.elapsed_ms} ms after a warm-up request",
                )
            )
        is_https = base.startswith("https://")
        for name, why in SECURITY_HEADERS.items():
            if name == "strict-transport-security" and not is_https:
                continue
            present = name in home.headers
            # `frame-ancestors` in the CSP replaces X-Frame-Options.
            if name == "x-frame-options" and "frame-ancestors" in home.headers.get(
                "content-security-policy", ""
            ):
                present = True
            report.checks.append(Check(f"header-{name}", present, f"`{name}` on /"))
            if not present:
                report.findings.append(
                    Finding(
                        f"security-header-{name}",
                        "low",
                        f"`{name}` is missing on /",
                        f"GET {base}/ answered {home.status} without `{name}`: {why}",
                    )
                )
    return report


def to_markdown(report: Report) -> str:
    lines = [
        "# Audit report",
        "",
        f"- App: {report.app_url}",
        f"- Collected at: {report.collected_at}",
        f"- Checks: {sum(c.ok for c in report.checks)} of {len(report.checks)} passed",
        f"- Findings: {len(report.findings)}",
        "",
        "## Checks",
        "",
        "| Check | Result | Detail | ms |",
        "|---|---|---|---|",
    ]
    for check in report.checks:
        ms = "" if check.elapsed_ms is None else str(check.elapsed_ms)
        lines.append(
            f"| `{check.id}` | {'ok' if check.ok else 'FAIL'} | {check.detail} | {ms} |"
        )
    lines += ["", "## Findings", ""]
    if not report.findings:
        lines.append("None.")
    for finding in report.findings:
        lines += [
            f"### `{finding.id}` ({finding.severity})",
            "",
            finding.title,
            "",
            f"Evidence: {finding.evidence}",
            "",
        ]
    return "\n".join(lines) + "\n"


def write(report: Report, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "app_url": report.app_url,
        "collected_at": report.collected_at,
        "checks": [vars(c) for c in report.checks],
        "findings": [vars(f) for f in report.findings],
    }
    (out_dir / "report.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app-url", required=True, help="address of the deployed app")
    parser.add_argument(
        "--out", required=True, type=Path, help="directory for report.json/.md"
    )
    args = parser.parse_args(argv)
    try:
        report = collect(args.app_url)
    except ValueError as error:
        print(f"::error::{error}")
        return 1
    write(report, args.out)
    print(to_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
