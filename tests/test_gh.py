from __future__ import annotations

import pytest

from gitconvoy import feature as feature_cmd
from gitconvoy import ghutil
from gitconvoy import train as train_cmd
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import Feature, FeatureRepo, State, Train, TrainRepo, load, save


def _feature_with_pr(workspace) -> None:
    save(workspace, State(current_feature="demo"))
    state = load(workspace)
    state.features["demo"] = Feature(
        name="demo",
        branch="feature/demo",
        repos=[
            FeatureRepo(
                id="schd",
                path="extensions/schd",
                pr="https://github.com/renglo/schd/pull/9",
            )
        ],
    )
    save(workspace, state)


def test_approve_requires_gh(workspace, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    _feature_with_pr(workspace)
    monkeypatch.setattr("gitconvoy.gitutil.gh_bin", lambda: None)
    with pytest.raises(GitConvoyError, match="gh is not on PATH"):
        feature_cmd.approve(workspace, load(workspace))


def test_approve_all_participants(workspace, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    _feature_with_pr(workspace)
    monkeypatch.setattr("gitconvoy.ghutil.require_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(
        "gitconvoy.feature.gitutil.pr_merge_status",
        lambda repo, branch, pr_url=None: "pending",
    )
    monkeypatch.setattr(
        "gitconvoy.feature.gitutil.github_slug",
        lambda repo: "renglo/schd",
    )
    monkeypatch.setattr(
        "gitconvoy.ghutil.pr_details",
        lambda slug, number, cwd=None: {
            "reviewDecision": "",
            "statusCheckRollup": {"state": "SUCCESS"},
        },
    )
    approved: list[int] = []

    def fake_approve(slug, number, cwd=None):
        approved.append(number)
        return True, "approved"

    monkeypatch.setattr("gitconvoy.ghutil.approve_pr", fake_approve)
    data = feature_cmd.approve(workspace, load(workspace))
    assert data["ok"] is True
    assert approved == [9]
    assert data["repos"][0]["status"] == "approved"


def test_approve_blocks_failing_checks(workspace, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    _feature_with_pr(workspace)
    monkeypatch.setattr("gitconvoy.ghutil.require_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(
        "gitconvoy.feature.gitutil.pr_merge_status",
        lambda repo, branch, pr_url=None: "pending",
    )
    monkeypatch.setattr(
        "gitconvoy.feature.gitutil.github_slug",
        lambda repo: "renglo/schd",
    )
    monkeypatch.setattr(
        "gitconvoy.ghutil.pr_details",
        lambda slug, number, cwd=None: {
            "reviewDecision": "",
            "statusCheckRollup": {"state": "FAILURE"},
        },
    )
    with pytest.raises(GitConvoyError, match="checks failure"):
        feature_cmd.approve(workspace, load(workspace))


def test_run_publish_status() -> None:
    assert ghutil.run_publish_status({"status": "completed", "conclusion": "success"}) == "success"
    assert ghutil.run_publish_status({"status": "completed", "conclusion": "failure"}) == "failure"
    assert ghutil.run_publish_status({"status": "in_progress"}) == "pending"
    assert ghutil.run_publish_status(None) == "missing"


def test_aggregate_workflow_status() -> None:
    rows = [{"status": "success"}, {"status": "success"}]
    assert ghutil.aggregate_workflow_status(rows) == "success"
    rows = [{"status": "success"}, {"status": "failure"}]
    assert ghutil.aggregate_workflow_status(rows) == "failure"


def test_verify_skips_non_publishers(workspace, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29", status="stabilizing")
    train.add_repo(
        TrainRepo(id="console", path="console", rc_tag="v0.0.1-rc.1")
    )
    state.trains["2026-08-29"] = train
    save(workspace, state)
    (workspace / "console").mkdir()
    monkeypatch.setattr("gitconvoy.ghutil.require_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr("gitconvoy.train.tag_push_workflows", lambda repo: [])
    data = train_cmd.verify(workspace, load(workspace))
    assert data["skipped_count"] == 1
    assert data["repos"][0]["status"] == "skip"


def test_verify_success(workspace, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29", status="stabilizing")
    train.add_repo(
        TrainRepo(id="schd", path="extensions/schd", rc_tag="v1.0.1-rc.1")
    )
    state.trains["2026-08-29"] = train
    save(workspace, state)
    monkeypatch.setattr("gitconvoy.ghutil.require_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(
        "gitconvoy.train.tag_push_workflows",
        lambda repo: ["publish-extension.yml"],
    )
    monkeypatch.setattr(
        "gitconvoy.train.gitutil.github_slug",
        lambda repo: "renglo/schd",
    )
    monkeypatch.setattr("gitconvoy.ghutil.tag_sha", lambda repo, tag: "abc1234")
    monkeypatch.setattr(
        "gitconvoy.ghutil.publish_runs_for_commit",
        lambda slug, commit, workflow_files, cwd=None: [
            {
                "file": "publish-extension.yml",
                "status": "success",
                "run_url": "https://github.com/renglo/schd/actions/runs/1",
                "run": {"status": "completed", "conclusion": "success"},
            }
        ],
    )
    data = train_cmd.verify(workspace, load(workspace))
    assert data["ok"] is True
    assert data["verified_count"] == 1
    assert data["repos"][0]["status"] == "success"


def test_verify_failure_returns_full_report(workspace, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29")
    train.add_repo(
        TrainRepo(id="schd", path="extensions/schd", rc_tag="v1.0.1-rc.1")
    )
    state.trains["2026-08-29"] = train
    save(workspace, state)
    monkeypatch.setattr("gitconvoy.ghutil.require_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(
        "gitconvoy.train.tag_push_workflows",
        lambda repo: ["publish-extension.yml"],
    )
    monkeypatch.setattr(
        "gitconvoy.train.gitutil.github_slug",
        lambda repo: "renglo/schd",
    )
    monkeypatch.setattr("gitconvoy.ghutil.tag_sha", lambda repo, tag: "abc1234")
    monkeypatch.setattr(
        "gitconvoy.ghutil.publish_runs_for_commit",
        lambda slug, commit, workflow_files, cwd=None: [
            {
                "file": "publish-extension.yml",
                "status": "failure",
                "run_url": "https://github.com/renglo/schd/actions/runs/2",
                "run": {"status": "completed", "conclusion": "failure"},
            }
        ],
    )
    data = train_cmd.verify(workspace, load(workspace))
    assert data["ok"] is False
    text = train_cmd.format_verify_text(data)
    assert "failed (1):" in text
    assert "schd" in text


def test_verify_shows_succeeded_and_failed(workspace, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    api = workspace / "dev" / "renglo-api"
    claw = workspace / "extensions" / "claw"
    api.mkdir(parents=True)
    claw.mkdir(parents=True)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29")
    train.add_repo(
        TrainRepo(id="renglo-api", path="dev/renglo-api", rc_tag="v0.0.2-rc.1")
    )
    train.add_repo(
        TrainRepo(id="claw", path="extensions/claw", rc_tag="v1.0.1-rc.1")
    )
    state.trains["2026-08-29"] = train
    save(workspace, state)
    monkeypatch.setattr("gitconvoy.ghutil.require_gh", lambda: "/usr/bin/gh")
    monkeypatch.setattr(
        "gitconvoy.train.tag_push_workflows",
        lambda repo: ["publish-extension.yml"],
    )

    def slug(repo):
        return "renglo/renglo-api" if "renglo-api" in str(repo) else "renglo/claw"

    monkeypatch.setattr("gitconvoy.train.gitutil.github_slug", slug)
    monkeypatch.setattr("gitconvoy.ghutil.tag_sha", lambda repo, tag: "abc1234")

    def fake_runs(slug, commit, workflow_files, cwd=None):
        if "renglo-api" in slug:
            return [
                {
                    "file": "publish-python.yml",
                    "status": "success",
                    "run_url": "https://github.com/renglo/renglo-api/actions/runs/1",
                }
            ]
        return [
            {
                "file": "publish-extension.yml",
                "status": "failure",
                "run_url": "https://github.com/renglo/claw/actions/runs/2",
            }
        ]

    monkeypatch.setattr("gitconvoy.ghutil.publish_runs_for_commit", fake_runs)
    data = train_cmd.verify(workspace, load(workspace))
    text = train_cmd.format_verify_text(data)
    assert data["ok"] is False
    assert "succeeded (1):" in text
    assert "renglo-api" in text
    assert "failed (1):" in text
    assert "claw" in text
