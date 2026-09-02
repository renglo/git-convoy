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


def test_publish_merges_main_into_develop(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31")
    train_cmd.tag_rc(workspace, state, push=False)
    data = train_cmd.publish(workspace, state, push=False)
    assert data["repos"]
    for row in data["repos"]:
        assert row["synced_develop"] is True
        rel = "extensions/schd" if row["id"] == "schd" else "dev/renglo-lib"
        repo = workspace / rel
        assert gitutil.is_ancestor(repo, row["tag"], "develop")
        assert gitutil.current_branch(repo) == "develop"
    with pytest.raises(GitConvoyError, match="no repos are ahead"):
        train_cmd.cut(workspace, state, "2026-09-01")


def test_publish_then_new_develop_work_is_cuttable(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    train_cmd.publish(workspace, state, push=False)
    lib = workspace / "dev" / "renglo-lib"
    git(lib, "tag", "v1.0.0")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    (schd / "next.py").write_text("print('next')\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "next feature")
    data = train_cmd.cut(workspace, state, "2026-09-01")
    assert {repo["id"] for repo in data["repos"]} == {"schd"}


def test_publish_skips_develop_sync_when_no_develop(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "main")
    git(schd, "branch", "-D", "develop")
    data = train_cmd.publish(workspace, state, push=False)
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert schd_row["synced_develop"] is False
    assert gitutil.current_branch(schd) == "main"


def test_publish_develop_conflict_leaves_train_published(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "diverge develop")
    data = train_cmd.publish(workspace, state, push=False)
    assert data["ok"] is False
    assert "train mergeback" in (data.get("note") or "")
    assert load(workspace).trains["2026-08-31"].status == "published"
    assert gitutil.rev_parse(schd, "MERGE_HEAD") is None
    retry = train_cmd.mergeback(workspace, load(workspace), push=False)
    assert retry["ok"] is False
    assert retry["failed"] == ["schd"]


def test_mergeback_continues_past_one_conflict(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31")
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "diverge develop")
    data = train_cmd.publish(workspace, state, push=False)
    assert data["ok"] is False
    assert data["mergeback"]["failed"] == ["schd"]
    lib_row = next(row for row in data["repos"] if row["id"] == "renglo-lib")
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert lib_row["synced_develop"] is True
    assert schd_row["synced_develop"] is False
    lib = workspace / "dev" / "renglo-lib"
    assert gitutil.is_ancestor(lib, lib_row["tag"], "develop")


def test_mergeback_unsticks_develop_behind_tagged_main(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    train_cmd.tag_rc(workspace, state, push=False)
    schd = workspace / "extensions" / "schd"
    before = gitutil.rev_parse(schd, "develop")
    train_cmd.publish(workspace, state, push=False)
    git(schd, "checkout", "develop")
    git(schd, "reset", "--hard", before)
    tag = load(workspace).trains["2026-08-31"].repos[0].stable_tag
    assert tag
    assert not gitutil.is_ancestor(schd, tag, "develop")
    data = train_cmd.mergeback(workspace, load(workspace), push=False)
    assert data["ok"] is True
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert schd_row["status"] == "merged"
    assert gitutil.is_ancestor(schd, tag, "develop")
    again = train_cmd.mergeback(workspace, load(workspace), push=False)
    already = next(row for row in again["repos"] if row["id"] == "schd")
    assert again["ok"] is True
    assert already["status"] == "already"


def test_mergeback_refuses_before_publish(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    state = State()
    train_cmd.cut(workspace, state, "2026-08-31", repo_ids=["schd"])
    with pytest.raises(GitConvoyError, match="mergeback runs after train publish"):
        train_cmd.mergeback(workspace, state, push=False)
