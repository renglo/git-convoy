from __future__ import annotations

from pathlib import Path

import pytest

from gitconvoy import gitutil
from gitconvoy import sync as sync_cmd
from gitconvoy.errors import GitConvoyError

from conftest import git, init_repo


def test_sync_develop_without_feature_or_train(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "main")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "2.0.0"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stable on main")
    git(schd, "tag", "v2.0.0")
    assert not gitutil.is_ancestor(schd, "v2.0.0", "develop")
    data = sync_cmd.sync_product_repos(workspace, push=False)
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert data["ok"] is True
    assert schd_row["status"] == "merged"
    assert gitutil.is_ancestor(schd, "v2.0.0", "develop")


def test_sync_develop_filters_repos(workspace: Path) -> None:
    data_repo = init_repo(workspace / "extensions" / "data")
    git(data_repo, "checkout", "main")
    (data_repo / "pyproject.toml").write_text(
        '[project]\nname = "data"\nversion = "2.0.0"\n'
    )
    git(data_repo, "add", "-A")
    git(data_repo, "commit", "-m", "stable on main")
    git(data_repo, "tag", "v2.0.0")
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "main")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "3.0.0"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stable on main")
    git(schd, "tag", "v3.0.0")
    data = sync_cmd.sync_product_repos(workspace, repo_ids=["data"], push=False)
    assert data["ok"] is True
    assert [row["id"] for row in data["repos"]] == ["data"]
    assert gitutil.is_ancestor(data_repo, "v2.0.0", "develop")
    assert not gitutil.is_ancestor(schd, "v3.0.0", "develop")


def test_sync_develop_continues_past_conflict(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    for repo in (schd, lib):
        git(repo, "checkout", "main")
        (repo / "pyproject.toml").write_text(
            f'[project]\nname = "{repo.name}"\nversion = "2.0.0"\n'
        )
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "stable on main")
        git(repo, "tag", "v2.0.0")
    git(schd, "checkout", "develop")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "diverge develop")
    data = sync_cmd.sync_product_repos(workspace, push=False)
    assert data["ok"] is False
    assert data["failed"] == ["schd"]
    lib_row = next(row for row in data["repos"] if row["id"] == "renglo-lib")
    assert lib_row["status"] == "merged"
    assert gitutil.is_ancestor(lib, "v2.0.0", "develop")


def test_sync_develop_cli(workspace: Path, monkeypatch, capsys) -> None:
    from gitconvoy.cli import main

    monkeypatch.chdir(workspace)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "main")
    (schd / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "2.0.0"\n'
    )
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stable on main")
    git(schd, "tag", "v2.0.0")
    capsys.readouterr()
    assert main(["sync", "develop", "--no-push"]) == 0
    out = capsys.readouterr().out
    assert "sync develop" in out
    assert gitutil.is_ancestor(schd, "v2.0.0", "develop")


def test_sync_develop_unknown_repo(workspace: Path) -> None:
    with pytest.raises(GitConvoyError, match="repo not in workspace"):
        sync_cmd.sync_product_repos(workspace, repo_ids=["missing"], push=False)
