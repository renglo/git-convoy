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
    assert gitutil.current_branch(schd) == "develop"


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


def test_sync_develop_ignores_untracked_on_develop(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    (schd / "src" / "pkg.egg-info").mkdir(parents=True)
    (schd / "src" / "pkg.egg-info" / "PKG-INFO").write_text("artifact\n")
    assert gitutil.is_dirty(schd)
    assert not gitutil.has_tracked_changes(schd)
    data = sync_cmd.sync_develop_from_ref(
        schd, repo_id="schd", push=False, retry_hint="retry"
    )
    assert data["status"] in {"already", "merged", "skipped"}


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


def test_sync_develop_creates_missing_develop(workspace: Path) -> None:
    wl = init_repo(workspace / "dev" / "apollo-wl", develop=False)
    assert not gitutil.has_local_branch(wl, "develop")
    data = sync_cmd.sync_product_repos(workspace, repo_ids=["apollo-wl"], push=False)
    row = next(item for item in data["repos"] if item["id"] == "apollo-wl")
    assert data["ok"] is True
    assert row["status"] in {"already", "merged"}
    assert row.get("develop_created") is True
    assert gitutil.has_local_branch(wl, "develop")
    assert gitutil.current_branch(wl) == "develop"


def _tag_stable_on_main(repo: Path, version: str = "2.0.0") -> None:
    git(repo, "checkout", "main")
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "{repo.name}"\nversion = "{version}"\n'
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", f"stable {version}")
    git(repo, "tag", f"v{version}")


def test_sync_workspace_on_develop_merges_stable(workspace: Path) -> None:
    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    _tag_stable_on_main(schd)
    git(schd, "checkout", "develop")
    git(lib, "checkout", "develop")
    from gitconvoy.state import State

    data = sync_cmd.sync_workspace(workspace, State(), push=False)
    assert data["ok"] is True
    assert data["remaining"] == 0
    assert gitutil.current_branch(schd) == "develop"
    assert gitutil.current_branch(lib) == "develop"
    assert gitutil.is_ancestor(schd, "v2.0.0", "develop")


def test_sync_workspace_cli(workspace: Path, monkeypatch, capsys) -> None:
    from gitconvoy.cli import main

    monkeypatch.chdir(workspace)
    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "main")
    capsys.readouterr()
    assert main(["sync", "--no-push"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("sync:")
    assert "all repos synchronized" in out
    assert gitutil.current_branch(schd) == "main"


def test_sync_workspace_reports_dirty_and_continues(workspace: Path) -> None:
    from gitconvoy.state import State

    schd = workspace / "extensions" / "schd"
    lib = workspace / "dev" / "renglo-lib"
    git(schd, "checkout", "develop")
    readme = (schd / "README.md").read_text()
    (schd / "README.md").write_text(readme + "dirty\n")
    data = sync_cmd.sync_workspace(workspace, State(), push=False)
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    lib_row = next(row for row in data["repos"] if row["id"] == "renglo-lib")
    assert data["ok"] is False
    assert data["remaining"] == 1
    assert data["pending"] == ["schd"]
    assert schd_row["status"] == "needs-commit"
    assert "commit or stash" in schd_row["next"]
    assert lib_row["status"] in {"already", "merged", "pulled"}
    assert gitutil.current_branch(schd) == "develop"
    again = sync_cmd.sync_workspace(workspace, State(), push=False)
    assert again["pending"] == ["schd"]


def test_sync_workspace_keeps_feature_branch(workspace: Path) -> None:
    from gitconvoy.state import State

    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    git(schd, "checkout", "-b", "feature/blast-radius")
    (schd / "work.txt").write_text("feature\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "feature work")
    data = sync_cmd.sync_workspace(workspace, State(), push=False)
    assert data["ok"] is True
    assert gitutil.current_branch(schd) == "feature/blast-radius"


def test_sync_workspace_allows_empty_feature_sheet(workspace: Path) -> None:
    from gitconvoy import feature as feature_cmd
    from gitconvoy.state import load

    feature_cmd.start(workspace, load(workspace), "blast-radius")
    data = sync_cmd.sync_workspace(workspace, load(workspace), push=False)
    assert data["ok"] is True
    schd = workspace / "extensions" / "schd"
    assert gitutil.current_branch(schd) == "develop"


def test_sync_workspace_merges_develop_into_topic_branch(workspace: Path) -> None:
    from gitconvoy.state import State

    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    git(schd, "checkout", "-b", "feature/old")
    (schd / "old.txt").write_text("work\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "unmerged feature")
    git(schd, "checkout", "develop")
    (schd / "from-develop.txt").write_text("latest\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "landed on develop")
    git(schd, "checkout", "feature/old")
    data = sync_cmd.sync_workspace(workspace, State(), push=False)
    schd_row = next(row for row in data["repos"] if row["id"] == "schd")
    assert data["ok"] is True
    assert schd_row["status"] == "merged"
    assert gitutil.current_branch(schd) == "feature/old"
    assert (schd / "from-develop.txt").read_text() == "latest\n"
    assert (schd / "old.txt").read_text() == "work\n"


def test_sync_workspace_release_ignores_develop(workspace: Path) -> None:
    from gitconvoy.state import State

    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    git(schd, "checkout", "-b", "release/2026-W34")
    (schd / "FIX.md").write_text("stabilize\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "stabilize on release")
    fix = git(schd, "rev-parse", "HEAD").stdout.strip()
    git(schd, "reset", "--hard", "HEAD~1")
    git(schd, "update-ref", "refs/remotes/origin/release/2026-W34", fix)
    git(schd, "checkout", "develop")
    (schd / "FEATURE.md").write_text("next train\n")
    git(schd, "add", "-A")
    git(schd, "commit", "-m", "feature after the cut")
    git(schd, "checkout", "release/2026-W34")
    data = sync_cmd.sync_workspace(workspace, State(), push=False)
    row = next(item for item in data["repos"] if item["id"] == "schd")
    assert row["status"] == "merged"
    assert gitutil.current_branch(schd) == "release/2026-W34"
    assert (schd / "FIX.md").read_text() == "stabilize\n"
    assert not (schd / "FEATURE.md").exists()


def test_sync_workspace_stays_on_empty_topic_branch(workspace: Path) -> None:
    from gitconvoy.state import State

    schd = workspace / "extensions" / "schd"
    git(schd, "checkout", "develop")
    git(schd, "checkout", "-b", "feature/old")
    data = sync_cmd.sync_workspace(workspace, State(), push=False)
    assert data["ok"] is True
    assert gitutil.current_branch(schd) == "feature/old"


def test_sync_ops_develop_does_not_merge_raw_main(workspace: Path) -> None:
    launcher = init_repo(workspace / "ops" / "launcher")
    (launcher / "gitconvoy.toml").write_text('role = "ops"\n')
    git(launcher, "add", "gitconvoy.toml")
    git(launcher, "commit", "-m", "marker")
    from gitconvoy import membership
    from gitconvoy.workspace import discover_repos

    membership.refresh_membership(workspace, discover_repos(workspace))

    git(launcher, "checkout", "main")
    (launcher / "MAIN.md").write_text("main only\n")
    git(launcher, "add", "MAIN.md")
    git(launcher, "commit", "-m", "main moved ahead")
    git(launcher, "update-ref", "refs/remotes/origin/main", git(launcher, "rev-parse", "HEAD").stdout.strip())
    git(launcher, "checkout", "develop")

    data = sync_cmd.sync_ops_repos(workspace, repo_ids=["launcher"], push=False)
    row = next(item for item in data["repos"] if item["id"] == "launcher")
    assert data["ok"] is True
    assert row["branch"] == "develop"
    assert not (launcher / "MAIN.md").exists()


def test_sync_ops_develop_merges_hotfix_tag(workspace: Path) -> None:
    launcher = init_repo(workspace / "ops" / "launcher")
    (launcher / "gitconvoy.toml").write_text('role = "ops"\n')
    git(launcher, "add", "gitconvoy.toml")
    git(launcher, "commit", "-m", "marker")
    from gitconvoy import membership
    from gitconvoy.workspace import discover_repos

    membership.refresh_membership(workspace, discover_repos(workspace))

    git(launcher, "checkout", "main")
    (launcher / "HOTFIX.md").write_text("hotfix\n")
    git(launcher, "add", "HOTFIX.md")
    git(launcher, "commit", "-m", "hotfix on main")
    git(launcher, "tag", "v0.1.1")
    git(launcher, "update-ref", "refs/remotes/origin/main", git(launcher, "rev-parse", "HEAD").stdout.strip())
    git(launcher, "checkout", "develop")

    data = sync_cmd.sync_ops_repos(workspace, repo_ids=["launcher"], push=False)
    row = next(item for item in data["repos"] if item["id"] == "launcher")
    assert data["ok"] is True
    assert row["status"] == "merged"
    assert (launcher / "HOTFIX.md").read_text() == "hotfix\n"


def test_sync_workspace_ignores_active_train(workspace: Path) -> None:
    from gitconvoy.state import State, Train, save

    state = State(current_train="2026-W34")
    state.trains["2026-W34"] = Train(
        name="2026-W34", branch="release/2026-W34", status="cut"
    )
    save(workspace, state)
    data = sync_cmd.sync_workspace(workspace, state, push=False)
    assert data["ok"] is True
    assert data["remaining"] == 0
