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

TAG = re.compile(r"(?<!\S)@(\w+)")  # not the @ of an e-mail address
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


# The artifact is produced by the PR's own copy of these files. A PR that changes them can make its
# own check say what it likes, so the person who merges must read those changes first.
WATCHED_FILES = (
    ".github/scripts/browser_check.py",
    ".github/workflows/browser-check.yml",
    "e2e/playwright.config.ts",
)


def watched_files_touched(changed_files: list[str]) -> list[str]:
    return [name for name in changed_files if name in WATCHED_FILES]


def assess(directory: Path, *, pr_head_sha: str, pr_title: str) -> tuple[bool, str]:
    """The merge decision from a downloaded artifact.

    The verdict stored in the artifact is NOT trusted: it was computed by the PR's own code, and
    the title may have changed after the run. It is recomputed here, by this (base branch) copy of
    the script, from the raw Playwright report and the PR's current title. Only the head SHA and the
    run facts are taken from `result.json`. The files are searched for, so the layout of the
    artifact does not matter.
    """
    found_result = next(directory.rglob("result.json"), None)
    found_report = next(directory.rglob("playwright-report.json"), None)
    if found_result is None or found_report is None:
        return False, (
            "REFUSED: the artifact has no result.json or no playwright-report.json "
            f"(looked in {directory})."
        )
    stored = json.loads(found_result.read_text(encoding="utf-8"))
    report = json.loads(found_report.read_text(encoding="utf-8"))
    recomputed = build_result(
        scenarios_from_report(report),
        head_sha=stored["head_sha"],
        merge_sha=stored["merge_sha"],
        pr_number=stored["pr"],
        pr_title=pr_title,
        run_url=stored["run_url"],
        finished_at=stored["finished_at"],
    )
    return check_for_merge(recomputed, pr_head_sha=pr_head_sha)


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
    pr = json.loads(gh("pr", "view", str(arguments.pr), "--json", "headRefOid,title"))
    head_sha, title = pr["headRefOid"], pr["title"]
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
                ok, message = assess(
                    Path(directory), pr_head_sha=head_sha, pr_title=title
                )
                print(message)
                touched = watched_files_touched(
                    gh("pr", "diff", str(arguments.pr), "--name-only").split()
                )
                if touched:
                    print(
                        "WARNING: this PR changes the check itself ("
                        + ", ".join(touched)
                        + "): the artifact comes from the PR's own version of it. "
                        "Read those changes before trusting the result."
                    )
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
