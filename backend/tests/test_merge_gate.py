"""The merge gate (`.github/scripts/merge_gate.py`, run by `merge-gate.yml`).

A person approves a merge by adding the label `merge-approved`. The gate then checks, on the PR's
current head SHA, that the checks are green, the browser artifact matches the head and the review
has no blocker, and records who approved which SHA in a status and a comment. A new commit has a new
SHA, so an earlier approval does not carry over. The script lives outside `backend/`, so it is
loaded by path.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "merge_gate.py"

HEAD = "347abb927b9c6d0a2ac8c0c0460c7756fd53fbab"
OTHER = "9f1c2d3e4b5a69788796a5b4c3d2e1f001122334"
RUN_URL = "https://github.com/Kamazoh1/ai-for-developers-project-387/actions/runs/1000"
REVIEW_STARTED = "2026-11-08T18:15:18Z"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("merge_gate", SCRIPT)
    assert spec is not None and spec.loader is not None, f"no script at {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # `@dataclass` looks its module up here
    spec.loader.exec_module(module)
    return module


def run(name: str, conclusion: str | None = "success", started: str = REVIEW_STARTED) -> dict:
    status = "completed" if conclusion else "in_progress"
    return {"name": name, "status": status, "conclusion": conclusion, "started_at": started}


GREEN = [run("verify"), run("image"), run("browser-check"), run("review")]


def verdict(
    blockers: int, created: str = "2026-11-08T18:20:00Z", login: str = "claude[bot]"
) -> dict:
    body = (
        f"**Review (advice for the human who merges): blockers: {blockers}, concerns: 1, nits: 0**"
    )
    return {"user": {"login": login}, "body": body, "created_at": created}


def decide(gate, **overrides):
    arguments = {
        "sender_type": "User",
        "sender_login": "Kamazoh1",
        "permission": "admin",
        "pr_open": True,
        "pr_draft": False,
        "event_head_sha": HEAD,
        "current_head_sha": HEAD,
        "check_runs": GREEN,
        "comments": [verdict(0)],
        "browser_ok": True,
        "browser_message": "OK: the browser check passed",
    }
    arguments.update(overrides)
    return gate.decide(**arguments)


def test_a_person_with_write_access_approves_a_green_head(gate):
    decision = decide(gate)

    assert decision.ok
    assert decision.reasons == []


def test_a_bot_cannot_approve_a_merge(gate):
    decision = decide(gate, sender_type="Bot", sender_login="claude[bot]")

    assert not decision.ok
    assert any("person" in reason for reason in decision.reasons)


def test_read_only_access_cannot_approve(gate):
    decision = decide(gate, permission="read")

    assert not decision.ok
    assert any("write access" in reason for reason in decision.reasons)


@pytest.mark.parametrize("permission", ["write", "maintain", "admin"])
def test_write_level_access_can_approve(gate, permission):
    assert decide(gate, permission=permission).ok


def test_the_approval_is_refused_when_the_head_moved_since_the_label(gate):
    decision = decide(gate, event_head_sha=HEAD, current_head_sha=OTHER)

    assert not decision.ok
    assert any(HEAD in reason and OTHER in reason for reason in decision.reasons)


@pytest.mark.parametrize("override", [{"pr_open": False}, {"pr_draft": True}])
def test_a_closed_or_draft_pr_is_not_approved(gate, override):
    assert not decide(gate, **override).ok


def test_every_required_check_must_be_green_on_this_commit(gate):
    runs = [run("verify"), run("image", "failure"), run("review")]  # browser-check is missing

    decision = decide(gate, check_runs=runs)

    assert not decision.ok
    text = " ".join(decision.reasons)
    assert "image" in text and "failure" in text
    assert "browser-check" in text and "no run" in text


def test_a_check_that_is_still_running_is_not_green(gate):
    decision = decide(gate, check_runs=[*GREEN[:3], run("review", conclusion=None)])

    assert not decision.ok
    assert any("review" in reason and "running" in reason for reason in decision.reasons)


def test_only_the_latest_run_of_a_check_counts(gate):
    # the first review run failed (the limit), the re-run passed
    runs = [
        *GREEN[:3],
        run("review", "failure", started="2026-11-08T17:00:00Z"),
        run("review", "success", started="2026-11-08T18:00:00Z"),
    ]
    assert decide(gate, check_runs=runs).ok

    runs = [
        *GREEN[:3],
        run("review", "success", started="2026-11-08T17:00:00Z"),
        run("review", "failure", started="2026-11-08T18:00:00Z"),
    ]
    assert not decide(gate, check_runs=runs).ok


def test_a_blocker_in_the_review_of_this_commit_stops_the_approval(gate):
    decision = decide(gate, comments=[verdict(0, "2026-11-08T18:16:00Z"), verdict(2)])

    assert not decision.ok
    assert any("2 blocker" in reason for reason in decision.reasons)


def test_a_review_comment_older_than_the_review_run_is_not_this_commits_verdict(gate):
    old_blocker = verdict(3, created="2026-11-08T10:00:00Z")

    decision = decide(gate, comments=[old_blocker])

    assert decision.ok  # a stale verdict neither blocks nor passes ...
    assert any("no review verdict" in note for note in decision.notes)  # ... and the record says so


def test_comments_of_other_authors_are_not_a_review_verdict(gate):
    decision = decide(gate, comments=[verdict(5, login="someone")])

    assert decision.ok
    assert any("no review verdict" in note for note in decision.notes)


def test_a_browser_artifact_of_another_commit_stops_the_approval(gate):
    decision = decide(
        gate, browser_ok=False, browser_message="REFUSED: the artifact is for 9f1c2d3, not the head"
    )

    assert not decision.ok
    assert any("REFUSED" in reason for reason in decision.reasons)


def test_the_approval_comment_records_who_which_sha_and_what_was_checked(gate):
    decision = decide(gate, comments=[verdict(0)])

    text = gate.approval_comment("Kamazoh1", HEAD, "2026-11-08T19:30:00Z", decision, RUN_URL)

    assert "@Kamazoh1" in text and HEAD in text and "2026-11-08T19:30:00Z" in text
    assert RUN_URL in text
    assert gate.marker(HEAD) in text
    assert "verify" in text and "browser-check" in text


def test_the_refusal_comment_lists_every_reason_and_says_the_label_was_removed(gate):
    decision = decide(gate, sender_type="Bot", check_runs=[])

    text = gate.refusal_comment("claude[bot]", HEAD, decision, RUN_URL)

    assert HEAD in text and RUN_URL in text
    assert text.count("\n- ") >= len(decision.reasons)
    assert "removed" in text


def test_a_status_description_fits_the_limit_of_github(gate):
    assert len(gate.status_description("x" * 500)) <= 140
    assert gate.status_description("short") == "short"
