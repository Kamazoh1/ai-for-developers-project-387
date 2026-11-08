"""The merge gate (merge-gate.yml): the human decision to merge, recorded against one commit.

A person approves a merge by adding the label `merge-approved` to a PR once the checks are green.
The gate then checks, on the PR's CURRENT head SHA, who approved, that every required check is green
on that commit, that the browser artifact belongs to it and passes, and that the review of this
commit has no blocker. It records the result as the commit status `merge-gate` and a comment with
who, which SHA and when. A new commit has a new SHA with no approval: the gate resets itself and
removes the label. A refused approval removes the label too, with every reason in a comment.

Run by `pull_request_target` from the BASE branch, without checking out PR code: the gate cannot be
edited by the PR it judges. Tests: backend/tests/test_merge_gate.py. Standard library and `gh` only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

LABEL = "merge-approved"
CONTEXT = "merge-gate"
REQUIRED_CHECKS = ("verify", "image", "browser-check", "review")
WRITE_LEVELS = {"write", "maintain", "admin"}
BLOCKERS = re.compile(r"blockers:\s*(\d+)", re.IGNORECASE)


@dataclass
class Decision:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)


def marker(head_sha: str) -> str:
    return f"<!-- merge-gate:{head_sha} -->"


def status_description(text: str) -> str:
    """GitHub allows 140 characters in a commit status description."""
    return text if len(text) <= 140 else text[:139] + "…"


def latest_runs(check_runs: list[dict]) -> dict[str, dict]:
    """The latest run of every check name: a re-run replaces the earlier one."""
    latest: dict[str, dict] = {}
    for run in check_runs:
        known = latest.get(run["name"])
        if known is None or run["started_at"] > known["started_at"]:
            latest[run["name"]] = run
    return latest


def check_problems(check_runs: list[dict]) -> list[str]:
    latest = latest_runs(check_runs)
    problems = []
    for name in REQUIRED_CHECKS:
        run = latest.get(name)
        if run is None:
            problems.append(f"{name}: no run for this commit")
        elif run["status"] != "completed":
            problems.append(f"{name}: still running")
        elif run["conclusion"] != "success":
            problems.append(f"{name}: {run['conclusion']}")
    return problems


def review_blockers(comments: list[dict], review_started_at: str | None) -> int | None:
    """Blockers in the newest review comment written since the review run of this commit started."""
    if review_started_at is None:
        return None
    fresh = [
        comment
        for comment in comments
        if comment["user"]["login"] == "claude[bot]"
        and comment["created_at"] >= review_started_at
        and BLOCKERS.search(comment["body"])
    ]
    if not fresh:
        return None
    newest = max(fresh, key=lambda comment: comment["created_at"])
    return int(BLOCKERS.search(newest["body"]).group(1))  # type: ignore[union-attr]


def decide(
    *,
    sender_type: str,
    sender_login: str,
    permission: str,
    pr_open: bool,
    pr_draft: bool,
    event_head_sha: str,
    current_head_sha: str,
    check_runs: list[dict],
    comments: list[dict],
    browser_ok: bool,
    browser_message: str,
) -> Decision:
    decision = Decision(ok=False)
    if sender_type != "User":
        decision.reasons.append(
            f"{sender_login} is not a person ({sender_type}): the decision to merge is a human's"
        )
    elif permission not in WRITE_LEVELS:
        decision.reasons.append(
            f"{sender_login} has no write access to the repository (permission: {permission})"
        )
    if not pr_open:
        decision.reasons.append("the PR is not open")
    if pr_draft:
        decision.reasons.append("the PR is a draft")
    if event_head_sha != current_head_sha:
        decision.reasons.append(
            f"the head moved since the label was added: the approval was for {event_head_sha}, "
            f"the head is now {current_head_sha}"
        )
    decision.reasons.extend(check_problems(check_runs))
    if not browser_ok:
        decision.reasons.append(browser_message)

    review_run = latest_runs(check_runs).get("review")
    blockers = review_blockers(
        comments, review_run["started_at"] if review_run else None
    )
    if blockers is None:
        decision.notes.append(
            "no review verdict was written for this commit (a PR that changes the review "
            "workflow itself is not reviewed by it): decide on the diff yourself"
        )
    elif blockers > 0:
        decision.reasons.append(
            f"the review of this commit reports {blockers} blocker(s)"
        )
    else:
        decision.checked.append("review verdict: 0 blockers")

    decision.checked[:0] = [f"{name}: success" for name in REQUIRED_CHECKS]
    decision.ok = not decision.reasons
    return decision


def approval_comment(
    login: str, head_sha: str, now: str, decision: Decision, run_url: str
) -> str:
    lines = [
        marker(head_sha),
        f"**Merge approved by @{login} for `{head_sha}` at {now}.**",
        "",
        "Checked on this commit: " + "; ".join(decision.checked) + ".",
        "The browser-check artifact belongs to this head SHA and passes.",
    ]
    lines += [f"- Note: {note}" for note in decision.notes]
    lines += [
        "",
        f"A new commit has a new SHA and needs a new approval. Gate run: {run_url}",
    ]
    return "\n".join(lines)


def refusal_comment(login: str, head_sha: str, decision: Decision, run_url: str) -> str:
    lines = [
        marker(head_sha),
        f"**Merge approval by @{login} refused for `{head_sha}`.**",
        "",
        "Reasons:",
    ]
    lines += [f"- {reason}" for reason in decision.reasons]
    lines += [
        "",
        (
            f"The label `{LABEL}` was removed. When the reasons are gone, add it again. "
            f"Gate run: {run_url}"
        ),
    ]
    return "\n".join(lines)


# --- the side effects -------------------------------------------------------------------------


def gh(*args: str, check: bool = True) -> str:
    done = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if check and done.returncode != 0:
        raise subprocess.CalledProcessError(
            done.returncode, done.args, done.stdout, done.stderr
        )
    return done.stdout


def json_lines(path: str, jq: str) -> list[dict]:
    """Every page of an API list as one JSON object per line (no dependency on `gh --slurp`)."""
    out = gh("api", "--paginate", path, "--jq", jq)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def fetch_check_runs(repo: str, sha: str) -> list[dict]:
    return json_lines(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100",
        ".check_runs[] | {name, status, conclusion, started_at}",
    )


def fetch_comments(repo: str, pr_number: int) -> list[dict]:
    return json_lines(
        f"repos/{repo}/issues/{pr_number}/comments?per_page=100",
        ".[] | {user: {login: .user.login}, body, created_at}",
    )


def set_status(repo: str, sha: str, state: str, description: str, url: str) -> None:
    gh(
        "api",
        "-X",
        "POST",
        f"repos/{repo}/statuses/{sha}",
        "-f",
        f"state={state}",
        "-f",
        f"context={CONTEXT}",
        "-f",
        f"description={status_description(description)}",
        "-f",
        f"target_url={url}",
    )


def current_state(repo: str, sha: str) -> str | None:
    out = gh("api", f"repos/{repo}/commits/{sha}/status", "--jq", ".statuses")
    for status in json.loads(out):
        if status["context"] == CONTEXT:
            return status["state"]
    return None


def comment(repo: str, pr_number: int, body: str) -> None:
    gh("pr", "comment", str(pr_number), "--repo", repo, "--body", body)


def remove_label(repo: str, pr_number: int) -> None:
    gh(
        "api",
        "-X",
        "DELETE",
        f"repos/{repo}/issues/{pr_number}/labels/{LABEL}",
        check=False,
    )


def main() -> int:
    repo = os.environ["REPO"]
    pr_number = int(os.environ["PR_NUMBER"])
    action = os.environ["ACTION"]
    run_url = os.environ["RUN_URL"]
    pr = json.loads(gh("api", f"repos/{repo}/pulls/{pr_number}"))
    head_sha = pr["head"]["sha"]
    short = head_sha[:7]

    if action in {"opened", "reopened", "synchronize", "ready_for_review"}:
        # A new commit has a new SHA: nothing approved earlier counts. The status first, then the
        # label, so the `unlabeled` event that follows finds a pending status and does nothing.
        set_status(
            repo,
            head_sha,
            "pending",
            f"waiting for a human approval of {short}",
            run_url,
        )
        remove_label(repo, pr_number)
        print(f"Reset: {short} waits for a human approval.")
        return 0

    if os.environ.get("LABEL_NAME") != LABEL:
        return 0

    sender_login = os.environ["SENDER_LOGIN"]
    if action == "unlabeled":
        if current_state(repo, head_sha) == "success":
            set_status(
                repo,
                head_sha,
                "pending",
                f"approval withdrawn by {sender_login}",
                run_url,
            )
            print(f"Approval of {short} withdrawn by {sender_login}.")
        return 0
    if action != "labeled":
        return 0

    sender_type = os.environ["SENDER_TYPE"]
    permission = "none"
    if sender_type == "User":
        permission = (
            gh(
                "api",
                f"repos/{repo}/collaborators/{sender_login}/permission",
                "--jq",
                ".permission",
                check=False,
            ).strip()
            or "none"
        )
    check_runs = fetch_check_runs(repo, head_sha)
    comments = fetch_comments(repo, pr_number)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import browser_check

        browser_ok, browser_message, warnings = browser_check.verify_pr(
            pr_number, head_sha, pr["title"]
        )
    except (subprocess.CalledProcessError, KeyError, ValueError, OSError) as error:
        browser_ok, browser_message, warnings = (
            False,
            f"browser check could not be read: {error}",
            [],
        )

    decision = decide(
        sender_type=sender_type,
        sender_login=sender_login,
        permission=permission,
        pr_open=pr["state"] == "open",
        pr_draft=bool(pr["draft"]),
        event_head_sha=os.environ["EVENT_HEAD_SHA"],
        current_head_sha=head_sha,
        check_runs=check_runs,
        comments=comments,
        browser_ok=browser_ok,
        browser_message=browser_message,
    )
    decision.notes.extend(warnings)
    if decision.ok:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        set_status(
            repo,
            head_sha,
            "success",
            f"approved by {sender_login} for {short}",
            run_url,
        )
        comment(
            repo,
            pr_number,
            approval_comment(sender_login, head_sha, now, decision, run_url),
        )
        print(f"Approved {head_sha} by {sender_login}.")
        return 0

    set_status(repo, head_sha, "failure", decision.reasons[0], run_url)
    comment(repo, pr_number, refusal_comment(sender_login, head_sha, decision, run_url))
    remove_label(repo, pr_number)
    print(f"::error title=Merge approval refused::{'; '.join(decision.reasons)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
