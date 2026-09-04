from __future__ import annotations

import json
from pathlib import Path

import pytest

from gitconvoy import feature as feature_cmd
from gitconvoy import gitutil
from gitconvoy.cli import main
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, load, save
from gitconvoy.workspace import find_workspace

from conftest import git


def test_start_and_adopt_uncommitted(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    feature_cmd.start(workspace, state, "blast-radius")
    state = load(workspace)
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    data = feature_cmd.adopt(workspace, state)
    assert [row["id"] for row in data["adopted"]] == ["schd"]
    assert gitutil.current_branch(schd) == "feature/blast-radius"
    assert gitutil.current_branch(workspace / "dev" / "renglo-lib") == "develop"
    state = load(workspace)
    assert state.features["blast-radius"].repo_ids() == ["schd"]


def test_adopt_skips_and_drops_empty_feature_branch(workspace: Path) -> None:
    feature_cmd.start(workspace, State(), "blast-radius")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "feature/blast-radius")
    state = load(workspace)
    state.features["blast-radius"].add_repo("schd", "extensions/schd")
    save(workspace, state)
    data = feature_cmd.adopt(workspace, load(workspace))
    assert data["adopted"] == []
    assert [row["id"] for row in data["dropped"]] == ["schd"]
    assert data["dropped"][0]["reason"] == "on-feature-no-changes"
    assert gitutil.current_branch(schd) == "develop"
    assert gitutil.has_local_branch(schd, "feature/blast-radius")
    assert load(workspace).features["blast-radius"].repo_ids() == []


def test_adopt_picks_up_existing_branch_with_commits(workspace: Path) -> None:
    feature_cmd.start(workspace, State(), "blast-radius")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "feature/blast-radius")
    (schd / "handler.py").write_text("print('x')\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "wip")
    git(schd, "checkout", "develop")
    data = feature_cmd.adopt(workspace, load(workspace))
    assert [row["id"] for row in data["adopted"]] == ["schd"]
    assert data["adopted"][0]["action"] == "picked-up"
    assert gitutil.current_branch(schd) == "feature/blast-radius"
    assert load(workspace).features["blast-radius"].repo_ids() == ["schd"]


def test_adopt_drops_bom_from_feature_sheet(workspace: Path) -> None:
    feature_cmd.start(workspace, State(), "blast-radius")
    state = load(workspace)
    state.features["blast-radius"].add_repo("stanley-bom", "ops/stanley-bom")
    state.features["blast-radius"].add_repo("schd", "extensions/schd")
    save(workspace, state)
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    data = feature_cmd.adopt(workspace, load(workspace))
    assert any(row["id"] == "stanley-bom" for row in data["dropped"])
    assert all(row["id"] != "stanley-bom" for row in data["adopted"])
    assert "stanley-bom" not in load(workspace).features["blast-radius"].repo_ids()
    assert "schd" in load(workspace).features["blast-radius"].repo_ids()


def test_start_picks_up_existing_feature_branch(workspace: Path) -> None:
    state = State()
    feature_cmd.start(workspace, state, "blast-radius")
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    (schd / "handler.py").write_text("print('x')\n")
    feature_cmd.adopt(workspace, load(workspace))
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "wip")
    data = feature_cmd.start(workspace, load(workspace), "blast-radius")
    assert gitutil.current_branch(schd) == "feature/blast-radius"
    assert gitutil.current_branch(lib) == "develop"
    assert [row["id"] for row in data["repos"]] == ["schd"]
    assert data["repos"][0]["action"] == "already-on-feature"
    assert data["repo_count"] == 1
    state = load(workspace)
    assert state.features["blast-radius"].repo_ids() == ["schd"]


def test_start_picks_up_existing_branch_after_lost_sheet(workspace: Path) -> None:
    feature_cmd.start(workspace, State(), "blast-radius")
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    feature_cmd.adopt(workspace, load(workspace))
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "wip")
    save(workspace, State())
    data = feature_cmd.start(workspace, load(workspace), "blast-radius")
    assert gitutil.current_branch(schd) == "feature/blast-radius"
    assert [row["id"] for row in data["repos"]] == ["schd"]
    assert data["repos"][0]["action"] == "already-on-feature"
    assert load(workspace).features["blast-radius"].repo_ids() == ["schd"]


