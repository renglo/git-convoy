from __future__ import annotations

import json
from pathlib import Path

from gitconvoy import feature as feature_cmd
from gitconvoy import gitutil
from gitconvoy.cli import main
from gitconvoy.state import State, load, save
from gitconvoy.workspace import find_workspace


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
