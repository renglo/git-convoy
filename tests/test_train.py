from __future__ import annotations

import json
from pathlib import Path

import pytest

from gitconvoy import gitutil
from gitconvoy import train as train_cmd
from gitconvoy.cli import main
from gitconvoy.errors import GitConvoyError
from gitconvoy.state import State, Train, TrainRepo, load, save

from conftest import git, init_repo


def _service_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("service\n")
    git(path, "add", "-A")
    git(path, "commit", "-m", "init")
    git(path, "checkout", "-b", "develop")
    (path / "handler.py").write_text("print('x')\n")
    git(path, "add", "-A")
    git(path, "commit", "-m", "work")
    return path


def test_cut_skips_repos_without_version_file(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    _service_repo(workspace / "dev" / "webhook")
    schd = workspace / "extensions" / "schd"
    (schd / "note.txt").write_text("ahead\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "ahead on schd")
    state = State()
    data = train_cmd.cut(workspace, state, "2026-08-29")
    repo_ids = {repo["id"] for repo in data["repos"]}
    skipped_ids = {item["id"] for item in data["skipped"]}
    assert "schd" in repo_ids
    assert "webhook" in skipped_ids
    assert "webhook" not in repo_ids


def test_cut_explicit_repo_requires_version_file(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    _service_repo(workspace / "dev" / "webhook")
    state = State()
    with pytest.raises(GitConvoyError, match="webhook: no version file"):
        train_cmd.cut(workspace, state, "2026-08-29", repo_ids=["webhook"])


def test_cut_all_skipped_raises(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "dev").mkdir(parents=True)
    (root / "extensions").mkdir()
    console = init_repo(root / "console")
    git(console, "tag", "v1.0.0")
    _service_repo(root / "dev" / "webhook")
    state = State()
    with pytest.raises(GitConvoyError, match="skipped without version files"):
        train_cmd.cut(root, state, "2026-08-29")


def test_delete_removes_release_branches_and_train_sheet(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29", status="cut")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "release/2026-08-29")
    git(schd, "commit", "--allow-empty", "-m", "train")
    train.add_repo(TrainRepo(id="schd", path="extensions/schd", to="1.0.1rc1"))
    state.trains["2026-08-29"] = train
    save(workspace, state)
    data = train_cmd.delete(workspace, load(workspace), yes=True)
    assert data["deleted"] is True
    assert gitutil.current_branch(schd) == "develop"
    assert not gitutil.has_local_branch(schd, "release/2026-08-29")
    state = load(workspace)
    assert state.current_train is None
    assert "2026-08-29" not in state.trains


def test_delete_requires_yes_for_json(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    state = State(current_train="2026-08-29")
    train = Train(name="2026-08-29", branch="release/2026-08-29")
    train.add_repo(TrainRepo(id="schd", path="extensions/schd"))
    state.trains["2026-08-29"] = train
    save(workspace, state)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "-b", "release/2026-08-29")
    capsys.readouterr()
    assert main(["--json", "train", "delete"]) == 1
    err = json.loads(capsys.readouterr().out)
    assert "--yes" in err["error"]
    assert gitutil.has_local_branch(schd, "release/2026-08-29")
