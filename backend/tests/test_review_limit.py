"""The per-PR limit of review runs (`.github/scripts/review_limit.py`).

The script runs in `review.yml` before the model is called: when a PR has used up its reviews, the
workflow refuses with the reason, the head SHA and a link to the logs, and the model is never
called. It lives outside `backend/`, so it is loaded by path.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "review_limit.py"

REPO = "Kamazoh1/ai-for-developers-project-387"
RUN_URL = f"https://github.com/{REPO}/actions/runs/700"
SHA = "347abb927b9c6d0a2ac8c0c0460c7756fd53fbab"


@pytest.fixture(scope="module")
def review_limit():
    spec = importlib.util.spec_from_file_location("review_limit", SCRIPT)
    assert spec is not None and spec.loader is not None, f"no script at {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # `@dataclass` looks its module up here
    spec.loader.exec_module(module)
    return module


def finished(run_id: int, pr: int = 14, conclusion: str | None = "success") -> dict:
    return {"id": run_id, "pull_requests": [pr], "conclusion": conclusion}


def decide(review_limit, runs: list[dict], max_runs: int = 3):
    return review_limit.decide(
        runs,
        pr_number=14,
        current_run_id=700,
        max_runs=max_runs,
        head_sha=SHA,
        run_url=RUN_URL,
    )


def test_a_pr_below_the_limit_is_reviewed(review_limit):
    decision = decide(review_limit, [finished(1), finished(2)], max_runs=3)

    assert decision.allowed
    assert decision.used == 2


def test_a_pr_that_used_up_its_reviews_is_refused_with_reason_sha_and_logs(review_limit):
    runs = [finished(1), finished(2), finished(3, conclusion="failure")]

    decision = decide(review_limit, runs, max_runs=3)

    assert not decision.allowed
    assert decision.used == 3
    # the reason, the exact commit that was NOT reviewed, and where to read the logs
    assert "3 of 3" in decision.message
    assert SHA in decision.message
    assert RUN_URL in decision.message
    assert "not reviewed" in decision.message.lower()


def test_only_finished_runs_of_this_pr_count(review_limit):
    runs = [
        finished(1),
        finished(700),  # the run that is asking
        finished(2, pr=9),  # another PR
        finished(3, conclusion="skipped"),  # the job's `if` kept it away from the model
        finished(4, conclusion="cancelled"),  # replaced by a newer push
        finished(5, conclusion=None),  # still running
    ]

    decision = decide(review_limit, runs, max_runs=3)

    assert decision.used == 1
    assert decision.allowed


def test_the_marker_lets_the_workflow_post_the_refusal_once_per_commit(review_limit):
    decision = decide(review_limit, [finished(1), finished(2), finished(3)], max_runs=3)

    assert review_limit.marker(SHA) in decision.message
    assert review_limit.marker(SHA) != review_limit.marker("0" * 40)


@pytest.mark.parametrize(
    "raw, expected", [("2", 2), (" 7 ", 7), ("", 5), ("many", 5), ("0", 5), ("-1", 5)]
)
def test_a_missing_or_broken_setting_falls_back_to_the_default(review_limit, raw, expected):
    assert review_limit.parse_max_runs(raw) == expected
