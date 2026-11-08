"""Per-PR limit of review runs, checked by code before the model is called (review.yml).

A PR gets `max_runs` finished reviews. When they are used up, the next run refuses: it comments on
the PR once per commit, writes the reason to the job summary and exits non-zero, so the model step
never starts and the check is red instead of silently missing. Tests: backend/tests/test_review_limit.py.

Only the standard library and the `gh` CLI are used: the job has no toolchain installed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_MAX_RUNS = 5
# A run that reached a verdict used the model. `skipped` never started the job, `cancelled` was
# replaced by a newer push, and a run without a conclusion is still going.
COUNTED_CONCLUSIONS = {"success", "failure"}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    used: int
    max_runs: int
    message: str


def parse_max_runs(raw: str) -> int:
    """The repository variable REVIEW_MAX_RUNS_PER_PR; empty or broken means the default."""
    try:
        value = int(raw.strip())
    except ValueError:
        return DEFAULT_MAX_RUNS
    return value if value > 0 else DEFAULT_MAX_RUNS


def marker(head_sha: str) -> str:
    """Hidden mark of the refusal comment: one comment per commit, not one per attempt."""
    return f"<!-- review-limit:{head_sha} -->"


def count_used(runs: list[dict], pr_number: int, current_run_id: int) -> int:
    return sum(
        1
        for run in runs
        if run["id"] != current_run_id
        and pr_number in run["pull_requests"]
        and run["conclusion"] in COUNTED_CONCLUSIONS
    )


def refusal_message(used: int, max_runs: int, head_sha: str, run_url: str) -> str:
    return (
        f"{marker(head_sha)}\n"
        "**Review skipped: the limit of reviews for this PR is used up.**\n\n"
        f"- **Reason:** {used} of {max_runs} review runs are already used on this PR "
        "(the limit is the repository variable `REVIEW_MAX_RUNS_PER_PR`, 5 by default). "
        "The model was not called.\n"
        f"- **Head SHA:** `{head_sha}`. This commit was **not reviewed**.\n"
        f"- **Logs:** {run_url}\n\n"
        "To get another review, a maintainer raises the limit and pushes a commit or re-runs "
        "the check."
    )


def decide(
    runs: list[dict],
    *,
    pr_number: int,
    current_run_id: int,
    max_runs: int,
    head_sha: str,
    run_url: str,
) -> Decision:
    used = count_used(runs, pr_number, current_run_id)
    if used < max_runs:
        return Decision(
            True,
            used,
            max_runs,
            f"{used} of {max_runs} review runs used before this one",
        )
    return Decision(
        False, used, max_runs, refusal_message(used, max_runs, head_sha, run_url)
    )


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout


def fetch_runs(repo: str) -> list[dict]:
    """Runs of review.yml with the PRs they belong to (one JSON object per line)."""
    out = gh(
        "api",
        "--paginate",
        f"repos/{repo}/actions/workflows/review.yml/runs?per_page=100",
        "--jq",
        ".workflow_runs[] | {id, conclusion, pull_requests: [.pull_requests[].number]}",
    )
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def already_commented(repo: str, pr_number: int, head_sha: str) -> bool:
    out = gh(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{pr_number}/comments?per_page=100",
        "--jq",
        ".[].body",
    )
    return marker(head_sha) in out


def main() -> int:
    repo = os.environ["REPO"]
    pr_number = int(os.environ["PR_NUMBER"])
    head_sha = os.environ["HEAD_SHA"]
    run_url = os.environ["RUN_URL"]
    decision = decide(
        fetch_runs(repo),
        pr_number=pr_number,
        current_run_id=int(os.environ["RUN_ID"]),
        max_runs=parse_max_runs(os.environ.get("MAX_RUNS", "")),
        head_sha=head_sha,
        run_url=run_url,
    )
    if decision.allowed:
        print(f"Review allowed: {decision.message}.")
        return 0

    if not already_commented(repo, pr_number, head_sha):
        gh("pr", "comment", str(pr_number), "--repo", repo, "--body", decision.message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(decision.message + "\n")
    # The annotation carries the reason, the SHA and the logs link on the check itself.
    print(
        f"::error title=Review limit reached::{decision.used} of {decision.max_runs} review runs "
        f"used on PR #{pr_number}; commit {head_sha} was not reviewed; logs: {run_url}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
