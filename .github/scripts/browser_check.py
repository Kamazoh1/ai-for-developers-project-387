"""Independent browser check of a pull request (browser-check.yml) and its merge-time comparison.

`build` turns the Playwright JSON report into `result.json`: the verdict, every scenario and the
exact head SHA of the PR. The workflow uploads it as the artifact `browser-check-<head sha>`.
`verify <pr>` is for the person who decides on the merge: it downloads the artifact of the PR's
current head and refuses when the artifact belongs to another commit or the verdict is not a pass.

Scenario tags are part of the test title: `@main` marks a scenario of the feature the PR brings,
`@adjacent` a neighbouring scenario that must keep working. A `feat` PR needs both, any other PR
needs the adjacent one. Tests: backend/tests/test_browser_check.py.

Only the standard library and the `gh` CLI are used.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

TAG = re.compile(r"@(\w+)")
FEATURE_TITLE = re.compile(r"^feat(\([^)]*\))?!?:")
# Playwright test statuses: `expected` is a pass, `unexpected` a failure, `flaky` passed only after
# a retry (the config has none, so it would be a surprise and counts as a failure).
STATUS = {
    "expected": "passed",
    "unexpected": "failed",
    "flaky": "failed",
    "skipped": "skipped",
}


@dataclass(frozen=True)
class Scenario:
    title: str
    tags: tuple[str, ...]
    status: str
    duration_ms: int


def scenarios_from_report(report: dict) -> list[Scenario]:
    found: list[Scenario] = []

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                duration = sum(
                    result.get("duration", 0) for result in test.get("results", [])
                )
                found.append(
                    Scenario(
                        title=spec["title"],
                        tags=tuple(TAG.findall(spec["title"])),
                        status=STATUS.get(test.get("status", ""), "failed"),
                        duration_ms=duration,
                    )
                )
        for child in suite.get("suites", []):
            walk(child)

    for suite in report.get("suites", []):
        walk(suite)
    return found


def build_result(
    scenarios: list[Scenario],
    *,
    head_sha: str,
    merge_sha: str,
    pr_number: int,
    pr_title: str,
    run_url: str,
    finished_at: str,
) -> dict:
    def passed(tag: str) -> bool:
        return any(tag in s.tags and s.status == "passed" for s in scenarios)

    reasons = [f"scenario failed: {s.title}" for s in scenarios if s.status == "failed"]
    if not scenarios:
        reasons.append("the report has no scenarios")
    if not passed("adjacent"):
        reasons.append(
            "no passing @adjacent scenario (a neighbouring flow that must keep working)"
        )
    if FEATURE_TITLE.match(pr_title) and not passed("main"):
        reasons.append(
            "a feat PR needs a passing @main scenario (the feature in the browser)"
        )

    return {
        "head_sha": head_sha,  # the PR's head: what the merge decision is compared with
        "merge_sha": merge_sha,  # the merge result with the base that the browser really ran
        "pr": pr_number,
        "pr_title": pr_title,
        "run_url": run_url,
        "finished_at": finished_at,
        "verdict": "fail" if reasons else "pass",
        "reasons": reasons,
        "scenarios": [
            {
                "title": s.title,
                "tags": list(s.tags),
                "status": s.status,
                "duration_ms": s.duration_ms,
            }
            for s in scenarios
        ],
    }


def check_for_merge(result: dict, *, pr_head_sha: str) -> tuple[bool, str]:
    if result["head_sha"] != pr_head_sha:
        return False, (
            f"REFUSED: the artifact is for {result['head_sha']}, which is not the current head "
            f"of the PR ({pr_head_sha}). Run the browser check again on the current head."
        )
    if result["verdict"] != "pass":
        return False, (
            f"REFUSED: the browser check of {pr_head_sha} did not pass (verdict: fail): "
            + "; ".join(result["reasons"])
            + f". Logs: {result['run_url']}"
        )
    return True, (
        f"OK: the browser check passed on {pr_head_sha} "
        f"({len(result['scenarios'])} scenarios). Logs: {result['run_url']}"
    )


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout


def command_build(arguments: argparse.Namespace) -> int:
    report = json.loads(Path(arguments.report).read_text(encoding="utf-8"))
    result = build_result(
        scenarios_from_report(report),
        head_sha=os.environ["HEAD_SHA"],
        merge_sha=os.environ["MERGE_SHA"],
        pr_number=int(os.environ["PR_NUMBER"]),
        pr_title=os.environ["PR_TITLE"],
        run_url=os.environ["RUN_URL"],
        finished_at=os.environ["FINISHED_AT"],
    )
    Path(arguments.out).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(f"browser check of {result['head_sha']}: {result['verdict']}")
    for reason in result["reasons"]:
        print(f"::error title=Browser check::{reason}")
    return 0 if result["verdict"] == "pass" else 1


def command_verify(arguments: argparse.Namespace) -> int:
    head_sha = gh(
        "pr", "view", str(arguments.pr), "--json", "headRefOid", "--jq", ".headRefOid"
    ).strip()
    runs = json.loads(
        gh(
            "run",
            "list",
            "--workflow",
            "browser-check.yml",
            "--commit",
            head_sha,
            "--json",
            "databaseId",
            "--limit",
            "10",
        )
    )
    with tempfile.TemporaryDirectory() as directory:
        for run in runs:
            downloaded = subprocess.run(
                [
                    "gh",
                    "run",
                    "download",
                    str(run["databaseId"]),
                    "-n",
                    f"browser-check-{head_sha}",
                    "-D",
                    directory,
                ],
                capture_output=True,
                text=True,
                check=False,  # a missing artifact is not an error: try the next run
            )
            if downloaded.returncode == 0:
                result = json.loads(
                    (Path(directory) / "result.json").read_text(encoding="utf-8")
                )
                ok, message = check_for_merge(result, pr_head_sha=head_sha)
                print(message)
                return 0 if ok else 1
    print(
        f"REFUSED: no browser-check artifact for the current head {head_sha} of PR #{arguments.pr}."
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "build", help="Playwright JSON report -> result.json (workflow)"
    )
    build.add_argument("--report", required=True)
    build.add_argument("--out", required=True)
    build.set_defaults(handler=command_build)
    verify = commands.add_parser(
        "verify", help="compare the artifact with the PR head (merge time)"
    )
    verify.add_argument("pr", type=int)
    verify.set_defaults(handler=command_verify)
    arguments = parser.parse_args()
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
