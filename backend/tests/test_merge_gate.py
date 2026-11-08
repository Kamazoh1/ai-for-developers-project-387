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


WORKFLOW = {
    "verify": ".github/workflows/ci.yml",
    "image": ".github/workflows/ci.yml",
    "browser-check": ".github/workflows/browser-check.yml",
    "review": ".github/workflows/review.yml",
}


def run(
    name: str,
    conclusion: str | None = "success",
    started: str = REVIEW_STARTED,
    workflow: str | None = None,
) -> dict:
    status = "completed" if conclusion else "in_progress"
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started,
        "workflow": workflow or WORKFLOW[name],
    }


GREEN = [run("verify"), run("image"), run("browser-check"), run("review")]


def verdict(
    blockers: int,
    created: str = "2026-11-08T18:20:00Z",
    login: str = "claude[bot]",
    head: str = HEAD,
) -> dict:
    body = (
        f"Review of head `{head[:7]}`: blockers: {blockers}, concerns: 1, nits: 0\n\n"
        "Spec check: not applicable."
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
        "changed_files": ["README.md"],
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


def test_a_verdict_for_another_commit_is_not_this_commits_verdict_and_nothing_is_approved(gate):
    decision = decide(gate, comments=[verdict(0, head=OTHER)])

    assert not decision.ok  # fail closed: the check was green but the review never said anything
    assert any("no review verdict" in reason for reason in decision.reasons)


def test_comments_of_other_authors_are_not_a_review_verdict(gate):
    decision = decide(gate, comments=[verdict(0, login="someone")])

    assert not decision.ok
    assert any("no review verdict" in reason for reason in decision.reasons)


def test_a_newer_claude_comment_that_says_blockers_zero_does_not_replace_the_verdict(gate):
    # the interactive agent also posts as claude[bot]; only the review's verdict line counts
    chatter = {
        "user": {"login": "claude[bot]"},
        "body": "Looks fine to me, blockers: 0, concerns: 0 in my view.",
        "created_at": "2026-11-08T18:50:00Z",
    }

    decision = decide(gate, comments=[verdict(2), chatter])

    assert not decision.ok
    assert any("2 blocker" in reason for reason in decision.reasons)


@pytest.mark.parametrize("file", [".github/workflows/review.yml", "REVIEW.md"])
def test_a_pr_that_changes_the_review_itself_may_have_no_verdict_but_the_record_says_so(gate, file):
    decision = decide(gate, comments=[], changed_files=["README.md", file])

    assert decision.ok
    assert any("no review verdict" in note for note in decision.notes)


def test_a_check_with_the_right_name_from_another_workflow_does_not_count(gate):
    # a PR adds a workflow whose job is called `review` and succeeds after the real one failed
    runs = [
        *GREEN[:3],
        run("review", "failure", started="2026-11-08T17:00:00Z"),
        run(
            "review",
            "success",
            started="2026-11-08T18:00:00Z",
            workflow=".github/workflows/evil.yml",
        ),
    ]

    decision = decide(gate, check_runs=runs)

    assert not decision.ok
    assert any("review: failure" in reason for reason in decision.reasons)


def test_a_pr_that_changes_workflows_is_noted_in_the_record(gate):
    decision = decide(gate, changed_files=[".github/workflows/ci.yml", "README.md"])

    assert decision.ok
    assert any(".github/workflows/ci.yml" in note for note in decision.notes)


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


# --- the events: what `main()` writes for each of them -------------------------------------------


class Repo:
    """A stand-in for `gh` and the reads of the gate: records every write, never touches GitHub."""

    def __init__(self, gate, monkeypatch, tmp_path):
        self.calls: list[str] = []
        self.status: str | None = None  # state of the `merge-gate` status on the head
        self.checks = GREEN
        self.comments = [verdict(0)]
        self.files = ["README.md"]
        self.browser = (True, "OK: the browser check passed", [])
        monkeypatch.setattr(gate, "gh", self.gh)
        monkeypatch.setattr(gate, "fetch_check_runs", lambda repo, sha: self.checks)
        monkeypatch.setattr(gate, "fetch_comments", lambda repo, number: self.comments)
        monkeypatch.setattr(gate, "fetch_changed_files", lambda repo, number: self.files)
        sys.path.insert(0, str(SCRIPT.parent))
        browser_check = importlib.import_module("browser_check")
        monkeypatch.setattr(browser_check, "verify_pr", lambda n, sha, title: self.browser)

    def gh(self, *args, check=True):
        import json

        text = " ".join(args)
        self.calls.append(text)
        if text.startswith("api repos/R/pulls/5") and "-X" not in text:
            return json.dumps(
                {"state": "open", "draft": False, "title": "ci: x", "head": {"sha": HEAD}}
            )
        if text.endswith("--jq .statuses"):
            return json.dumps(
                [] if self.status is None else [{"context": "merge-gate", "state": self.status}]
            )
        if "permission" in text:
            return "admin\n"
        return ""

    def writes(self) -> list[str]:
        return [c for c in self.calls if "-X POST" in c or "-X DELETE" in c]


@pytest.fixture
def repo(gate, monkeypatch, tmp_path):
    return Repo(gate, monkeypatch, tmp_path)


def fire(gate, monkeypatch, action, **env):
    base = {
        "REPO": "R",
        "PR_NUMBER": "5",
        "ACTION": action,
        "RUN_URL": RUN_URL,
        "EVENT_HEAD_SHA": HEAD,
        "SENDER_LOGIN": "Kamazoh1",
        "SENDER_TYPE": "User",
        "LABEL_NAME": "merge-approved",
    }
    for key, value in {**base, **env}.items():
        monkeypatch.setenv(key, value)
    return gate.main()


def test_a_new_commit_waits_for_approval_and_drops_the_label_status_first(gate, monkeypatch, repo):
    assert fire(gate, monkeypatch, "synchronize") == 0

    writes = repo.writes()
    assert "state=pending" in writes[0] and f"statuses/{HEAD}" in writes[0]
    assert writes[1].endswith("labels/merge-approved")  # after the status, see the workflow


def test_a_person_labelling_a_green_head_approves_it(gate, monkeypatch, repo):
    assert fire(gate, monkeypatch, "labeled") == 0

    writes = repo.writes()
    assert "state=success" in writes[0]
    assert "issues/5/comments" in writes[1] and HEAD in writes[1] and "Kamazoh1" in writes[1]
    assert not any("DELETE" in w for w in writes)  # the label stays on an approved head


def test_a_bot_labelling_is_refused_with_the_reasons_and_the_label_is_removed(
    gate, monkeypatch, repo
):
    code = fire(gate, monkeypatch, "labeled", SENDER_TYPE="Bot", SENDER_LOGIN="claude[bot]")

    assert code == 1
    writes = repo.writes()
    assert "state=failure" in writes[0]
    assert "refused" in writes[1] and "not a person" in writes[1]
    assert writes[2].endswith("labels/merge-approved")


def test_a_red_check_refuses_even_a_person(gate, monkeypatch, repo):
    repo.checks = [*GREEN[:3], run("review", "failure")]

    assert fire(gate, monkeypatch, "labeled") == 1
    assert any("state=failure" in w for w in repo.writes())


def test_a_head_that_moved_after_the_label_is_refused(gate, monkeypatch, repo):
    assert fire(gate, monkeypatch, "labeled", EVENT_HEAD_SHA=OTHER) == 1


def test_withdrawing_the_label_of_an_approval_makes_the_head_pending_again(gate, monkeypatch, repo):
    repo.status = "success"

    assert fire(gate, monkeypatch, "unlabeled") == 0
    assert "state=pending" in repo.writes()[0] and "withdrawn" in repo.writes()[0]


def test_the_gates_own_label_removal_after_a_refusal_changes_nothing(gate, monkeypatch, repo):
    repo.status = "failure"

    assert fire(gate, monkeypatch, "unlabeled") == 0
    assert repo.writes() == []


def test_a_head_that_never_got_a_status_is_made_pending_by_the_next_event(gate, monkeypatch, repo):
    # a reset can be dropped from the queue; the next event reconciles it
    repo.status = None

    assert fire(gate, monkeypatch, "unlabeled") == 0
    assert "state=pending" in repo.writes()[0]


def test_other_labels_are_ignored(gate, monkeypatch, repo):
    assert fire(gate, monkeypatch, "labeled", LABEL_NAME="bug") == 0
    assert repo.writes() == []
