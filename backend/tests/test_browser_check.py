"""The independent browser check (`.github/scripts/browser_check.py`, run by `browser-check.yml`).

It turns the Playwright report into `result.json`, the artifact that records the verdict and the
exact head SHA of the PR, and at the moment of the merge decision it compares that SHA with the PR's
current head. The script lives outside `backend/`, so it is loaded by path.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "browser_check.py"

HEAD = "347abb927b9c6d0a2ac8c0c0460c7756fd53fbab"
NEWER_HEAD = "9f1c2d3e4b5a69788796a5b4c3d2e1f001122334"
MERGE = "1ee280847b681218fdbd4a32d9777ee4e3b5b499"


@pytest.fixture(scope="module")
def browser_check():
    spec = importlib.util.spec_from_file_location("browser_check", SCRIPT)
    assert spec is not None and spec.loader is not None, f"no script at {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # `@dataclass` looks its module up here
    spec.loader.exec_module(module)
    return module


def spec(title: str, status: str) -> dict:
    """One Playwright JSON-report spec: `expected` is a pass, `unexpected` a failure."""
    return {"title": title, "tests": [{"status": status, "results": [{"duration": 1200}]}]}


def report(*specs: dict) -> dict:
    """A report with the specs split over a file suite and a nested describe, as Playwright does."""
    half = len(specs) // 2
    return {
        "suites": [
            {
                "title": "booking.spec.ts",
                "specs": list(specs[:half]),
                "suites": [{"title": "nested", "specs": list(specs[half:])}],
            }
        ]
    }


MAIN_OK = spec("@main a guest leaves a topic and the owner sees it", "expected")
ADJACENT_OK = spec("@adjacent two guests race for one slot", "expected")


def build(browser_check, rep: dict, pr_title: str = "feat: let guests leave a topic (#6)"):
    return browser_check.build_result(
        browser_check.scenarios_from_report(rep),
        head_sha=HEAD,
        merge_sha=MERGE,
        pr_number=14,
        pr_title=pr_title,
        run_url="https://github.com/Kamazoh1/ai-for-developers-project-387/actions/runs/800",
        finished_at="2026-11-08T19:00:00Z",
    )


def test_the_report_becomes_scenarios_with_tags_and_status(browser_check):
    rep = report(MAIN_OK, spec("@adjacent the race", "unexpected"), spec("plain one", "skipped"))

    scenarios = browser_check.scenarios_from_report(rep)

    assert [(s.title, s.tags, s.status) for s in scenarios] == [
        ("@main a guest leaves a topic and the owner sees it", ("main",), "passed"),
        ("@adjacent the race", ("adjacent",), "failed"),
        ("plain one", (), "skipped"),
    ]


def test_a_feature_with_passing_main_and_adjacent_scenarios_passes_and_records_the_head_sha(
    browser_check,
):
    result = build(browser_check, report(MAIN_OK, ADJACENT_OK))

    assert result["verdict"] == "pass"
    assert result["reasons"] == []
    assert result["head_sha"] == HEAD  # the exact commit of the PR
    assert result["merge_sha"] == MERGE  # what the browser really ran against
    assert result["pr"] == 14
    assert result["run_url"].endswith("/runs/800")
    assert {s["title"]: s["status"] for s in result["scenarios"]} == {
        MAIN_OK["title"]: "passed",
        ADJACENT_OK["title"]: "passed",
    }


def test_a_feature_without_a_main_scenario_fails(browser_check):
    result = build(browser_check, report(ADJACENT_OK, spec("@adjacent another", "expected")))

    assert result["verdict"] == "fail"
    assert any("@main" in reason for reason in result["reasons"])


def test_a_change_that_is_not_a_feature_needs_only_the_adjacent_scenario(browser_check):
    result = build(
        browser_check,
        report(ADJACENT_OK, spec("@adjacent another", "expected")),
        pr_title="ci: cap the reviews per PR",
    )

    assert result["verdict"] == "pass"


def test_a_failed_scenario_fails_the_check_and_is_named(browser_check):
    broken = spec("@main a guest leaves a topic and the owner sees it", "unexpected")

    result = build(browser_check, report(broken, ADJACENT_OK))

    assert result["verdict"] == "fail"
    assert any(broken["title"] in reason for reason in result["reasons"])


def test_a_run_without_any_adjacent_scenario_fails(browser_check):
    result = build(browser_check, report(MAIN_OK, spec("untagged", "expected")))

    assert result["verdict"] == "fail"
    assert any("@adjacent" in reason for reason in result["reasons"])


def test_at_the_merge_decision_the_artifact_must_belong_to_the_current_head(browser_check):
    result = build(browser_check, report(MAIN_OK, ADJACENT_OK))

    ok, message = browser_check.check_for_merge(result, pr_head_sha=HEAD)
    assert ok
    assert HEAD in message

    stale_ok, stale_message = browser_check.check_for_merge(result, pr_head_sha=NEWER_HEAD)
    assert not stale_ok
    # both SHAs and the reason, so the person deciding sees what to re-run
    assert HEAD in stale_message and NEWER_HEAD in stale_message
    assert "not the current head" in stale_message


def test_a_failed_verdict_is_not_a_reason_to_merge_even_for_the_current_head(browser_check):
    broken = spec("@adjacent the race", "unexpected")
    result = build(browser_check, report(MAIN_OK, broken))

    ok, message = browser_check.check_for_merge(result, pr_head_sha=HEAD)

    assert not ok
    assert "fail" in message