def test_start_picks_up_origin_feature_branch(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "feature/blast-radius")
    (schd / "handler.py").write_text("print('x')\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "wip")
    tip = gitutil.rev_parse(schd, "HEAD")
    git(schd, "checkout", "develop")
    git(schd, "update-ref", "refs/remotes/origin/feature/blast-radius", tip)
    git(schd, "branch", "-D", "feature/blast-radius")
    data = feature_cmd.start(workspace, State(), "blast-radius")
    assert gitutil.current_branch(schd) == "feature/blast-radius"
    assert data["repos"][0]["action"] == "picked-up"
    assert load(workspace).features["blast-radius"].repo_ids() == ["schd"]


def test_start_skips_empty_feature_branch(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "feature/blast-radius")
    git(schd, "checkout", "develop")
    data = feature_cmd.start(workspace, State(), "blast-radius")
    assert gitutil.current_branch(schd) == "develop"
    assert data["repos"] == []
    assert data["repo_count"] == 0
    skipped = [row for row in data["workspace"] if row["id"] == "schd"]
    assert skipped[0]["skipped"] == "empty-feature-branch"
    assert gitutil.has_local_branch(schd, "feature/blast-radius")


def test_start_picks_up_dirty_repo_already_on_feature(workspace: Path) -> None:
    feature_cmd.start(workspace, State(), "blast-radius")
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    feature_cmd.adopt(workspace, load(workspace))
    data = feature_cmd.start(workspace, load(workspace), "blast-radius")
    assert gitutil.current_branch(schd) == "feature/blast-radius"
    assert gitutil.is_dirty(schd)
    assert data["repos"][0]["action"] == "already-on-feature"
    assert data["repos"][0]["dirty"] is True


def test_switch_refuses_dirty(workspace: Path) -> None:
    state = State()
    feature_cmd.start(workspace, state, "auth")
    state = load(workspace)
    feature_cmd.start(workspace, state, "payload")
    schd = workspace / "extensions" / "schd"
    (schd / "dirty.py").write_text("n\n")
    try:
        feature_cmd.switch(workspace, load(workspace), "auth")
    except Exception as exc:
        assert "dirty" in str(exc)
    else:
        raise AssertionError("expected dirty switch to fail")


def test_status_json_roundtrip(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "demo"]) == 0
    assert main(["--json", "status"]) == 0
    out = capsys.readouterr().out
    assert "demo" in out
    assert find_workspace(workspace) == workspace


