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

import contextlib
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
# A required check counts only when it comes from this workflow file: a PR can add a workflow with a
# job of the same name that always succeeds, and a name alone would not tell them apart.
EXPECTED_WORKFLOW = {
    "verify": ".github/workflows/ci.yml",
    "image": ".github/workflows/ci.yml",
    "browser-check": ".github/workflows/browser-check.yml",
    "review": ".github/workflows/review.yml",
}
REQUIRED_CHECKS = tuple(EXPECTED_WORKFLOW)
# Files that change the review itself: a PR touching them may get no verdict from it.
REVIEW_FILES = (
    ".github/workflows/review.yml",
    "REVIEW.md",
    ".github/scripts/spec_link.py",
    ".github/scripts/review_limit.py",
)
WRITE_LEVELS = {"write", "maintain", "admin"}
# The first line of the review comment (REVIEW.md "Output"): it names the commit it is about.
VERDICT = re.compile(
    r"^\W*Review of head\W*([0-9a-f]{7,40})\b[^\n]*?blockers:\s*(\d+)", re.MULTILINE
)


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
    """The latest run of every required check, from its own workflow only; a re-run replaces it."""
    latest: dict[str, dict] = {}
    for run in check_runs:
        if run.get("workflow") != EXPECTED_WORKFLOW.get(run["name"]):
            continue
        known = latest.get(run["name"])
        started = run.get("started_at") or ""
        if known is None or started > (known.get("started_at") or ""):
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


def review_blockers(comments: list[dict], head_sha: str) -> int | None:
    """Blockers in the newest review comment that names this head commit, or None.

    Only the verdict line counts (`Review of head <sha>: blockers: N, ...`): the interactive
    agent also posts as claude[bot], and a reply that says "blockers: 0" must not pass for it.
    """
    verdicts = []
    for comment in comments:
        if comment["user"]["login"] != "claude[bot]":
            continue
        found = VERDICT.search(comment["body"])
        if found and head_sha.startswith(found.group(1)):
            verdicts.append((comment["created_at"], int(found.group(2))))
    return max(verdicts)[1] if verdicts else None


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
    changed_files: list[str],
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

    blockers = review_blockers(comments, current_head_sha)
    if blockers is None:
        message = (
            f"no review verdict for this commit: the review wrote no `Review of head "
            f"{current_head_sha[:7]}` summary"
        )
        if any(name in REVIEW_FILES for name in changed_files):
            decision.notes.append(
                f"{message}. This PR changes the review itself, which then reviews nothing: "
                "decide on the diff yourself"
            )
        else:
            decision.reasons.append(message)
    elif blockers > 0:
        decision.reasons.append(
            f"the review of this commit reports {blockers} blocker(s)"
        )
    else:
        decision.checked.append("review verdict: 0 blockers")

    workflows = [
        name for name in changed_files if name.startswith(".github/workflows/")
    ]
    if workflows:
        decision.notes.append(
            f"this PR changes workflow files ({', '.join(workflows)}): a workflow can write "
            "commit statuses and comments like this gate; read them before merging"
        )

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
        # Say what GitHub answered: the exception alone shows only the exit code.
        print(f"gh {' '.join(args[:3])} failed: {done.stderr.strip()}", file=sys.stderr)
        raise subprocess.CalledProcessError(
            done.returncode, done.args, done.stdout, done.stderr
        )
    return done.stdout


def json_lines(path: str, jq: str) -> list[dict]:
    """Every page of an API list as one JSON object per line (no dependency on `gh --slurp`)."""
    out = gh("api", "--paginate", path, "--jq", jq)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def fetch_check_runs(repo: str, sha: str) -> list[dict]:
    """Jobs of the required workflows on this commit, each tagged with its workflow file."""
    jobs: list[dict] = []
    wanted = set(EXPECTED_WORKFLOW.values())
    runs = json_lines(
        f"repos/{repo}/actions/runs?head_sha={sha}&event=pull_request&per_page=100",
        ".workflow_runs[] | {id, path}",
    )
    for run in runs:
        if run["path"] not in wanted:
            continue
        for job in json_lines(
            f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100",
            ".jobs[] | {name, status, conclusion, started_at}",
        ):
            jobs.append({**job, "workflow": run["path"]})
    return jobs


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


def fetch_changed_files(repo: str, pr_number: int) -> list[str]:
    out = gh(
        "api",
        "--paginate",
        f"repos/{repo}/pulls/{pr_number}/files?per_page=100",
        "--jq",
        ".[].filename",
    )
    return out.split()


def comment(repo: str, pr_number: int, body: str) -> None:
    # The issues API: it needs only `issues: write`, and a PR is an issue for comments.
    gh(
        "api",
        "-X",
        "POST",
        f"repos/{repo}/issues/{pr_number}/comments",
        "-f",
        f"body={body}",
    )


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
        state = current_state(repo, head_sha)
        if state == "success":
            set_status(
                repo,
                head_sha,
                "pending",
                f"approval withdrawn by {sender_login}",
                run_url,
            )
            print(f"Approval of {short} withdrawn by {sender_login}.")
        elif state is None:
            # A queued reset can be dropped when newer events join the group: reconcile here.
            set_status(
                repo,
                head_sha,
                "pending",
                f"waiting for a human approval of {short}",
                run_url,
            )
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
    changed_files = fetch_changed_files(repo, pr_number)
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
        changed_files=changed_files,
        browser_ok=browser_ok,
        browser_message=browser_message,
    )
    decision.notes.extend(warnings)
    if decision.ok:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            # The record first, the status after it: `success` never stands without its comment.
            comment(
                repo,
                pr_number,
                approval_comment(sender_login, head_sha, now, decision, run_url),
            )
            set_status(
                repo,
                head_sha,
                "success",
                f"approved by {sender_login} for {short}",
                run_url,
            )
        except Exception:
            with contextlib.suppress(Exception):
                set_status(
                    repo,
                    head_sha,
                    "error",
                    "the gate could not record the approval: see the run",
                    run_url,
                )
            raise
        print(f"Approved {head_sha} by {sender_login}.")
        return 0

    set_status(repo, head_sha, "failure", decision.reasons[0], run_url)
    comment(repo, pr_number, refusal_comment(sender_login, head_sha, decision, run_url))
    remove_label(repo, pr_number)
    print(f"::error title=Merge approval refused::{'; '.join(decision.reasons)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