def test_push_without_participants_fails(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    capsys.readouterr()
    assert main(["--json", "feature", "push"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "no participant repos" in err["error"]


def test_push_sends_feature_branch_no_prs(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    capsys.readouterr()
    calls: list[tuple] = []

    def fake_push(repo: Path, *args: str) -> None:
        calls.append((Path(repo), args))

    monkeypatch.setattr("gitconvoy.feature.gitutil.push", fake_push)
    assert main(["--json", "feature", "push"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["branch"] == "feature/blast-radius"
    assert "No PRs opened" in data["note"]
    assert [row["id"] for row in data["repos"]] == ["schd"]
    assert data["repos"][0]["dirty"] is True
    assert len(calls) == 1
    assert calls[0][1] == ("-u", "origin", "feature/blast-radius")
    assert Path(calls[0][0]).name == "schd"
    state = load(workspace)
    assert state.features["blast-radius"].status == "in-progress"
    assert state.features["blast-radius"].repos[0].pr is None


def test_abandon_requires_yes_for_json(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    capsys.readouterr()
    assert main(["--json", "feature", "abandon"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "--yes" in err["error"]
    assert gitutil.current_branch(schd) == "feature/blast-radius"


def test_abandon_deletes_local_branch(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    capsys.readouterr()
    assert main(["--json", "feature", "abandon", "--yes"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["abandoned"] is True
    assert gitutil.current_branch(schd) == "develop"
    assert not gitutil.has_local_branch(schd, "feature/blast-radius")
    assert gitutil.current_branch(lib) == "develop"
    assert not (schd / "handler.py").exists()
    state = load(workspace)
    assert state.current_feature is None
    assert "blast-radius" not in state.features


def test_abandon_no_keeps_branch(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    data = feature_cmd.abandon(
        workspace,
        load(workspace),
        yes=False,
        as_json=False,
        is_tty=True,
        input_fn=lambda prompt="": "no",
    )
    assert data["abandoned"] is False
    assert gitutil.has_local_branch(schd, "feature/blast-radius")


def _prepare_participant(workspace: Path, monkeypatch) -> Path:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    gitutil.run(schd, "add", "-A")
    gitutil.run(schd, "commit", "-m", "feat")
    state = load(workspace)
    state.features["blast-radius"].repos[0].pr = "https://github.com/renglo/schd/pull/1"
    save(workspace, state)
    return schd


def test_show_reports_merged(workspace: Path, monkeypatch) -> None:
    schd = _prepare_participant(workspace, monkeypatch)
    gitutil.checkout(schd, "develop")
    gitutil.merge(schd, "feature/blast-radius")
    data = feature_cmd.show(workspace, load(workspace))
    assert data["repos"][0]["merge_status"] == "merged"
    assert data["status"] == "merged"
    assert data["merged_count"] == 1
    assert "feature close" in (data.get("note") or "")


def test_show_reports_pending(workspace: Path, monkeypatch) -> None:
    _prepare_participant(workspace, monkeypatch)
    data = feature_cmd.show(workspace, load(workspace))
    assert data["repos"][0]["merge_status"] == "pending"
    assert data["status"] == "in-review"
    assert data["merged_count"] == 0
    assert "PRs open" in (data.get("note") or "")


def test_show_reports_committed_after_commit(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    gitutil.run(schd, "add", "-A")
    gitutil.run(schd, "commit", "-m", "feat")
    data = feature_cmd.show(workspace, load(workspace))
    assert data["repos"][0]["merge_status"] == "committed"
    assert data["status"] == "in-progress"
    assert data["merged_count"] == 0
    assert "feature prs" in (data.get("note") or "")


def test_show_reports_uncommitted_when_dirty_and_undiverged(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    save(workspace, State())
    assert main(["--json", "init"]) == 0
    assert main(["--json", "feature", "start", "blast-radius"]) == 0
    schd = workspace / "extensions" / "schd"
    (schd / "handler.py").write_text("print('x')\n")
    assert main(["--json", "feature", "adopt"]) == 0
    state = load(workspace)
    state.features["blast-radius"].status = "merged"
    save(workspace, state)
    data = feature_cmd.show(workspace, load(workspace))
    assert data["repos"][0]["merge_status"] == "uncommitted"
    assert data["status"] == "in-progress"
    assert data["merged_count"] == 0
    assert load(workspace).features["blast-radius"].status == "in-progress"
    assert "feature commit" in (data.get("note") or "")


def test_close_requires_all_merged(workspace: Path, monkeypatch, capsys) -> None:
    _prepare_participant(workspace, monkeypatch)
    capsys.readouterr()
    assert main(["--json", "feature", "close", "--yes"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "not all participants merged" in err["error"]


def test_close_after_merge(workspace: Path, monkeypatch, capsys) -> None:
    schd = _prepare_participant(workspace, monkeypatch)
    gitutil.checkout(schd, "develop")
    gitutil.merge(schd, "feature/blast-radius")
    capsys.readouterr()
    assert main(["--json", "feature", "close", "--yes"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["closed"] is True
    assert gitutil.current_branch(schd) == "develop"
    assert not gitutil.has_local_branch(schd, "feature/blast-radius")
    state = load(workspace)
    assert state.current_feature is None
    assert "blast-radius" not in state.features


def test_prs_syncs_develop_before_opening(workspace: Path, monkeypatch) -> None:
    schd = _prepare_participant(workspace, monkeypatch)
    git(schd, "checkout", "main")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "2.0.0"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stable on main")
    git(schd, "tag", "v2.0.0")
    assert not gitutil.is_ancestor(schd, "v2.0.0", "develop")
    monkeypatch.setattr(feature_cmd, "_push_feature_branches", lambda _w, _f: [])
    data = feature_cmd.prs(workspace, load(workspace), use_gh=False)
    assert data["develop_sync"]["ok"] is True
    assert gitutil.is_ancestor(schd, "v2.0.0", "develop")
    assert gitutil.current_branch(schd) == "feature/blast-radius"


def test_prs_refuses_on_develop_sync_conflict(workspace: Path, monkeypatch) -> None:
    schd = _prepare_participant(workspace, monkeypatch)
    git(schd, "checkout", "main")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "2.0.0"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stable on main")
    git(schd, "tag", "v2.0.0")
    git(schd, "checkout", "develop")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "diverge develop")
    with pytest.raises(GitConvoyError, match="develop sync failed"):
        feature_cmd.prs(workspace, load(workspace), use_gh=False)
    assert gitutil.current_branch(schd) == "feature/blast-radius"
